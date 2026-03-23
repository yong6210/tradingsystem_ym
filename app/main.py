from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.execution_routes import router as execution_router
from app.api.routes import router
from app.core.config import get_settings
from app.db.session import init_db

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


app.include_router(router, prefix=settings.api_prefix)
app.include_router(execution_router, prefix=settings.api_prefix)
