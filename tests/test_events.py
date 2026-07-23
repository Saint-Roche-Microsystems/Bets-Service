"""Tests de los eventos de dominio que sustituyen al recálculo en proceso.

Con un publisher en memoria: el destino real (exchange ``bets.events`` de RabbitMQ) lo
cablea Olivier en T-027, y lo que hay que fijar aquí es *qué* se publica y *cuándo*.
"""

from datetime import datetime
from io import BytesIO

import pytest
from httpx import AsyncClient
from openpyxl import Workbook

from bets_service.api.deps import get_event_publisher
from bets_service.domain.entities.bet_event import BetEvent, BetEventType
from bets_service.infrastructure.excel.columns import COLUMNS
from bets_service.main import app
from tests.conftest import DEFAULT_USER_ID, sample_bet_payload, user_headers


def _import_record(**overrides) -> dict:
    """Fila de la plantilla de importación. Naive: Excel no guarda zona horaria."""

    record = {
        "sport": "Fútbol",
        "league": "LaLiga",
        "event": "Real Madrid vs Barcelona",
        "bet_type": "SIMPLE",
        "market": "1X2",
        "selection": "Real Madrid",
        "odds": 2.0,
        "stake": 10.0,
        "bookmaker": "Bet365",
        "event_datetime": datetime(2026, 8, 1, 20, 0),
        "status": "PENDING",
    }
    record.update(overrides)
    return record


def _build_import_xlsx(records: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append([c.header for c in COLUMNS])
    for record in records:
        ws.append([record.get(c.field) for c in COLUMNS])
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


class RecordingPublisher:
    """Guarda en memoria los eventos publicados."""

    def __init__(self) -> None:
        self.events: list[BetEvent] = []

    async def publish(self, event: BetEvent) -> None:
        self.events.append(event)

    @property
    def types(self) -> list[str]:
        return [e.event_type.value for e in self.events]


class BrokenPublisher:
    """Simula el bus caído."""

    async def publish(self, event: BetEvent) -> None:
        raise ConnectionError("RabbitMQ no responde.")


@pytest.fixture
def publisher():
    """Publisher en memoria, retirado al terminar para no contaminar otros tests."""

    recorder = RecordingPublisher()
    app.dependency_overrides[get_event_publisher] = lambda: recorder
    try:
        yield recorder
    finally:
        app.dependency_overrides.pop(get_event_publisher, None)


async def test_create_publishes_bet_created(client: AsyncClient, publisher: RecordingPublisher):
    resp = await client.post("/bets", json=sample_bet_payload(), headers=user_headers())

    assert publisher.types == [BetEventType.CREATED.value]
    event = publisher.events[0]
    assert event.user_id == DEFAULT_USER_ID
    assert event.bet_id == resp.json()["id"]
    assert event.occurred_at is not None


async def test_update_publishes_bet_updated(client: AsyncClient, publisher: RecordingPublisher):
    created = await client.post("/bets", json=sample_bet_payload(), headers=user_headers())
    bet_id = created.json()["id"]

    await client.put(f"/bets/{bet_id}", json={"odds": 3.0}, headers=user_headers())

    assert publisher.types == [BetEventType.CREATED.value, BetEventType.UPDATED.value]
    assert publisher.events[-1].bet_id == bet_id


async def test_delete_publishes_bet_deleted(client: AsyncClient, publisher: RecordingPublisher):
    created = await client.post("/bets", json=sample_bet_payload(), headers=user_headers())
    bet_id = created.json()["id"]

    await client.delete(f"/bets/{bet_id}", headers=user_headers())

    assert publisher.types[-1] == BetEventType.DELETED.value
    assert publisher.events[-1].bet_id == bet_id


async def test_event_carries_request_id(client: AsyncClient, publisher: RecordingPublisher):
    """El evento hereda el ``X-Request-Id`` de la petición: traza a través del bus."""

    headers = {**user_headers(), "X-Request-ID": "trace-me-123"}
    await client.post("/bets", json=sample_bet_payload(), headers=headers)

    assert publisher.events[0].request_id == "trace-me-123"


async def test_rejected_bet_publishes_nothing(client: AsyncClient, publisher: RecordingPublisher):
    """Sólo se anuncian mutaciones que de verdad ocurrieron."""

    await client.post("/bets", json=sample_bet_payload(odds=0.5), headers=user_headers())

    assert publisher.events == []


async def test_publisher_failure_does_not_break_the_request(client: AsyncClient):
    """Si el bus está caído la apuesta se crea igual: ya está persistida y es la verdad."""

    app.dependency_overrides[get_event_publisher] = lambda: BrokenPublisher()

    resp = await client.post("/bets", json=sample_bet_payload(), headers=user_headers())

    assert resp.status_code == 201

    listed = await client.get("/bets", headers=user_headers())
    assert listed.json()["total"] == 1


async def test_import_publishes_one_event_per_imported_bet(
    client: AsyncClient, publisher: RecordingPublisher
):
    """Un parlay ocupa dos filas del Excel pero es una sola apuesta: un solo evento.

    Es la diferencia entre contar filas y contar apuestas, y determina cuántas veces
    recalculará progression-service.
    """

    data = _build_import_xlsx(
        [
            # Parlay: dos filas con el mismo ticket.
            _import_record(bet_type="PARLAY", odds=2.0, event="A", ticket="T1"),
            _import_record(sport="Tenis", event="B", selection="Y", odds=3.0, ticket="T1"),
            # Una simple.
            _import_record(event="C"),
            # Una inválida: no debe publicar nada.
            _import_record(event="D", odds=0.5),
        ]
    )
    files = {"file": ("apuestas.xlsx", data, "application/octet-stream")}
    summary = await client.post("/bets/import", files=files, headers=user_headers())

    assert summary.json()["imported"] == 2
    assert publisher.types == [BetEventType.CREATED.value] * 2

    listed = (await client.get("/bets", headers=user_headers())).json()
    assert {e.bet_id for e in publisher.events} == {b["id"] for b in listed["items"]}


def test_event_message_is_serializable():
    """El evento debe poder viajar por el bus tal cual."""

    import json

    event = BetEvent(
        event_type=BetEventType.CREATED,
        user_id="u1",
        bet_id="b1",
        request_id="r1",
    )
    message = json.loads(json.dumps(event.as_message()))

    assert message["event_type"] == "bet.created"
    assert message["user_id"] == "u1"
    assert message["bet_id"] == "b1"
    assert message["request_id"] == "r1"
    assert message["occurred_at"]
