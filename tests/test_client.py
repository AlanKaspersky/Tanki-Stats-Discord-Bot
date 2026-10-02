import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from proxy.models import ProxyConfig
from proxy.pool import ProxyPool
from utils.tanki_client import fetch_tanki_stats, _parse_stats_payload


class Response:
    def __init__(self, status=200, payload=None, error=None):
        self.status, self.payload, self.error = status, payload, error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        if self.error:
            raise self.error
        return self.payload


def pool():
    return ProxyPool(
        [
            ProxyConfig(
                id=str(i),
                name=str(i),
                address="example.invalid",
                port=443,
                uuid="test",
                local_http_port=18000 + i,
            )
            for i in range(3)
        ]
    )


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_request_returns_stats(self):
        session = SimpleNamespace(
            get=Mock(return_value=Response(payload={"response": {"score": 1}}))
        )
        self.assertEqual(await fetch_tanki_stats(session, "url"), ({"score": 1}, None))

    async def test_429_rotates_and_recovers(self):
        p = pool()
        session = SimpleNamespace(
            get=Mock(
                side_effect=[
                    Response(429),
                    Response(payload={"response": {"score": 1}}),
                ]
            )
        )
        self.assertEqual(
            await fetch_tanki_stats(session, "url", p), ({"score": 1}, None)
        )
        urls = [call.kwargs["proxy"] for call in session.get.call_args_list]
        self.assertNotEqual(urls[0], urls[1])
        self.assertEqual(p.cooldown_count, 1)
        await p.cleanup_task_binding()

    async def test_all_429_returns_exhaustion_instead_of_unhandled_exception(self):
        p = pool()
        with patch.dict("os.environ", {"PROFILE_FETCH_429_ABORT": "10"}):
            session = SimpleNamespace(get=Mock(return_value=Response(429)))
            stats, reason = await fetch_tanki_stats(session, "url", p)
        self.assertIsNone(stats)
        self.assertIn("429", reason)
        self.assertEqual(p.cooldown_count, 3)
        await p.cleanup_task_binding()

    async def test_connection_rotation_exhaustion_is_structured(self):
        p = pool()
        p.rotate_for_current_task = AsyncMock(
            side_effect=__import__(
                "proxy.pool", fromlist=["ProxyPoolExhausted"]
            ).ProxyPoolExhausted()
        )
        session = SimpleNamespace(get=Mock(side_effect=asyncio.TimeoutError()))
        stats, reason = await fetch_tanki_stats(session, "url", p)
        self.assertIsNone(stats)
        self.assertEqual(reason, "proxy pool exhausted")
        await p.cleanup_task_binding()

    async def test_404_is_not_retried_as_proxy_failure(self):
        p = pool()
        session = SimpleNamespace(get=Mock(return_value=Response(404)))
        self.assertEqual(
            await fetch_tanki_stats(session, "url", p), (None, "API HTTP 404")
        )
        self.assertEqual(session.get.call_count, 1)
        await p.cleanup_task_binding()

    async def test_invalid_json_is_a_fetch_failure(self):
        session = SimpleNamespace(
            get=Mock(return_value=Response(error=ValueError("invalid JSON")))
        )
        self.assertEqual(
            await fetch_tanki_stats(session, "url"), (None, "invalid API JSON")
        )

    async def test_malformed_payloads_do_not_reach_formatter(self):
        for payload in [
            [],
            {"response": []},
            {"response": "bad"},
            {"response": {"kills": "bad"}},
            {"response": {"modesPlayed": [{}]}},
            {"response": {"turretsPlayed": [None]}},
        ]:
            with self.subTest(payload=payload):
                self.assertIsNone(_parse_stats_payload(payload))
                session = SimpleNamespace(
                    get=Mock(return_value=Response(payload=payload))
                )
                result = await fetch_tanki_stats(session, "url")
                self.assertEqual(result, (None, "empty or invalid API response"))
