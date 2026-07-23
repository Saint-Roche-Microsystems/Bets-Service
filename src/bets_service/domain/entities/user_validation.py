"""Resultado de validar un usuario contra users-service.

Entidad de dominio pura: es la forma en que este servicio entiende la respuesta del patrón
TCP ``users.validate``, con independencia de cómo la serialice el transporte.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class UserValidation:
    """Estado operativo de un usuario.

    ``locked`` no lo decide users-service por sí mismo: procede de auth-service
    (``GET /internal/lock-status/{user_id}``), que aquél consulta en el hop B->C y combina
    en su respuesta. Es lo que permite que una cuenta bloqueada por intentos de login
    fallidos tampoco pueda seguir apostando.
    """

    active: bool
    tier: str = "standard"
    locked: bool = False

    @property
    def can_bet(self) -> bool:
        """Indica si el usuario puede operar: cuenta activa y sin bloqueo temporal."""

        return self.active and not self.locked
