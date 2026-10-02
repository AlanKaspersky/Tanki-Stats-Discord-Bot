from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)


def load_sources_file(path: Path) -> Tuple[List[str], List[str]]:
    """Load proxies_sources.txt.

    Returns:
        (vless_uris, subscription_urls)
    """
    if not path.exists():
        logger.warning("Proxies sources file not found: %s", path)
        return [], []

    vless_uris: List[str] = []
    subscription_urls: List[str] = []

    content = path.read_text(encoding="utf-8")
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.lower().startswith("vless://"):
            vless_uris.append(stripped)
        elif stripped.startswith("http://") or stripped.startswith("https://"):
            subscription_urls.append(stripped)
        else:
            logger.warning("Skipping unrecognized source line: %s", stripped[:80])

    logger.info(
        "Loaded %d vless URIs and %d subscription URLs from %s",
        len(vless_uris),
        len(subscription_urls),
        path,
    )
    return vless_uris, subscription_urls
