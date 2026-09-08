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


# create_all only creates missing TABLES -- it never alters existing ones. Columns added to
# a table after a DB already exists must be listed here so _migrate() can ALTER them in
# (SQLite supports ADD COLUMN), preserving already-researched character data instead of
# forcing a DB reset. Swap for Alembic if the schema outgrows this.
_COLUMN_MIGRATIONS = {
    "verdicts": [
        ("win_probability_a", "INTEGER"),
        ("win_probability_b", "INTEGER"),
        ("tie_probability", "INTEGER"),
    ],
    "matchups": [
        ("pending_review_json", "TEXT"),
    ],
}


# SQLite cannot alter an inline UNIQUE constraint, so tables whose *constraints* changed are
# dropped and recreated by create_all instead. Only safe for derived data that can be
# regenerated on demand -- never for researched characters or matchup history.
# {table: sentinel column whose absence means "old shape, rebuild"}
_TABLE_REBUILDS = {
    "cinematic_scenes": "scenario",
}


def _migrate(conn) -> None:
    from sqlalchemy import text

    is_sqlite = conn.dialect.name == "sqlite"

    def columns_of(table: str) -> set:
        if is_sqlite:
            return {row[1] for row in conn.execute(text(f'PRAGMA table_info("{table}")'))}
        # Postgres: PRAGMA doesn't exist -- read the catalog instead. An empty set for a
        # table that isn't there yet means the same thing as the SQLite branch above.
        return {
            row[0]
            for row in conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
                {"t": table},
            )
        }

    for table, columns in _COLUMN_MIGRATIONS.items():
        existing = columns_of(table)
        if not existing:
            continue  # table doesn't exist yet; create_all just made it with all columns
        for name, ddl_type in columns:
            if name not in existing:
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {name} {ddl_type}'))

    for table, sentinel in _TABLE_REBUILDS.items():
        existing = columns_of(table)
        if existing and sentinel not in existing:
            conn.execute(text(f'DROP TABLE "{table}"'))


async def init_db() -> None:
    """Creates all tables, applies additive column migrations, and seeds reference data."""
    from src.db import models  # noqa: F401  (import registers ORM classes onto Base.metadata)
    from src.db.seed import seed_catalog

    async with engine.begin() as conn:
        await conn.run_sync(_migrate)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await seed_catalog(session)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
