"""
Intelligent Scraper — Replica Autoscaler

Run-to-completion script, triggered on a schedule (Railway cron, every 5
minutes — see railway.com project settings for this service) rather than a
persistent process: it only needs to sample state and maybe issue one API
call, so a long-running process here would just be more always-on cost,
undermining the entire point of this script.

Scaling rule, deliberately asymmetric:
  - Scale UP to MAX_REPLICAS the moment any job is queued and we're below
    that ceiling. No reason to be slow about using capacity we're already
    paying to have available the moment there's real work waiting.
  - Scale DOWN to MIN_REPLICAS only when the ENTIRE fleet is confirmed
    idle — zero running AND zero pending jobs, fleet-wide, read fresh from
    the jobs table itself, not an approximation. Never while any job is
    active anywhere, so a replica is never removed out from under real
    work. Railway's own replica removal is a graceful drain (confirmed via
    their docs), but this rule means there's never anything TO drain in
    the first place — the replica being removed is always already idle.

Requires:
  DATABASE_URL       -- same Postgres connection the worker/API use.
  RAILWAY_API_TOKEN  -- a PROJECT token (not account/workspace) scoped to
                        this environment, created from the project's
                        Settings -> Tokens page. Authenticates via the
                        Project-Access-Token header, not Bearer -- see
                        https://docs.railway.com/integrations/api.
"""

import asyncio
import logging
import os

import asyncpg
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [autoscaler] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

RAILWAY_API = "https://backboard.railway.com/graphql/v2"
WORKER_SERVICE_ID = "3bdded2c-19e1-4a81-9fb2-e44d4b11ff41"
ENVIRONMENT_ID = "8f8d6ae1-9655-4846-af0a-95bf3a94b87e"

# Matches the validated Step 4 ceiling (3 replicas x MAX_GLOBAL_CONCURRENT=2 =
# 6 concurrent jobs, live-tested with zero double-claiming). MIN_REPLICAS=1
# (not 0) so a newly submitted job during an idle stretch always starts
# immediately -- no cold-start wait, since something is always polling.
MIN_REPLICAS = 1
MAX_REPLICAS = 3


async def _gql(client: httpx.AsyncClient, query: str, variables: dict) -> dict:
    resp = await client.post(
        RAILWAY_API,
        json={"query": query, "variables": variables},
        headers={
            "Project-Access-Token": os.environ["RAILWAY_API_TOKEN"],
            "Content-Type": "application/json",
        },
        timeout=15,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("errors"):
        raise RuntimeError(f"Railway API error: {body['errors']}")
    return body["data"]


async def _get_replicas(client: httpx.AsyncClient) -> int:
    data = await _gql(
        client,
        """
        query ($serviceId: String!, $environmentId: String!) {
            serviceInstance(serviceId: $serviceId, environmentId: $environmentId) {
                numReplicas
            }
        }
        """,
        {"serviceId": WORKER_SERVICE_ID, "environmentId": ENVIRONMENT_ID},
    )
    return data["serviceInstance"]["numReplicas"] or 1


async def _set_replicas(client: httpx.AsyncClient, n: int) -> None:
    await _gql(
        client,
        """
        mutation ($serviceId: String!, $environmentId: String!, $input: ServiceInstanceUpdateInput!) {
            serviceInstanceUpdate(serviceId: $serviceId, environmentId: $environmentId, input: $input)
        }
        """,
        {
            "serviceId": WORKER_SERVICE_ID,
            "environmentId": ENVIRONMENT_ID,
            "input": {"numReplicas": n},
        },
    )


async def main() -> None:
    from app.config import settings  # same DB settings the worker/API already use

    conn = await asyncpg.connect(settings.database_url, statement_cache_size=0)
    try:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                COUNT(*) FILTER (WHERE status = 'running') AS running
            FROM jobs
            """
        )
    finally:
        await conn.close()

    pending, running = row["pending"], row["running"]

    async with httpx.AsyncClient() as client:
        current = await _get_replicas(client)
        log.info(f"pending={pending} running={running} current_replicas={current}")

        if pending > 0 and current < MAX_REPLICAS:
            log.info(f"work queued and under capacity — scaling {current} -> {MAX_REPLICAS}")
            await _set_replicas(client, MAX_REPLICAS)
        elif pending == 0 and running == 0 and current > MIN_REPLICAS:
            log.info(f"fleet confirmed idle — scaling {current} -> {MIN_REPLICAS}")
            await _set_replicas(client, MIN_REPLICAS)
        else:
            log.info("no scaling change needed")


if __name__ == "__main__":
    asyncio.run(main())
