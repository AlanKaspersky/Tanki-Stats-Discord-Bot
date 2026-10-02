from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Awaitable, Callable, List, Optional, Tuple

from proxy.pool import ProxyPoolExhausted
from utils.tanki_client import summarize_failure_reason

logger = logging.getLogger(__name__)

_POOL_EXHAUSTED_MESSAGE = "все прокси временно недоступны"

ProcessAccountFn = Callable[
    [dict],
    Awaitable[Tuple[bool, Optional[str], Optional[dict]]],
]
WaitBeforeRetryFn = Callable[[Optional[str]], Awaitable[None]]


def daily_stats_settings() -> tuple[int, float, float, int]:
    workers = int(
        os.getenv(
            "DAILY_STATS_WORKERS",
            os.getenv("SNAPSHOT_WORKERS", "20"),
        )
    )
    delay = float(
        os.getenv(
            "DAILY_STATS_DELAY",
            os.getenv("SNAPSHOT_DELAY", "0"),
        )
    )
    retry_delay = float(os.getenv("DAILY_STATS_RETRY_DELAY", "2.0"))
    max_attempts = int(os.getenv("DAILY_STATS_MAX_ATTEMPTS", "5"))
    return max(1, workers), max(0.0, delay), max(0.0, retry_delay), max(1, max_attempts)


def _is_pool_exhausted_reason(reason: Optional[str]) -> bool:
    if not reason:
        return False
    lower = reason.lower()
    return (
        "proxy pool exhausted" in lower
        or _POOL_EXHAUSTED_MESSAGE in lower
        or "все прокси в cooldown" in lower
        or "all proxies in cooldown" in lower
        or "all proxies temporarily unavailable" in lower
    )


async def collect_daily_stats_parallel(
    accounts: List[dict],
    process_account: ProcessAccountFn,
    *,
    dry_run: bool = False,
    wait_before_retry: Optional[WaitBeforeRetryFn] = None,
    log_dry_run_stats: Optional[Callable[[str, dict], None]] = None,
) -> tuple[int, List[dict], bool, float]:
    """Parallel daily stats collection with proxy pool exhaustion handling.

    Returns:
        (processed_count, final_failures, pool_exhausted, elapsed_seconds)
    """
    if not accounts:
        return 0, [], False, 0.0

    max_workers, delay, _, max_attempts_per_account = daily_stats_settings()
    max_workers = max(1, min(max_workers, len(accounts)))

    queue: asyncio.Queue = asyncio.Queue()
    for account in accounts:
        queue.put_nowait(account)

    processed = 0
    final_failures: List[dict] = []
    attempt_counts: dict[str, int] = {}
    stats_lock = asyncio.Lock()
    pool_exhausted = False
    pool_exhausted_logged = False
    log_prefix = "🧪 [dry-run] " if dry_run else ""
    started_at = time.monotonic()

    async def mark_pool_exhausted(account: dict) -> None:
        nonlocal pool_exhausted, pool_exhausted_logged
        nickname = account.get("nickname", "Unknown")
        async with stats_lock:
            pool_exhausted = True
            if account not in final_failures:
                final_failures.append(account)
            if not pool_exhausted_logged:
                pool_exhausted_logged = True
                logger.warning(
                    "%sПрокси-пул исчерпан во время сбора (%d аккаунтов в очереди)",
                    log_prefix,
                    len(accounts),
                )
        logger.warning(
            "%s⚠️ %s: все прокси в cooldown",
            log_prefix,
            nickname,
        )

    async def worker() -> None:
        nonlocal processed

        while True:
            account = await queue.get()
            try:
                if account is None:
                    return

                nickname = account.get("nickname", "Unknown")

                if pool_exhausted:
                    await mark_pool_exhausted(account)
                    continue

                attempt = attempt_counts.get(nickname, 0) + 1
                attempt_counts[nickname] = attempt
                if attempt == 1:
                    logger.info("%s🔍 %s: проверка", log_prefix, nickname)
                else:
                    logger.info(
                        "%s🔄 %s: повтор #%d",
                        log_prefix,
                        nickname,
                        attempt - 1,
                    )

                try:
                    success, failure_reason, stats = await process_account(account)
                except ProxyPoolExhausted:
                    await mark_pool_exhausted(account)
                    continue

                if success:
                    if dry_run and stats and log_dry_run_stats:
                        log_dry_run_stats(nickname, stats)
                    async with stats_lock:
                        processed += 1
                    if delay > 0:
                        await asyncio.sleep(delay)
                    continue

                if failure_reason is None:
                    logger.error(
                        "%s❌ %s: не удалось сохранить или отправить",
                        log_prefix,
                        nickname,
                    )
                    async with stats_lock:
                        final_failures.append(account)
                    if delay > 0:
                        await asyncio.sleep(delay)
                    continue

                if _is_pool_exhausted_reason(failure_reason):
                    await mark_pool_exhausted(account)
                    continue

                if attempt >= max_attempts_per_account:
                    short_reason = summarize_failure_reason(failure_reason)
                    logger.error(
                        "%s❌ %s: %s — лимит попыток (%d)",
                        log_prefix,
                        nickname,
                        short_reason,
                        max_attempts_per_account,
                    )
                    async with stats_lock:
                        final_failures.append(account)
                    continue

                short_reason = summarize_failure_reason(failure_reason)
                logger.warning(
                    "%s⚠️ %s: %s — повтор в очереди",
                    log_prefix,
                    nickname,
                    short_reason,
                )
                if wait_before_retry is not None:
                    await wait_before_retry(failure_reason)
                queue.put_nowait(account)
            except Exception:
                logger.exception(
                    "%sОшибка обработки аккаунта %s",
                    log_prefix,
                    account.get("nickname", "Unknown"),
                )
                async with stats_lock:
                    if account not in final_failures:
                        final_failures.append(account)
            finally:
                queue.task_done()

    logger.info(
        "%s🚀 Параллельный сбор: %d аккаунтов, %d workers, delay=%.2fs",
        log_prefix,
        len(accounts),
        max_workers,
        delay,
    )

    workers = [asyncio.create_task(worker()) for _ in range(max_workers)]
    try:
        await queue.join()
        for _ in workers:
            queue.put_nowait(None)
        await asyncio.gather(*workers)
    finally:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

    elapsed = time.monotonic() - started_at
    logger.info(
        "%s🏁 Параллельный сбор завершён за %.2fs: ✅ %d | ❌ %d | pool_exhausted=%s",
        log_prefix,
        elapsed,
        processed,
        len(final_failures),
        pool_exhausted,
    )
    return processed, final_failures, pool_exhausted, elapsed
