from __future__ import annotations

import logging
import json
from collections import Counter
from html import unescape
import re
from typing import List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from proxy.models import ProxyConfig
from proxy.xray_compat import apply_xray_compat

logger = logging.getLogger(__name__)
EMAIL_MASK = re.compile(r"\[\s*email\s*protected\s*\]", re.IGNORECASE)


def has_masked_authority(uri: str) -> bool:
    authority = unquote(unescape(uri)).split("://", 1)[-1]
    authority = re.split(r"[/?#]", authority, maxsplit=1)[0]
    return EMAIL_MASK.search(authority) is not None


def _first_param(params: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        values = params.get(key)
        if values:
            value = values[0].strip()
            if value:
                return value
    return default


def parse_vless_uri(
    uri: str, local_http_port: int = 0, *, failure_counts: Optional[Counter[str]] = None
) -> Optional[ProxyConfig]:
    """Parse a vless:// URI into ProxyConfig."""
    raw = unescape(uri.strip())
    if not raw.lower().startswith("vless://"):
        return None

    def reject(reason: str) -> None:
        if failure_counts is not None:
            failure_counts[reason] += 1
        logger.debug("Skipping invalid VLESS entry: %s", reason)

    if has_masked_authority(raw):
        reject("masked user ID/address (email protection)")
        return None

    try:
        parsed = urlparse(raw)
        if not parsed.hostname or not parsed.username:
            reject("missing host or user ID")
            return None

        port = 443 if parsed.port is None else parsed.port
        params = parse_qs(parsed.query, keep_blank_values=False)
        uuid = unquote(parsed.username)
        address = parsed.hostname
        name = unquote(parsed.fragment) if parsed.fragment else f"{address}:{port}"

        security = _first_param(params, "security", default="none")
        network = _first_param(params, "type", "network", default="tcp")
        flow = _first_param(params, "flow")
        sni = _first_param(params, "sni", "serverName")
        fp = _first_param(params, "fp", default="chrome")
        public_key = _first_param(params, "pbk", "publicKey", "public_key", "password")
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
            stream_settings=_uri_stream_settings(params, network, security),
            user_settings={
                "encryption": _first_param(params, "encryption", default="none")
            },
        )
        skip = apply_xray_compat(config)
        if skip:
            reject(skip.split("=", 1)[0])
            return None

        config.id = config.connection_id()
        config.assign_tags()
        return config
    except Exception as exc:
        reject(f"invalid URI syntax ({type(exc).__name__})")
        return None


def _uri_stream_settings(params: dict, network: str, security: str) -> dict:
    from proxy.xray_compat import normalize_network

    network = normalize_network(network, security)
    host = _first_param(params, "host")
    path = _first_param(params, "path", default="/")
    settings = {}
    if network in ("ws", "httpupgrade", "xhttp"):
        key = {
            "ws": "wsSettings",
            "httpupgrade": "httpupgradeSettings",
            "xhttp": "xhttpSettings",
        }[network]
        settings[key] = {"host": host, "path": path}
        if network == "xhttp":
            settings[key]["mode"] = _first_param(params, "mode", default="auto")
            extra = _first_param(params, "extra")
            if extra:
                value = json.loads(extra)
                if not isinstance(value, dict):
                    raise ValueError("XHTTP extra must be an object")
                settings[key]["extra"] = value
        elif network == "ws":
            early_data = _first_param(params, "ed")
            if early_data and "ed=" not in path:
                settings[key]["path"] += (
                    "&" if "?" in path else "?"
                ) + f"ed={int(early_data)}"
    elif network == "grpc":
        settings["grpcSettings"] = {
            "serviceName": _first_param(params, "serviceName", "service_name"),
            "multiMode": _first_param(params, "mode") == "multi",
            "authority": _first_param(params, "authority", "host"),
        }
    elif (
        network == "raw"
        and _first_param(params, "headerType", default="none") != "none"
    ):
        header_type = _first_param(params, "headerType")
        if header_type != "http":
            raise ValueError("Unsupported RAW header")
        settings["rawSettings"] = {
            "header": {"type": "http", "request": {"path": [path]}}
        }
        if host:
            settings["rawSettings"]["header"]["request"]["headers"] = {
                "Host": host.split(",")
            }
    if security.lower() in ("tls", "reality"):
        key = "tlsSettings" if security.lower() == "tls" else "realitySettings"
        settings[key] = {}
        alpn = _first_param(params, "alpn")
        if alpn and key == "tlsSettings":
            settings[key]["alpn"] = [
                value.strip() for value in alpn.split(",") if value.strip()
            ]
        insecure = _first_param(params, "allowInsecure", "insecure")
        if insecure and key == "tlsSettings":
            settings[key]["allowInsecure"] = insecure.lower() in ("1", "true", "yes")
        spider_x = _first_param(params, "spx", "spiderX")
        if spider_x and key == "realitySettings":
            settings[key]["spiderX"] = spider_x
        pqv = _first_param(params, "pqv", "mldsa65Verify")
        if pqv and key == "realitySettings":
            settings[key]["mldsa65Verify"] = pqv
    return settings


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
