from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from proxy.models import ProxyConfig

logger = logging.getLogger(__name__)

REALITY_NETWORKS = frozenset({"tcp", "raw", "xhttp", "grpc"})
SUPPORTED_SECURITY = frozenset({"reality", "tls"})


def normalize_network(network: str, security: str) -> str:
    """Привести type/network из URI к значению для xray streamSettings.network."""
    n = (network or "tcp").lower().strip()
    sec = (security or "reality").lower().strip()
    if sec == "reality" and n == "tcp":
        return "raw"
    return n


def xray_skip_reason(config: ProxyConfig) -> Optional[str]:
    """Причина пропуска прокси; None — можно писать в proxies.json и xray config."""
    security = (config.security or "").lower().strip()
    network_uri = (config.network or "tcp").lower().strip()

    if security not in SUPPORTED_SECURITY:
        return f"unsupported security={security!r} (need reality or tls)"

    if security == "reality":
        if network_uri not in REALITY_NETWORKS:
            return (
                f"REALITY does not support network={network_uri!r} "
                f"(allowed: tcp/raw, xhttp, grpc)"
            )
        if not config.public_key:
            return "REALITY missing publicKey (pbk)"
        if not config.short_id:
            return "REALITY missing shortId (sid)"

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
