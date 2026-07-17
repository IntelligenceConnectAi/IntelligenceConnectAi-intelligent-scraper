from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import close_db_pool, init_db_pool
from app.routers import auth, plans, usage, jobs, billing, register


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


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}
