"""Punto de entrada del bets-service (app factory)."""

import logging
from contextlib import asynccontextmanager

import aio_pika
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from bets_service.api.routers import bets
from bets_service.core.config import get_settings
from bets_service.core.exceptions import (
    DomainError,
    ForbiddenError,
    InvalidCredentialsError,
    NotFoundError,
    UserValidationUnavailableError,
)
from bets_service.core.logging import Timer, new_request_id, set_request_id, setup_logging
from bets_service.infrastructure.database.mongo import (
    create_client,
    ensure_indexes,
    get_database,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestiona la conexión a MongoDB y los índices durante el ciclo de vida.

    El backfill de estadísticas del monolito no viaja aquí: recalcular la progresión de
    todos los usuarios al arrancar pertenece a progression-service, y además debe ser un
    job explícito y no lógica de arranque bloqueante (T-029).
    """

    settings = get_settings()
    client = create_client(
        settings.mongo_uri,
        max_pool_size=settings.mongo_max_pool_size,
        server_selection_timeout_ms=settings.mongo_server_selection_timeout_ms,
    )
    db = get_database(client, settings.mongo_db_name)

    app.state.mongo_client = client
    app.state.db = db

    await ensure_indexes(db)

    # Publisher real de eventos (T-027): sin URL configurada, el servicio sigue con el
    # publisher de log de desarrollo (ver deps.get_event_publisher).
    rabbit_connection = None
    if settings.rabbitmq_url:
        rabbit_connection = await aio_pika.connect_robust(settings.rabbitmq_url)
        channel = await rabbit_connection.channel()
        # passive=True: el exchange ya lo declara la infraestructura (T-025); este
        # servicio sólo publica en él, no es dueño de su topología.
        app.state.bets_events_exchange = await channel.get_exchange(
            settings.bets_events_exchange
        )
    else:
        app.state.bets_events_exchange = None

    try:
        yield
    finally:
        if rabbit_connection is not None:
            await rabbit_connection.close()
        await client.close()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log estructurado (JSON) de cada petición REST: método, ruta, status y duración.

    Es el punto único de log de peticiones: el access log por defecto de uvicorn se
    desactiva en :func:`setup_logging` para no duplicar cada línea. También propaga un
    ``request_id`` (nuevo o heredado de ``X-Request-ID``) que aparece en todos los logs
    generados durante la petición, incluidos los eventos de dominio publicados.
    """

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or new_request_id()
        set_request_id(request_id)
        timer = Timer()

        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "Excepción no controlada procesando petición",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "client_ip": request.client.host if request.client else None,
                    "duration_ms": timer.elapsed_ms(),
                },
            )
            raise

        logger.info(
            "Petición procesada",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": timer.elapsed_ms(),
                "client_ip": request.client.host if request.client else None,
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Rechaza con 413 peticiones cuyo ``Content-Length`` supere el límite configurado.

    Se comprueba por cabecera antes de leer el body: evita bufferizar payloads enormes en
    memoria (p. ej. subidas de plantillas .xlsx maliciosamente grandes).
    """

    def __init__(self, app, max_body_bytes: int) -> None:
        super().__init__(app)
        self._max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > self._max_body_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Cuerpo de la petición demasiado grande."},
                    )
            except ValueError:
                pass
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Añade cabeceras de hardening y quita ``Server`` (revela uvicorn/versión)."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["Server"] = "api"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response


def _register_exception_handlers(app: FastAPI) -> None:
    """Traduce las excepciones de dominio a respuestas HTTP uniformes y las loguea."""

    status_map: dict[type[DomainError], int] = {
        NotFoundError: 404,
        InvalidCredentialsError: 401,
        ForbiddenError: 403,
        UserValidationUnavailableError: 503,
    }

    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        status_code = status_map.get(type(exc), 400)
        headers: dict[str, str] | None = None
        if status_code == 401:
            headers = {"WWW-Authenticate": "Bearer"}

        # 5xx (errores no anticipados o dependencias caídas) se loguean como error; los 4xx
        # (validación, permisos, credenciales) son parte del flujo normal y son warning.
        log_level = logging.ERROR if status_code >= 500 else logging.WARNING
        logger.log(
            log_level,
            "Excepción de dominio: %s",
            exc.message,
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": status_code,
                "exc_type": type(exc).__name__,
            },
        )

        return JSONResponse(
            status_code=status_code,
            content={"detail": exc.message},
            headers=headers,
        )

    app.add_exception_handler(DomainError, domain_error_handler)


def create_app() -> FastAPI:
    """Construye y configura la aplicación FastAPI."""

    settings = get_settings()
    setup_logging(settings.log_level)

    # Fallar aquí es preferible a arrancar aceptando cualquier X-User-Id: sin el secreto de
    # servicio, la identidad que llega por cabecera no está respaldada por nada.
    if not settings.internal_api_key:
        raise RuntimeError(
            "INTERNAL_API_KEY no está configurada: cualquiera podría operar en nombre de "
            "otro usuario. Genera un valor con `openssl rand -hex 32`."
        )

    app = FastAPI(
        title=settings.app_name,
        description=settings.app_description,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_body_bytes=settings.max_request_body_bytes)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=settings.cors_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # El frontend necesita leer el nombre del fichero al descargar la plantilla .xlsx.
        expose_headers=["Content-Disposition"],
    )

    _register_exception_handlers(app)

    app.include_router(bets.router)

    @app.get("/health", tags=["health"], summary="Comprobación de salud")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
