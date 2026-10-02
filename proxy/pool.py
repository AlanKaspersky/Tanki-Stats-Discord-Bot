from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from typing import Dict, List, Optional, Set

from proxy.models import ProxyConfig

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if not raw:
        return default
    raw = raw.strip()
    try:
        return float(raw)
    except ValueError:
        cleaned = re.sub(r"[^\d.+-].*$", "", raw)
        try:
            value = float(cleaned)
            logger.warning("Env %s contained garbage (%r), using %s", name, raw, value)
            return value
        except ValueError:
            logger.warning("Env %s invalid (%r), using default %s", name, raw, default)
            return default


TAG_PROXY = "proxy"
TAG_API_429 = "api_429"
TAG_API = "api"
TAG_MANUAL = "manual"


class ProxyPoolExhausted(Exception):
    """Raised when all proxies are in cooldown."""


class ProxyPool:
    """Sticky proxy pool with rate-limit cooldown and smart selection."""

    def __init__(
        self,
        proxies: list[ProxyConfig],
        cooldown_seconds: float = 60.0,
        rate_limit_cooldown_seconds: Optional[float] = None,
    ) -> None:
        if not proxies:
            raise ValueError("ProxyPool requires at least one proxy")

        self._proxies: Dict[str, ProxyConfig] = {p.id: p for p in proxies}
        self._cooldown_seconds = cooldown_seconds
        self._rate_limit_cooldown_seconds = (
            rate_limit_cooldown_seconds
            if rate_limit_cooldown_seconds is not None
            else _env_float("PROXY_429_COOLDOWN", 2.0)
        )
        self._cooldown_until: Dict[str, float] = {}
        self._success_at: Dict[str, float] = {}
        self._connection_failures: Dict[str, int] = {}
        self._task_bindings: Dict[asyncio.Task, str] = {}
        self._lock = asyncio.Lock()

    @property
    def size(self) -> int:
        return len(self._proxies)

    @property
    def cooldown_count(self) -> int:
        now = time.monotonic()
        return sum(1 for until in self._cooldown_until.values() if until > now)

    def get_proxy_by_id(self, proxy_id: str) -> Optional[ProxyConfig]:
        return self._proxies.get(proxy_id)

    def _is_in_cooldown(self, proxy_id: str) -> bool:
        until = self._cooldown_until.get(proxy_id)
        if until is None:
            return False
        return time.monotonic() < until

    def _cleanup_expired_cooldowns(self) -> None:
        now = time.monotonic()
        expired = [pid for pid, until in self._cooldown_until.items() if until <= now]
        for pid in expired:
            del self._cooldown_until[pid]

    def _available_proxy_ids(self, exclude: Optional[Set[str]] = None) -> List[str]:
        exclude = exclude or set()
        self._cleanup_expired_cooldowns()
        return [
            proxy_id
            for proxy_id in self._proxies
            if proxy_id not in exclude and not self._is_in_cooldown(proxy_id)
        ]

    def _proxy_score(self, proxy_id: str) -> float:
        """Выше = лучше: недавний успех и меньше [proxy]-сбоев."""
        last_ok = self._success_at.get(proxy_id, 0.0)
        failures = self._connection_failures.get(proxy_id, 0)
        if last_ok:
            return last_ok - failures * 1_000_000.0
        return -failures * 1_000_000.0 - 1_000.0

    def _pick_next_available(self, exclude: Optional[Set[str]] = None) -> str:
        """Приоритет недавно успешным; среди лучших — случайный выбор."""
        available = self._available_proxy_ids(exclude)
        if not available:
            raise ProxyPoolExhausted(
                f"All {len(self._proxies)} proxies are in cooldown "
                f"({self.cooldown_count} active cooldowns)"
            )
        ranked = sorted(available, key=self._proxy_score, reverse=True)
        top_n = min(5, len(ranked))
        return random.choice(ranked[:top_n])

    async def get_for_current_task(self) -> str:
        """Return HTTP proxy URL sticky-bound to current asyncio task."""
        task = asyncio.current_task()
        if task is None:
            proxy_id = self._pick_next_available()
            return self._proxies[proxy_id].http_proxy_url()

        async with self._lock:
            bound_id = self._task_bindings.get(task)
            if (
                bound_id
                and bound_id in self._proxies
                and not self._is_in_cooldown(bound_id)
            ):
                return self._proxies[bound_id].http_proxy_url()

            proxy_id = self._pick_next_available()
            self._task_bindings[task] = proxy_id
            logger.debug(
                "Task bound to proxy %s (%s)", proxy_id, self._proxies[proxy_id].name
            )
            return self._proxies[proxy_id].http_proxy_url()

    async def get_proxy_id_for_current_task(self) -> Optional[str]:
        task = asyncio.current_task()
        if task is None:
            return None
        async with self._lock:
            return self._task_bindings.get(task)

    async def _set_cooldown(
        self,
        proxy_url: Optional[str],
        seconds: float,
        reason: str,
        *,
        tag: str = TAG_PROXY,
    ) -> None:
        async with self._lock:
            proxy_id = self._resolve_proxy_id(proxy_url)
            if proxy_id is None:
                return
            self._cooldown_until[proxy_id] = time.monotonic() + seconds
            logger.debug(
                "Proxy %s cooldown [%s]: %s for %.0fs (%d/%d in cooldown)",
                proxy_id,
                tag,
                reason,
                seconds,
                self.cooldown_count,
                self.size,
            )

    async def mark_rate_limited(
        self,
        proxy_url: Optional[str] = None,
        *,
        reason: str = "HTTP 429 from Tanki API",
    ) -> None:
        """HTTP 429 от API — короткий cooldown (прокси до API достучался)."""
        await self._set_cooldown(
            proxy_url, self._rate_limit_cooldown_seconds, reason, tag=TAG_API_429
        )

    async def mark_connection_failed(
        self,
        proxy_url: Optional[str] = None,
        *,
        reason: str = "no TCP/TLS through proxy (API not reached)",
    ) -> None:
        """Нет связи через локальный порт / TLS — cooldown."""
        async with self._lock:
            proxy_id = self._resolve_proxy_id(proxy_url)
            if proxy_id is not None:
                self._connection_failures[proxy_id] = (
                    self._connection_failures.get(proxy_id, 0) + 1
                )

        await self._set_cooldown(
            proxy_url, self._cooldown_seconds, reason, tag=TAG_PROXY
        )

    async def rotate_for_current_task(
        self,
        *,
        cooldown_previous: bool = True,
        previous_cooldown_seconds: Optional[float] = None,
        rotation_tag: str = TAG_MANUAL,
        rotation_reason: Optional[str] = None,
    ) -> str:
        """Rotate to next available proxy for current task. Returns new proxy URL."""
        task = asyncio.current_task()
        async with self._lock:
            old_id: Optional[str] = None
            if task is not None:
                old_id = self._task_bindings.pop(task, None)

            exclude = {old_id} if old_id else set()
            if old_id and cooldown_previous:
                seconds = (
                    previous_cooldown_seconds
                    if previous_cooldown_seconds is not None
                    else self._cooldown_seconds
                )
                self._cooldown_until[old_id] = time.monotonic() + seconds

            try:
                new_id = self._pick_next_available(exclude=exclude)
            except ProxyPoolExhausted:
                if task is not None and old_id:
                    self._task_bindings[task] = old_id
                raise

            if task is not None:
                self._task_bindings[task] = new_id

            if rotation_reason:
                logger.debug(
                    "Rotated proxy [%s]: %s -> %s — %s (%d in cooldown)",
                    rotation_tag,
                    old_id or "none",
                    new_id,
                    rotation_reason,
                    self.cooldown_count,
                )
            else:
                logger.debug(
                    "Rotated proxy [%s]: %s -> %s (%d in cooldown)",
                    rotation_tag,
                    old_id or "none",
                    new_id,
                    self.cooldown_count,
                )
            return self._proxies[new_id].http_proxy_url()

    async def mark_success(self, proxy_url: Optional[str] = None) -> None:
        """Успешный запрос: приоритет в выборе, сброс счётчика [proxy]-сбоев."""
        async with self._lock:
            proxy_id = self._resolve_proxy_id(proxy_url)
            if proxy_id is None:
                return
            self._success_at[proxy_id] = time.monotonic()
            self._connection_failures.pop(proxy_id, None)

    def _resolve_proxy_id(self, proxy_url: Optional[str]) -> Optional[str]:
        if proxy_url:
            for proxy_id, config in self._proxies.items():
                if config.http_proxy_url() == proxy_url:
                    return proxy_id

        task = asyncio.current_task()
        if task is not None:
            return self._task_bindings.get(task)
        return None

    def seconds_until_available(self) -> float:
        """Seconds until at least one proxy leaves cooldown (0 if available now)."""
        self._cleanup_expired_cooldowns()
        if self._available_proxy_ids():
            return 0.0
        now = time.monotonic()
        if not self._cooldown_until:
            return 1.0
        return max(0.0, min(self._cooldown_until.values()) - now) + 0.25

    async def wait_until_available(self, max_wait: Optional[float] = None) -> float:
        """Wait until a proxy is available. Returns seconds actually waited."""
        wait = self.seconds_until_available()
        if max_wait is not None:
            wait = min(wait, max_wait)
        if wait > 0:
            logger.debug(
                "Waiting %.1fs for proxy availability (%d/%d in cooldown)",
                wait,
                self.cooldown_count,
                self.size,
            )
            await asyncio.sleep(wait)
        return wait

    async def cleanup_task_binding(self) -> None:
        """Remove binding for current task (call when worker exits)."""
        task = asyncio.current_task()
        if task is None:
            return
        async with self._lock:
            self._task_bindings.pop(task, None)
