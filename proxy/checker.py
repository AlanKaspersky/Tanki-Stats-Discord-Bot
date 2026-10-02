from __future__ import annotations

import asyncio
from contextlib import ExitStack
import os
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
        warmup = float(os.getenv("PROXY_CHECK_XRAY_WARMUP", "1.5"))
        if warmup > 0:
            await asyncio.sleep(warmup)

    async def stop(self) -> None:
        try:
            await self.runner.stop_async()
        finally:
            self._directory.cleanup()
