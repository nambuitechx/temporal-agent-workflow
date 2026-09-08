"""Async engine + sessionmaker cho Postgres control-plane — giống
`app/core/db.py` bên synaptix-platform (mục 4 design doc). Cả `worker/` (đọc
registry trong Activity) và `backend/` (CRUD usecase) đều import module này.
"""
from __future__ import annotations

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://xora:xora@localhost:5432/xora_agent_loop",
)

# echo=False mặc định — bật qua SQL_ECHO=1 lúc debug cục bộ, không bật ở CI/prod.
_engine = create_async_engine(DATABASE_URL, echo=os.environ.get("SQL_ECHO") == "1", pool_pre_ping=True)

async_session_maker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
