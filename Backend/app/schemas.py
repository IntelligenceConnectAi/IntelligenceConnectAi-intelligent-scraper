"""
Pydantic response models — matched to DB rows and views.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class User(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    full_name: str | None = None
    is_admin: bool = False
    is_active: bool = True
    created_at: datetime


class Plan(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    price_monthly: Decimal
    leads_per_month: int
    leads_per_day: int
    cities_per_job: int
    keywords_per_job: int
    history_days: int
    concurrent_jobs: int
    email_scraping: bool
    api_access: bool


class CurrentPlanResponse(BaseModel):
    """From user_current_plan view."""
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    email: str
    plan_id: str | None = None
    plan_name: str | None = None
    price_monthly: Decimal | None = None
    daily_limit: int | None = None
    monthly_limit: int | None = None
    cities_per_job: int | None = None
    concurrent_jobs: int | None = None
    email_scraping: bool | None = None
    api_access: bool | None = None
    subscription_status: str | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool | None = None


class TodayUsageResponse(BaseModel):
    """From user_today_usage view."""
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    email: str
    daily_limit: int | None = None
    leads_used_today: int
    leads_with_web_today: int
    leads_no_web_today: int
    emails_found_today: int
    jobs_run_today: int
    leads_remaining: int


# ─────────────────────────────────────────────────────
# JOB SCHEMAS
# ─────────────────────────────────────────────────────
class CreateJobRequest(BaseModel):
    industry: str
    state: str
    cities: List[str]

    @field_validator("cities")
    @classmethod
    def cities_not_empty(cls, v):
        if not v:
            raise ValueError("At least one city is required")
        return v


class JobCityProgress(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    city: str
    maps_status: str
    maps_leads: Optional[int] = 0


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    industry: str
    state: str
    cities: List[str]
    status: str
    current_step: Optional[str] = None
    current_city: Optional[str] = None
    cities_done: int = 0
    cities_total: int = 0
    total_raw: int = 0
    total_clean: int = 0
    with_website: int = 0
    no_website: int = 0
    emails_found: int = 0
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    city_progress: List[JobCityProgress] = []


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    industry: str
    state: str
    cities: List[str]
    status: str
    total_clean: int = 0
    emails_found: int = 0
    created_at: datetime
    completed_at: Optional[datetime] = None