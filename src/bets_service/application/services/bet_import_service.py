"""Caso de uso: importar apuestas (simples y parlays) desde filas de un Excel.

Orquesta la validación y creación reutilizando las reglas existentes:
* ``BetCreate`` (schema Pydantic) como única fuente de validación de campos.
* ``BetService.create_bet`` para crear cada apuesta (valida al usuario contra
  users-service y calcula los campos derivados).

No contiene lógica de lectura de Excel: recibe filas ya leídas por el adaptador
de infraestructura. Las filas que comparten un mismo valor en la columna
``Ticket`` se combinan en un **parlay** (1ª fila = datos del ticket + selección
principal; siguientes = selecciones adicionales). Las filas sin ticket son
apuestas **simples**.
"""

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from bets_service.api.schemas.bet import BetCreate
from bets_service.application.services.bet_service import BetService
from bets_service.domain.entities.bet import BetType
from bets_service.domain.repositories.bet_repository import BetRepository

#: Campos que componen una selección (leg) de un parlay.
_LEG_FIELDS = ("sport", "league", "event", "market", "selection", "odds")


@dataclass
class RowError:
    """Error asociado a una fila del archivo."""

    row: int
    field: str
    error: str


@dataclass
class ImportSummary:
    """Resumen del resultado de una importación.

    ``total_rows`` cuenta filas físicas; ``imported``/``rejected`` cuentan
    **apuestas** (un parlay puede ocupar varias filas pero es una sola apuesta).
    """

    total_rows: int = 0
    imported: int = 0
    rejected: int = 0
    errors: list[RowError] = field(default_factory=list)


class BetImportService:
    """Procesa filas de apuestas: agrupa parlays, valida, evita duplicados y crea."""

    def __init__(self, bet_service: BetService, bet_repository: BetRepository) -> None:
        self._bets = bet_service
        self._repo = bet_repository

    async def import_rows(
        self, user_id: str, rows: list[tuple[int, dict[str, Any]]]
    ) -> ImportSummary:
        """Importa las filas dadas para ``user_id`` y devuelve el resumen."""

        summary = ImportSummary(total_rows=len(rows))
        state = _ImportState()

        for row_number, base_record in self._assemble(rows):
            await self._process(user_id, row_number, base_record, summary, state)

        return summary

    def _assemble(self, rows: list[tuple[int, dict[str, Any]]]) -> list[tuple[int, dict[str, Any]]]:
        """Combina las filas en apuestas: agrupa por ``ticket`` los parlays.

        Devuelve una lista de ``(nº de fila representativa, record listo para
        BetCreate)`` conservando el orden de aparición.
        """

        groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        order: list[tuple[str, Any]] = []

        for row_number, record in rows:
            record = dict(record)
            ticket = record.pop("ticket", None)
            if ticket:
                if ticket not in groups:
                    groups[ticket] = []
                    order.append(("group", ticket))
                groups[ticket].append((row_number, record))
            else:
                order.append(("single", (row_number, record)))

        assembled: list[tuple[int, dict[str, Any]]] = []
        for kind, payload in order:
            if kind == "single":
                assembled.append(payload)
            else:
                assembled.append(self._build_parlay(groups[payload]))
        return assembled

    @staticmethod
    def _build_parlay(
        group: list[tuple[int, dict[str, Any]]],
    ) -> tuple[int, dict[str, Any]]:
        """Construye el record de un parlay a partir de sus filas agrupadas."""

        group.sort(key=lambda item: item[0])
        first_row, base = group[0][0], dict(group[0][1])
        if len(group) > 1:
            # Con varias filas es forzosamente un parlay.
            base["bet_type"] = BetType.PARLAY.value
            base["legs"] = [
                {f: record[f] for f in _LEG_FIELDS if f in record} for _, record in group[1:]
            ]
        return first_row, base

    async def _process(
        self,
        user_id: str,
        row_number: int,
        record: dict[str, Any],
        summary: "ImportSummary",
        state: "_ImportState",
    ) -> None:
        try:
            data = BetCreate(**record)
        except ValidationError as exc:
            for err in exc.errors():
                loc = err.get("loc") or ()
                field_name = ".".join(str(part) for part in loc)
                summary.errors.append(RowError(row_number, field_name, err["msg"]))
            summary.rejected += 1
            return

        # Duplicados dentro del archivo (evento + selección + fecha).
        key = (data.event, data.selection, data.event_datetime)
        if key in state.seen_keys:
            summary.errors.append(
                RowError(row_number, "evento", "Apuesta duplicada dentro del archivo.")
            )
            summary.rejected += 1
            return
        state.seen_keys.add(key)

        # reference_id repetido en el archivo o ya existente en la BD.
        if data.reference_id:
            if data.reference_id in state.seen_refs:
                summary.errors.append(
                    RowError(
                        row_number, "reference_id", "ID de referencia duplicado en el archivo."
                    )
                )
                summary.rejected += 1
                return
            if await self._repo.reference_exists(user_id, data.reference_id):
                summary.errors.append(
                    RowError(
                        row_number,
                        "reference_id",
                        "El ID de referencia ya existe para el usuario.",
                    )
                )
                summary.rejected += 1
                return
            state.seen_refs.add(data.reference_id)

        try:
            await self._bets.create_bet(user_id, data.model_dump())
        except Exception as exc:  # una apuesta mala no detiene el resto
            summary.errors.append(RowError(row_number, "", str(exc)))
            summary.rejected += 1
            return

        summary.imported += 1


@dataclass
class _ImportState:
    """Estado de deduplicación durante una importación."""

    seen_keys: set[tuple] = field(default_factory=set)
    seen_refs: set[str] = field(default_factory=set)
