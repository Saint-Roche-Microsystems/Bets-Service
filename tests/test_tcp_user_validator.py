"""Tests del cliente TCP real ``TcpUserValidator`` (T-017).

Se ejercita contra un servidor asyncio mínimo que reproduce el framing del transporte
``Transport.TCP`` de Nest (``<longitud>#<json>``), sin necesitar el users-service real.
La verificación contra el servicio Nest real se hace aparte, en integración.
"""

import asyncio
import json

import pytest

from bets_service.core.exceptions import UserValidationUnavailableError
from bets_service.infrastructure.tcp.users_validator import TcpUserValidator


def _encode(payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":")).encode()
    return f"{len(body)}#".encode() + body


async def _read_frame(reader: asyncio.StreamReader) -> dict:
    length = int((await reader.readuntil(b"#"))[:-1])
    body = await reader.readexactly(length)
    return json.loads(body.decode())


async def _serve(handler):
    """Levanta un servidor Nest-like en un puerto libre y devuelve (server, port)."""

    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def test_parses_active_response():
    async def handler(reader, writer):
        req = await _read_frame(reader)
        assert req["pattern"] == "users.validate"
        assert req["data"] == {"user_id": "u1"}
        writer.write(
            _encode(
                {
                    "id": req["id"],
                    "response": {"active": True, "tier": "gold", "locked": False},
                    "isDisposed": True,
                }
            )
        )
        await writer.drain()
        writer.close()

    server, port = await _serve(handler)
    async with server:
        validator = TcpUserValidator("127.0.0.1", port, timeout_seconds=5.0)
        result = await validator.validate("u1")

    assert result.active is True
    assert result.tier == "gold"
    assert result.locked is False
    assert result.can_bet is True


async def test_parses_locked_response():
    async def handler(reader, writer):
        req = await _read_frame(reader)
        writer.write(
            _encode(
                {
                    "id": req["id"],
                    "response": {"active": True, "tier": "standard", "locked": True},
                    "isDisposed": True,
                }
            )
        )
        await writer.drain()
        writer.close()

    server, port = await _serve(handler)
    async with server:
        validator = TcpUserValidator("127.0.0.1", port, timeout_seconds=5.0)
        result = await validator.validate("u1")

    assert result.locked is True
    assert result.can_bet is False


async def test_error_response_raises_unavailable():
    async def handler(reader, writer):
        req = await _read_frame(reader)
        writer.write(
            _encode({"id": req["id"], "err": "boom", "isDisposed": True})
        )
        await writer.drain()
        writer.close()

    server, port = await _serve(handler)
    async with server:
        validator = TcpUserValidator("127.0.0.1", port, timeout_seconds=5.0)
        with pytest.raises(UserValidationUnavailableError):
            await validator.validate("u1")


async def test_connection_refused_raises_unavailable():
    # Puerto sin nadie escuchando.
    validator = TcpUserValidator("127.0.0.1", 1, timeout_seconds=2.0)
    with pytest.raises(UserValidationUnavailableError):
        await validator.validate("u1")


async def test_timeout_raises_unavailable():
    async def handler(reader, writer):
        await _read_frame(reader)
        await asyncio.sleep(1.0)  # más lento que el timeout
        writer.close()

    server, port = await _serve(handler)
    async with server:
        validator = TcpUserValidator("127.0.0.1", port, timeout_seconds=0.2)
        with pytest.raises(UserValidationUnavailableError):
            await validator.validate("u1")
