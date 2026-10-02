from __future__ import annotations

import asyncio
import logging
import platform
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class XrayRunner:
    """Manages xray-core subprocess lifecycle."""

    def __init__(
        self,
        binary_path: Path,
        config_path: Path,
    ) -> None:
        self.binary_path = binary_path
        self.config_path = config_path
        self._process: Optional[subprocess.Popen] = None

    @staticmethod
    def resolve_binary(base_dir: Path, env_path: Optional[str] = None) -> Path:
        """Resolve xray binary path from env or defaults."""
        system = platform.system()

        def validate(candidate: Path) -> Optional[str]:
            with candidate.open("rb") as stream:
                header = stream.read(4)
            if system == "Windows" and header == b"\x7fELF":
                return f"{candidate} — Linux ELF binary. Windows requires xray.exe from the Windows release."
            if system in ("Linux", "Darwin") and header[:2] == b"MZ":
                return f"{candidate} — Windows executable. Install Xray for {system}."
            return None

        base_dir = base_dir.resolve()
        candidates: list[Path] = []
        if env_path:
            candidate = Path(env_path)
            if not candidate.is_absolute():
                candidate = base_dir / candidate
            if not candidate.is_file():
                raise FileNotFoundError(
                    f"XRAY_BINARY_PATH points to a missing file: {candidate}"
                )
            error = validate(candidate)
            if error:
                raise OSError(error)
            return candidate.resolve()

        if system == "Windows":
            candidates.extend([base_dir / "xray.exe", base_dir / "xray"])
        else:
            candidates.extend([base_dir / "xray", base_dir / "xray.exe"])

        incompatible = []
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                error = validate(candidate)
                if error:
                    incompatible.append(error)
                    continue
                return candidate.resolve()

        if incompatible:
            raise OSError(" ".join(incompatible))

        searched = ", ".join(str(c) for c in candidates)
        raise FileNotFoundError(
            f"xray binary not found. Searched: {searched}. "
            f"Set XRAY_BINARY_PATH in .env or place xray/xray.exe in project root."
        )

    def test_config(self) -> str:
        """Validate config via `xray run -test`; return error text or empty string."""
        cmd = [str(self.binary_path), "run", "-test", "-c", str(self.config_path)]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return "xray config test timed out after 120s"
        if result.returncode == 0:
            return ""
        return (result.stderr or result.stdout or "unknown config error").strip()

    def start(self) -> None:
        """Start xray subprocess."""
        if self._process is not None and self._process.poll() is None:
            logger.warning("xray is already running (pid=%s)", self._process.pid)
            return

        if not self.config_path.exists():
            raise FileNotFoundError(f"xray config not found: {self.config_path}")

        cmd = [str(self.binary_path), "run", "-c", str(self.config_path)]
        logger.info("Starting xray: %s", " ".join(cmd))

        creationflags = 0
        if platform.system() == "Windows":
            creationflags = subprocess.CREATE_NO_WINDOW

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        except OSError as exc:
            if platform.system() == "Windows" and self.binary_path.name == "xray":
                raise OSError(
                    f"Cannot execute {self.binary_path}. "
                    "On Windows you likely need xray.exe (Linux binary won't run)."
                ) from exc
            raise

        for _ in range(10):
            if self._process.poll() is not None:
                output = self.test_config()
                raise RuntimeError(
                    f"xray exited immediately with code {self._process.returncode}: {output}"
                )
            time.sleep(0.2)

        logger.info("xray started (pid=%s)", self._process.pid)

    async def start_async(self) -> None:
        """Start xray and wait briefly for startup."""
        loop = asyncio.get_running_loop()
        started = loop.run_in_executor(None, self._start_sync)
        try:
            await asyncio.shield(started)
        except asyncio.CancelledError:
            await asyncio.gather(started, return_exceptions=True)
            await self.stop_async()
            raise

    def _start_sync(self) -> None:
        if self._process is not None and self._process.poll() is None:
            return
        self.start()

    def stop(self) -> None:
        """Stop xray subprocess."""
        if self._process is None:
            return

        if self._process.poll() is None:
            logger.info("Stopping xray (pid=%s)", self._process.pid)
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("xray did not stop gracefully, killing")
                self._process.kill()
                self._process.wait(timeout=3)

        self._process = None
        logger.info("xray stopped")

    async def stop_async(self) -> None:
        loop = asyncio.get_running_loop()
        stopped = loop.run_in_executor(None, self.stop)
        try:
            await asyncio.shield(stopped)
        except asyncio.CancelledError:
            await asyncio.gather(stopped, return_exceptions=True)
            raise

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def restart(self) -> None:
        self.stop()
        self.start()

    async def restart_async(self) -> None:
        await self.stop_async()
        await self.start_async()
