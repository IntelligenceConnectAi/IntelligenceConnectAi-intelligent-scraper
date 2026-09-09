from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import close_db_pool, init_db_pool
from app.routers import (
    auth, plans, usage, jobs, billing, register, admin, client_business, dashboard,
    people_leads, admin_people_leads, lead_files, history,
    organization, notifications, integrations,
    support, admin_support,
    admin_clients, admin_jobs, admin_lead_files, admin_audit_logs, admin_dashboard,
    campaign_organizer,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db_pool()
    yield
    await close_db_pool()


app = FastAPI(
    title="Intelligent Scraper API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router,     prefix="/auth",     tags=["auth"])
app.include_router(register.router, prefix="/auth",     tags=["auth"])
app.include_router(plans.router,    prefix="/plans",    tags=["plans"])
app.include_router(usage.router,    prefix="/usage",    tags=["usage"])
app.include_router(jobs.router,     prefix="/jobs",     tags=["jobs"])
app.include_router(billing.router,  prefix="/billing",  tags=["billing"])
app.include_router(admin.router,    prefix="/admin",    tags=["admin"])
app.include_router(client_business.router, prefix="/client/business-requests", tags=["client"])
app.include_router(dashboard.router, prefix="/dashboard/client", tags=["client"])
app.include_router(people_leads.router, prefix="/people-leads/requests", tags=["people-leads"])
app.include_router(admin_people_leads.router, prefix="/admin/people-leads/requests", tags=["admin"])
app.include_router(lead_files.router, prefix="/lead-files", tags=["lead-files"])
app.include_router(history.router,    prefix="/history",    tags=["history"])
app.include_router(organization.router, prefix="/organization", tags=["organization"])
app.include_router(notifications.router,             prefix="/notifications",             tags=["notifications"])
app.include_router(notifications.preferences_router,  prefix="/notification-preferences",  tags=["notifications"])
app.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
app.include_router(support.router, prefix="/support/tickets", tags=["support"])
app.include_router(admin_support.router, prefix="/admin/support/tickets", tags=["admin"])
app.include_router(admin_clients.router, prefix="/admin/clients", tags=["admin"])
app.include_router(admin_jobs.router, prefix="/admin/jobs", tags=["admin"])
app.include_router(admin_lead_files.router, prefix="/admin/lead-files", tags=["admin"])
app.include_router(admin_audit_logs.router, prefix="/admin/audit-logs", tags=["admin"])
app.include_router(admin_dashboard.router, prefix="/admin/dashboard", tags=["admin"])
app.include_router(campaign_organizer.router, prefix="/campaign-organizer", tags=["campaign-organizer"])


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}
