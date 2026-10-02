from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from proxy.models import ProxyConfig
from proxy.xray_compat import filter_xray_compatible
from utils.storage import atomic_write_json

logger = logging.getLogger(__name__)


def save_proxies_json(path: Path, proxies: List[ProxyConfig]) -> None:
    """Save normalized proxy list to JSON."""
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "proxies": [proxy.to_dict() for proxy in proxies],
    }
    atomic_write_json(path, payload)
    logger.info("Saved %d proxies to %s", len(proxies), path)


def load_proxies_json(path: Path) -> List[ProxyConfig]:
    """Load proxy list from JSON."""
    if not path.exists():
        return []

    data = json.loads(path.read_text(encoding="utf-8"))
    proxies = [ProxyConfig.from_dict(item) for item in data.get("proxies", [])]
    proxies, dropped = filter_xray_compatible(proxies)
    if dropped:
        logger.warning(
            "Dropped %d xray-incompatible proxies while loading %s",
            dropped,
            path,
        )
    logger.info("Loaded %d proxies from %s", len(proxies), path)
    return proxies
