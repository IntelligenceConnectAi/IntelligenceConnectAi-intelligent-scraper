"""
Phase 5 — post-completion lead-file indexing (§23.8, §27's hook pattern).
Turns a completed business job or a delivered People Leads file into lead_files
row(s). Both entry points are deliberately best-effort — callers MUST wrap these
in their own try/except so an indexing failure never fails or un-completes the
underlying job/request. Idempotent via lead_files' UNIQUE(source_type, source_id,
file_category) + ON CONFLICT DO NOTHING.
"""

import asyncpg

from app.deps import get_current_org_id


async def index_business_job_files(conn: asyncpg.Connection, *, job_id) -> None:
    job = await conn.fetchrow(
        """
        SELECT id, user_id, industry, state, status, with_web_csv, no_web_csv,
               with_website, no_website, emails_found
        FROM jobs WHERE id = $1
        """,
        job_id,
    )
    if not job or job["status"] != "done":
        return

    org_id = await get_current_org_id(conn, job["user_id"])

    if job["with_web_csv"] and job["with_website"] > 0:
        await conn.execute(
            """
            INSERT INTO lead_files
                (organization_id, user_id, source_type, source_id, file_category,
                 display_name, storage_path, file_type, file_size,
                 record_count, website_count, email_count, state, industry_or_category)
            VALUES ($1,$2,'business',$3,'business_with_website',$4,$5,'csv',NULL,$6,$6,$7,$8,$9)
            ON CONFLICT (source_type, source_id, file_category) DO NOTHING
            """,
            org_id, job["user_id"], job["id"],
            f"{job['industry']} — {job['state']} (With Website)",
            job["with_web_csv"], job["with_website"], job["emails_found"],
            job["state"], job["industry"],
        )

    if job["no_web_csv"] and job["no_website"] > 0:
        await conn.execute(
            """
            INSERT INTO lead_files
                (organization_id, user_id, source_type, source_id, file_category,
                 display_name, storage_path, file_type, file_size,
                 record_count, website_count, email_count, state, industry_or_category)
            VALUES ($1,$2,'business',$3,'business_no_website',$4,$5,'csv',NULL,$6,0,0,$7,$8)
            ON CONFLICT (source_type, source_id, file_category) DO NOTHING
            """,
            org_id, job["user_id"], job["id"],
            f"{job['industry']} — {job['state']} (No Website)",
            job["no_web_csv"], job["no_website"], job["state"], job["industry"],
        )


async def index_people_lead_file(conn: asyncpg.Connection, *, request_id) -> None:
    row = await conn.fetchrow(
        """
        SELECT r.id, r.organization_id, r.requested_by, r.request_name, r.lead_type,
               r.state, r.city, r.delivered_quantity,
               f.storage_path, f.file_type, f.file_size, f.email_count
        FROM people_lead_requests r
        JOIN people_lead_files f ON f.request_id = r.id
        WHERE r.id = $1
        ORDER BY f.created_at DESC LIMIT 1
        """,
        request_id,
    )
    if not row or row["delivered_quantity"] <= 0:
        return

    await conn.execute(
        """
        INSERT INTO lead_files
            (organization_id, user_id, source_type, source_id, file_category,
             display_name, storage_path, file_type, file_size,
             record_count, website_count, email_count, state, city, industry_or_category)
        VALUES ($1,$2,'people',$3,'people_leads',$4,$5,$6,$7,$8,0,$9,$10,$11,$12)
        ON CONFLICT (source_type, source_id, file_category) DO NOTHING
        """,
        row["organization_id"], row["requested_by"], row["id"], row["request_name"],
        row["storage_path"], row["file_type"], row["file_size"], row["delivered_quantity"],
        row["email_count"], row["state"], row["city"], row["lead_type"],
    )
