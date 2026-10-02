from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from proxy.models import ProxyConfig
from proxy.xray_compat import normalize_network

logger = logging.getLogger(__name__)


def _build_outbound(proxy: ProxyConfig) -> Dict[str, Any]:
    stream_settings: Dict[str, Any] = {
        "network": normalize_network(proxy.network, proxy.security),
    }

    if proxy.security == "reality":
        stream_settings["security"] = "reality"
        stream_settings["realitySettings"] = {
            "serverName": proxy.sni,
            "fingerprint": proxy.fp,
            "publicKey": proxy.public_key,
            "shortId": proxy.short_id,
            "show": False,
        }
    elif proxy.security == "tls":
        stream_settings["security"] = "tls"
        stream_settings["tlsSettings"] = {
            "serverName": proxy.sni or proxy.address,
            "fingerprint": proxy.fp,
        }

    user: Dict[str, Any] = {
        "id": proxy.uuid,
        "encryption": "none",
    }
    if proxy.flow:
        user["flow"] = proxy.flow

    outbound: Dict[str, Any] = {
        "tag": proxy.outbound_tag,
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": proxy.address,
                    "port": proxy.port,
                    "users": [user],
                }
            ]
        },
        "streamSettings": stream_settings,
    }
    return outbound


def _build_inbound(proxy: ProxyConfig) -> Dict[str, Any]:
    return {
        "tag": proxy.inbound_tag,
        "listen": "127.0.0.1",
        "port": proxy.local_http_port,
        "protocol": "http",
        "settings": {},
        "sniffing": {
            "enabled": False,
        },
    }


def build_xray_config(proxies: List[ProxyConfig]) -> Dict[str, Any]:
    """Build full xray-core JSON config for all proxies."""
    inbounds = [_build_inbound(proxy) for proxy in proxies]
    outbounds = [_build_outbound(proxy) for proxy in proxies]
    outbounds.append({"protocol": "freedom", "tag": "direct", "settings": {}})

    routing_rules = [
        {
            "type": "field",
            "inboundTag": [proxy.inbound_tag],
            "outboundTag": proxy.outbound_tag,
        }
        for proxy in proxies
    ]

    config: Dict[str, Any] = {
        "log": {"loglevel": "warning"},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {
            "domainStrategy": "AsIs",
            "rules": routing_rules,
        },
    }
    return config


def write_xray_config(path: Path, proxies: List[ProxyConfig]) -> None:
    """Write xray runtime config to disk."""
    config = build_xray_config(proxies)
    from utils.storage import atomic_write_json

    atomic_write_json(path, config)
    logger.info("Wrote xray config with %d proxies to %s", len(proxies), path)
