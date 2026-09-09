"""
Lead file download/rename scoping, plus stats/charts response shape. Cross-org GET
access is already covered by test_organization_isolation.py -- this file covers the
PATCH (rename) and download mutation paths specifically, and the aggregate endpoints.
"""

import pytest

from tests.factories import make_client, make_lead_file

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_owner_can_list_stats_charts_download_and_rename(client, db_conn, auth_user_pool, make_headers):
    owner = auth_user_pool[0]
    owner_id, org_id = await make_client(db_conn, owner)
    file_id = await make_lead_file(db_conn, org_id, owner_id, record_count=25)
    headers = make_headers(owner)

    list_resp = await client.get("/lead-files", headers=headers)
    assert list_resp.status_code == 200
    assert any(f["id"] == str(file_id) for f in list_resp.json())

    stats_resp = await client.get("/lead-files/stats", headers=headers)
    assert stats_resp.status_code == 200
    assert stats_resp.json()["total_files"] >= 1

    charts_resp = await client.get("/lead-files/charts", headers=headers)
    assert charts_resp.status_code == 200
    assert "business_vs_people" in charts_resp.json()

    download_resp = await client.get(f"/lead-files/{file_id}/download", headers=headers)
    assert download_resp.status_code == 200
    assert download_resp.json()["url"]

    rename_resp = await client.patch(f"/lead-files/{file_id}", json={"display_name": "Renamed File"}, headers=headers)
    assert rename_resp.status_code == 200
    assert rename_resp.json()["display_name"] == "Renamed File"


async def test_cross_org_user_cannot_rename_or_download(client, db_conn, auth_user_pool, make_headers):
    owner = auth_user_pool[1]
    owner_id, org_id = await make_client(db_conn, owner)
    file_id = await make_lead_file(db_conn, org_id, owner_id)

    outsider = auth_user_pool[2]
    await make_client(db_conn, outsider)
    headers = make_headers(outsider)

    rename_resp = await client.patch(f"/lead-files/{file_id}", json={"display_name": "Stolen"}, headers=headers)
    assert rename_resp.status_code == 404

    download_resp = await client.get(f"/lead-files/{file_id}/download", headers=headers)
    assert download_resp.status_code == 404
