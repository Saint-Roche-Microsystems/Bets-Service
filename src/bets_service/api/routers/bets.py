"""Router de apuestas: CRUD con paginación y filtros.

Todas las rutas exigen el secreto de servicio (``X-Internal-Key``) y la identidad del
usuario (``X-User-Id``), que inyecta el api-gateway tras validar el JWT en el borde.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status

from bets_service.api.deps import (
    CurrentUserId,
    get_bet_import_service,
    get_bet_service,
    require_internal_key,
)
from bets_service.api.schemas.bet import (
    BetCreate,
    BetResponse,
    BetUpdate,
    PaginatedBets,
)
from bets_service.api.schemas.imports import ImportSummaryResponse
from bets_service.application.services.bet_import_service import BetImportService
from bets_service.application.services.bet_service import BetService
from bets_service.core.exceptions import InvalidImportFileError
from bets_service.domain.entities.bet import BetStatus, BetType
from bets_service.infrastructure.excel.bet_import_reader import read_bet_rows
from bets_service.infrastructure.excel.template_generator import build_bet_template

router = APIRouter(
    prefix="/bets",
    tags=["bets"],
    dependencies=[Depends(require_internal_key)],
)

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.post(
    "",
    response_model=BetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear una apuesta",
)
async def create_bet(
    body: BetCreate,
    user_id: CurrentUserId,
    service: Annotated[BetService, Depends(get_bet_service)],
) -> BetResponse:
    bet = await service.create_bet(user_id, body.model_dump())
    return BetResponse.from_entity(bet)


@router.get(
    "",
    response_model=PaginatedBets,
    summary="Listar las apuestas del usuario con paginación y filtros",
)
async def list_bets(
    user_id: CurrentUserId,
    service: Annotated[BetService, Depends(get_bet_service)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status_filter: Annotated[BetStatus | None, Query(alias="status")] = None,
    sport: str | None = None,
    bet_type: BetType | None = None,
) -> PaginatedBets:
    items, total = await service.list_bets(
        user_id,
        page=page,
        page_size=page_size,
        status=status_filter,
        sport=sport,
        bet_type=bet_type,
    )
    return PaginatedBets(
        items=[BetResponse.from_entity(b) for b in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/template",
    summary="Descargar la plantilla Excel para importar apuestas",
    response_class=Response,
    responses={
        200: {
            "content": {_XLSX_MEDIA_TYPE: {}},
            "description": "Archivo .xlsx con encabezados y listas desplegables "
            "(Estado, Tipo de apuesta).",
        }
    },
)
async def download_template(_user_id: CurrentUserId) -> Response:
    """Genera y descarga la plantilla `.xlsx`.

    Columnas: Deporte, Liga, Evento, Tipo de apuesta (SIMPLE/PARLAY), Mercado,
    Selección, Cuota (>1), Stake (>0), Casa de apuestas, Fecha y hora del evento,
    Estado (PENDING/WON/LOST/VOID), Notas y ID de referencia (opcional).
    """

    content = build_bet_template()
    return Response(
        content=content,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="plantilla_apuestas.xlsx"'},
    )


@router.post(
    "/import",
    response_model=ImportSummaryResponse,
    summary="Importar apuestas desde un archivo .xlsx",
)
async def import_bets(
    user_id: CurrentUserId,
    service: Annotated[BetImportService, Depends(get_bet_import_service)],
    file: Annotated[UploadFile, File(description="Archivo .xlsx con las apuestas.")],
) -> ImportSummaryResponse:
    """Procesa la plantilla rellena y devuelve un resumen de la importación.

    Cada fila se valida con las mismas reglas que la creación individual y las
    filas con errores se rechazan sin detener el procesamiento de las demás.
    """

    if not (file.filename or "").lower().endswith(".xlsx"):
        raise InvalidImportFileError("El archivo debe tener extensión .xlsx.")

    data = await file.read()
    rows = read_bet_rows(data)
    summary = await service.import_rows(user_id, rows)
    return ImportSummaryResponse.from_summary(summary)


@router.get(
    "/{bet_id}",
    response_model=BetResponse,
    summary="Obtener una apuesta por su ID",
)
async def get_bet(
    bet_id: str,
    user_id: CurrentUserId,
    service: Annotated[BetService, Depends(get_bet_service)],
) -> BetResponse:
    bet = await service.get_bet(user_id, bet_id)
    return BetResponse.from_entity(bet)


@router.put(
    "/{bet_id}",
    response_model=BetResponse,
    summary="Editar una apuesta",
)
async def update_bet(
    bet_id: str,
    body: BetUpdate,
    user_id: CurrentUserId,
    service: Annotated[BetService, Depends(get_bet_service)],
) -> BetResponse:
    changes = body.model_dump(exclude_unset=True)
    bet = await service.update_bet(user_id, bet_id, changes)
    return BetResponse.from_entity(bet)


@router.delete(
    "/{bet_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una apuesta",
)
async def delete_bet(
    bet_id: str,
    user_id: CurrentUserId,
    service: Annotated[BetService, Depends(get_bet_service)],
) -> None:
    await service.delete_bet(user_id, bet_id)
