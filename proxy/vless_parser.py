from __future__ import annotations

import logging
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from proxy.models import ProxyConfig
from proxy.xray_compat import apply_xray_compat

logger = logging.getLogger(__name__)


def _first_param(params: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        values = params.get(key)
        if values:
            value = values[0].strip()
            if value:
                return value
    return default


def parse_vless_uri(uri: str, local_http_port: int = 0) -> Optional[ProxyConfig]:
    """Parse a vless:// URI into ProxyConfig."""
    raw = uri.strip()
    if not raw.lower().startswith("vless://"):
        return None

    try:
        parsed = urlparse(raw)
        if not parsed.hostname or not parsed.username:
            logger.warning("Invalid vless URI (missing host or uuid): %s", raw[:80])
            return None

        port = parsed.port or 443
        params = parse_qs(parsed.query, keep_blank_values=False)
        uuid = parsed.username
        address = parsed.hostname
        name = unquote(parsed.fragment) if parsed.fragment else f"{address}:{port}"

        security = _first_param(params, "security", default="reality")
        network = _first_param(params, "type", "network", default="tcp")
        flow = _first_param(params, "flow")
        sni = _first_param(params, "sni", "host")
        fp = _first_param(params, "fp", default="chrome")
        public_key = _first_param(params, "pbk", "publicKey", "public_key")
        short_id = _first_param(params, "sid", "shortId", "short_id")

        proxy_id = ProxyConfig.make_id(uuid, address, port)
        config = ProxyConfig(
            id=proxy_id,
            name=name,
            address=address,
            port=port,
            uuid=uuid,
            flow=flow,
            security=security,
            network=network,
            sni=sni,
            fp=fp,
            public_key=public_key,
            short_id=short_id,
            local_http_port=local_http_port,
        )
        skip = apply_xray_compat(config)
        if skip:
            logger.debug(
                "Skipping vless (xray incompatible): %s — %s",
                name,
                skip,
            )
            return None

        config.assign_tags()
        return config
    except Exception as exc:
        logger.warning("Failed to parse vless URI: %s (%s)", raw[:80], exc)
        return None


def extract_vless_lines(content: str) -> List[str]:
    """Extract vless:// lines from plain text or mixed content."""
    lines: List[str] = []
    for line in content.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.lower().startswith("vless://"):
            lines.append(stripped)
            continue
        for part in stripped.split():
            if part.lower().startswith("vless://"):
                lines.append(part)
    return lines
