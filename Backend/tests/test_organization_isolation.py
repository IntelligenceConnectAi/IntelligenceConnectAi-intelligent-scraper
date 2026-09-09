"""
The highest-value security test category: cross-tenant data isolation.

Two distinct scoping rules exist in this codebase and a generic "cross-org 404"
helper would silently miss the difference between them:
  - jobs.py scopes by user_id (per-user, not org-wide) — confirmed by reading it.
  - people_lead_requests / lead_files / support_tickets scope by organization_id
    (any active member of the org can see any of them) — confirmed in Phases 4/5/7.

So this file tests BOTH cross-org access (404 for all four resource types) AND the
same-org-different-member case, which only actually distinguishes the two scoping
rules (jobs -> 404, the other three -> 200).
"""

import pytest

from tests.factories import (
    add_member,
    make_client,
    make_job,
    make_lead_file,
    make_people_lead_request,
    make_support_ticket,
    make_user,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _make_org_with_resources(conn, owner_auth_user):
    owner_id, org_id = await make_client(conn, owner_auth_user)
    job_id = await make_job(conn, owner_id, status="done", total_clean=5)
    request_id = await make_people_lead_request(conn, org_id, owner_id)
    file_id = await make_lead_file(conn, org_id, owner_id)
    ticket_id = await make_support_ticket(conn, org_id, owner_id)
    return {
        "owner_id": owner_id, "org_id": org_id, "job_id": job_id,
        "request_id": request_id, "file_id": file_id, "ticket_id": ticket_id,
    }


async def test_cross_org_access_is_rejected_for_every_resource_type(client, db_conn, auth_user_pool, make_headers):
    org_a = await _make_org_with_resources(db_conn, auth_user_pool[0])

    outsider = auth_user_pool[1]
    await make_client(db_conn, outsider)
    headers = make_headers(outsider)

    assert (await client.get(f"/jobs/{org_a['job_id']}", headers=headers)).status_code == 404
    assert (await client.get(f"/people-leads/requests/{org_a['request_id']}", headers=headers)).status_code == 404
    assert (await client.get(f"/lead-files/{org_a['file_id']}", headers=headers)).status_code == 404
    assert (await client.get(f"/support/tickets/{org_a['ticket_id']}", headers=headers)).status_code == 404


async def test_same_org_scoping_differs_by_resource_type(client, db_conn, auth_user_pool, make_headers):
    owner = auth_user_pool[2]
    org = await _make_org_with_resources(db_conn, owner)

    teammate = auth_user_pool[3]
    await make_user(db_conn, teammate["id"], teammate["email"], platform_role="client")
    await add_member(db_conn, org["org_id"], teammate["id"], role="client_member")
    headers = make_headers(teammate)

    # jobs.py is per-user scoped — a teammate in the SAME org still cannot see a job
    # they didn't create. This is the case a generic cross-org helper would miss.
    job_resp = await client.get(f"/jobs/{org['job_id']}", headers=headers)
    assert job_resp.status_code == 404

    # These three are genuinely org-wide — any active member sees any org resource.
    assert (await client.get(f"/people-leads/requests/{org['request_id']}", headers=headers)).status_code == 200
    assert (await client.get(f"/lead-files/{org['file_id']}", headers=headers)).status_code == 200
    assert (await client.get(f"/support/tickets/{org['ticket_id']}", headers=headers)).status_code == 200
