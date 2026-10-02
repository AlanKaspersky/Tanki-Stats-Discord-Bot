from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class ProxyConfig:
    """Normalized VLESS+Reality proxy configuration."""

    id: str
    name: str
    address: str
    port: int
    uuid: str
    flow: str = ""
    security: str = "reality"
    network: str = "tcp"
    sni: str = ""
    fp: str = "chrome"
    public_key: str = ""
    short_id: str = ""
    local_http_port: int = 0
    inbound_tag: str = field(default="", repr=False)
    outbound_tag: str = field(default="", repr=False)
    stream_settings: Dict[str, Any] = field(default_factory=dict)
    user_settings: Dict[str, Any] = field(default_factory=dict)
    outbound_options: Dict[str, Any] = field(default_factory=dict)

    def connection_id(self) -> str:
        from proxy.xray_config import _build_outbound

        outbound = _build_outbound(self)
        outbound.pop("tag", None)
        for server in outbound["settings"]["vnext"]:
            for user in server["users"]:
                user.pop("email", None)
                user.pop("level", None)
        raw = json.dumps(outbound, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def make_id(uuid: str, address: str, port: int) -> str:
        raw = f"{uuid}@{address}:{port}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def http_proxy_url(self) -> str:
        return f"http://127.0.0.1:{self.local_http_port}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "address": self.address,
            "port": self.port,
            "uuid": self.uuid,
            "flow": self.flow,
            "security": self.security,
            "network": self.network,
            "sni": self.sni,
            "fp": self.fp,
            "public_key": self.public_key,
            "short_id": self.short_id,
            "local_http_port": self.local_http_port,
            "stream_settings": deepcopy(self.stream_settings),
            "user_settings": deepcopy(self.user_settings),
            "outbound_options": deepcopy(self.outbound_options),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProxyConfig":
        proxy_id = data["id"]
        return cls(
            id=proxy_id,
            name=data.get("name", proxy_id),
            address=data["address"],
            port=int(data["port"]),
            uuid=data["uuid"],
            flow=data.get("flow", ""),
            security=data.get("security", "reality"),
            network=data.get("network", "tcp"),
            sni=data.get("sni", ""),
            fp=data.get("fp", "chrome"),
            public_key=data.get("public_key", ""),
            short_id=data.get("short_id", ""),
            local_http_port=int(data.get("local_http_port", 0)),
            inbound_tag=f"http-in-{proxy_id}",
            outbound_tag=f"vless-out-{proxy_id}",
            stream_settings=deepcopy(data.get("stream_settings", {})),
            user_settings=deepcopy(data.get("user_settings", {})),
            outbound_options=deepcopy(data.get("outbound_options", {})),
        )

    def assign_tags(self) -> None:
        self.inbound_tag = f"http-in-{self.id}"
        self.outbound_tag = f"vless-out-{self.id}"
