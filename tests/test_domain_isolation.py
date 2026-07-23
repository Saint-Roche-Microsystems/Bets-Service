"""Guardia de aislamiento de dominio.

bets-service es dueño de las apuestas y de nada más. Estos tests convierten esa regla en
algo que falla en CI si alguien vuelve a importar el dominio de otro servicio o a leer sus
colecciones — que es exactamente el acoplamiento que la migración vino a deshacer.
"""

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "bets_service"

#: Nombres que delatan una dependencia con un dominio ajeno, buscados como código (no en
#: comentarios ni docstrings, donde sí es legítimo mencionarlos para explicar la frontera).
FORBIDDEN = (
    "user_statistics",
    "user_progression",
    "UserStatistics",
    "UserProgression",
    "UserRepository",
    "ProgressionService",
    "StatisticsService",
    "StatisticsSynchronizer",
    "fijazo_api",
)


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Líneas de código del archivo, sin comentarios ni bloques de docstring."""

    lines: list[tuple[int, str]] = []
    in_docstring = False
    delimiter = ""

    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()

        if in_docstring:
            if delimiter in line:
                in_docstring = False
            continue

        for candidate in ('"""', "'''"):
            if line.startswith(candidate):
                # Docstring de una sola línea: se abre y cierra en la misma.
                if line.count(candidate) == 1:
                    in_docstring = True
                    delimiter = candidate
                line = ""
                break

        line = re.sub(r"#.*$", "", line).strip()
        if line:
            lines.append((number, line))

    return lines


@pytest.mark.parametrize("path", sorted(SRC.rglob("*.py")), ids=lambda p: p.name)
def test_no_foreign_domain_in_code(path: Path):
    offenders = [
        f"{path.name}:{number}: {line}"
        for number, line in _code_lines(path)
        for name in FORBIDDEN
        if name in line
    ]
    assert not offenders, "Dependencia con un dominio ajeno:\n" + "\n".join(offenders)


async def test_service_only_touches_the_bets_collection(test_db):
    """La base del servicio no debe acumular colecciones de otros dominios."""

    from bets_service.infrastructure.database.mongo import ensure_indexes

    await ensure_indexes(test_db)
    collections = set(await test_db.list_collection_names())

    assert collections <= {"bets"}
