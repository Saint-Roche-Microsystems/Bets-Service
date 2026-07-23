"""Implementaciones del puerto :class:`~bets_service.application.ports.UserValidator`.

El transporte real es TCP contra el microservicio Nest de users-service
(``@MessagePattern('users.validate')``). Mientras ese cliente no exista (T-017, de
Olivier), ``AlwaysValidUserValidator`` mantiene el servicio operativo en desarrollo.
"""

from __future__ import annotations

import logging

from bets_service.core.exceptions import UserValidationUnavailableError
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

    * Petición  — ``{"pattern": "users.validate", "id": <str>, "data": {"user_id": <str>}}``
    * Respuesta — ``{"id": <str>, "response": {"active": bool, "tier": str, "locked": bool}}``

    ambos con el framing de ``Transport.TCP`` de Nest (``<longitud>#<json>``).

    Cuando exista el cliente, esta clase es el único punto que hay que rellenar:
    ``BetService`` depende del puerto, no de ella. Debe traducir timeouts y errores de
    socket a :class:`UserValidationUnavailableError` para que la API responda 503.
    """

    def __init__(self, host: str, port: int, timeout_seconds: float) -> None:
        self._host = host
        self._port = port
        self._timeout_seconds = timeout_seconds

    async def validate(self, user_id: str) -> UserValidation:
        raise UserValidationUnavailableError(
            "El cliente TCP hacia users-service aún no está implementado (T-017)."
        )
