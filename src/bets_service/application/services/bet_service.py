"""Casos de uso de apuestas: CRUD con campos calculados y control de propiedad."""

from datetime import datetime, timezone
from typing import Any

from bets_service.application.ports import StatisticsSynchronizer, UserValidator
from bets_service.core.exceptions import ForbiddenError, InvalidBetError, NotFoundError
from bets_service.domain.entities.bet import Bet, BetLeg, BetStatus, BetType
from bets_service.domain.repositories.bet_repository import BetRepository


def _normalize_legs(data: dict[str, Any]) -> None:
    """Convierte ``legs`` de dicts a :class:`BetLeg` in-place, si están presentes."""

    legs = data.get("legs")
    if legs:
        data["legs"] = [BetLeg(**leg) if isinstance(leg, dict) else leg for leg in legs]


def _validate_type_vs_legs(bet: Bet) -> None:
    """Invariante SIMPLE/PARLAY frente al número de selecciones adicionales."""

    if bet.bet_type == BetType.SIMPLE and bet.legs:
        raise InvalidBetError("Una apuesta simple no puede tener selecciones adicionales.")
    if bet.bet_type == BetType.PARLAY and len(bet.legs) < 1:
        raise InvalidBetError("Un parlay requiere al menos una selección adicional (2 en total).")


class BetService:
    """Reglas de negocio para la gestión de apuestas.

    Toda operación sobre una apuesta concreta valida que pertenezca al usuario
    autenticado; en caso contrario se comporta como si no existiera (404),
    evitando filtrar la existencia de recursos ajenos.

    Antes de aceptar una mutación consulta a ``users-service`` (puerto ``UserValidator``)
    que la cuenta esté activa y sin bloquear.

    Si se le inyecta un ``StatisticsSynchronizer``, tras cada mutación recalcula
    las estadísticas del usuario para mantener el ranking sincronizado.
    """

    def __init__(
        self,
        bet_repository: BetRepository,
        user_validator: UserValidator,
        stats_sync: StatisticsSynchronizer | None = None,
    ) -> None:
        self._bets = bet_repository
        self._users = user_validator
        self._stats_sync = stats_sync

    async def _sync_stats(self, user_id: str) -> None:
        if self._stats_sync is not None:
            await self._stats_sync.recalculate(user_id)

    async def _ensure_can_bet(self, user_id: str) -> None:
        """Comprueba contra users-service que el usuario puede operar.

        Fail-closed: si el validador no puede responder deja pasar la
        ``UserValidationUnavailableError`` (-> 503) en vez de asumir que la cuenta está
        sana. Aceptar la apuesta a ciegas permitiría a una cuenta bloqueada seguir
        apostando justo mientras el servicio que la bloquea está caído.
        """

        validation = await self._users.validate(user_id)
        if not validation.active:
            raise ForbiddenError("La cuenta está desactivada.")
        if validation.locked:
            raise ForbiddenError("La cuenta está bloqueada temporalmente.")

    async def create_bet(self, user_id: str, data: dict[str, Any]) -> Bet:
        """Crea una apuesta para el usuario y calcula los campos derivados."""

        await self._ensure_can_bet(user_id)

        data = dict(data)
        _normalize_legs(data)
        bet = Bet(user_id=user_id, **data)
        _validate_type_vs_legs(bet)
        bet.recalculate()
        created = await self._bets.create(bet)
        await self._sync_stats(user_id)
        return created

    async def get_bet(self, user_id: str, bet_id: str) -> Bet:
        """Devuelve una apuesta del usuario o lanza :class:`NotFoundError`."""

        bet = await self._bets.get_by_id(bet_id)
        if bet is None or bet.user_id != user_id:
            raise NotFoundError("Apuesta no encontrada.")
        return bet

    async def list_bets(
        self,
        user_id: str,
        *,
        page: int = 1,
        page_size: int = 20,
        status: BetStatus | None = None,
        sport: str | None = None,
        bet_type: BetType | None = None,
    ) -> tuple[list[Bet], int]:
        """Lista las apuestas del usuario con paginación y filtros."""

        skip = (page - 1) * page_size
        return await self._bets.list_by_user(
            user_id,
            skip=skip,
            limit=page_size,
            status=status,
            sport=sport,
            bet_type=bet_type,
        )

    async def update_bet(self, user_id: str, bet_id: str, changes: dict[str, Any]) -> Bet:
        """Actualiza los campos indicados de una apuesta del usuario."""

        await self._ensure_can_bet(user_id)
        bet = await self.get_bet(user_id, bet_id)

        changes = dict(changes)
        _normalize_legs(changes)
        for key, value in changes.items():
            setattr(bet, key, value)

        _validate_type_vs_legs(bet)
        bet.recalculate()
        bet.updated_at = datetime.now(timezone.utc)
        updated = await self._bets.update(bet)
        await self._sync_stats(user_id)
        return updated

    async def delete_bet(self, user_id: str, bet_id: str) -> None:
        """Elimina una apuesta del usuario o lanza :class:`NotFoundError`."""

        # Reutiliza get_bet para verificar propiedad y existencia.
        await self.get_bet(user_id, bet_id)
        await self._bets.delete(bet_id)
        await self._sync_stats(user_id)
