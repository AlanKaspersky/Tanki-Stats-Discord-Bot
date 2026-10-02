from __future__ import annotations

import base64
import logging
from typing import List

import aiohttp

logger = logging.getLogger(__name__)


def decode_subscription_body(body: str) -> str:
    """Decode subscription body (plain text or base64)."""
    text = body.strip()
    if not text:
        return ""

    if text.lower().startswith("vless://") or text.startswith("http"):
        return text

    try:
        padding = "=" * (-len(text) % 4)
        decoded = base64.b64decode(text + padding)
        return decoded.decode("utf-8", errors="ignore")
    except Exception:
        return text


async def fetch_subscription(url: str, session: aiohttp.ClientSession) -> str:
    """Fetch subscription content from URL."""
    try:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "TankiRatingBot/1.0"},
        ) as response:
            response.raise_for_status()
            return await response.text()
    except aiohttp.ClientError as exc:
        logger.error("Failed to fetch subscription %s: %s", url, exc)
        return ""


async def fetch_all_subscriptions(
    urls: List[str],
    session: aiohttp.ClientSession,
) -> List[str]:
    """Fetch and decode all subscription URLs, return combined vless lines."""
    all_lines: List[str] = []
    for url in urls:
        body = await fetch_subscription(url, session)
        if not body:
            continue
        decoded = decode_subscription_body(body)
        if decoded:
            all_lines.append(decoded)
    return all_lines
