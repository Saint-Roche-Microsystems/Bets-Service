"""Router interno: lectura de apuestas servicio a servicio, no expuesta al cliente final.

Este servicio es el dueño de la colección ``bets``; nadie más la lee directamente. Quien
necesite las apuestas de un usuario (hoy, el servicio de progresión para recalcular sus
estadísticas al consumir ``bet.created``) las pide por aquí.

Diferencia clave con ``/bets/*``: allí la identidad llega resuelta en ``X-User-Id`` porque
el llamante es una persona detrás del api-gateway; aquí el llamante es otro servicio que
pregunta por un usuario cualquiera, así que el ``user_id`` viaja como query param y no se
usa ``CurrentUserId``. El secreto de servicio se declara a nivel de router, igual que en
auth-service: ninguna ruta interna que se añada después puede olvidarse de la protección.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from bets_service.api.deps import get_bet_service, require_internal_key
from bets_service.api.schemas.bet import BetResponse, PaginatedBets
from bets_service.api.schemas.internal import UserIdsResponse
from bets_service.application.services.bet_service import BetService

router = APIRouter(
    prefix="/internal",
    tags=["internal"],
    dependencies=[Depends(require_internal_key)],
)


@router.get(
    "/bets/user-ids",
    response_model=UserIdsResponse,
    summary="Listar los user_ids con al menos una apuesta",
)
async def list_user_ids(
    service: Annotated[BetService, Depends(get_bet_service)],
) -> UserIdsResponse:
    """Enumera a quién hay que recalcular en una carga inicial o un backfill."""

    return UserIdsResponse(user_ids=await service.list_user_ids())


@router.get(
    "/bets",
    response_model=PaginatedBets,
    summary="Listar las apuestas de un usuario (servicio a servicio)",
)
async def list_bets_of_user(
    service: Annotated[BetService, Depends(get_bet_service)],
    user_id: Annotated[str, Query(min_length=1, description="Dueño de las apuestas.")],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 200,
) -> PaginatedBets:
    """Misma forma de respuesta que ``GET /bets``, pero para un usuario arbitrario.

    El tope de 500 es más alto que el de la ruta pública (100) porque el consumidor recorre
    el historial completo de un usuario, no una pantalla; y sigue acotado para que una
    respuesta no crezca sin límite. Quien necesite todo el historial itera hasta ``total``.

    No valida al usuario contra users-service: es una lectura, y ``list_bets`` no pasa por
    ``_ensure_can_bet``. Un usuario inexistente devuelve simplemente una página vacía.
    """

    items, total = await service.list_bets(user_id, page=page, page_size=page_size)
    return PaginatedBets(
        items=[BetResponse.from_entity(bet) for bet in items],
        total=total,
        page=page,
        page_size=page_size,
    )
