"""
One full walk of the real People Leads state machine: create -> assign -> upload
(exercising real column-matching/dedup logic against an in-memory CSV) -> review
(both the approve AND reject branches -- reject goes to 'cleaning_data', not
'revision_required', an easy detail to get backwards) -> deliver -> the client sees
Completed + a working download_url + the right notification at each step.
"""

import pytest

from tests.factories import make_admin, make_client

pytestmark = pytest.mark.asyncio(loop_scope="session")

CSV_CONTENT = (
    b"name,phone,email\n"
    b"John Doe,305-555-1234,john@example.com\n"
    b"Jane Smith,305-555-5678,jane@example.com\n"
)


async def test_full_people_leads_lifecycle(client, db_conn, auth_user_pool, make_headers):
    client_user = auth_user_pool[0]
    client_id, org_id = await make_client(db_conn, client_user, plan_id="pro")
    client_headers = make_headers(client_user)

    admin_user = auth_user_pool[1]
    await make_admin(db_conn, admin_user, permissions=["people_leads_admin", "support_admin"])
    admin_headers = make_headers(admin_user)

    # 1. Client creates request
    create_resp = await client.post(
        "/people-leads/requests",
        json={"request_name": "Test Lifecycle", "lead_type": "property_owners", "state": "FL", "requested_quantity": 10},
        headers=client_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    request_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "Submitted"

    submitted_count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM notifications WHERE user_id = $1 AND type = 'people_request_submitted'", client_id
    )
    assert submitted_count == 1

    # 2. Admin assigns
    assign_resp = await client.post(
        f"/admin/people-leads/requests/{request_id}/assign",
        json={"admin_user_id": str(admin_user["id"])},
        headers=admin_headers,
    )
    assert assign_resp.status_code == 200, assign_resp.text
    assert assign_resp.json()["internal_status"] == "assigned"

    client_view = await client.get(f"/people-leads/requests/{request_id}", headers=client_headers)
    assert client_view.json()["status"] == "Processing"

    # 3. Admin uploads — exercises real column-matching + phone/email validation/dedup
    upload_resp = await client.post(
        f"/admin/people-leads/requests/{request_id}/upload",
        files={"file": ("leads.csv", CSV_CONTENT, "text/csv")},
        headers=admin_headers,
    )
    assert upload_resp.status_code == 200, upload_resp.text
    assert upload_resp.json()["accepted_rows"] == 2
    assert upload_resp.json()["rejected_rows"] == 0

    detail = await client.get(f"/admin/people-leads/requests/{request_id}", headers=admin_headers)
    assert detail.json()["internal_status"] == "quality_review"

    # 4a. Reject branch — kicked back for rework, NOT revision_required
    reject_resp = await client.post(
        f"/admin/people-leads/requests/{request_id}/review",
        json={"decision": "reject", "notes": "bad data"},
        headers=admin_headers,
    )
    assert reject_resp.status_code == 200, reject_resp.text
    assert reject_resp.json()["internal_status"] == "cleaning_data"

    # re-upload to reach quality_review again for the approve path
    await client.post(
        f"/admin/people-leads/requests/{request_id}/upload",
        files={"file": ("leads2.csv", CSV_CONTENT, "text/csv")},
        headers=admin_headers,
    )

    # 4b. Approve branch
    approve_resp = await client.post(
        f"/admin/people-leads/requests/{request_id}/review",
        json={"decision": "approve", "notes": "looks good"},
        headers=admin_headers,
    )
    assert approve_resp.status_code == 200, approve_resp.text
    assert approve_resp.json()["internal_status"] == "approved"

    # 5. Deliver
    deliver_resp = await client.post(
        f"/admin/people-leads/requests/{request_id}/deliver",
        json={},
        headers=admin_headers,
    )
    assert deliver_resp.status_code == 200, deliver_resp.text
    assert deliver_resp.json()["internal_status"] == "delivered"
    assert deliver_resp.json()["client_status"] == "Completed"

    # Client sees Completed + a working download_url + the completion notification
    client_final = await client.get(f"/people-leads/requests/{request_id}", headers=client_headers)
    assert client_final.json()["status"] == "Completed"
    assert client_final.json()["download_url"]

    completed_count = await db_conn.fetchval(
        "SELECT COUNT(*) FROM notifications WHERE user_id = $1 AND type = 'people_request_completed'", client_id
    )
    assert completed_count == 1
