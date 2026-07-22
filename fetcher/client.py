"""Async HTTP client with retry, UA rotation, and rate-limiter integration."""

import asyncio
import random
import httpx
from .rate_limiter import RateLimiter

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
]

class FetcherClient:
    """Async HTTP client for East Money APIs with retry and rate limiting."""

    def __init__(self, limiter: RateLimiter | None = None, timeout: float = 30.0):
        self.limiter = limiter
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        return self._client

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://data.eastmoney.com/",
        }

    async def post_json(self, url: str, data: dict, max_retries: int = 3) -> dict | None:
        """POST with JSON body, rate-limited, with exponential backoff retry."""
        client = await self._get_client()
        last_err = None
        for attempt in range(max_retries):
            if self.limiter:
                await self.limiter.acquire()
            try:
                resp = await client.post(url, data=data, headers=self._headers())
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                last_err = e
                status = getattr(e, 'response', None)
                status_code = status.status_code if status else None
                if status_code in (429, 503):
                    wait = 2 ** attempt
                    await asyncio.sleep(wait)
                    continue
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 + attempt * 0.5)
                    continue
        print(f"[ERROR] POST {url} failed after {max_retries} retries: {last_err}")
        return None

    async def get_json(self, url: str, params: dict | None = None, max_retries: int = 3) -> dict | None:
        """GET request, rate-limited, with retry."""
        client = await self._get_client()
        last_err = None
        for attempt in range(max_retries):
            if self.limiter:
                await self.limiter.acquire()
            try:
                resp = await client.get(url, params=params, headers=self._headers())
                resp.raise_for_status()
                return resp.json()
            except (httpx.HTTPStatusError, httpx.RequestError) as e:
                last_err = e
                status = getattr(e, 'response', None)
                status_code = status.status_code if status else None
                if status_code in (429, 503):
                    wait = 2 ** attempt
                    await asyncio.sleep(wait)
                    continue
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 + attempt * 0.5)
                    continue
        print(f"[ERROR] GET {url} failed after {max_retries} retries: {last_err}")
        return None

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
