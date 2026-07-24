"""Publisher real del puerto :class:`~bets_service.application.ports.BetEventPublisher`.

Publica al exchange topic ``bets.events`` (declarado en T-025) con routing key igual al
tipo de evento (``bet.created``/``bet.updated``/``bet.deleted``), que casa con el binding
``bet.#`` de la cola ``progression.recalc``. La conexión/canal/exchange se abren una vez en
el lifespan de la app (ver ``main.py``) y se reutilizan en cada publicación.
"""

from __future__ import annotations

import json

import aio_pika

from bets_service.domain.entities.bet_event import BetEvent


class RabbitMqBetEventPublisher:
    """Publica eventos de apuesta en el exchange ``bets.events`` de RabbitMQ."""

    def __init__(self, exchange: aio_pika.abc.AbstractExchange) -> None:
        self._exchange = exchange

    async def publish(self, event: BetEvent) -> None:
        body = json.dumps(event.as_message(), separators=(",", ":")).encode("utf-8")
        message = aio_pika.Message(
            body=body,
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        # Deja que el error se propague: BetService._publish ya lo captura y registra sin
        # revertir la apuesta (ya persistida).
        await self._exchange.publish(message, routing_key=event.event_type.value)
