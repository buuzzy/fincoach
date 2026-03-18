from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker, AsyncEngine
from sqlalchemy.orm import DeclarativeBase
from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_async_session: async_sessionmaker[AsyncSession] | None = None


def _build_engine() -> AsyncEngine:
    """Create async engine with driver-specific options."""
    url = get_settings().effective_database_url

    # Supabase / PgBouncer in transaction mode does not support prepared statements.
    # Disable the statement cache so asyncpg works correctly.
    if url.startswith("postgresql"):
        connect_args = {"statement_cache_size": 0}
    else:
        connect_args = {}

    return create_async_engine(
        url,
        echo=False,
        connect_args=connect_args,
    )


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_async_session() -> async_sessionmaker[AsyncSession]:
    global _async_session
    if _async_session is None:
        _async_session = async_sessionmaker(get_engine(), class_=AsyncSession, expire_on_commit=False)
    return _async_session


# Convenience alias for backward compatibility
def async_session_factory():
    return get_async_session()


async def init_db():
    """Create all tables (no-op for Supabase where tables are pre-created via SQL)."""
    engine = get_engine()
    url = str(engine.url)
    if url.startswith("postgresql"):
        # Tables already created in Supabase via migration script — skip DDL
        import logging
        logging.getLogger(__name__).info("[db] PostgreSQL detected — skipping create_all (tables pre-exist)")
        return
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    session_maker = get_async_session()
    async with session_maker() as session:
        yield session


def reset_engine():
    """Reset engine and session (used in tests to pick up new DATABASE_URL)."""
    global _engine, _async_session
    _engine = None
    _async_session = None
