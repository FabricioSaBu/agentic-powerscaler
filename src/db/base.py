"""
Async SQLAlchemy engine, session factory, and declarative base for the PowerScaler DB.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from src.core.config import settings

engine = create_async_engine(settings.database_url, echo=settings.debug)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Creates all tables and seeds reference/taxonomy data. Swap create_all for Alembic if the schema outgrows this."""
    from src.db import models  # noqa: F401  (import registers ORM classes onto Base.metadata)
    from src.db.seed import seed_catalog

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await seed_catalog(session)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
