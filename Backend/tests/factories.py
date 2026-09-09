"""
Thin SQL-insert helpers for test fixtures — raw SQL, not app code, deliberately
minimal. Every insert here happens on the test's own transactional connection
(see conftest.py) and rolls back automatically at teardown.
"""

from uuid import uuid4

from app.storage import upload_csv


async def make_user(conn, auth_id, email, *, full_name=None, platform_role="client", is_active=True):
    await conn.execute(
        """
        INSERT INTO users (id, email, full_name, is_admin, is_active, platform_role)
        VALUES ($1,$2,$3,false,$4,$5)
        ON CONFLICT (id) DO UPDATE SET
            full_name = EXCLUDED.full_name, is_active = EXCLUDED.is_active, platform_role = EXCLUDED.platform_role
        """,
        auth_id, email, full_name or email.split("@")[0], is_active, platform_role,
    )
    return auth_id


async def make_org(conn, owner_user_id, *, name=None):
    org_id = uuid4()
    await conn.execute(
        "INSERT INTO organizations (id, name, owner_user_id) VALUES ($1,$2,$3)",
        org_id, name or f"Test Org {org_id.hex[:6]}", owner_user_id,
    )
    await conn.execute(
        "INSERT INTO organization_members (organization_id, user_id, role, is_active) VALUES ($1,$2,'account_owner',true)",
        org_id, owner_user_id,
    )
    return org_id


async def add_member(conn, org_id, user_id, *, role="client_member"):
    await conn.execute(
        """
        INSERT INTO organization_members (organization_id, user_id, role, is_active)
        VALUES ($1,$2,$3,true)
        ON CONFLICT (organization_id, user_id) DO UPDATE SET role = EXCLUDED.role, is_active = true
        """,
        org_id, user_id, role,
    )


async def make_subscription(conn, user_id, *, plan_id="starter", status="active"):
    await conn.execute(
        """
        INSERT INTO subscriptions (user_id, plan_id, status, current_period_end)
        VALUES ($1,$2,$3, NOW() + INTERVAL '30 days')
        ON CONFLICT (user_id) DO UPDATE SET plan_id = EXCLUDED.plan_id, status = EXCLUDED.status
        """,
        user_id, plan_id, status,
    )


async def make_client(conn, auth_user, *, plan_id="starter", org_name=None):
    """Full client setup: users row + org + account_owner membership + active subscription."""
    user_id = auth_user["id"]
    await make_user(conn, user_id, auth_user["email"], platform_role="client")
    org_id = await make_org(conn, user_id, name=org_name)
    await make_subscription(conn, user_id, plan_id=plan_id)
    return user_id, org_id


async def make_admin(conn, auth_user, *, platform_role="admin", permissions=None):
    user_id = auth_user["id"]
    await make_user(conn, user_id, auth_user["email"], platform_role=platform_role)
    for perm in (permissions or []):
        await grant_permission(conn, user_id, perm)
    return user_id


async def grant_permission(conn, admin_user_id, permission_key, *, granted_by=None):
    await conn.execute(
        "INSERT INTO admin_permissions (admin_user_id, permission_key, granted_by) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
        admin_user_id, permission_key, granted_by,
    )


async def make_job(conn, user_id, *, status="pending", industry="plumbers", state="FL", cities=None, total_clean=0):
    cities = cities or ["Miami"]
    row = await conn.fetchrow(
        """
        INSERT INTO jobs (user_id, industry, state, cities, status, cities_total, total_clean)
        VALUES ($1,$2,$3,$4,$5,$6,$7)
        RETURNING id
        """,
        user_id, industry, state, cities, status, len(cities), total_clean,
    )
    return row["id"]


async def make_people_lead_request(
    conn, org_id, requested_by, *, request_name="Test Request",
    lead_type="property_owners", state="FL", quantity=100,
):
    row = await conn.fetchrow(
        """
        INSERT INTO people_lead_requests
            (organization_id, requested_by, request_name, lead_type, state, requested_quantity, client_status, internal_status)
        VALUES ($1,$2,$3,$4,$5,$6,'Submitted','new')
        RETURNING id
        """,
        org_id, requested_by, request_name, lead_type, state, quantity,
    )
    return row["id"]


async def make_lead_file(
    conn, org_id, user_id, *, source_type="business", source_id=None,
    file_category="business_with_website", display_name="Test File", record_count=10,
):
    """Every real lead_files row corresponds to an actually-uploaded storage object —
    the download/sign-url endpoint fails with a real 400 from Supabase Storage
    otherwise (caught by actually running this test against the real local stack,
    not a mock). So this factory uploads real (tiny) content to the same storage
    path it inserts, matching that invariant."""
    storage_path = f"{org_id}/test/{uuid4()}.csv"
    await upload_csv(storage_path, b"Name,Phone\nTest Lead,555-0100\n", content_type="text/csv")

    row = await conn.fetchrow(
        """
        INSERT INTO lead_files
            (organization_id, user_id, source_type, source_id, file_category, display_name,
             storage_path, file_type, record_count, website_count, email_count)
        VALUES ($1,$2,$3,$4,$5,$6,$7,'csv',$8,0,0)
        RETURNING id
        """,
        org_id, user_id, source_type, source_id or uuid4(), file_category, display_name,
        storage_path, record_count,
    )
    return row["id"]


async def make_support_ticket(conn, org_id, created_by, *, subject="Test Ticket", category="other"):
    row = await conn.fetchrow(
        """
        INSERT INTO support_tickets (organization_id, created_by, subject, category)
        VALUES ($1,$2,$3,$4)
        RETURNING id
        """,
        org_id, created_by, subject, category,
    )
    ticket_id = row["id"]
    await conn.execute(
        """
        INSERT INTO support_ticket_messages (ticket_id, sender_user_id, sender_is_admin, is_internal_note, body)
        VALUES ($1,$2,false,false,'Initial message')
        """,
        ticket_id, created_by,
    )
    return ticket_id
