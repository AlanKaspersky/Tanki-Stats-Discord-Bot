from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from typing import Iterator

from proxy.models import ProxyConfig
from proxy.vless_parser import extract_vless_lines, parse_vless_uri
from proxy.xray_compat import apply_xray_compat


def import_subscription(
    content: str, failures: Counter[str], counts: Counter[str]
) -> Iterator[ProxyConfig]:
    text = content.lstrip("\ufeff \t\r\n")
    if text.startswith(("{", "[")):
        try:
            document = json.loads(text)
        except (ValueError, RecursionError):
            failures["invalid JSON subscription"] += 1
            return
        yield from _import_document(document, failures, counts)
        return
    for uri in extract_vless_lines(content):
        counts["entries"] += 1
        proxy = parse_vless_uri(uri, failure_counts=failures)
        if proxy is not None:
            yield proxy


def _import_document(document, failures, counts) -> Iterator[ProxyConfig]:
    if isinstance(document, list):
        for item in document:
            yield from _import_document(item, failures, counts)
    elif isinstance(document, str):
        yield from import_subscription(document, failures, counts)
    elif isinstance(document, dict):
        if "outbounds" in document:
            if not isinstance(document["outbounds"], list):
                failures["invalid JSON outbounds list"] += 1
                return
            for outbound in document["outbounds"]:
                yield from _import_outbound(outbound, failures, counts)
        elif document.get("protocol") == "vless":
            yield from _import_outbound(document, failures, counts)
        elif "configs" in document:
            yield from _import_document(document["configs"], failures, counts)
        else:
            failures["unsupported JSON subscription format"] += 1
    else:
        failures["unsupported JSON subscription entry"] += 1


def _import_outbound(outbound, failures, counts) -> Iterator[ProxyConfig]:
    if not isinstance(outbound, dict) or outbound.get("protocol") != "vless":
        failures["non-VLESS JSON outbound"] += 1
        return
    try:
        stream = deepcopy(outbound.get("streamSettings", {}))
        if outbound.get("proxySettings") or stream.get("sockopt", {}).get(
            "dialerProxy"
        ):
            failures["JSON outbound requires another outbound"] += 1
            return
        security = stream.get("security", "none").lower()
        tls = stream.get(
            "realitySettings" if security == "reality" else "tlsSettings", {}
        )
        servers = outbound.get("settings", {}).get("vnext")
        if servers is None:
            settings = outbound["settings"]
            servers = [
                {
                    "address": settings["address"],
                    "port": settings["port"],
                    "users": [settings],
                }
            ]
        for server in servers:
            if not isinstance(server, dict) or not isinstance(
                server.get("users"), list
            ):
                failures["invalid JSON VLESS server"] += 1
                continue
            for user in server["users"]:
                counts["entries"] += 1
                try:
                    if not isinstance(server["address"], str) or not server["address"]:
                        raise ValueError("Invalid server address")
                    if isinstance(server["port"], (bool, float)):
                        raise ValueError("Invalid server port")
                    if user.get("reverse"):
                        failures["unsupported VLESS reverse outbound"] += 1
                        continue
                    options = {
                        key: deepcopy(value)
                        for key, value in outbound.items()
                        if key not in ("tag", "protocol", "settings", "streamSettings")
                    }
                    options["settings"] = {
                        key: deepcopy(value)
                        for key, value in outbound["settings"].items()
                        if key
                        not in (
                            "vnext",
                            "address",
                            "port",
                            "id",
                            "flow",
                            "encryption",
                            "level",
                            "email",
                        )
                    }
                    config = ProxyConfig(
                        id="",
                        name=str(outbound.get("tag", "JSON VLESS")),
                        address=str(server["address"]).lower(),
                        port=int(server["port"]),
                        uuid=user["id"],
                        flow=user.get("flow", ""),
                        security=security,
                        network=stream.get("network", "raw"),
                        sni=tls.get("serverName", ""),
                        fp=tls.get(
                            "fingerprint", "chrome" if security == "reality" else ""
                        ),
                        public_key=tls.get("password") or tls.get("publicKey", ""),
                        short_id=tls.get("shortId", ""),
                        stream_settings=deepcopy(stream),
                        user_settings={
                            key: deepcopy(value)
                            for key, value in user.items()
                            if key not in ("address", "port", "users", "vnext")
                        },
                        outbound_options=options,
                    )
                    reason = apply_xray_compat(config)
                    if reason:
                        failures[reason.split("=", 1)[0]] += 1
                        continue
                    config.id = config.connection_id()
                    config.assign_tags()
                    yield config
                except (KeyError, TypeError, ValueError, AttributeError):
                    failures["invalid JSON VLESS entry"] += 1
    except (KeyError, TypeError, ValueError, AttributeError):
        failures["invalid JSON VLESS outbound"] += 1
