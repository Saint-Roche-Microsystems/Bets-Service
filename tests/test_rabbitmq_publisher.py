"""Tests del publisher real de RabbitMQ (T-027), con un exchange doble."""

import json

from bets_service.domain.entities.bet_event import BetEvent, BetEventType
from bets_service.infrastructure.events.rabbitmq_publisher import RabbitMqBetEventPublisher


class FakeExchange:
    """Registra cada publicación en memoria."""

    def __init__(self) -> None:
        self.published: list[tuple[bytes, str]] = []

    async def publish(self, message, *, routing_key: str) -> None:
        self.published.append((message.body, routing_key))


async def test_publishes_with_event_type_as_routing_key():
    exchange = FakeExchange()
    publisher = RabbitMqBetEventPublisher(exchange)
    event = BetEvent(event_type=BetEventType.CREATED, user_id="u1", bet_id="b1")

    await publisher.publish(event)

    assert len(exchange.published) == 1
    body, routing_key = exchange.published[0]
    assert routing_key == "bet.created"
    assert json.loads(body) == event.as_message()


async def test_updated_and_deleted_use_their_own_routing_key():
    exchange = FakeExchange()
    publisher = RabbitMqBetEventPublisher(exchange)

    await publisher.publish(BetEvent(event_type=BetEventType.UPDATED, user_id="u1", bet_id="b1"))
    await publisher.publish(BetEvent(event_type=BetEventType.DELETED, user_id="u1", bet_id="b1"))

    assert [rk for _, rk in exchange.published] == ["bet.updated", "bet.deleted"]
