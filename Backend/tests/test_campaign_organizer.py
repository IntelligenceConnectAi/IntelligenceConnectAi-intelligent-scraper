"""
Campaign Organizer — pure pandas-logic tests against app/campaign_organizer_logic.py
(no DB/auth fixtures needed for most of these) plus one thin integration test
for the actual HTTP endpoint.
"""

import io
import zipfile
from base64 import b64decode

import pandas as pd
import pytest

from app.campaign_organizer_logic import (
    build_tail,
    build_zip_bytes,
    clean_phone,
    count_phone_email_totals,
    explode_dialer_rows,
    explode_email_rows,
    explode_sms_rows,
    filter_properties_seller_leads,
    merge_business_leads,
    merge_people_leads,
    normalize_mls_status,
    split_dataframe,
)


def _row(**kwargs):
    base = {f"Phone {n}": "" for n in range(1, 6)}
    base.update({f"Phone {n} Type": "" for n in range(1, 6)})
    base.update({f"Email {n}": "" for n in range(1, 6)})
    base.update(kwargs)
    return base


# ── normalize_mls_status / filter_properties_seller_leads ──

def test_normalize_mls_status_blank_becomes_off_market():
    assert normalize_mls_status("") == "Off Market"
    assert normalize_mls_status("nan") == "Off Market"
    assert normalize_mls_status(None) == "Off Market"


def test_normalize_mls_status_valid_value_passthrough():
    assert normalize_mls_status("Active") == "Active"
    assert normalize_mls_status("PENDING") == "PENDING"


def test_normalize_mls_status_invalid_value_dropped():
    assert normalize_mls_status("Something Else") is None


def test_filter_properties_seller_leads_keeps_known_and_blank_drops_invalid():
    df = pd.DataFrame([
        _row(**{"MLS Status": "Active"}),
        _row(**{"MLS Status": ""}),
        _row(**{"MLS Status": "Bogus Status"}),
    ])
    result = filter_properties_seller_leads(df)
    assert len(result) == 2
    statuses = set(result["MLS Status"])
    assert statuses == {"Active", "Off Market"}


def test_filter_properties_seller_leads_missing_column_returns_empty():
    df = pd.DataFrame([_row(Name="Test")])
    result = filter_properties_seller_leads(df)
    assert result.empty


# ── merge ──

def test_merge_people_leads_drops_dnc_columns():
    df1 = pd.DataFrame([_row(**{"Phone 1 DNC": "yes", "Name": "A"})])
    df2 = pd.DataFrame([_row(**{"Phone 1 DNC": "no", "Name": "B"})])
    merged = merge_people_leads([df1, df2])
    assert len(merged) == 2
    assert "Phone 1 DNC" not in merged.columns


def test_merge_business_leads_simple_concat():
    df1 = pd.DataFrame([{"Name": "A"}])
    df2 = pd.DataFrame([{"Name": "B"}])
    merged = merge_business_leads([df1, df2])
    assert len(merged) == 2
    assert list(merged["Name"]) == ["A", "B"]


def test_count_phone_email_totals_across_five_groups():
    df = pd.DataFrame([
        _row(**{"Phone 1": "5551234567", "Phone 2": "5559876543", "Email 1": "a@example.com"}),
        _row(**{"Phone 3": "5551112222"}),
    ])
    phones, emails = count_phone_email_totals(df)
    assert phones == 3
    assert emails == 1


# ── channel exploders ──

def test_explode_dialer_rows_requires_phone():
    df = pd.DataFrame([
        _row(**{"Phone 1": "5551234567", "Phone 1 Type": "Mobile"}),
        _row(**{"Email 1": "noPhone@example.com"}),  # no phone at all -> excluded
    ])
    out = explode_dialer_rows(df, "camp")
    assert len(out) == 1
    assert out.iloc[0]["Phone Number"] == "5551234567"


def test_explode_sms_rows_drops_landline_but_keeps_row_via_email():
    df = pd.DataFrame([
        _row(**{"Phone 1": "5551234567", "Phone 1 Type": "Landline", "Email 1": "a@example.com"}),
    ])
    out = explode_sms_rows(df, "camp")
    assert len(out) == 1
    assert out.iloc[0]["Phone Number"] == ""  # landline dropped
    assert out.iloc[0]["Email"] == "a@example.com"


def test_explode_sms_rows_landline_with_no_email_excluded():
    df = pd.DataFrame([
        _row(**{"Phone 1": "5551234567", "Phone 1 Type": "Landline"}),
    ])
    out = explode_sms_rows(df, "camp")
    assert out.empty


