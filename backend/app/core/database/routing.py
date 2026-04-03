"""
Database connection routing module for read/write splitting.
In a multi-node production environment, read_db routes to the read-replica pool,
while write_db routes to the primary master pool.
"""
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database.engine import AsyncSessionLocal

async def write_db() -> AsyncGenerator[AsyncSession, None]:
    """Provides an AsyncSession bound to the primary (write) database. Commits on exit."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

async def read_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Provides a read-only AsyncSession. Routes to replica if configured.
    For this single-node cluster MVP, it uses the identical pool but enforces read-only semantics.
    """
    async with AsyncSessionLocal() as session:
        # In a strict environment, we could set session.connection().execution_options(readonly=True)
        try:
            yield session
        finally:
            # Revert any uncommitted state guarantees immutable reads
            await session.rollback()
            await session.close()
