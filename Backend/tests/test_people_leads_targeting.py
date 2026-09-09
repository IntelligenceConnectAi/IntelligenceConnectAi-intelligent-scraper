"""
The one spot in the People Leads business-targeting feature with real collision
risk: targeting_filters_json is shared with the pre-existing admin-revision-
message scratch key (written via `||`, deleted via `- 'key'` in
people_leads.py::respond_people_lead_request). Confirms a client's submitted
`targeting` survives an admin's request-revision round trip untouched, and that
`admin_revision_message` never leaks into a client-facing response.
"""

import pytest

from tests.factories import make_admin, make_client

pytestmark = pytest.mark.asyncio(loop_scope="session")

TARGETING_PAYLOAD = {
    "business_name": "ABC Plumbing",
    "business_type": {"id": "plumbing", "name": "Plumbing", "category": "HOME SERVICES — EMERGENCY", "is_other": False},
    "target_audience": "Consumers",
    "filter_stacks": ["bal"],
    "cities": ["Miami", "Fort Lauderdale"],
}


async def test_targeting_roundtrips_and_survives_admin_revision(client, db_conn, auth_user_pool, make_headers):
    client_user = auth_user_pool[4]
    client_id, org_id = await make_client(db_conn, client_user, plan_id="pro")
    client_headers = make_headers(client_user)

    admin_user = auth_user_pool[5]
    await make_admin(db_conn, admin_user, permissions=["people_leads_admin"])
    admin_headers = make_headers(admin_user)

    # 1. Create with a populated targeting object.
    create_resp = await client.post(
        "/people-leads/requests",
        json={
            "request_name": "Targeting Roundtrip", "lead_type": "other", "state": "FL",
            "city": "Miami", "zip_codes": [], "requested_quantity": 25,
            "targeting": TARGETING_PAYLOAD,
        },
        headers=client_headers,
    )
    assert create_resp.status_code == 201, create_resp.text
    request_id = create_resp.json()["id"]
    assert create_resp.json()["targeting"] == TARGETING_PAYLOAD

    # 2. GET as the client — confirm it round-trips, both detail and list.
    detail_resp = await client.get(f"/people-leads/requests/{request_id}", headers=client_headers)
    assert detail_resp.json()["targeting"] == TARGETING_PAYLOAD

    list_resp = await client.get("/people-leads/requests", headers=client_headers)
    listed = next(r for r in list_resp.json() if r["id"] == request_id)
    assert listed["targeting"] == TARGETING_PAYLOAD

    # 3. Admin requests revision — writes admin_revision_message into the same
    # jsonb column via a non-destructive `||` merge.
    revision_resp = await client.post(
        f"/admin/people-leads/requests/{request_id}/request-revision",
        json={"message": "Please confirm the ZIP codes you want covered."},
        headers=admin_headers,
    )
    assert revision_resp.status_code == 200, revision_resp.text
    # Admin's own response legitimately sees the raw blob with both keys.
    assert revision_resp.json()["targeting_filters_json"]["targeting"] == TARGETING_PAYLOAD
    assert "admin_revision_message" in revision_resp.json()["targeting_filters_json"]

    # 4. Re-GET as the client: targeting still intact, revision message never leaks.
    needs_info_resp = await client.get(f"/people-leads/requests/{request_id}", headers=client_headers)
    body = needs_info_resp.json()
    assert body["status"] == "Needs Information"
    assert body["targeting"] == TARGETING_PAYLOAD
    assert "admin_revision_message" not in body
    assert "Please confirm the ZIP codes" in body["message"]  # surfaced via `message`, not a raw field

    # 5. Client responds — clears admin_revision_message, targeting must survive.
    respond_resp = await client.post(
        f"/people-leads/requests/{request_id}/respond",
        json={"client_instructions": "Cover all of Miami-Dade county."},
        headers=client_headers,
    )
    assert respond_resp.status_code == 200, respond_resp.text
    assert respond_resp.json()["targeting"] == TARGETING_PAYLOAD
