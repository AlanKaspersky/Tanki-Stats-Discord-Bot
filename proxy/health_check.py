from __future__ import annotations

import asyncio
import logging
import os
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
    return aiohttp.ClientTimeout(total=float(os.getenv("PROXY_CHECK_TIMEOUT", "15")))


ProgressCallback = Optional[Callable[[int, int, int, int], Awaitable[None]]]


@dataclass
class ProxyFilterReport:
    total: int
    working: int
    failed: int
    working_proxies: List[ProxyConfig]
    failed_proxy_ids: List[str]


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

    async def check_one(proxy: ProxyConfig) -> None:
        nonlocal checked
        ok = await _check_single_proxy(
            session, proxy, test_user, timeout, failure_counts=failure_counts
        )
        async with lock:
            checked += 1
            if ok:
                working.append(proxy)
            else:
                failed_ids.append(proxy.id)
            if progress_callback and (checked % 10 == 0 or checked == total):
                await progress_callback(checked, total, len(working), len(failed_ids))

    semaphore = asyncio.Semaphore(workers)

    async def run_with_limit(proxy: ProxyConfig) -> None:
        async with semaphore:
            await check_one(proxy)

    await asyncio.gather(*(run_with_limit(proxy) for proxy in proxies))

    if progress_callback:
        await progress_callback(total, total, len(working), len(failed_ids))

    logger.info(
        "Proxy health check done: %d/%d working, %d failed",
        len(working),
        total,
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
        total=total,
        working=len(working),
        failed=len(failed_ids),
        working_proxies=working,
        failed_proxy_ids=failed_ids,
    )
