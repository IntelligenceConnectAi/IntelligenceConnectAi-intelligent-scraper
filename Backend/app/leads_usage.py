"""
Shared usage-window logic, used by both app/routers/dashboard.py (display) and
app/routers/people_leads.py (the create-request limit check) — kept in one place
so the two can never silently disagree about what "this period" means or how much
of it has been used.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg


def compute_period_window(current_period_end: Optional[datetime]) -> tuple[Optional[datetime], Optional[datetime]]:
    """Billing-cycle window when we have one; otherwise the caller should fall back
    to a calendar-month query (see get_leads_used_period). Assumes a monthly cycle —
    fine today (checkout only wires monthly Stripe prices), will need a stored
    period_start once annual billing exists."""
    if current_period_end:
        return current_period_end - timedelta(days=30), current_period_end
    return None, None


async def get_leads_used_period(
    conn: asyncpg.Connection,
    user_id,
    org_id,
    current_period_end: Optional[datetime],
) -> int:
    """Business leads (jobs.total_clean, by user_id) + delivered People Leads
    (people_lead_requests.delivered_quantity, by org_id), same window for both."""
    period_start, period_end = compute_period_window(current_period_end)

    if period_start:
        business_used = await conn.fetchval(
            """
            SELECT COALESCE(SUM(total_clean), 0) FROM jobs
            WHERE user_id = $1 AND status = 'done'
              AND completed_at >= $2 AND completed_at <= $3
            """,
            user_id, period_start, period_end,
        )
        people_used = await conn.fetchval(
            """
            SELECT COALESCE(SUM(delivered_quantity), 0) FROM people_lead_requests
            WHERE organization_id = $1 AND client_status = 'Completed'
              AND completed_at >= $2 AND completed_at <= $3
            """,
            org_id, period_start, period_end,
        )
    else:
        business_used = await conn.fetchval(
            """
            SELECT COALESCE(SUM(total_clean), 0) FROM jobs
            WHERE user_id = $1 AND status = 'done'
              AND completed_at >= date_trunc('month', NOW())
            """,
            user_id,
        )
        people_used = await conn.fetchval(
            """
            SELECT COALESCE(SUM(delivered_quantity), 0) FROM people_lead_requests
            WHERE organization_id = $1 AND client_status = 'Completed'
              AND completed_at >= date_trunc('month', NOW())
            """,
            org_id,
        )

    return (business_used or 0) + (people_used or 0)


async def get_effective_monthly_limit(
    conn: asyncpg.Connection,
    org_id,
    plan_monthly_limit: Optional[int],
    current_period_end: Optional[datetime],
) -> int:
    """plan_monthly_limit + any 'paid' lead_topups whose stamped period_end matches
    the CURRENT period (see migrations/0012_lead_topups.sql). Keyed by org_id, not
    user_id, matching how the base plan limit is already treated as an org-wide
    pool elsewhere in this file. A topup can only ever be purchased against a real
    current_period_end (see billing.py::create_topup_checkout), so there's nothing
    to look up when there's no active subscription."""
    if not plan_monthly_limit or not current_period_end:
        return plan_monthly_limit or 0
    topup_total = await conn.fetchval(
        """
        SELECT COALESCE(SUM(package_size), 0) FROM lead_topups
        WHERE organization_id = $1 AND status = 'paid' AND period_end = $2
        """,
        org_id, current_period_end,
    )
    return plan_monthly_limit + (topup_total or 0)


def days_until(target: Optional[datetime]) -> Optional[int]:
    if not target:
        return None
    import math
    now = datetime.now(timezone.utc)
    return max(0, math.ceil((target - now).total_seconds() / 86400))
