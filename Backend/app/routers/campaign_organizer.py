"""
Campaign Organizer — stateless list-processing tool ported from the team's
existing standalone Streamlit script. No DB access, no org/role gating: any
logged-in user (client or admin) can use it, matching the precedent in
app/routers/history.py / integrations.py for routes with no org/role concept.
See app/campaign_organizer_logic.py for the actual pandas logic.
"""

import base64
import logging
import os

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.campaign_organizer_logic import (
    CHANNEL_EXPLODERS,
    build_tail,
    build_zip_bytes,
    count_phone_email_totals,
    dataframe_to_csv_bytes,
    filter_properties_seller_leads,
    merge_business_leads,
    merge_people_leads,
    read_upload_dataframe,
    split_dataframe,
)
from app.deps import CurrentUserDep
from app.schemas import (
    BusinessLeadsProcessResponse,
    CampaignDownload,
    ChannelCounts,
    PeopleLeadsProcessResponse,
)
from app.security_utils import MAX_UPLOAD_BYTES, safe_filename

log = logging.getLogger(__name__)
router = APIRouter()

MAX_FILES_PER_REQUEST = 20
MAX_TOTAL_UPLOAD_BYTES = 50 * 1024 * 1024  # 50MB

PEOPLE_LEADS_EXTENSIONS = {".xlsx"}
BUSINESS_LEADS_EXTENSIONS = {".xlsx", ".csv"}


async def _read_files(files: list[UploadFile], allowed_extensions: set[str]) -> list:
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No files uploaded")
    if len(files) > MAX_FILES_PER_REQUEST:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Upload at most {MAX_FILES_PER_REQUEST} files at once")

    dfs = []
    total_bytes = 0
    for f in files:
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"'{f.filename}': only {', '.join(sorted(allowed_extensions))} files are accepted",
            )
        content = await f.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"'{f.filename}' exceeds {MAX_UPLOAD_BYTES // (1024*1024)}MB limit")
        total_bytes += len(content)
        if total_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Total upload exceeds {MAX_TOTAL_UPLOAD_BYTES // (1024*1024)}MB limit")
        try:
            dfs.append(read_upload_dataframe(content, f.filename or ""))
        except Exception:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Could not parse '{f.filename}' — check it is a valid CSV/Excel export")
    return dfs


_CHANNEL_LABELS = {"dialer": "CC", "sms": "SMS", "email": "EMAIL"}


def _process_channels_to_zip(df, channels: list[str], tail: str, tag, split_count: int) -> tuple[dict, dict]:
    """Mirrors the original's build_zip(channel_parts) — one folder per channel
    inside a single zip, not a separate zip per channel/chunk."""
    counts = {}
    zip_members: dict[str, bytes] = {}
    for channel in channels:
        label = _CHANNEL_LABELS[channel]
        exploded = CHANNEL_EXPLODERS[channel](df, "")
        counts[channel] = len(exploded)
        for name, chunk_df in split_dataframe(exploded, label, tail, tag, split_count):
            zip_members[f"{label}/{name}.csv"] = dataframe_to_csv_bytes(chunk_df)
    return counts, zip_members


@router.post("/people-leads/process", response_model=PeopleLeadsProcessResponse)
async def process_people_leads(
    user: CurrentUserDep,
    files: list[UploadFile] = File(...),
    name_mode: str = Form("freeform"),
    freeform_name: str = Form(""),
    month: str = Form(""),
    year: str = Form("2026"),
    state: str = Form(""),
    deal_type: str = Form(""),
    marketing_channels: list[str] = Form([]),
    properties_channels: list[str] = Form([]),
    split_count: int = Form(1),
):
    if not marketing_channels and not properties_channels:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select at least one output channel")

    dfs = await _read_files(files, PEOPLE_LEADS_EXTENSIONS)
    merged = merge_people_leads(dfs)
    orig_phone_count, orig_email_count = count_phone_email_totals(merged)

    structured = name_mode == "structured"
    tail = build_tail(structured, month, year, state, deal_type, freeform_name)
    if not tail:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Campaign name is required")

    all_downloads: list[CampaignDownload] = []
    marketing_counts = None
    properties_counts = None

    if marketing_channels:
        counts, zip_members = _process_channels_to_zip(merged, marketing_channels, tail, None, split_count)
        marketing_counts = ChannelCounts(**{"dialer": 0, "sms": 0, "email": 0, **counts})
        if zip_members:
            filename = safe_filename(f"Marketing Process - {tail}.zip")
            zip_b64 = _zip_to_base64(zip_members)
            all_downloads.append(CampaignDownload(group="marketing", label=filename, filename=filename, content_base64=zip_b64))

    if properties_channels:
        props_df = filter_properties_seller_leads(merged)
        counts, zip_members = _process_channels_to_zip(props_df, properties_channels, tail, "PROPERTIES", split_count)
        properties_counts = ChannelCounts(**{"dialer": 0, "sms": 0, "email": 0, **counts})
        if zip_members:
            filename = safe_filename(f"Properties Seller Leads - {tail}.zip")
            zip_b64 = _zip_to_base64(zip_members)
            all_downloads.append(CampaignDownload(group="properties", label=filename, filename=filename, content_base64=zip_b64))

    return PeopleLeadsProcessResponse(
        total_rows=len(merged),
        orig_phone_count=orig_phone_count,
        orig_email_count=orig_email_count,
        campaign_name=tail,
        marketing_counts=marketing_counts,
        properties_counts=properties_counts,
        downloads=all_downloads,
    )


@router.post("/business-leads/process", response_model=BusinessLeadsProcessResponse)
async def process_business_leads(
    user: CurrentUserDep,
    files: list[UploadFile] = File(...),
    name_mode: str = Form("freeform"),
    freeform_name: str = Form(""),
    month: str = Form(""),
    year: str = Form("2026"),
    state: str = Form(""),
    deal_type: str = Form(""),
    split_count: int = Form(1),
):
    dfs = await _read_files(files, BUSINESS_LEADS_EXTENSIONS)
    merged = merge_business_leads(dfs)

    structured = name_mode == "structured"
    tail = build_tail(structured, month, year, state, deal_type, freeform_name)
    if not tail:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Campaign name is required")

    chunks = split_dataframe(merged, "LEADS", tail, None, split_count)
    members = {f"LEADS/{name}.csv": dataframe_to_csv_bytes(chunk_df) for name, chunk_df in chunks}

    filename = safe_filename(f"Business Leads - {tail}.zip")
    return BusinessLeadsProcessResponse(
        total_rows=len(merged),
        campaign_name=tail,
        download=CampaignDownload(group="business", label=filename, filename=filename, content_base64=_zip_to_base64(members)),
    )


def _zip_to_base64(members: dict[str, bytes]) -> str:
    return base64.b64encode(build_zip_bytes(members)).decode("ascii")
