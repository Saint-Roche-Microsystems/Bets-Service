"""Conexión a MongoDB usando el driver async oficial de PyMongo."""

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase


def create_client(
    mongo_uri: str,
    *,
    max_pool_size: int = 10,
    server_selection_timeout_ms: int = 10_000,
) -> AsyncMongoClient:
    """Crea un cliente async de MongoDB.

    ``tz_aware=True`` hace que las fechas leídas vuelvan como *aware* (UTC), de modo que
    ``event_datetime`` y los metadatos de la apuesta se puedan comparar con
    ``datetime.now(timezone.utc)`` sin errores.
    """

    return AsyncMongoClient(
        mongo_uri,
        tz_aware=True,
        maxPoolSize=max_pool_size,
        serverSelectionTimeoutMS=server_selection_timeout_ms,
    )


def get_database(client: AsyncMongoClient, db_name: str) -> AsyncDatabase:
    """Devuelve la base de datos indicada del cliente."""

    return client[db_name]


async def ensure_indexes(db: AsyncDatabase) -> None:
    """Crea los índices de ``bets_db`` (idempotente).

    - ``bets.user_id`` para acelerar el listado por usuario.
    - ``bets.(user_id, reference_id)`` sparse, para detectar referencias ya importadas.

    Esta base solo contiene apuestas: los usuarios y las estadísticas viven en las bases de
    sus propios servicios.
    """

    await db["bets"].create_index("user_id")
    await db["bets"].create_index(
        [("user_id", 1), ("reference_id", 1)],
        sparse=True,
    )
