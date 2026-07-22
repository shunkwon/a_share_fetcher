"""Token Bucket rate limiter for async operations."""

import time
import asyncio


class RateLimiter:
    """Token bucket rate limiter. Refills at `rpm` rate, allows `burst` concurrent."""

    def __init__(self, rpm: int, burst: int = 3):
        self.rate = rpm / 60.0       # tokens per second
        self.capacity = burst
        self.tokens = float(burst)
        self.last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        """Wait until a token is available, then consume it."""
        async with self._lock:
            while self.tokens < 1:
                await asyncio.sleep(0.3)
                now = time.monotonic()
                elapsed = now - self.last
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last = now
            self.tokens -= 1
            self.last = time.monotonic()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        pass
