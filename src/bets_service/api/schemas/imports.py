"""Schemas Pydantic para el resultado de la importación de apuestas."""

from pydantic import BaseModel

from bets_service.application.services.bet_import_service import ImportSummary


class RowErrorResponse(BaseModel):
    """Error de una fila del archivo importado."""

    row: int
    field: str
    error: str


class ImportSummaryResponse(BaseModel):
    """Resumen del resultado de la importación."""

    total_rows: int
    imported: int
    rejected: int
    errors: list[RowErrorResponse]

    @classmethod
    def from_summary(cls, summary: ImportSummary) -> "ImportSummaryResponse":
        return cls(
            total_rows=summary.total_rows,
            imported=summary.imported,
            rejected=summary.rejected,
            errors=[RowErrorResponse(**vars(e)) for e in summary.errors],
        )
