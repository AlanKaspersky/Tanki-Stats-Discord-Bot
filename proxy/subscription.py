from __future__ import annotations

import asyncio
import base64
import logging
from typing import Awaitable, Callable, List, Optional
from urllib.parse import urlsplit

import aiohttp
from proxy.vless_parser import extract_vless_lines, has_masked_authority

logger = logging.getLogger(__name__)


def decode_subscription_body(body: str) -> str:
    """Decode subscription body (plain text or base64)."""
    text = body.strip()
    if not text:
        return ""

    if text.lower().startswith("vless://") or text.startswith("http"):
        return text

    try:
        compact = "".join(text.split())
        padding = "=" * (-len(compact) % 4)
        decoded = base64.b64decode(compact + padding, altchars=b"-_", validate=True)
        return decoded.decode("utf-8")
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
        logger.error(
            "Failed to fetch subscription from %s: %s",
            urlsplit(url).hostname,
            type(exc).__name__,
        )
        return ""


async def fetch_all_subscriptions(
    urls: List[str],
    session: aiohttp.ClientSession,
    *,
    stage_callback: Optional[Callable[[str], Awaitable[None]]] = None,
) -> List[str]:
    """Fetch and decode all subscription URLs, return combined vless lines."""
    all_lines: List[str] = []
    for index, url in enumerate(urls, 1):
        if stage_callback:
            await stage_callback(f"Загрузка подписки {index}/{len(urls)}...")
        body = await fetch_subscription(url, session)
        if not body:
            continue
        decoded, masked = await asyncio.to_thread(_decode_and_count_masks, body)
        if decoded:
            if masked:
                logger.warning(
                    "Subscription #%d (%s) contains %d masked email placeholders; affected VLESS entries cannot be restored",
                    index,
                    urlsplit(url).hostname,
                    masked,
                )
            all_lines.append(decoded)
    return all_lines


def _decode_and_count_masks(body: str) -> tuple[str, int]:
    decoded = decode_subscription_body(body)
    masked = sum(has_masked_authority(line) for line in extract_vless_lines(decoded))
    return decoded, masked
