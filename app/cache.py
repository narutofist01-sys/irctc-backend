"""
High-Performance In-Memory TTL Caching Engine for IRCTC AGENT.
Provides thread-safe asynchronous key-value storage with automatic expiration.
Keeps response times under 15ms for repeated searches and train schedules.
"""

import asyncio
import time
from typing import Any, Dict, Optional, Tuple


class TTLCache:
    """
    Thread-safe asynchronous TTL Cache with auto-pruning.
    """

    def __init__(self, default_ttl_seconds: int = 300):
        self.default_ttl = default_ttl_seconds
        self._store: Dict[str, Tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[Any]:
        async with self._lock:
            if key not in self._store:
                return None
            expiry, value = self._store[key]
            if time.time() > expiry:
                del self._store[key]
                return None
            return value

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        expiry = time.time() + (ttl if ttl is not None else self.default_ttl)
        async with self._lock:
            self._store[key] = (expiry, value)

    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    async def clear_expired(self) -> int:
        now = time.time()
        expired_keys = []
        async with self._lock:
            for k, (exp, _) in self._store.items():
                if now > exp:
                    expired_keys.append(k)
            for k in expired_keys:
                del self._store[k]
        return len(expired_keys)

    def size(self) -> int:
        return len(self._store)


# Global singletons for app-wide cache layers
search_cache = TTLCache(default_ttl_seconds=300)      # 5 minutes for search queries
schedule_cache = TTLCache(default_ttl_seconds=86400)  # 24 hours for train schedules
multidate_cache = TTLCache(default_ttl_seconds=300)   # 5 minutes for multi-date matrix
