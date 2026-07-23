"""Tests del parlay multi-selección (validación y cuota combinada).

Migrados del monolito. El caso que comprobaba las estadísticas resultantes
(``/statistics/me``) no viaja aquí: ese endpoint es de progression-service. Lo que sí
pertenece a este servicio —que la cuota combinada quede bien calculada y persistida, que es
el dato del que aquellas estadísticas se derivan— se comprueba abajo.
"""

from httpx import AsyncClient

from tests.conftest import sample_bet_payload, user_headers


def _leg(**overrides) -> dict:
    leg = {
        "sport": "Tenis",
        "league": "ATP",
        "event": "X vs Y",
        "market": "Ganador",
        "selection": "X",
        "odds": 3.0,
    }
    leg.update(overrides)
    return leg


async def test_create_parlay_combines_odds(client: AsyncClient):
    payload = sample_bet_payload(bet_type="PARLAY", odds=2.0, stake=10, legs=[_leg(odds=3.0)])
    resp = await client.post("/bets", json=payload, headers=user_headers())
    assert resp.status_code == 201
    data = resp.json()
    assert data["bet_type"] == "PARLAY"
    assert len(data["legs"]) == 1
    assert data["combined_odds"] == 6.0  # 2.0 * 3.0
    assert data["potential_return"] == 60.0  # 10 * 6
    assert data["potential_profit"] == 50.0


async def test_simple_with_legs_rejected(client: AsyncClient):
    payload = sample_bet_payload(bet_type="SIMPLE", legs=[_leg()])
    resp = await client.post("/bets", json=payload, headers=user_headers())
    assert resp.status_code == 422


async def test_parlay_without_legs_rejected(client: AsyncClient):
    payload = sample_bet_payload(bet_type="PARLAY", legs=[])
    resp = await client.post("/bets", json=payload, headers=user_headers())
    assert resp.status_code == 422


async def test_parlay_leg_odds_validated(client: AsyncClient):
    payload = sample_bet_payload(bet_type="PARLAY", legs=[_leg(odds=0.5)])
    resp = await client.post("/bets", json=payload, headers=user_headers())
    assert resp.status_code == 422


async def test_parlay_combined_odds_survive_update_and_reload(client: AsyncClient):
    """La cuota combinada se recalcula al editar y se persiste, no se recalcula al leer.

    Es el dato del que progression-service derivará el beneficio realizado, así que tiene
    que quedar bien guardado en la apuesta.
    """

    h = user_headers()
    payload = sample_bet_payload(
        bet_type="PARLAY", odds=2.0, stake=10, legs=[_leg(sport="Tenis", odds=3.0)]
    )
    created = await client.post("/bets", json=payload, headers=h)
    bet_id = created.json()["id"]

    updated = await client.put(f"/bets/{bet_id}", json={"status": "WON"}, headers=h)
    assert updated.status_code == 200
    assert updated.json()["status"] == "WON"
    assert updated.json()["combined_odds"] == 6.0

    reloaded = (await client.get(f"/bets/{bet_id}", headers=h)).json()
    assert reloaded["combined_odds"] == 6.0
    assert reloaded["potential_profit"] == 50.0  # 10 * (6 - 1)
    assert [leg["sport"] for leg in reloaded["legs"]] == ["Tenis"]
