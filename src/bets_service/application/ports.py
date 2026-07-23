"""Puertos (interfaces) de la capa de aplicación.

Permiten que un caso de uso dependa de una capacidad abstracta en lugar de una
implementación concreta, evitando acoplamiento y ciclos de import.
"""

from typing import Protocol


class StatisticsSynchronizer(Protocol):
    """Capacidad de recalcular las estadísticas de un usuario.

    Heredado del monolito, donde lo implementaba ``ProgressionService`` y ``BetService`` lo
    llamaba en proceso tras cada mutación.

    En la arquitectura de microservicios ese recálculo pertenece a progression-service y
    debe llegar por eventos, no por una llamada síncrona: este puerto se retira en T-021 y
    su hueco lo ocupa el publisher de eventos de dominio (T-022). Aquí nunca se inyecta una
    implementación real.
    """

    async def recalculate(self, user_id: str) -> None: ...
