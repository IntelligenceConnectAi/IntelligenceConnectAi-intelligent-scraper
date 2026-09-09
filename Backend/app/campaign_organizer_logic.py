"""
Campaign Organizer — pure pandas/zip logic, ported from the team's existing
standalone Streamlit tool (`clean (1).py`). No FastAPI/DB imports here on
purpose — this module is independently unit-testable and has zero relationship
to org/client data (see Backend/app/routers/campaign_organizer.py for the
stateless request/response wrapper around it).

The original wrote intermediate merge results to /tmp disk because Streamlit
reruns the whole script on every widget interaction within one long-lived
process. A single FastAPI request/response cycle does merge -> process -> zip
in one function call, so everything here stays in memory via io.BytesIO.
"""

import io
import math
import zipfile
from typing import Optional

import pandas as pd

PHONE_GROUPS = [(f"Phone {n}", f"Phone {n} Type", f"Email {n}") for n in range(1, 6)]
DNC_COLS = [f"Phone {n} DNC" for n in range(1, 6)]

MLS_STATUSES = {
    "ACTIVE", "ACTIVE UNDER CONTRACT", "CANCELED", "CANCELLED", "COMING SOON",
    "CONTINGENT", "DELETED", "EXPIRED", "FAIL", "FAILED",
    "PENDING", "REMOVED", "WITHDRAWN",
}
MLS_STATUS_COLUMN = "MLS Status"

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


# ── Small value helpers ──────────────────────────────────────────────────
def get_val(row, col: str) -> str:
    if col not in row.index:
        return ""
    v = str(row[col]).strip()
    return "" if v.lower() == "nan" else v


def clean_phone(val: str) -> str:
    if not val:
        return ""
    try:
        return str(int(float(val)))
    except (ValueError, TypeError):
        return val


def build_campaign_name(channel: str, tail: str, tag: Optional[str] = None, wk: Optional[int] = None) -> str:
    tag_part = f" - {tag}" if tag else ""
    wk_part = f" - WK{wk}" if wk else ""
    return f"{channel}{tag_part}{wk_part} - {tail}"


def build_tail(structured: bool, month: str, year: str, state: str, deal_type: str, freeform_name: str) -> str:
    if structured:
        return f"{month} - {year} - {state.strip().upper()} - {deal_type.strip()}"
    return freeform_name.strip()


