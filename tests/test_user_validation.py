"""Tests de la validación del usuario contra users-service (hop A->B).

Se ejercita con dobles en memoria del puerto ``UserValidator``: el cliente TCP real es
T-017 y el contrato ya está fijado, así que lo que importa comprobar aquí es cómo reacciona
el servicio a cada respuesta posible.
"""

from httpx import AsyncClient

from bets_service.api.deps import get_user_validator
from bets_service.core.exceptions import UserValidationUnavailableError
from bets_service.domain.entities.user_validation import UserValidation
from bets_service.main import app
from tests.conftest import sample_bet_payload, user_headers


class StubUserValidator:
    """Devuelve siempre la misma validación y registra a quién se preguntó."""

    def __init__(self, validation: UserValidation) -> None:
        self._validation = validation
        self.asked: list[str] = []

    async def validate(self, user_id: str) -> UserValidation:
        self.asked.append(user_id)
        return self._validation


class UnavailableUserValidator:
    """Simula users-service caído o un timeout de red."""

    async def validate(self, user_id: str) -> UserValidation:
        raise UserValidationUnavailableError("users-service no responde.")


def _override(validator) -> None:
    app.dependency_overrides[get_user_validator] = lambda: validator


async def test_active_user_can_create_bet(client: AsyncClient):
    _override(StubUserValidator(UserValidation(active=True)))

    resp = await client.post("/bets", json=sample_bet_payload(), headers=user_headers())

    assert resp.status_code == 201


async def test_inactive_user_is_rejected(client: AsyncClient):
    _override(StubUserValidator(UserValidation(active=False)))

    resp = await client.post("/bets", json=sample_bet_payload(), headers=user_headers())

    assert resp.status_code == 403
    assert "desactivada" in resp.json()["detail"]


async def test_locked_user_is_rejected(client: AsyncClient):
    """Una cuenta bloqueada en auth-service tampoco puede apostar.

    Es la razón de ser de la cadena A->B->C: el dato del bloqueo nace en auth-service,
    users-service lo consulta y bets-service lo aplica.
    """

    _override(StubUserValidator(UserValidation(active=True, locked=True)))

    resp = await client.post("/bets", json=sample_bet_payload(), headers=user_headers())

    assert resp.status_code == 403
    assert "bloqueada" in resp.json()["detail"]


async def test_unavailable_users_service_fails_closed(client: AsyncClient):
    """Si no se puede confirmar el estado de la cuenta, no se acepta la apuesta."""

    _override(UnavailableUserValidator())

    resp = await client.post("/bets", json=sample_bet_payload(), headers=user_headers())

    assert resp.status_code == 503


async def test_rejected_bet_is_not_persisted(client: AsyncClient):
    """La validación ocurre antes de tocar Mongo: nada se guarda a medias."""

    _override(StubUserValidator(UserValidation(active=False)))
    await client.post("/bets", json=sample_bet_payload(), headers=user_headers())

    _override(StubUserValidator(UserValidation(active=True)))
    listed = await client.get("/bets", headers=user_headers())

    assert listed.json()["total"] == 0


async def test_update_also_validates(client: AsyncClient):
    """No basta con vigilar la creación: editar una apuesta también es operar."""

    _override(StubUserValidator(UserValidation(active=True)))
    created = await client.post("/bets", json=sample_bet_payload(), headers=user_headers())
    bet_id = created.json()["id"]

    _override(StubUserValidator(UserValidation(active=True, locked=True)))
    resp = await client.put(f"/bets/{bet_id}", json={"odds": 3.0}, headers=user_headers())

    assert resp.status_code == 403


async def test_validator_is_asked_about_the_header_user(client: AsyncClient):
    """Se valida al usuario de la cabecera, no a otro."""

    stub = StubUserValidator(UserValidation(active=True))
    _override(stub)

    await client.post("/bets", json=sample_bet_payload(), headers=user_headers("abc123"))

    assert stub.asked == ["abc123"]


async def test_default_validator_is_permissive_without_users_service(client: AsyncClient):
    """Sin USERS_SERVICE_TCP_HOST el servicio acepta cualquier usuario (modo desarrollo)."""

    # Sin override: se usa el validador que resuelve get_user_validator con la config real.
    resp = await client.post("/bets", json=sample_bet_payload(), headers=user_headers())

    assert resp.status_code == 201
