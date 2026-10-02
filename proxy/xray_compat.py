from __future__ import annotations

import logging
import base64
from typing import List, Optional, Tuple

from proxy.models import ProxyConfig

logger = logging.getLogger(__name__)

REALITY_NETWORKS = frozenset({"tcp", "raw", "xhttp", "grpc"})
SUPPORTED_SECURITY = frozenset({"reality", "tls", "none"})
SUPPORTED_NETWORKS = frozenset({"raw", "tcp", "ws", "grpc", "xhttp", "httpupgrade"})
SUPPORTED_FLOWS = frozenset({"", "xtls-rprx-vision", "xtls-rprx-vision-udp443"})


def valid_xray_user_id(value: str) -> bool:
    """Match Xray 26.x UUID parsing, including custom IDs up to 30 UTF-8 bytes."""
    if not isinstance(value, str):
        return False
    try:
        text = value.encode("utf-8")
    except UnicodeError:
        return False
    length = len(text)
    if length < 32 or length > 36:
        return 0 < length <= 30
    for group_size in (8, 4, 4, 4, 12):
        if text.startswith(b"-"):
            text = text[1:]
        group = text[:group_size]
        if len(group) != group_size or any(
            char not in b"0123456789abcdefABCDEF" for char in group
        ):
            return False
        text = text[group_size:]
    return True


def normalize_network(network: str, security: str) -> str:
    """Привести type/network из URI к значению для xray streamSettings.network."""
    n = (network or "tcp").lower().strip()
    n = {"websocket": "ws", "splithttp": "xhttp", "tcp": "raw"}.get(n, n)
    return n


def xray_skip_reason(config: ProxyConfig) -> Optional[str]:
    """Причина пропуска прокси; None — можно писать в proxies.json и xray config."""
    security = (config.security or "").lower().strip()
    network_uri = (config.network or "tcp").lower().strip()

    if security not in SUPPORTED_SECURITY:
        return f"unsupported security={security!r}"
    network_uri = normalize_network(network_uri, security)
    if network_uri not in SUPPORTED_NETWORKS:
        return f"unsupported network={network_uri!r}"
    if not config.address or not 1 <= config.port <= 65535:
        return "invalid server address or port"

    if not valid_xray_user_id(config.uuid):
        return "invalid VLESS user ID for Xray"

    if (config.flow or "") not in SUPPORTED_FLOWS:
        return f"unsupported VLESS flow={config.flow!r}"

    if security == "reality":
        if network_uri not in REALITY_NETWORKS:
            return (
                f"REALITY does not support network={network_uri!r} "
                f"(allowed: tcp/raw, xhttp, grpc)"
            )
        if not config.public_key:
            return "REALITY missing publicKey (pbk)"
        try:
            if (
                "=" in config.public_key
                or len(
                    base64.b64decode(
                        config.public_key + "=" * (-len(config.public_key) % 4),
                        altchars=b"-_",
                        validate=True,
                    )
                )
                != 32
            ):
                return "invalid REALITY publicKey"
        except (ValueError, TypeError):
            return "invalid REALITY publicKey"
        if (
            len(config.short_id) > 16
            or len(config.short_id) % 2
            or any(char not in "0123456789abcdefABCDEF" for char in config.short_id)
        ):
            return "invalid REALITY shortId"

    return None


def apply_xray_compat(config: ProxyConfig) -> Optional[str]:
    """Нормализует поля config; возвращает причину пропуска или None."""
    config.security = (config.security or "reality").lower().strip()
    reason = xray_skip_reason(config)
    if reason:
        return reason
    config.network = normalize_network(config.network, config.security)
    return None


def filter_xray_compatible(
    proxies: List[ProxyConfig],
) -> Tuple[List[ProxyConfig], int]:
    """Оставить только прокси, с которыми xray соберёт outbound."""
    kept: List[ProxyConfig] = []
    dropped = 0
    for proxy in proxies:
        reason = apply_xray_compat(proxy)
        if reason:
            dropped += 1
            logger.debug(
                "Skipping proxy %s (%s): %s",
                proxy.id,
                proxy.name,
                reason,
            )
            continue
        proxy.assign_tags()
        kept.append(proxy)
    return kept, dropped
