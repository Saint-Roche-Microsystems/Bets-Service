"""Tests de integración de la gestión de apuestas.

Migrados del monolito (``tests/test_bets.py``) sin cambiar los casos: la extracción del
servicio no debe alterar el comportamiento observable del CRUD. Lo único que cambia es
cómo se identifica al usuario — cabeceras del gateway en vez de un login previo.
"""

from httpx import AsyncClient

from tests.conftest import (
    DEFAULT_USER_ID,
    INTERNAL_API_KEY,
    OTHER_USER_ID,
    sample_bet_payload,
    user_headers,
)


async def test_create_bet_computes_fields(client: AsyncClient):
    resp = await client.post(
        "/bets", json=sample_bet_payload(odds=2.0, stake=10.0), headers=user_headers()
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["potential_return"] == 20.0
    assert data["potential_profit"] == 10.0
    assert data["implied_probability"] == 0.5
    assert data["created_at"]
    assert data["updated_at"]


async def test_create_bet_invalid_odds(client: AsyncClient):
    resp = await client.post("/bets", json=sample_bet_payload(odds=0.9), headers=user_headers())
    assert resp.status_code == 422


async def test_create_bet_invalid_stake(client: AsyncClient):
    resp = await client.post("/bets", json=sample_bet_payload(stake=0), headers=user_headers())
    assert resp.status_code == 422


async def test_create_bet_requires_internal_key(client: AsyncClient):
    """Sin el secreto de servicio nadie puede operar, aunque traiga un X-User-Id."""

    resp = await client.post(
        "/bets", json=sample_bet_payload(), headers={"X-User-Id": DEFAULT_USER_ID}
    )
    assert resp.status_code == 401


async def test_create_bet_requires_user_id(client: AsyncClient):
    """Con el secreto pero sin identidad tampoco: no hay a quién atribuir la apuesta."""

    resp = await client.post(
        "/bets", json=sample_bet_payload(), headers={"X-Internal-Key": INTERNAL_API_KEY}
    )
    assert resp.status_code == 401


async def test_create_bet_rejects_wrong_internal_key(client: AsyncClient):
    resp = await client.post(
        "/bets",
        json=sample_bet_payload(),
        headers={"X-User-Id": DEFAULT_USER_ID, "X-Internal-Key": "clave-incorrecta"},
    )
    assert resp.status_code == 401


async def test_get_bet_by_id(client: AsyncClient):
    created = await client.post("/bets", json=sample_bet_payload(), headers=user_headers())
    bet_id = created.json()["id"]
    resp = await client.get(f"/bets/{bet_id}", headers=user_headers())
    assert resp.status_code == 200
    assert resp.json()["id"] == bet_id


async def test_list_bets_pagination_and_filter(client: AsyncClient):
    for i in range(3):
        await client.post(
            "/bets",
            json=sample_bet_payload(
                sport="Tenis" if i == 0 else "Fútbol",
                reference_id=f"REF{i}",
            ),
            headers=user_headers(),
        )

    # Paginación
    resp = await client.get("/bets?page=1&page_size=2", headers=user_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2

    # Filtro por deporte
    resp = await client.get("/bets?sport=Tenis", headers=user_headers())
    assert resp.json()["total"] == 1


async def test_update_bet_recalculates(client: AsyncClient):
    created = await client.post(
        "/bets", json=sample_bet_payload(odds=2.0, stake=10.0), headers=user_headers()
    )
    bet_id = created.json()["id"]
    resp = await client.put(f"/bets/{bet_id}", json={"odds": 3.0}, headers=user_headers())
    assert resp.status_code == 200
    data = resp.json()
    assert data["odds"] == 3.0
    assert data["potential_return"] == 30.0
    assert data["potential_profit"] == 20.0


async def test_delete_bet(client: AsyncClient):
    created = await client.post("/bets", json=sample_bet_payload(), headers=user_headers())
    bet_id = created.json()["id"]
    resp = await client.delete(f"/bets/{bet_id}", headers=user_headers())
    assert resp.status_code == 204
    resp = await client.get(f"/bets/{bet_id}", headers=user_headers())
    assert resp.status_code == 404


async def test_user_isolation(client: AsyncClient):
    """La propiedad de una apuesta ya no la respalda una consulta a ``users``.

    Ahora depende solo del ``user_id`` de la cabecera, así que conviene fijar la invariante:
    otro usuario recibe 404 (no 403), sin poder averiguar que la apuesta existe.
    """

    created = await client.post("/bets", json=sample_bet_payload(), headers=user_headers())
    bet_id = created.json()["id"]

    other = user_headers(OTHER_USER_ID)

    resp = await client.get(f"/bets/{bet_id}", headers=other)
    assert resp.status_code == 404

    resp = await client.put(f"/bets/{bet_id}", json={"odds": 5.0}, headers=other)
    assert resp.status_code == 404

    resp = await client.delete(f"/bets/{bet_id}", headers=other)
    assert resp.status_code == 404

    resp = await client.get("/bets", headers=other)
    assert resp.json()["total"] == 0


async def test_health_does_not_require_credentials(client: AsyncClient):
    """El health check queda fuera del secreto: lo consulta el orquestador."""

    resp = await client.get("/health")
    assert resp.status_code == 200
