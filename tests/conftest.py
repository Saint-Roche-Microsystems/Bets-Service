"""Fixtures compartidas para los tests de integración del bets-service.

Requieren una instancia de MongoDB accesible (por defecto en
``mongodb://localhost:27017``; configurable con ``TEST_MONGO_URI``). Con el
docker-compose del servicio basta con levantar ``mongo``.
"""

import os

# ``create_app`` aborta si no hay secreto de servicio, y se ejecuta al importar
# ``bets_service.main``: hay que fijarlo antes de esa importación.
INTERNAL_API_KEY = "test-internal-key"
os.environ.setdefault("INTERNAL_API_KEY", INTERNAL_API_KEY)

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from pymongo import AsyncMongoClient  # noqa: E402

from bets_service.api.deps import get_db  # noqa: E402
from bets_service.infrastructure.database.mongo import ensure_indexes  # noqa: E402
from bets_service.main import app  # noqa: E402

TEST_MONGO_URI = os.getenv("TEST_MONGO_URI", "mongodb://localhost:27017")
TEST_DB_NAME = os.getenv("TEST_DB_NAME", "bets_test")

#: Identidad por defecto de los tests. Es un ObjectId válido porque en producción el
#: user_id proviene del ``_id`` de la credencial en auth-service, aunque aquí sea opaco.
DEFAULT_USER_ID = "6a60c83b2a0af5b4ab9745cf"
OTHER_USER_ID = "6a60c83b2a0af5b4ab9745aa"


@pytest_asyncio.fixture
async def test_db():
    """Base de datos de test limpia con los índices creados."""

    client = AsyncMongoClient(TEST_MONGO_URI, tz_aware=True)  # igual que producción
    db = client[TEST_DB_NAME]

    await db["bets"].drop()
    await ensure_indexes(db)

    try:
        yield db
    finally:
        await db["bets"].drop()
        await client.close()


@pytest_asyncio.fixture
async def client(test_db):
    """Cliente HTTP asíncrono con la BD de test inyectada."""

    app.dependency_overrides[get_db] = lambda: test_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def user_headers(user_id: str = DEFAULT_USER_ID) -> dict[str, str]:
    """Cabeceras que inyecta el api-gateway: identidad + secreto de servicio."""

    return {"X-User-Id": user_id, "X-Internal-Key": INTERNAL_API_KEY}


def sample_bet_payload(**overrides) -> dict:
    """Payload válido de apuesta para reutilizar en los tests."""

    payload = {
        "sport": "Fútbol",
        "league": "LaLiga",
        "event": "Real Madrid vs Barcelona",
        "bet_type": "SIMPLE",
        "market": "1X2",
        "selection": "Real Madrid",
        "odds": 2.0,
        "stake": 10.0,
        "bookmaker": "Bet365",
        "event_datetime": "2026-08-01T20:00:00Z",
        "status": "PENDING",
        "notes": "El clásico",
        "reference_id": "ABC123",
    }
    payload.update(overrides)
    return payload
