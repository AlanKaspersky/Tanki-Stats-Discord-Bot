from __future__ import annotations

import asyncio
from collections import Counter
from copy import deepcopy
import logging
import os
import random
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

import aiohttp

from proxy.checker import XrayProxyChecker
from proxy.config_store import load_proxies_json, save_proxies_json
from proxy.health_check import ProxyFilterReport, filter_working_proxies
from proxy.models import ProxyConfig
from proxy.pool import ProxyPool
from proxy.sources_loader import load_sources_file
from proxy.sources_rewrite import rewrite_sources_keep_working
from proxy.subscription import fetch_all_subscriptions
from proxy.vless_parser import extract_vless_lines, parse_vless_uri
from proxy.xray_config import write_xray_config
from proxy.xray_runner import XrayRunner

ProgressCallback = Optional[Callable[[int, int, int, int], Awaitable[None]]]
StageCallback = Optional[Callable[[str], Awaitable[None]]]

logger = logging.getLogger(__name__)


class ProxyBootstrap:
    """Orchestrates proxy loading, xray startup and pool creation."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.enabled = os.getenv("XRAY_ENABLED", "true").lower() in ("1", "true", "yes")
        self.sources_path = base_dir / os.getenv(
            "PROXIES_SOURCES", "proxies_sources.txt"
        )
        self.proxies_json_path = base_dir / os.getenv("PROXIES_JSON", "proxies.json")
        self.xray_config_path = base_dir / os.getenv(
            "XRAY_CONFIG_PATH", "xray_config.runtime.json"
        )
        self.base_port = int(os.getenv("PROXY_BASE_PORT", "18001"))
        self.max_proxies = int(os.getenv("MAX_PROXIES", "0"))
        self.cooldown = float(os.getenv("PROXY_RATE_LIMIT_COOLDOWN", "60"))
        self.refresh_on_start = os.getenv(
            "REFRESH_PROXIES_ON_START", "true"
        ).lower() in (
            "1",
            "true",
            "yes",
        )

        self.pool: Optional[ProxyPool] = None
        self._runner: Optional[XrayRunner] = None
        self._proxies: List[ProxyConfig] = []
        self._pool_listeners: List[Callable[[Optional[ProxyPool]], None]] = []
        self._check_lock = asyncio.Lock()
        self._check_task: Optional[asyncio.Task] = None
        self._checker: Optional[XrayProxyChecker] = None
        self._stopping = False

    def on_pool_replaced(self, listener: Callable[[Optional[ProxyPool]], None]) -> None:
        """Вызывается при каждом новом ProxyPool (например после /proxycheck)."""
        self._pool_listeners.append(listener)

    def _notify_pool_replaced(self) -> None:
        for listener in self._pool_listeners:
            listener(self.pool)
        if self.pool is not None:
            logger.info(
                "Proxy pool updated for consumers: %d proxies, ports %d-%d",
                self.pool.size,
                self._proxies[0].local_http_port,
                self._proxies[-1].local_http_port,
            )

    async def start(self, session: Optional[aiohttp.ClientSession] = None) -> None:
        """Start the cached serving pool; refresh sources separately after readiness."""
        self._stopping = False
        if not self.enabled:
            logger.info("XRAY_ENABLED=false, proxy pool disabled")
            return

        if self.refresh_on_start:
            logger.info(
                "Обновление источников при старте перенесено в отдельную фоновую проверку"
            )
        cached = load_proxies_json(self.proxies_json_path)
        if not cached:
            logger.info(
                "Кэш прокси отсутствует или пуст; рабочий пул будет создан фоновой проверкой"
            )
            return
        if not 1 <= self.base_port <= 65535:
            raise ValueError("PROXY_BASE_PORT must be between 1 and 65535")
        capacity = 65536 - self.base_port
        if len(cached) > capacity:
            logger.warning(
                "Кэш из %d прокси превышает доступные %d локальных портов; пропускаю запуск кэша, фоновая проверка соберёт рабочий пул",
                len(cached),
                capacity,
            )
            return
        self._proxies = cached

        self._prepare_proxy_ports(self._proxies)
        write_xray_config(self.xray_config_path, self._proxies)

        binary = XrayRunner.resolve_binary(
            self.base_dir,
            os.getenv("XRAY_BINARY_PATH"),
        )
        self._runner = XrayRunner(binary, self.xray_config_path)
        await self._runner.start_async()

        self.pool = ProxyPool(self._proxies, cooldown_seconds=self.cooldown)
        logger.info(
            "Proxy bootstrap ready: %d proxies, ports %d-%d",
            len(self._proxies),
            self._proxies[0].local_http_port,
            self._proxies[-1].local_http_port,
        )

    async def parse_proxies_from_sources(
        self,
        session: Optional[aiohttp.ClientSession] = None,
        *,
        stage_callback: StageCallback = None,
    ) -> List[ProxyConfig]:
        """Parse all vless configs from proxies_sources.txt (incl. subscriptions)."""
        vless_uris, subscription_urls = await asyncio.to_thread(
            load_sources_file, self.sources_path
        )

        subscription_content: List[str] = []
        if subscription_urls:
            close_session = False
            if session is None:
                session = aiohttp.ClientSession()
                close_session = True
            try:
                subscription_content = await fetch_all_subscriptions(
                    subscription_urls, session, stage_callback=stage_callback
                )
            finally:
                if close_session and session:
                    await session.close()

        if stage_callback:
            await stage_callback("Разбор и проверка совместимости полученных VLESS...")
        return await asyncio.to_thread(
            self._parse_source_content, vless_uris, subscription_content
        )

    def _parse_source_content(
        self, vless_uris: List[str], subscription_content: List[str]
    ) -> List[ProxyConfig]:
        all_vless_lines = list(vless_uris)
        for content in subscription_content:
            all_vless_lines.extend(extract_vless_lines(content))

        seen_ids: set[str] = set()
        proxies: List[ProxyConfig] = []
        skipped = 0
        failure_counts: Counter[str] = Counter()

        for line in all_vless_lines:
            config = parse_vless_uri(
                line, local_http_port=0, failure_counts=failure_counts
            )
            if config is None:
                skipped += 1
                continue
            if config.id in seen_ids:
                continue
            seen_ids.add(config.id)
            proxies.append(config)

            if self.max_proxies > 0 and len(proxies) >= self.max_proxies:
                break

        logger.info(
            "Parsed %d xray-compatible proxies from %d vless URIs (%d skipped)",
            len(proxies),
            len(all_vless_lines),
            skipped,
        )
        if failure_counts:
            logger.warning(
                "Skipped source entries: %s",
                ", ".join(
                    f"{reason}: {count}"
                    for reason, count in sorted(failure_counts.items())
                ),
            )
        return proxies

    async def refresh_proxies(
        self, session: Optional[aiohttp.ClientSession] = None
    ) -> None:
        """Refresh through health checks; never persist unverified candidate lists."""
        if session is None:
            async with aiohttp.ClientSession() as owned_session:
                await self.filter_working_proxies_from_sources(
                    owned_session, rewrite_sources=False
                )
        else:
            await self.filter_working_proxies_from_sources(
                session, rewrite_sources=False
            )

    def _prepare_proxy_ports(self, proxies: List[ProxyConfig]) -> None:
        if self.base_port < 1 or self.base_port + len(proxies) - 1 > 65535:
            raise RuntimeError(
                "PROXY_BASE_PORT and proxy count exceed the TCP port range"
            )
        for index, proxy in enumerate(proxies):
            proxy.local_http_port = self.base_port + index
            proxy.assign_tags()

    async def _restart_xray_with_proxies(self, proxies: List[ProxyConfig]) -> None:
        self._prepare_proxy_ports(proxies)

        write_xray_config(self.xray_config_path, proxies)

        if self._runner is None:
            binary = XrayRunner.resolve_binary(
                self.base_dir,
                os.getenv("XRAY_BINARY_PATH"),
            )
            self._runner = XrayRunner(binary, self.xray_config_path)
            await self._runner.start_async()
            return

        if self._runner.is_running:
            await self._runner.restart_async()
        else:
            await self._runner.start_async()

        warmup = float(os.getenv("PROXY_CHECK_XRAY_WARMUP", "1.5"))
        if warmup > 0:
            await asyncio.sleep(warmup)

    def _apply_working_proxies(self, working: List[ProxyConfig]) -> None:
        for index, proxy in enumerate(working):
            proxy.local_http_port = self.base_port + index
            proxy.assign_tags()

        self._proxies = working
        save_proxies_json(self.proxies_json_path, working)
        self.pool = (
            ProxyPool(working, cooldown_seconds=self.cooldown) if working else None
        )
        self._notify_pool_replaced()

    async def _health_check_proxies_resilient(
        self,
        proxies: List[ProxyConfig],
        session: aiohttp.ClientSession,
        *,
        progress_callback: ProgressCallback = None,
        checked_offset: int = 0,
        total_all: int = 0,
        working_offset: int = 0,
        failed_offset: int = 0,
        working_target: int = 0,
    ) -> ProxyFilterReport:
        """Run health check via xray; bisect batch if xray rejects the config."""
        if not proxies:
            return ProxyFilterReport(0, 0, 0, [], [])

        try:
            await self._checker.restart(proxies)
        except RuntimeError as exc:
            if len(proxies) <= 1:
                bad_id = proxies[0].id
                logger.warning(
                    "xray rejected proxy config %s, skipping: %s",
                    bad_id,
                    exc,
                )
                return ProxyFilterReport(1, 0, 1, [], [bad_id])

            logger.warning(
                "Xray rejected a batch of %d proxy configs; checking two smaller groups",
                len(proxies),
            )
            mid = len(proxies) // 2
            left = await self._health_check_proxies_resilient(
                proxies[:mid],
                session,
                progress_callback=progress_callback,
                checked_offset=checked_offset,
                total_all=total_all,
                working_offset=working_offset,
                failed_offset=failed_offset,
                working_target=working_target,
            )
            if working_target > 0 and left.working >= working_target:
                left.candidate_count = len(proxies)
                return left
            right = await self._health_check_proxies_resilient(
                proxies[mid:],
                session,
                progress_callback=progress_callback,
                checked_offset=checked_offset + left.total,
                total_all=total_all,
                working_offset=working_offset + left.working,
                failed_offset=failed_offset + left.failed,
                working_target=max(0, working_target - left.working),
            )
            return ProxyFilterReport(
                total=left.total + right.total,
                working=left.working + right.working,
                failed=left.failed + right.failed,
                working_proxies=left.working_proxies + right.working_proxies,
                failed_proxy_ids=left.failed_proxy_ids + right.failed_proxy_ids,
                candidate_count=len(proxies),
            )

        async def batch_progress(
            checked: int, batch_total: int, working: int, failed: int
        ) -> None:
            if not progress_callback:
                return
            await progress_callback(
                checked_offset + checked,
                total_all or batch_total,
                working_offset + working,
                failed_offset + failed,
            )

        return await filter_working_proxies(
            proxies,
            session,
            progress_callback=batch_progress,
            working_target=working_target,
        )

    async def filter_working_proxies_from_sources(
        self,
        session: aiohttp.ClientSession,
        *,
        progress_callback: ProgressCallback = None,
        rewrite_sources: bool = True,
        replacement_lock: Optional[asyncio.Lock] = None,
        working_target: Optional[int] = None,
        stage_callback: StageCallback = None,
    ) -> ProxyFilterReport:
        """Scan independently; acquire the serving lock only to publish a new pool."""
        if self._check_lock.locked() and stage_callback:
            await stage_callback(
                "Ожидание завершения уже запущенной проверки прокси..."
            )
        async with self._check_lock:
            if self._stopping:
                raise RuntimeError("Proxy bootstrap is stopping")
            if working_target is None:
                working_target = (
                    0
                    if rewrite_sources
                    else int(os.getenv("PROXY_WORKING_TARGET", "50"))
                )
            if working_target < 0:
                raise ValueError("PROXY_WORKING_TARGET must be zero or positive")
            if rewrite_sources and working_target:
                raise ValueError("Source rewriting requires a complete proxy check")
            self._check_task = asyncio.current_task()
            try:
                return await self._filter_working_proxies_from_sources(
                    session,
                    progress_callback=progress_callback,
                    rewrite_sources=rewrite_sources,
                    replacement_lock=replacement_lock,
                    working_target=working_target,
                    stage_callback=stage_callback,
                )
            except Exception:
                logger.exception("Проверка прокси не завершена")
                raise
            finally:
                try:
                    await self._stop_checker()
                finally:
                    self._check_task = None

    async def _stop_checker(self) -> None:
        if self._checker is not None:
            checker, self._checker = self._checker, None
            await checker.stop()

    async def _publish_working_proxies(self, working: List[ProxyConfig]) -> None:
        previous = deepcopy(self._proxies)
        previous_pool = self.pool
        try:
            await self._restart_xray_with_proxies(working)
            self._apply_working_proxies(working)
        except (Exception, asyncio.CancelledError):
            logger.exception("Не удалось переключить Xray; восстанавливаю рабочий пул")
            try:
                if previous:
                    await self._restart_xray_with_proxies(previous)
                    save_proxies_json(self.proxies_json_path, previous)
                    self._proxies = previous
                    self.pool = previous_pool
                else:
                    if self._runner is not None:
                        await self._runner.stop_async()
                        self._runner = None
                    self.pool = None
            except Exception:
                logger.exception("Не удалось восстановить прежнюю конфигурацию Xray")
                if self._runner is not None:
                    await self._runner.stop_async()
                    self._runner = None
                self.pool = None
                self._notify_pool_replaced()
            raise

    async def _filter_working_proxies_from_sources(
        self,
        session: aiohttp.ClientSession,
        *,
        progress_callback: ProgressCallback = None,
        rewrite_sources: bool = True,
        replacement_lock: Optional[asyncio.Lock] = None,
        working_target: int = 0,
        stage_callback: StageCallback = None,
    ) -> ProxyFilterReport:
        """Check all proxies from sources; save only working ones to proxies.json."""
        if not self.enabled:
            raise RuntimeError("XRAY_ENABLED=false, proxy check unavailable")

        if stage_callback:
            await stage_callback("Загрузка источников прокси...")
        candidates = deepcopy(
            await self.parse_proxies_from_sources(
                session, stage_callback=stage_callback
            )
        )
        if not candidates:
            raise RuntimeError(f"No proxies parsed from {self.sources_path}")

        if working_target > 0:
            previous_ids = {proxy.id for proxy in self._proxies}
            known = [proxy for proxy in candidates if proxy.id in previous_ids]
            others = [proxy for proxy in candidates if proxy.id not in previous_ids]
            random.shuffle(others)
            candidates = known + others

        binary = XrayRunner.resolve_binary(self.base_dir, os.getenv("XRAY_BINARY_PATH"))
        self._checker = XrayProxyChecker(
            binary,
            self.xray_config_path.parent,
            {proxy.local_http_port for proxy in self._proxies},
        )
        logger.info(
            "Проверка прокси запущена в отдельном Xray; рабочий пул остаётся доступен"
        )

        batch_size = int(os.getenv("PROXY_CHECK_BATCH_SIZE", "400"))
        batch_size = max(1, batch_size)
        total = len(candidates)
        if progress_callback:
            await progress_callback(0, total, 0, 0)

        all_working: List[ProxyConfig] = []
        all_failed_ids: List[str] = []
        checked_so_far = 0

        for start in range(0, total, batch_size):
            batch = candidates[start : start + batch_size]
            batch_report = await self._health_check_proxies_resilient(
                batch,
                session,
                progress_callback=progress_callback,
                checked_offset=checked_so_far,
                total_all=total,
                working_offset=len(all_working),
                failed_offset=len(all_failed_ids),
                working_target=max(0, working_target - len(all_working)),
            )
            all_working.extend(batch_report.working_proxies)
            all_failed_ids.extend(batch_report.failed_proxy_ids)
            checked_so_far += batch_report.total

            if progress_callback:
                await progress_callback(
                    checked_so_far,
                    total,
                    len(all_working),
                    len(all_failed_ids),
                )

            logger.info(
                "Proxy check batch %d-%d/%d: %d working, %d failed so far",
                start + 1,
                checked_so_far,
                total,
                len(all_working),
                len(all_failed_ids),
            )
            if working_target > 0 and len(all_working) >= working_target:
                logger.info(
                    "Proxy target reached: %d working; checked %d/%d candidates",
                    len(all_working),
                    checked_so_far,
                    total,
                )
                break

        report = ProxyFilterReport(
            total=checked_so_far,
            working=len(all_working),
            failed=len(all_failed_ids),
            working_proxies=all_working,
            failed_proxy_ids=all_failed_ids,
            candidate_count=total,
        )

        working = report.working_proxies
        if not working:
            raise RuntimeError(
                f"No working proxies found ({report.failed} failed of {report.total})"
            )

        await self._stop_checker()
        if stage_callback:
            await stage_callback(
                f"Проверено {report.total}/{total}; рабочих: {len(working)}. "
                "Ожидание текущих запросов и переключение рабочего пула..."
            )
        async with replacement_lock or asyncio.Lock():
            await self._publish_working_proxies(deepcopy(working))

        if rewrite_sources:
            rewrite_sources_keep_working(
                self.sources_path,
                {proxy.id for proxy in working},
            )

        logger.info(
            "Filtered proxies: %d working saved to %s, %d failed, %d unchecked",
            len(working),
            self.proxies_json_path,
            report.failed,
            report.unchecked,
        )
        return report

    async def stop(self) -> None:
        """Stop xray subprocess."""
        self._stopping = True
        task = self._check_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self._stop_checker()
        if self._runner is not None:
            await self._runner.stop_async()
            self._runner = None
        self.pool = None
        logger.info("Proxy bootstrap stopped")

    @property
    def is_active(self) -> bool:
        return self.enabled and self.pool is not None