def test_explode_email_rows_requires_email_keeps_non_landline_phone():
    df = pd.DataFrame([
        _row(**{"Phone 1": "5551234567", "Phone 1 Type": "Mobile", "Email 1": "a@example.com"}),
        _row(**{"Phone 1": "5551112222", "Phone 1 Type": "Mobile"}),  # no email -> excluded
    ])
    out = explode_email_rows(df, "camp")
    assert len(out) == 1
    assert out.iloc[0]["Phone Number"] == "5551234567"
    assert out.iloc[0]["Email"] == "a@example.com"


def test_explode_email_rows_drops_landline_phone_but_keeps_row():
    df = pd.DataFrame([
        _row(**{"Phone 1": "5551234567", "Phone 1 Type": "Landline", "Email 1": "a@example.com"}),
    ])
    out = explode_email_rows(df, "camp")
    assert len(out) == 1
    assert out.iloc[0]["Phone Number"] == ""


def test_clean_phone_strips_excel_float_artifact():
    assert clean_phone("5551234567.0") == "5551234567"
    assert clean_phone("") == ""


# ── naming / split ──

def test_build_tail_structured_vs_freeform():
    assert build_tail(True, "JAN", "2026", "fl", "Luxury Land", "") == "JAN - 2026 - FL - Luxury Land"
    assert build_tail(False, "", "", "", "", "  My Campaign  ") == "My Campaign"


def test_split_dataframe_single_chunk_no_wk_suffix():
    df = pd.DataFrame([{"x": 1}, {"x": 2}])
    parts = split_dataframe(df, "CC", "TAIL", None, 1)
    assert len(parts) == 1
    name, chunk = parts[0]
    assert name == "CC - TAIL"
    assert len(chunk) == 2


def test_split_dataframe_roughly_equal_chunks_with_wk_suffix():
    df = pd.DataFrame([{"x": i} for i in range(5)])
    parts = split_dataframe(df, "CC", "TAIL", "PROPERTIES", 2)
    assert len(parts) == 2
    names = [name for name, _ in parts]
    assert names == ["CC - PROPERTIES - WK1 - TAIL", "CC - PROPERTIES - WK2 - TAIL"]
    assert sum(len(chunk) for _, chunk in parts) == 5


def test_split_dataframe_empty_returns_no_parts():
    df = pd.DataFrame(columns=["x"])
    assert split_dataframe(df, "CC", "TAIL", None, 1) == []


# ── zip round-trip ──

def test_build_zip_bytes_roundtrip():
    members = {"CC/file1.csv": b"a,b\n1,2\n", "SMS/file2.csv": b"c,d\n3,4\n"}
    zip_bytes = build_zip_bytes(members)
    buf = io.BytesIO(zip_bytes)
    assert zipfile.is_zipfile(buf)
    with zipfile.ZipFile(buf) as zf:
        assert set(zf.namelist()) == {"CC/file1.csv", "SMS/file2.csv"}
        assert zf.read("CC/file1.csv") == b"a,b\n1,2\n"


# ── thin integration test ──

@pytest.mark.asyncio(loop_scope="session")
async def test_people_leads_process_endpoint_returns_zip_downloads(client, auth_user_pool, make_headers):
    user = auth_user_pool[0]

    df = pd.DataFrame([
        {"Phone 1": "5551234567", "Phone 1 Type": "Mobile", "Email 1": "a@example.com", "Name": "Alice"},
        {"Phone 1": "5559998888", "Phone 1 Type": "Landline", "Email 1": "b@example.com", "Name": "Bob"},
    ])
    buf = io.BytesIO()
    df.to_excel(buf, index=False, engine="openpyxl")
    buf.seek(0)

    resp = await client.post(
        "/campaign-organizer/people-leads/process",
        headers=make_headers(user),
        files={"files": ("leads.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={
            "name_mode": "freeform",
            "freeform_name": "Test Campaign",
            "marketing_channels": ["dialer", "sms"],
            "split_count": "1",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] == 2
    assert body["campaign_name"] == "Test Campaign"
    assert body["marketing_counts"]["dialer"] == 2  # dialer has no landline filter — both rows have a phone
    assert body["marketing_counts"]["sms"] == 2      # Bob's landline phone is dropped but his email keeps the row
    assert len(body["downloads"]) == 1
    assert body["downloads"][0]["group"] == "marketing"

    zip_bytes = b64decode(body["downloads"][0]["content_base64"])
    assert zipfile.is_zipfile(io.BytesIO(zip_bytes))
