from __future__ import annotations

import asyncio
import logging
import os
import math
from collections import Counter
from dataclasses import dataclass
from typing import Awaitable, Callable, List, Optional

import aiohttp

from proxy.models import ProxyConfig

logger = logging.getLogger(__name__)

API_URL = os.getenv(
    "PROXY_CHECK_API_URL",
    "https://ratings.tankionline.com/api/eu/profile/",
)


def profile_api_timeout() -> aiohttp.ClientTimeout:
    def _env_float(key, default):
        value = float(os.getenv(key, default))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{key} must be positive and finite")
        return value

    total = _env_float("PROXY_CHECK_TIMEOUT", "20")
    return aiohttp.ClientTimeout(
        total=total,
        connect=min(total, _env_float("PROXY_CHECK_CONNECT_TIMEOUT", "10")),
        sock_read=min(total, _env_float("PROXY_CHECK_READ_TIMEOUT", "15")),
    )


ProgressCallback = Optional[Callable[[int, int, int, int], Awaitable[None]]]


@dataclass
class ProxyFilterReport:
    total: int
    working: int
    failed: int
    working_proxies: List[ProxyConfig]
    failed_proxy_ids: List[str]
    candidate_count: Optional[int] = None

    @property
    def unchecked(self) -> int:
        return max(0, (self.candidate_count or self.total) - self.total)


async def _check_single_proxy(
    session: aiohttp.ClientSession,
    proxy: ProxyConfig,
    test_user: str,
    timeout: aiohttp.ClientTimeout,
    *,
    failure_counts: Optional[Counter[str]] = None,
) -> bool:
    """True if HTTP proxy reaches Tanki ratings API."""

    def failed(reason: str) -> bool:
        if failure_counts is not None:
            failure_counts[reason] += 1
        logger.debug("Proxy %s health check failed: %s", proxy.id, reason)
        return False

    try:
        async with session.get(
            API_URL,
            params={"user": test_user, "lang": "en"},
            proxy=proxy.http_proxy_url(),
            timeout=timeout,
        ) as response:
            if response.status == 429:
                return True
            if response.status != 200:
                return failed(f"HTTP {response.status}")
            try:
                payload = await response.json()
            except (aiohttp.ContentTypeError, ValueError):
                return failed("invalid JSON response")
            if not isinstance(payload, dict) or "responseType" not in payload:
                return failed("unexpected JSON schema")
            return True
    except aiohttp.ConnectionTimeoutError:
        return failed("connection timeout")
    except aiohttp.SocketTimeoutError:
        return failed("read timeout")
    except asyncio.TimeoutError:
        return failed("timeout")
    except aiohttp.ClientHttpProxyError as exc:
        return failed(f"proxy HTTP {exc.status}")
    except aiohttp.ClientProxyConnectionError:
        return failed("local proxy connection failed")
    except aiohttp.ClientSSLError:
        return failed("TLS error")
    except aiohttp.ClientConnectionError:
        return failed("connection error")
    except (aiohttp.ClientError, ValueError) as exc:
        return failed(type(exc).__name__)


async def filter_working_proxies(
    proxies: List[ProxyConfig],
    session: aiohttp.ClientSession,
    *,
    progress_callback: ProgressCallback = None,
    working_target: int = 0,
) -> ProxyFilterReport:
    """Test each local HTTP inbound; return proxies that reach the API."""
    if not proxies:
        return ProxyFilterReport(0, 0, 0, [], [])

    test_user = os.getenv("PROXY_CHECK_TEST_USER", "Tenobyte")
    workers = int(os.getenv("PROXY_CHECK_WORKERS", "25"))
    workers = max(1, min(workers, len(proxies)))
    timeout = profile_api_timeout()

    working: List[ProxyConfig] = []
    failed_ids: List[str] = []
    failure_counts: Counter[str] = Counter()
    lock = asyncio.Lock()
    checked = 0
    total = len(proxies)
    attempts = int(os.getenv("PROXY_CHECK_ATTEMPTS", "2"))
    if attempts < 1 or attempts > 5:
        raise ValueError("PROXY_CHECK_ATTEMPTS must be between 1 and 5")

    async def check_one(proxy: ProxyConfig) -> None:
        nonlocal checked
        for attempt in range(attempts):
            reasons: Counter[str] = Counter()
            ok = await _check_single_proxy(
                session, proxy, test_user, timeout, failure_counts=reasons
            )
            if ok:
                break
            transient = set(reasons) & {
                "timeout",
                "connection timeout",
                "read timeout",
                "connection error",
                "local proxy connection failed",
            }
            if not transient or attempt + 1 == attempts:
                failure_counts.update(reasons)
                break
            await asyncio.sleep(0.25)
        async with lock:
            checked += 1
            if ok:
                working.append(proxy)
            else:
                failed_ids.append(proxy.id)
            if progress_callback and (checked % 10 == 0 or checked == total):
                await progress_callback(checked, total, len(working), len(failed_ids))

    remaining = iter(proxies)

    async def worker() -> None:
        while working_target <= 0 or len(working) < working_target:
            proxy = next(remaining, None)
            if proxy is None:
                return
            await check_one(proxy)

    running = [asyncio.create_task(worker()) for _ in range(workers)]
    try:
        await asyncio.gather(*running)
    except BaseException:
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
        raise

    if progress_callback:
        await progress_callback(checked, total, len(working), len(failed_ids))

    logger.info(
        "Proxy health check done: %d/%d working, %d failed",
        len(working),
        checked,
        len(failed_ids),
    )
    if failure_counts:
        logger.warning(
            "Proxy health check failures: %s",
            ", ".join(
                f"{reason}: {count}" for reason, count in sorted(failure_counts.items())
            ),
        )
    return ProxyFilterReport(
        total=checked,
        working=len(working),
        failed=len(failed_ids),
        working_proxies=working,
        failed_proxy_ids=failed_ids,
        candidate_count=total,
    )
