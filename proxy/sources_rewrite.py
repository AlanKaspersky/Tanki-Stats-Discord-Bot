from __future__ import annotations

import logging
from pathlib import Path

from proxy.vless_parser import parse_vless_uri
from utils.storage import atomic_write_text

logger = logging.getLogger(__name__)


def rewrite_sources_keep_working(
    path: Path,
    working_ids: set[str],
) -> tuple[int, int]:
    """Remove vless:// lines from sources whose proxy id is not in working_ids.

    Subscription URLs, comments and blank lines are preserved.

    Returns:
        (kept_vless_count, removed_vless_count)
    """
    if not path.exists():
        return 0, 0

    lines_out: list[str] = []
    kept = 0
    removed = 0

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            lines_out.append(line)
            continue

        if stripped.lower().startswith("vless://"):
            config = parse_vless_uri(stripped, local_http_port=0)
            if config is not None and config.id in working_ids:
                lines_out.append(line)
                kept += 1
            else:
                removed += 1
            continue

        lines_out.append(line)

    text = "\n".join(lines_out)
    if lines_out:
        text += "\n"
    atomic_write_text(path, text)
    logger.info(
        "Rewrote %s: kept %d vless lines, removed %d",
        path,
        kept,
        removed,
    )
    return kept, removed
