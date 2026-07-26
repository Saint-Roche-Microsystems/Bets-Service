"""Configuración del bets-service cargada desde variables de entorno / .env."""

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Ajustes del servicio.

    Los valores se leen de variables de entorno (o de un archivo ``.env``).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Aplicación
    app_name: str = "Fijazo Bets Service"
    app_description: str = (
        "Apuestas de fijazoo: CRUD, cálculo de derivados e importación desde Excel."
    )
    app_version: str = "0.1.0"
    debug: bool = False
    # 2 MiB: aquí sí entran archivos (.xlsx de importación), a diferencia de auth-service.
    max_request_body_bytes: int = 2 * 1024 * 1024

    # CORS: en el destino final solo el api-gateway habla con este servicio, pero durante la
    # migración el frontend puede seguir apuntando aquí directamente.
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    cors_origin_regex: str | None = None

    # MongoDB: base propia del servicio. No contiene usuarios ni estadísticas; el ``user_id``
    # es un identificador opaco que llega en la cabecera.
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db_name: str = "bets_db"
    mongo_max_pool_size: int = 10
    mongo_server_selection_timeout_ms: int = 10_000

    # Secreto de servicio a servicio. Protege todas las rutas: la identidad del usuario llega
    # en la cabecera X-User-Id, así que sin este secreto cualquiera podría suplantar a otro
    # usuario. Sin valor, el servicio se niega a arrancar.
    internal_api_key: str = ""

    # users-service: validación del usuario por TCP antes de aceptar una apuesta (hop A->B).
    # Con el host vacío se usa un validador permisivo de desarrollo (ver
    # infrastructure/tcp/users_validator.py); no debe desplegarse así.
    users_service_tcp_host: str | None = None
    # 3011 es el puerto en el que users-service levanta su transporte TCP (su TCP_PORT).
    users_service_tcp_port: int = 3011
    users_service_timeout_seconds: float = 5.0

    # Logging: nivel raíz de la app (DEBUG/INFO/WARNING/ERROR). Los logs se emiten en JSON
    # (ver core/logging.py), un registro por petición REST más uno por excepción.
    log_level: str = "INFO"

    # RabbitMQ: publisher real de eventos de dominio (T-027) hacia el exchange declarado en
    # T-025. Con la URL vacía se usa el publisher de log de desarrollo (ver
    # infrastructure/events/logging_publisher.py); no debe desplegarse así.
    rabbitmq_url: str | None = None
    bets_events_exchange: str = "bets.events"

    # Sentry (error tracking, sin performance tracing). DSN vacío = SDK deshabilitado, no
    # rompe el arranque local.
    sentry_dsn: str = ""
    sentry_environment: str = "development"
    sentry_traces_sample_rate: float = 0.0

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Permite definir CORS_ORIGINS como lista separada por comas."""

        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    """Devuelve una instancia cacheada de :class:`Settings`."""

    return Settings()
