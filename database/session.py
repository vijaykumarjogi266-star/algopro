"""Algo Lab Async Database Session Management.

Provides async SQLAlchemy engine, session factories, and database connectivity checks.
"""

from typing import AsyncGenerator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.api.core.config import settings
from apps.api.core.logging import get_logger

logger = get_logger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG and settings.ENVIRONMENT == "development",
    future=True,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding database session with automatic cleanup."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_health() -> dict:
    """Performs a lightweight ping against PostgreSQL to verify connectivity."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            val = result.scalar()
            return {
                "status": "connected" if val == 1 else "unhealthy",
                "database": settings.POSTGRES_DB,
                "host": settings.POSTGRES_HOST,
            }
    except Exception as exc:
        logger.warning("Database health check ping failed", extra={"error": str(exc)})
        return {
            "status": "disconnected",
            "database": settings.POSTGRES_DB,
            "host": settings.POSTGRES_HOST,
            "error": str(exc),
        }
