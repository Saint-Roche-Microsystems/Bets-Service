"""Puertos (interfaces) de la capa de aplicación.

Permiten que un caso de uso dependa de una capacidad abstracta en lugar de una
implementación concreta, evitando acoplamiento y ciclos de import.
"""

from typing import Protocol

from bets_service.domain.entities.bet_event import BetEvent
from bets_service.domain.entities.user_validation import UserValidation


class UserValidator(Protocol):
    """Capacidad de confirmar que un usuario puede operar.

    Es el hop A->B de la cadena síncrona: ``bets-service`` pregunta a ``users-service``
    (patrón TCP ``users.validate``) si la cuenta está activa y con qué tier opera, antes de
    aceptar una apuesta.

    Se define como puerto para no bloquear la extracción de este servicio mientras el
    cliente TCP real (T-017, de Olivier) no exista. Debe señalar los fallos de transporte
    con :class:`UserValidationUnavailableError`: quien lo llama no conoce ``asyncio`` ni el
    framing de Nest.
    """

    async def validate(self, user_id: str) -> UserValidation: ...


class BetEventPublisher(Protocol):
    """Capacidad de anunciar que una apuesta cambió.

    Sustituye a la llamada en proceso que el monolito hacía a ``ProgressionService`` tras
    cada mutación (``stats_sync``): ahora la respuesta al cliente no espera al recálculo de
    estadísticas, rangos, logros y ranking.

    El destino real es el exchange ``bets.events`` de RabbitMQ, que Olivier cablea en
    T-027; hasta entonces se usa una implementación que sólo deja el evento en el log, de
    modo que el circuito se puede verificar sin levantar el broker.

    **Publicar no debe poder tumbar la operación**: la apuesta ya está persistida y es la
    fuente de verdad. Una implementación que falle debe registrarlo y devolver el control,
    no propagar la excepción; la proyección perdida se reconstruye con el backfill (T-029).
    """

    async def publish(self, event: BetEvent) -> None: ...
