"""Excepciones de dominio, independientes del framework web.

Se traducen a respuestas HTTP mediante handlers registrados en ``main.py``. Es el
subconjunto del monolito que aplica a apuestas, más los errores propios de la
comunicación con users-service.
"""


class DomainError(Exception):
    """Base para todos los errores de dominio."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    """El recurso solicitado no existe (o no pertenece al usuario). -> 404."""


class InvalidCredentialsError(DomainError):
    """Falta la identidad del usuario o el secreto de servicio. -> 401."""


class ForbiddenError(DomainError):
    """El usuario no tiene permiso para la acción (cuenta inactiva o bloqueada). -> 403."""


class InvalidBetError(DomainError):
    """La apuesta viola una regla de negocio (p. ej. SIMPLE/PARLAY vs legs). -> 400."""


class InvalidImportFileError(DomainError):
    """El archivo de importación es inválido (no es .xlsx o faltan columnas). -> 400."""


class UserValidationUnavailableError(DomainError):
    """No se pudo confirmar el estado del usuario contra users-service. -> 503.

    Se responde fail-closed: si no hay confirmación de que la cuenta está activa y sin
    bloquear, no se acepta la apuesta. Dejar pasar la operación permitiría que una cuenta
    bloqueada siguiera apostando durante una caída del servicio de usuarios.
    """
