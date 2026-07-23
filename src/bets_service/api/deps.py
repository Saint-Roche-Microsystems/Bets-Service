"""Dependencias de FastAPI: identidad del usuario, secreto de servicio y servicios.

A diferencia del monolito, aquí **no hay consulta a la colección ``users``**: la identidad
llega resuelta en la cabecera ``X-User-Id`` que inyecta el api-gateway tras validar el JWT
en el borde. Este servicio no vuelve a decodificar el token.
"""

import secrets
from typing import Annotated

from fastapi import Depends, Header, Request
from pymongo.asynchronous.database import AsyncDatabase

from bets_service.application.ports import UserValidator
from bets_service.application.services.bet_import_service import BetImportService
from bets_service.application.services.bet_service import BetService
from bets_service.core.config import Settings, get_settings
from bets_service.core.exceptions import InvalidCredentialsError
from bets_service.domain.repositories.bet_repository import BetRepository
from bets_service.infrastructure.repositories.mongo_bet_repository import MongoBetRepository
from bets_service.infrastructure.tcp.users_validator import (
    AlwaysValidUserValidator,
    TcpUserValidator,
)


def get_db(request: Request) -> AsyncDatabase:
    """Devuelve la base de datos MongoDB del estado de la aplicación."""

    return request.app.state.db


async def require_internal_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_internal_key: Annotated[str | None, Header()] = None,
) -> None:
    """Exige el secreto de servicio compartido en toda la superficie del servicio.

    Es imprescindible aquí: como la identidad del usuario se toma de una cabecera, sin este
    secreto cualquiera que alcanzara el servicio podría operar en nombre de otro usuario
    simplemente enviando su ``X-User-Id``.

    ``compare_digest`` evita filtrar el secreto por el tiempo que tarda la comparación.
    """

    if not settings.internal_api_key:
        # No debería ocurrir: main.py aborta el arranque sin secreto. Es la red de
        # seguridad por si alguien construye la app saltándose la factoría.
        raise InvalidCredentialsError("El secreto de servicio no está configurado.")

    if x_internal_key is None or not secrets.compare_digest(
        x_internal_key, settings.internal_api_key
    ):
        raise InvalidCredentialsError("Secreto de servicio inválido o ausente.")


async def get_current_user_id(
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    """Identidad del usuario en curso, resuelta por el api-gateway.

    El id es opaco para este servicio: solo se usa como clave de propiedad de las apuestas.
    """

    if not x_user_id:
        raise InvalidCredentialsError("Falta la cabecera X-User-Id.")
    return x_user_id


CurrentUserId = Annotated[str, Depends(get_current_user_id)]


def get_bet_repository(
    db: Annotated[AsyncDatabase, Depends(get_db)],
) -> BetRepository:
    return MongoBetRepository(db)


def get_user_validator(
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserValidator:
    """Validador de usuario, o el permisivo de desarrollo si no hay users-service."""

    if not settings.users_service_tcp_host:
        return AlwaysValidUserValidator()
    return TcpUserValidator(
        settings.users_service_tcp_host,
        settings.users_service_tcp_port,
        settings.users_service_timeout_seconds,
    )


def get_bet_service(
    bets: Annotated[BetRepository, Depends(get_bet_repository)],
    users: Annotated[UserValidator, Depends(get_user_validator)],
) -> BetService:
    return BetService(bets, users)


def get_bet_import_service(
    bet_service: Annotated[BetService, Depends(get_bet_service)],
    bets: Annotated[BetRepository, Depends(get_bet_repository)],
) -> BetImportService:
    return BetImportService(bet_service, bets)
