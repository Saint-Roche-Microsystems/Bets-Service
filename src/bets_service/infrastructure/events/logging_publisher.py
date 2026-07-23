"""Implementación del puerto :class:`~bets_service.application.ports.BetEventPublisher`.

Emite cada evento como una línea de log JSON, con el mismo ``request_id`` de la petición
que lo originó. Es la implementación por defecto hasta que exista el publisher de RabbitMQ
(T-027): deja el circuito completo verificable —y depurable— sin levantar el broker.
"""

from __future__ import annotations

import logging

from bets_service.domain.entities.bet_event import BetEvent

logger = logging.getLogger(__name__)


class LoggingBetEventPublisher:
    """Registra el evento en stdout en lugar de publicarlo en un bus."""

    async def publish(self, event: BetEvent) -> None:
        logger.info(
            "Evento de dominio: %s",
            event.event_type.value,
            extra={"event": event.as_message()},
        )
