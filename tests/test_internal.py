"""Tests del router interno (``/internal/*``): lectura de apuestas servicio a servicio.

A diferencia de ``/bets/*``, estas rutas no llevan identidad de usuario en cabecera: el
llamante es otro servicio y el ``user_id`` viaja como query param. Lo que sí comparten es
el secreto de servicio, que aquí se verifica con el mismo detalle que en auth-service.
"""

from httpx import AsyncClient

from tests.conftest import (
    DEFAULT_USER_ID,
    INTERNAL_API_KEY,
    OTHER_USER_ID,
    sample_bet_payload,
    user_headers,
)

INTERNAL_HEADERS = {"X-Internal-Key": INTERNAL_API_KEY}


async def _create_bets(client: AsyncClient, count: int, user_id: str = DEFAULT_USER_ID) -> None:
    for i in range(count):
        resp = await client.post(
            "/bets",
            json=sample_bet_payload(reference_id=f"REF-{user_id[-4:]}-{i}"),
            headers=user_headers(user_id),
        )
        assert resp.status_code == 201


async def test_list_bets_returns_only_the_requested_user(client: AsyncClient):
    await _create_bets(client, 2, DEFAULT_USER_ID)
    await _create_bets(client, 1, OTHER_USER_ID)

    resp = await client.get(
        f"/internal/bets?user_id={DEFAULT_USER_ID}", headers=INTERNAL_HEADERS
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


async def test_list_bets_paginates(client: AsyncClient):
    await _create_bets(client, 3)

    first = await client.get(
        f"/internal/bets?user_id={DEFAULT_USER_ID}&page=1&page_size=2",
        headers=INTERNAL_HEADERS,
    )
    second = await client.get(
        f"/internal/bets?user_id={DEFAULT_USER_ID}&page=2&page_size=2",
        headers=INTERNAL_HEADERS,
    )

    assert first.json()["total"] == 3
    assert len(first.json()["items"]) == 2
    assert first.json()["page"] == 1
    assert first.json()["page_size"] == 2
    assert len(second.json()["items"]) == 1

    # Sin solapamiento entre páginas: el consumidor las concatena tal cual.
    ids = {b["id"] for b in first.json()["items"]} | {b["id"] for b in second.json()["items"]}
    assert len(ids) == 3


async def test_list_bets_unknown_user_is_empty_not_404(client: AsyncClient):
    """Un usuario sin apuestas no es un error: el recálculo simplemente no tiene nada."""

    resp = await client.get("/internal/bets?user_id=no-existe", headers=INTERNAL_HEADERS)

    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0, "page": 1, "page_size": 200}


async def test_list_bets_response_shape_matches_public_list(client: AsyncClient):
    """Blinda el contrato: la ruta interna reutiliza ``BetResponse``, no una copia paralela.

    Si alguien cambia el schema público sin darse cuenta de que hay un consumidor
    servicio a servicio, este test no lo impide — pero sí garantiza que ambos lados
    describen la apuesta igual y que el consumidor puede parsear una sola forma.
    """

    await _create_bets(client, 1)

    public = await client.get("/bets", headers=user_headers())
    internal = await client.get(
        f"/internal/bets?user_id={DEFAULT_USER_ID}", headers=INTERNAL_HEADERS
    )

    assert internal.json()["items"] == public.json()["items"]


async def test_list_bets_rejects_page_size_over_cap(client: AsyncClient):
    over = await client.get(
        f"/internal/bets?user_id={DEFAULT_USER_ID}&page_size=501", headers=INTERNAL_HEADERS
    )
    at_cap = await client.get(
        f"/internal/bets?user_id={DEFAULT_USER_ID}&page_size=500", headers=INTERNAL_HEADERS
    )

    assert over.status_code == 422
    assert at_cap.status_code == 200


async def test_list_bets_requires_user_id(client: AsyncClient):
    resp = await client.get("/internal/bets", headers=INTERNAL_HEADERS)
    assert resp.status_code == 422


async def test_user_ids_lists_users_with_bets(client: AsyncClient):
    await _create_bets(client, 2, DEFAULT_USER_ID)
    await _create_bets(client, 1, OTHER_USER_ID)

    resp = await client.get("/internal/bets/user-ids", headers=INTERNAL_HEADERS)

    assert resp.status_code == 200
    assert set(resp.json()["user_ids"]) == {DEFAULT_USER_ID, OTHER_USER_ID}


async def test_user_ids_is_empty_without_bets(client: AsyncClient):
    resp = await client.get("/internal/bets/user-ids", headers=INTERNAL_HEADERS)
    assert resp.json() == {"user_ids": []}


async def test_internal_bets_rejects_missing_key(client: AsyncClient):
    resp = await client.get(f"/internal/bets?user_id={DEFAULT_USER_ID}")
    assert resp.status_code == 401


async def test_internal_bets_rejects_wrong_key(client: AsyncClient):
    resp = await client.get(
        f"/internal/bets?user_id={DEFAULT_USER_ID}",
        headers={"X-Internal-Key": "clave-incorrecta"},
    )
    assert resp.status_code == 401


async def test_user_ids_rejects_missing_key(client: AsyncClient):
    resp = await client.get("/internal/bets/user-ids")
    assert resp.status_code == 401


async def test_internal_key_checked_before_existence(client: AsyncClient):
    """Sin secreto, un usuario con apuestas y otro inexistente responden igual.

    Si la respuesta difiriera, un atacante sin credenciales podría enumerar qué usuarios
    han apostado comparando códigos de estado.
    """

    await _create_bets(client, 1, DEFAULT_USER_ID)

    with_bets = await client.get(f"/internal/bets?user_id={DEFAULT_USER_ID}")
    without_bets = await client.get("/internal/bets?user_id=no-existe")

    assert with_bets.status_code == without_bets.status_code == 401


async def test_internal_routes_do_not_require_user_header(client: AsyncClient):
    """El llamante es un servicio: no tiene un X-User-Id que ofrecer."""

    resp = await client.get(
        f"/internal/bets?user_id={DEFAULT_USER_ID}", headers=INTERNAL_HEADERS
    )
    assert resp.status_code == 200
    assert "X-User-Id" not in INTERNAL_HEADERS
