"""
Email-sending hook inside create_notification() — gated by (a) the existing
muted_categories check, (b) the new email_enabled preference, (c) whether the
notification `type` is in EMAIL_ELIGIBLE_TYPES. send_email() itself is
monkeypatched to a recording stub so these tests assert on the gating logic,
not on actually reaching Resend.
"""

import pytest

import app.notifications as notifications_module
from app.notifications import create_notification, notify_admins_with_permission
from tests.factories import grant_permission, make_admin, make_client, make_user

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest.fixture
def sent_emails(monkeypatch):
    calls = []

    async def _fake_send_email(*, to, subject, html_body):
        calls.append({"to": to, "subject": subject, "html_body": html_body})

    monkeypatch.setattr(notifications_module, "send_email", _fake_send_email)
    return calls


async def test_eligible_type_unmuted_default_prefs_sends_email(db_conn, auth_user_pool, sent_emails):
    user = auth_user_pool[0]
    user_id, _ = await make_client(db_conn, user)

    await create_notification(
        db_conn, user_id=user_id, category="business_updates", type="business_request_completed",
        title="Your request is ready", body="12 leads found.",
    )

    row = await db_conn.fetchrow("SELECT type FROM notifications WHERE user_id = $1", user_id)
    assert row["type"] == "business_request_completed"
    assert len(sent_emails) == 1
    assert sent_emails[0]["to"] == user["email"]
    assert sent_emails[0]["subject"] == "Your request is ready"


async def test_muted_category_skips_both_row_and_email(db_conn, auth_user_pool, sent_emails):
    user = auth_user_pool[1]
    user_id, _ = await make_client(db_conn, user)
    await db_conn.execute(
        "INSERT INTO notification_preferences (user_id, muted_categories) VALUES ($1, $2)",
        user_id, ["business_updates"],
    )

    await create_notification(
        db_conn, user_id=user_id, category="business_updates", type="business_request_completed",
        title="Your request is ready", body="12 leads found.",
    )

    row = await db_conn.fetchrow("SELECT type FROM notifications WHERE user_id = $1", user_id)
    assert row is None
    assert sent_emails == []


async def test_email_disabled_still_writes_row_but_skips_email(db_conn, auth_user_pool, sent_emails):
    user = auth_user_pool[2]
    user_id, _ = await make_client(db_conn, user)
    await db_conn.execute(
        "INSERT INTO notification_preferences (user_id, email_enabled) VALUES ($1, false)",
        user_id,
    )

    await create_notification(
        db_conn, user_id=user_id, category="business_updates", type="business_request_completed",
        title="Your request is ready", body="12 leads found.",
    )

    row = await db_conn.fetchrow("SELECT type FROM notifications WHERE user_id = $1", user_id)
    assert row["type"] == "business_request_completed"
    assert sent_emails == []


async def test_non_eligible_type_writes_row_but_skips_email(db_conn, auth_user_pool, sent_emails):
    user = auth_user_pool[3]
    user_id, _ = await make_client(db_conn, user)

    await create_notification(
        db_conn, user_id=user_id, category="business_updates", type="business_request_submitted",
        title="Request submitted", body="We're on it.",
    )

    row = await db_conn.fetchrow("SELECT type FROM notifications WHERE user_id = $1", user_id)
    assert row["type"] == "business_request_submitted"
    assert sent_emails == []


async def test_notify_admins_with_permission_reaches_super_admin_and_permission_holder(
    db_conn, auth_user_pool, sent_emails,
):
    super_admin = auth_user_pool[4]
    await make_user(db_conn, super_admin["id"], super_admin["email"], platform_role="super_admin")

    support_admin = auth_user_pool[5]
    await make_user(db_conn, support_admin["id"], support_admin["email"], platform_role="admin")
    await grant_permission(db_conn, support_admin["id"], "support_admin")

    other_admin = auth_user_pool[6]
    await make_user(db_conn, other_admin["id"], other_admin["email"], platform_role="admin")
    await grant_permission(db_conn, other_admin["id"], "billing_admin")

    await notify_admins_with_permission(
        db_conn, permission_key="support_admin",
        category="support", type="new_support_ticket",
        title="New support ticket", body="Acme Corp opened a ticket.",
    )

    # Subset check, not exact-set equality: the shared local dev DB can carry other
    # real super_admin rows from outside this test (they'd legitimately match too,
    # per the "super_admins hold every permission implicitly" rule) — this asserts
    # our two seeded users are reached and the non-holder is not, without assuming
    # the table is otherwise empty.
    recipients = {e["to"] for e in sent_emails}
    assert {super_admin["email"], support_admin["email"]} <= recipients
    assert other_admin["email"] not in recipients


async def test_new_people_lead_request_notifies_people_leads_admins(
    client, db_conn, auth_user_pool, make_headers, sent_emails,
):
    """Real HTTP creation, not the notify_admins_with_permission unit above —
    confirms people_leads.py's create endpoint actually fires it."""
    client_user = auth_user_pool[0]
    await make_client(db_conn, client_user, plan_id="pro")
    client_headers = make_headers(client_user)

    pl_admin = auth_user_pool[1]
    await make_admin(db_conn, pl_admin, permissions=["people_leads_admin"])

    unrelated_admin = auth_user_pool[2]
    await make_admin(db_conn, unrelated_admin, permissions=["support_admin"])

    resp = await client.post(
        "/people-leads/requests",
        json={"request_name": "Notify Admins Test", "lead_type": "other", "state": "FL", "requested_quantity": 10},
        headers=client_headers,
    )
    assert resp.status_code == 201, resp.text

    row = await db_conn.fetchrow(
        "SELECT type FROM notifications WHERE user_id = $1 AND type = 'new_people_request'", pl_admin["id"],
    )
    assert row is not None

    recipients = {e["to"] for e in sent_emails}
    assert pl_admin["email"] in recipients
    assert unrelated_admin["email"] not in recipients


async def test_assigning_people_lead_request_notifies_the_assigned_admin(
    client, db_conn, auth_user_pool, make_headers, sent_emails,
):
    client_user = auth_user_pool[3]
    await make_client(db_conn, client_user, plan_id="pro")
    client_headers = make_headers(client_user)

    pl_admin = auth_user_pool[4]
    await make_admin(db_conn, pl_admin, permissions=["people_leads_admin"])
    admin_headers = make_headers(pl_admin)

    create_resp = await client.post(
        "/people-leads/requests",
        json={"request_name": "Assign Notify Test", "lead_type": "other", "state": "FL", "requested_quantity": 10},
        headers=client_headers,
    )
    request_id = create_resp.json()["id"]
    sent_emails.clear()  # ignore the new-request email from creation above

    assign_resp = await client.post(
        f"/admin/people-leads/requests/{request_id}/assign",
        json={"admin_user_id": str(pl_admin["id"])},
        headers=admin_headers,
    )
    assert assign_resp.status_code == 200, assign_resp.text

    row = await db_conn.fetchrow(
        "SELECT type, body FROM notifications WHERE user_id = $1 AND type = 'people_request_assigned'", pl_admin["id"],
    )
    assert row is not None
    assert "Assign Notify Test" in row["body"]
    assert any(e["to"] == pl_admin["email"] for e in sent_emails)
