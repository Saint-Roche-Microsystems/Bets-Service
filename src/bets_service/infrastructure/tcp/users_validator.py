"""Implementaciones del puerto :class:`~bets_service.application.ports.UserValidator`.

El transporte real es TCP contra el microservicio Nest de users-service
(``@MessagePattern('users.validate')``). Mientras ese cliente no exista (T-017, de
Olivier), ``AlwaysValidUserValidator`` mantiene el servicio operativo en desarrollo.
"""

from __future__ import annotations

import asyncio
import json
import logging

from bets_service.core.exceptions import UserValidationUnavailableError
from bets_service.core.logging import get_request_id
from bets_service.domain.entities.user_validation import UserValidation

logger = logging.getLogger(__name__)


class AlwaysValidUserValidator:
    """Acepta cualquier usuario. Sólo para desarrollo, sin users-service delante.

    Deja rastro en el log de cada validación que no llegó a hacerse, para que no pase
    inadvertido que el servicio está corriendo sin la comprobación real.
    """

    async def validate(self, user_id: str) -> UserValidation:
        logger.info(
            "users-service no configurado: se acepta el usuario sin validar.",
            extra={"user_id": user_id},
        )
        return UserValidation(active=True, tier="standard", locked=False)


class TcpUserValidator:
    """Cliente TCP contra ``users.validate`` de users-service. **Pendiente de T-017.**

    El contrato con el que se integrará, ya fijado con Olivier:

    * Petición  — ``{"pattern": "users.validate", "id": <str>,
      "data": {"user_id": <str>, "request_id": <str|None>}}``
    * Respuesta — ``{"id": <str>, "response": {"active": bool, "tier": str, "locked": bool}}``

    ambos con el framing de ``Transport.TCP`` de Nest (``<longitud>#<json>``).

    Cuando exista el cliente, esta clase es el único punto que hay que rellenar:
    ``BetService`` depende del puerto, no de ella. Debe traducir timeouts y errores de
    socket a :class:`UserValidationUnavailableError` para que la API responda 503.
    """

    PATTERN = "users.validate"

    def __init__(self, host: str, port: int, timeout_seconds: float) -> None:
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds

    async def validate(self, user_id: str) -> UserValidation:
        try:
            response = await asyncio.wait_for(
                self._request({"user_id": user_id, "request_id": get_request_id()}),
                timeout=self._timeout_seconds,
            )
        except (asyncio.TimeoutError, OSError, ValueError) as exc:
            # Timeout, socket caído o respuesta ilegible: quien llama no conoce el
            # transporte, así que se traduce a un fallo de disponibilidad (API -> 503).
            raise UserValidationUnavailableError(
                f"No se pudo validar el usuario contra users-service: {exc}"
            ) from exc

        return UserValidation(
            active=bool(response.get("active", False)),
            tier=response.get("tier") or "standard",
            locked=bool(response.get("locked", False)),
        )

    async def _request(self, data: dict[str, object]) -> dict[str, object]:
        """Envía un mensaje al transporte TCP de Nest y devuelve el campo ``response``.

        Framing de Nest ``Transport.TCP``: cada mensaje va como ``<longitud>#<json>``,
        donde ``longitud`` es el número de bytes del JSON. La petición es
        ``{"pattern", "id", "data"}`` y la respuesta ``{"id", "response", "isDisposed"}``.
        """

        reader, writer = await asyncio.open_connection(self._host, self._port)
        try:
            payload = {"pattern": self.PATTERN, "id": "1", "data": data}
            writer.write(self._encode(payload))
            await writer.drain()

            message = await self._read_frame(reader)
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

        if message.get("err"):
            raise UserValidationUnavailableError(str(message["err"]))

        response = message.get("response")
        if not isinstance(response, dict):
            raise ValueError(f"Respuesta TCP sin objeto 'response': {message!r}")
        return response

    @staticmethod
    def _encode(payload: dict[str, object]) -> bytes:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return f"{len(body)}#".encode("utf-8") + body

    @staticmethod
    async def _read_frame(reader: asyncio.StreamReader) -> dict[str, object]:
        # Prefijo de longitud hasta el separador '#'.
        length_bytes = await reader.readuntil(b"#")
        length = int(length_bytes[:-1])
        body = await reader.readexactly(length)
        return json.loads(body.decode("utf-8"))
