"""Contrato de columnas de la plantilla de importación (fuente única de verdad).

Tanto el generador de plantilla como el lector usan este mapa para no divergir.
Cada columna asocia su encabezado (español) con el campo de ``BetCreate``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ColumnSpec:
    """Especificación de una columna de la plantilla."""

    header: str  # Texto visible en el Excel.
    field: str  # Campo correspondiente de BetCreate / modelo de dominio.
    required: bool  # Si es obligatorio para dar la fila por válida.
    width: int = 20


#: Columnas en orden. El ``reference_id`` es el único opcional.
COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("Deporte", "sport", True),
    ColumnSpec("Liga", "league", True),
    ColumnSpec("Evento", "event", True, width=28),
    ColumnSpec("Tipo de apuesta", "bet_type", True),
    ColumnSpec("Mercado", "market", True),
    ColumnSpec("Selección", "selection", True, width=24),
    ColumnSpec("Cuota", "odds", True, width=10),
    ColumnSpec("Stake", "stake", True, width=10),
    ColumnSpec("Casa de apuestas", "bookmaker", True),
    ColumnSpec("Fecha y hora del evento", "event_datetime", True, width=24),
    ColumnSpec("Estado", "status", True),
    ColumnSpec("Notas", "notes", False, width=30),
    ColumnSpec("ID de referencia", "reference_id", False),
    # Clave de agrupación de parlays: las filas con el mismo Ticket forman una
    # única apuesta combinada. No es un campo de la apuesta.
    ColumnSpec("Ticket", "ticket", False, width=14),
)

#: Valores válidos para las listas desplegables del Excel (valores del enum).
BET_TYPE_VALUES = ("SIMPLE", "PARLAY")
BET_STATUS_VALUES = ("PENDING", "WON", "LOST", "VOID")
