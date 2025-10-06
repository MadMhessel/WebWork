"""Shared token-bucket rate limiter helpers for Telegram I/O."""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Dict, Optional


class TokenBucket:
    """Simple token bucket supporting sync and async acquisition."""

    def __init__(self, rate: float, capacity: Optional[float] = None) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = float(rate)
        self.capacity = float(capacity if capacity is not None else max(rate, 1.0))
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def _refill_locked(self) -> None:
        now = time.monotonic()
        delta = now - self._updated
        if delta <= 0:
            return
        self._tokens = min(self.capacity, self._tokens + delta * self.rate)
        self._updated = now

    def _reserve_locked(self, tokens: float) -> float:
        self._refill_locked()
        missing = tokens - self._tokens
        if missing <= 0:
            self._tokens -= tokens
            return 0.0
        wait = missing / self.rate
        return max(wait, 0.0)

    def consume(self, tokens: float = 1.0) -> None:
        """Synchronously wait until ``tokens`` are available."""

        if tokens <= 0:
            return
        while True:
            with self._lock:
                wait = self._reserve_locked(tokens)
            if wait <= 0:
                return
            time.sleep(wait)

    async def acquire(self, tokens: float = 1.0) -> None:
        """Asynchronously wait until ``tokens`` are available."""

        if tokens <= 0:
            return
        while True:
            with self._lock:
                wait = self._reserve_locked(tokens)
            if wait <= 0:
                return
            await asyncio.sleep(wait)


_global_bucket: Optional[TokenBucket] = None
_per_key_buckets: Dict[str, TokenBucket] = {}
_registry_lock = threading.Lock()


def configure_global(rate: float) -> None:
    """Reset global limiter to ``rate`` tokens per second."""

    if rate <= 0:
        raise ValueError("rate must be positive")
    bucket = TokenBucket(rate)
    with _registry_lock:
        global _global_bucket
        _global_bucket = bucket
        _per_key_buckets.clear()


def get_global_bucket(default_rate: float = 25.0) -> TokenBucket:
    """Return the global bucket, initialising with ``default_rate`` if needed."""

    with _registry_lock:
        global _global_bucket
        if _global_bucket is None:
            _global_bucket = TokenBucket(max(default_rate, 0.1))
        return _global_bucket


def get_bucket(key: str, rate: float, capacity: Optional[float] = None) -> TokenBucket:
    """Return bucket for ``key`` creating it if necessary."""

    if rate <= 0:
        raise ValueError("rate must be positive")
    cache_key = f"{key}|{rate}|{capacity or 'auto'}"
    with _registry_lock:
        bucket = _per_key_buckets.get(cache_key)
        if bucket is None:
            bucket = TokenBucket(rate, capacity)
            _per_key_buckets[cache_key] = bucket
        return bucket
