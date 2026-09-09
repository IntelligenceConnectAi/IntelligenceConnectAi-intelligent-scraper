"""
Support ticket creation — the net-new admin-notification hook (§ email
notifications plan): a new ticket must notify every support_admin (and
super_admins, who hold every permission implicitly), on top of its existing
behavior of creating the ticket + first message.
"""

import pytest

from tests.factories import make_admin, make_client

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_create_ticket_notifies_support_admins(client, db_conn, auth_user_pool, make_headers):
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner, org_name="Acme Corp")

    support_admin = auth_user_pool[1]
    await make_admin(db_conn, support_admin, platform_role="admin", permissions=["support_admin"])

    other_admin = auth_user_pool[2]
    await make_admin(db_conn, other_admin, platform_role="admin", permissions=["billing_admin"])

    resp = await client.post(
        "/support/tickets",
        data={"subject": "Can't download my file", "category": "file_download", "body": "The link 404s."},
        headers=make_headers(owner),
    )
    assert resp.status_code == 201
    ticket_id = resp.json()["id"]

    admin_notif = await db_conn.fetchrow(
        "SELECT type, body FROM notifications WHERE user_id = $1 AND type = 'new_support_ticket'",
        support_admin["id"],
    )
    assert admin_notif is not None
    assert "Acme Corp" in admin_notif["body"]
    assert "Can't download my file" in admin_notif["body"]

    no_notif = await db_conn.fetchval(
        "SELECT id FROM notifications WHERE user_id = $1 AND type = 'new_support_ticket'",
        other_admin["id"],
    )
    assert no_notif is None

    # Ticket itself was still created normally — the notification hook is additive.
    ticket_row = await db_conn.fetchrow("SELECT subject FROM support_tickets WHERE id = $1", ticket_id)
    assert ticket_row["subject"] == "Can't download my file"
