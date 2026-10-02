from __future__ import annotations

import asyncio
from contextlib import ExitStack
import os
import math
from pathlib import Path
import socket
from tempfile import TemporaryDirectory

from proxy.models import ProxyConfig
from proxy.xray_config import write_xray_config
from proxy.xray_runner import XrayRunner


class XrayProxyChecker:
    """Own a temporary Xray runtime independently of the serving proxy pool."""

    def __init__(self, binary: Path, config_parent: Path, excluded_ports: set[int]):
        config_parent.mkdir(parents=True, exist_ok=True)
        self._directory = TemporaryDirectory(prefix=".xray-check-", dir=config_parent)
        self.config_path = Path(self._directory.name) / "config.json"
        self.runner = XrayRunner(binary, self.config_path)
        self.excluded_ports = excluded_ports

    async def restart(self, proxies: list[ProxyConfig]) -> None:
        await self.runner.stop_async()
        with ExitStack() as sockets:
            for proxy in proxies:
                while True:
                    reserved = sockets.enter_context(
                        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    )
                    reserved.bind(("127.0.0.1", 0))
                    port = reserved.getsockname()[1]
                    if port not in self.excluded_ports:
                        break
                proxy.local_http_port = port
                proxy.assign_tags()
            write_xray_config(self.config_path, proxies)
        await self.runner.start_async()
        await self._wait_for_ports(proxies)
        warmup = float(os.getenv("PROXY_CHECK_XRAY_WARMUP", "1.5"))
        if warmup > 0:
            await asyncio.sleep(warmup)

    async def _wait_for_ports(self, proxies: list[ProxyConfig]) -> None:
        timeout = float(os.getenv("PROXY_CHECK_START_TIMEOUT", "10"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("PROXY_CHECK_START_TIMEOUT must be positive and finite")
        deadline = asyncio.get_running_loop().time() + timeout
        pending = {proxy.local_http_port for proxy in proxies}

        async def listening(port):
            try:
                _, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", port), 0.25
                )
            except (OSError, asyncio.TimeoutError):
                return None
            writer.close()
            await writer.wait_closed()
            return port

        while pending:
            if asyncio.get_running_loop().time() >= deadline:
                raise asyncio.TimeoutError(
                    f"Checker Xray did not open {len(pending)} local ports within {timeout:g}s"
                )
            results = await asyncio.gather(*(listening(port) for port in pending))
            pending.difference_update(port for port in results if port is not None)
            if pending:
                await asyncio.sleep(0.05)

    async def stop(self) -> None:
        try:
            await self.runner.stop_async()
        finally:
            self._directory.cleanup()
