"""Process-wide connection pool."""
from typing import Optional

from db.driver import Pool, connect_pool

_POOL: Optional[Pool] = None


def open_pool(dsn: str, size: int = 4) -> Pool:
    """Opens the connection pool for dsn and keeps it in the module. Call it once per process: a second
    call replaces the stored pool without closing it, which leaks the first pool's sockets."""
    global _POOL
    _POOL = connect_pool(dsn, size=size)
    return _POOL


def close_pool() -> None:
    """Close."""
    global _POOL
    _POOL.close()
    _POOL = None
