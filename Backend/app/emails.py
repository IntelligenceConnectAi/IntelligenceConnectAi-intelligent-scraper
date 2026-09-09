"""
Email delivery for notifications (Resend) — see app/notifications.py for the
single hook point that calls this. Every notification-worthy event already
has a title/body written for the in-app row; this module wraps that same copy
in an HTML shell rather than maintaining a second, driftable set of per-event
templates.

The frontend has no URL-based routing (ClientApp/AdminApp use in-memory
useState navigation, not react-router), so email CTAs can only point at the
app root (settings.frontend_base_url) — not a specific deep-linked tab.
"""

import html
import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)

# Only these notification `type`s get an email — every existing call site's
# title/body still writes an in-app row regardless; this just gates the
# additive email step. Add to this set to extend coverage later — no call
# site changes needed.
EMAIL_ELIGIBLE_TYPES = {
    "payment_failure",
    "payment_disputed",
    "business_request_completed",
    "business_request_failed",
    "support_response",
    "team_invitation",
    "new_support_ticket",
    "people_request_completed",
    "new_people_request",
    "new_business_request",
    "people_request_assigned",
}


async def send_email(*, to: str, subject: str, html_body: str) -> None:
    """Never raises — a failed/unsent email must never break the caller
    (matches the create_notification isolation posture)."""
    if settings.email_mode != "send":
        log.info(f"[email:log-mode] to={to} subject={subject!r}")
        return

    if not settings.resend_api_key or not settings.email_from_address:
        log.warning(f"[email] EMAIL_MODE=send but resend_api_key/email_from_address unset — skipping to={to}")
        return

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                json={
                    "from": settings.email_from_address,
                    "to": [to],
                    "subject": subject,
                    "html": html_body,
                },
            )
            resp.raise_for_status()
    except Exception as e:
        log.error(f"[email] send failed to={to} subject={subject!r}: {e}", exc_info=True)


def render_notification_email(*, title: str, body: str, cta_label: str = "Open your dashboard") -> str:
    """Single-column, inline-CSS shell (email clients need inline styles, not
    a stylesheet). title/body come from call sites that interpolate
    user-controlled data (ticket subjects, org names) — must be escaped
    before landing in HTML, or it's an injection vector in email clients."""
    safe_title = html.escape(title)
    safe_body = html.escape(body)
    dashboard_url = settings.frontend_base_url

    return f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#f4f5fa;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;background:#ffffff;border-radius:12px;overflow:hidden;border:1px solid #e5e7f0;">
            <tr>
              <td style="padding:24px 28px;border-bottom:1px solid #e5e7f0;">
                <span style="font-size:15px;font-weight:700;color:#12131f;letter-spacing:-0.01em;">Intelligent Scraper</span>
              </td>
            </tr>
            <tr>
              <td style="padding:28px;">
                <h1 style="margin:0 0 12px;font-size:18px;font-weight:700;color:#12131f;">{safe_title}</h1>
                <p style="margin:0 0 24px;font-size:14px;line-height:1.6;color:#454a63;">{safe_body}</p>
                <a href="{dashboard_url}" style="display:inline-block;background:#00A187;color:#ffffff;text-decoration:none;font-size:14px;font-weight:600;padding:10px 20px;border-radius:8px;">{html.escape(cta_label)}</a>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 28px;background:#f7f8fc;border-top:1px solid #e5e7f0;">
                <p style="margin:0;font-size:12px;color:#8a8fa3;">
                  You're receiving this because you have an Intelligent Scraper account.
                  Manage notification preferences in Settings.
                </p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