# ── Merge ────────────────────────────────────────────────────────────────
def merge_people_leads(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    cleaned = []
    for df in dfs:
        df = df.drop(columns=[c for c in DNC_COLS if c in df.columns])
        cleaned.append(df)
    return pd.concat(cleaned, ignore_index=True)


def merge_business_leads(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    return pd.concat(dfs, ignore_index=True)


def count_phone_email_totals(df: pd.DataFrame) -> tuple[int, int]:
    phone_cols = [p for p, _t, _e in PHONE_GROUPS]
    email_cols = [e for _p, _t, e in PHONE_GROUPS]

    def _count_nonblank(cols):
        total = 0
        for col in cols:
            if col in df.columns:
                total += df[col].apply(
                    lambda x: 1 if pd.notna(x) and str(x).strip() not in ("", "nan") else 0
                ).sum()
        return int(total)

    return _count_nonblank(phone_cols), _count_nonblank(email_cols)


# ── MLS status / Properties-Seller-Leads filter ─────────────────────────
def normalize_mls_status(raw) -> Optional[str]:
    val = "" if raw is None else str(raw).strip()
    if val in ("", "nan"):
        return "Off Market"
    if val.upper() in MLS_STATUSES:
        return val
    return None


def filter_properties_seller_leads(df: pd.DataFrame) -> pd.DataFrame:
    if MLS_STATUS_COLUMN not in df.columns:
        return pd.DataFrame(columns=df.columns)

    blank_mask = df[MLS_STATUS_COLUMN].apply(lambda x: str(x).strip() in ("", "nan"))
    known_mask = df[MLS_STATUS_COLUMN].apply(lambda x: str(x).strip().upper() in MLS_STATUSES)
    known = df[known_mask].copy()
    blanks = df[blank_mask].copy()
    blanks[MLS_STATUS_COLUMN] = "Off Market"
    return pd.concat([known, blanks], ignore_index=True)


# ── Channel exploders ────────────────────────────────────────────────────
def _other_cols(df: pd.DataFrame, extra_exclude: list[str]) -> list[str]:
    all_pe = [p for p, _t, _e in PHONE_GROUPS] + [t for _p, t, _e in PHONE_GROUPS] + [e for _p, _t, e in PHONE_GROUPS]
    exclude = set(all_pe) | set(extra_exclude)
    return [c for c in df.columns if c not in exclude]


def explode_dialer_rows(df: pd.DataFrame, campaign_name: str) -> pd.DataFrame:
    other_cols = _other_cols(df, [])
    active_groups = [(p, t) for p, t, _e in PHONE_GROUPS if p in df.columns]
    rows = []
    for _, row in df.iterrows():
        for phone_col, type_col in active_groups:
            phone_val = clean_phone(get_val(row, phone_col))
            if not phone_val:
                continue
            new_row = {"Campaign Name": campaign_name, "Phone Number": phone_val, "Phone Type": get_val(row, type_col)}
            for col in other_cols:
                new_row[col] = get_val(row, col)
            rows.append(new_row)
    return pd.DataFrame(rows, columns=["Campaign Name", "Phone Number", "Phone Type"] + other_cols)


def explode_sms_rows(df: pd.DataFrame, campaign_name: str) -> pd.DataFrame:
    other_cols = _other_cols(df, [])
    active_groups = [(p, t, e) for p, t, e in PHONE_GROUPS if p in df.columns or e in df.columns]
    rows = []
    for _, row in df.iterrows():
        for phone_col, type_col, email_col in active_groups:
            phone_val = clean_phone(get_val(row, phone_col))
            phone_type = get_val(row, type_col)
            email_val = get_val(row, email_col)
            if phone_type.strip().lower() == "landline":
                phone_val = ""
            if not phone_val and not email_val:
                continue
            new_row = {"Campaign Name": campaign_name, "Phone Number": phone_val, "Phone Type": phone_type, "Email": email_val}
            for col in other_cols:
                new_row[col] = get_val(row, col)
            rows.append(new_row)
    return pd.DataFrame(rows, columns=["Campaign Name", "Phone Number", "Phone Type", "Email"] + other_cols)


def explode_email_rows(df: pd.DataFrame, campaign_name: str) -> pd.DataFrame:
    other_cols = _other_cols(df, [])
    active_groups = [(p, t, e) for p, t, e in PHONE_GROUPS if p in df.columns or e in df.columns]
    rows = []
    for _, row in df.iterrows():
        for phone_col, type_col, email_col in active_groups:
            email_val = get_val(row, email_col)
            if not email_val:
                continue
            phone_val = clean_phone(get_val(row, phone_col))
            phone_type = get_val(row, type_col)
            if phone_type.strip().lower() == "landline":
                phone_val = ""
            new_row = {"Campaign Name": campaign_name, "Phone Number": phone_val, "Phone Type": phone_type, "Email": email_val}
            for col in other_cols:
                new_row[col] = get_val(row, col)
            rows.append(new_row)
    return pd.DataFrame(rows, columns=["Campaign Name", "Phone Number", "Phone Type", "Email"] + other_cols)


CHANNEL_EXPLODERS = {"dialer": explode_dialer_rows, "sms": explode_sms_rows, "email": explode_email_rows}


# ── Split ────────────────────────────────────────────────────────────────
def split_dataframe(df: pd.DataFrame, channel: str, tail: str, tag: Optional[str], n: int) -> list[tuple[str, pd.DataFrame]]:
    """Returns [(campaign_name, chunk_df), ...]. n<=1 -> single chunk, no WK suffix."""
    if df.empty:
        return []
    if n <= 1:
        return [(build_campaign_name(channel, tail, tag=tag), df)]

    total = len(df)
    chunk_size = math.ceil(total / n)
    parts = []
    for i in range(n):
        chunk = df.iloc[i * chunk_size:(i + 1) * chunk_size].copy()
        if chunk.empty:
            continue
        name = build_campaign_name(channel, tail, tag=tag, wk=i + 1)
        chunk["Campaign Name"] = name
        parts.append((name, chunk))
    return parts


# ── Serialization ────────────────────────────────────────────────────────
def dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def build_zip_bytes(members: dict[str, bytes]) -> bytes:
    """members: {"folder/name.csv": csv_bytes, ...}"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    buf.seek(0)
    return buf.getvalue()


def read_upload_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext == "csv":
        return pd.read_csv(io.BytesIO(content), dtype=str)
    return pd.read_excel(io.BytesIO(content), dtype=str, engine="openpyxl")
