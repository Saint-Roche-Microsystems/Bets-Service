"""Puertos (interfaces) de la capa de aplicación.

Permiten que un caso de uso dependa de una capacidad abstracta en lugar de una
implementación concreta, evitando acoplamiento y ciclos de import.
"""

from typing import Protocol

from bets_service.domain.entities.user_validation import UserValidation


class UserValidator(Protocol):
    """Capacidad de confirmar que un usuario puede operar.

    Es el hop A->B de la cadena síncrona: ``bets-service`` pregunta a ``users-service``
    (patrón TCP ``users.validate``) si la cuenta está activa y con qué tier opera, antes de
    aceptar una apuesta.

    Se define como puerto para no bloquear la extracción de este servicio mientras el
    cliente TCP real (T-017, de Olivier) no exista. Debe señalar los fallos de transporte
    con :class:`UserValidationUnavailableError`: quien lo llama no conoce ``asyncio`` ni el
    framing de Nest.
    """

    async def validate(self, user_id: str) -> UserValidation: ...
