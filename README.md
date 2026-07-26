# bets-service

Microservicio de apuestas de **fijazoo**: CRUD de apuestas, cálculo de campos derivados e
importación desde Excel.

Es la **fuente de verdad** del sistema. Las estadísticas, el rango, los logros y el ranking
son proyecciones que progression-service deriva de las apuestas que viven aquí.

Extraído del monolito `fijazo-api` como Fase 3 de la migración a microservicios.

---

## Qué hace (y qué no)

**Sí:**

- CRUD de apuestas, simples y parlays, con control de propiedad por usuario.
- Calcula los campos derivados: cuota combinada, retorno y beneficio potenciales,
  probabilidad implícita.
- Genera la plantilla `.xlsx` e importa apuestas desde ella, agrupando parlays por ticket.
- Pregunta a users-service si la cuenta puede operar antes de aceptar una mutación.
- Publica `bet.created` / `bet.updated` / `bet.deleted` para que otros servicios reaccionen.

**No:**

- **No valida el JWT.** Eso lo hace el api-gateway una sola vez, en el borde; aquí la
  identidad llega ya resuelta en `X-User-Id`.
- **No conoce usuarios.** El `user_id` es un identificador opaco: no hay colección `users`
  ni consulta a otro servicio para leer un perfil.
- **No calcula estadísticas ni ranking.** Eso es de progression-service, que se entera por
  los eventos.

---

## Arrancarlo

Necesitas Docker, o Python 3.14 + Poetry.

### Con Docker (lo normal)

```bash
cp .env.example .env
# INTERNAL_API_KEY no puede quedar vacío: el servicio se niega a arrancar sin él.
sed -i "s/^INTERNAL_API_KEY=.*/INTERNAL_API_KEY=$(openssl rand -hex 32)/" .env

docker compose up --build -d
curl -s localhost:8002/health     # {"status":"ok"}
```

Levanta el servicio en el **8002** y un Mongo propio en el **27020** del host (27017 es del
monolito y 27019 de auth-service). Para pararlo: `docker compose down`.

### Sin Docker

```bash
cp .env.example .env
poetry install
poetry run uvicorn bets_service.main:app --reload --port 8002
```

### Tests

Requieren un Mongo accesible; se usa la base `bets_test` y se limpia sola.

```bash
TEST_MONGO_URI=mongodb://localhost:27020 poetry run pytest
```

---

## Cómo se llama a este servicio

Hay dos superficies distintas: `/bets/*`, que atiende a una persona detrás del gateway, y
`/internal/*`, que atiende a otro servicio.

Todas las rutas de `/bets/*` exigen **dos cabeceras**, que inyecta el api-gateway:

| Cabecera | Qué es |
|---|---|
| `X-User-Id` | Identidad del usuario, sacada del claim `sub` del JWT ya validado |
| `X-Internal-Key` | Secreto de servicio compartido |

Falta cualquiera de las dos, o el secreto no coincide → **401**.

El secreto no es opcional ni decorativo: como la identidad viaja en una cabecera, sin él
cualquiera que alcanzara el servicio podría operar en nombre de otro usuario sin más que
cambiar el `X-User-Id`. `/health` queda fuera para que lo consulte el orquestador.

```bash
curl -s localhost:8002/bets \
  -H "X-User-Id: 6a60c83b2a0af5b4ab9745cf" \
  -H "X-Internal-Key: $INTERNAL_API_KEY"
```

Las rutas de `/internal/*` exigen **solo el secreto**: el llamante es otro servicio, que no
tiene un `X-User-Id` propio que ofrecer y pregunta por un usuario cualquiera.

```bash
curl -s "localhost:8002/internal/bets?user_id=6a60c83b2a0af5b4ab9745cf" \
  -H "X-Internal-Key: $INTERNAL_API_KEY"
```

---

## Endpoints

Todos bajo `/bets`, todos acotados al usuario de la cabecera.

| Método | Ruta | Qué hace |
|---|---|---|
| `POST` | `/bets` | Crea una apuesta → `201` |
| `GET` | `/bets` | Lista con paginación (`page`, `page_size`) y filtros (`status`, `sport`, `bet_type`) |
| `GET` | `/bets/{id}` | Una apuesta |
| `PUT` | `/bets/{id}` | Edita y recalcula los derivados |
| `DELETE` | `/bets/{id}` | Elimina → `204` |
| `GET` | `/bets/template` | Descarga la plantilla `.xlsx` |
| `POST` | `/bets/import` | Importa apuestas desde un `.xlsx` relleno |

### Rutas internas (servicio a servicio)

No las enruta el api-gateway: solo son alcanzables desde la red interna, y exigen
`X-Internal-Key` (declarado a nivel de router, no por endpoint).

| Método | Ruta | Qué hace |
|---|---|---|
| `GET` | `/internal/bets?user_id=&page=&page_size=` | Apuestas de un usuario arbitrario. `page_size` 1..500 (default 200); misma forma de respuesta que `GET /bets` |
| `GET` | `/internal/bets/user-ids` | `{ "user_ids": [...] }` con los usuarios que tienen al menos una apuesta |

El tope de 500 es más alto que el de la ruta pública (100) porque el consumidor recorre el
historial completo de un usuario, no una pantalla. Para leerlo entero se itera hasta `total`.

### Crear una apuesta

```jsonc
// petición
{ "sport": "Fútbol", "league": "LaLiga", "event": "Real Madrid vs Barcelona",
  "bet_type": "SIMPLE", "market": "1X2", "selection": "Real Madrid",
  "odds": 2.0, "stake": 10.0, "bookmaker": "Bet365",
  "event_datetime": "2026-08-01T20:00:00Z", "status": "PENDING" }
// respuesta: se añaden los campos calculados
{ "id": "6a617db47729546dc1a36341", ...,
  "combined_odds": 2.0, "potential_return": 20.0,
  "potential_profit": 10.0, "implied_probability": 0.5 }
```

Un **parlay** añade selecciones extra en `legs`; la cuota combinada es el producto de todas.
`bet_type: SIMPLE` con `legs` → `422`, y `PARLAY` sin `legs` → `422`.

| Situación | Código |
|---|---|
| Falta cabecera o secreto incorrecto | `401` |
| Cuenta desactivada o bloqueada | `403` |
| Apuesta de otro usuario | `404` (no `403`: no se revela que existe) |
| Datos inválidos (cuota ≤ 1, stake ≤ 0, …) | `422` |
| users-service no responde | `503` |

### Importar desde Excel

La plantilla trae las columnas con validaciones y una columna **`Ticket`**: las filas que
comparten ticket se combinan en un solo parlay (la 1ª aporta los datos y la selección
principal; las siguientes, las selecciones adicionales). Las filas sin ticket son apuestas
simples.

```bash
curl -s localhost:8002/bets/template $H -o plantilla.xlsx
curl -s -X POST localhost:8002/bets/import $H -F "file=@plantilla.xlsx"
# {"total_rows": 3, "imported": 2, "rejected": 0, "errors": []}
```

`total_rows` cuenta filas físicas; `imported`/`rejected` cuentan **apuestas**. Una fila mala
no detiene el resto: se rechaza con su motivo en `errors` y el import continúa. También se
descartan los duplicados dentro del archivo y los `reference_id` que ya existan.

---

## Integraciones

### users-service — validación síncrona (hop A→B)

Antes de crear o editar una apuesta se consulta el patrón TCP `users.validate`:

```jsonc
// petición
{ "pattern": "users.validate", "id": "<str>", "data": { "user_id": "<str>" } }
// respuesta esperada
{ "id": "<str>", "response": { "active": true, "tier": "standard", "locked": false } }
```

`locked` no lo decide users-service: viene de auth-service
(`GET /internal/lock-status/{user_id}`), que aquél consulta en el hop B→C. Así una cuenta
bloqueada por intentos de login fallidos tampoco puede seguir apostando.

**Fail-closed**: si users-service no responde, se devuelve `503` y la apuesta **no** se crea.
Aceptarla a ciegas dejaría operar a una cuenta bloqueada justo mientras el servicio que la
bloquea está caído.

> **Estado**: el cliente TCP real es la tarea **T-017**. `TcpUserValidator`
> ([users_validator.py](src/bets_service/infrastructure/tcp/users_validator.py)) es su
> esqueleto, con el contrato de arriba documentado. Al implementarlo no hay que tocar nada
> más: `BetService` depende del puerto `UserValidator`, no de la clase.

### progression-service — eventos asíncronos

Tras cada mutación confirmada se publica un evento. La respuesta al cliente ya no espera al
recálculo de estadísticas, rangos, logros y ranking.

```jsonc
{ "event_type": "bet.created",          // o bet.updated / bet.deleted
  "user_id": "6a60c83b2a0af5b4ab9745cf",
  "bet_id": "6a617db47729546dc1a36341",
  "request_id": "smoke-trace-1",
  "occurred_at": "2026-07-23T02:34:28.085622+00:00" }
```

`user_id` es lo único que progression necesita (su recálculo es por usuario). `bet_id` y
`request_id` viajan para poder rastrear un recálculo hasta la petición que lo originó, ahora
que un solo flujo atraviesa varios procesos.

El evento **avisa**, no transporta el historial: para recalcular, progression-service vuelve
por `GET /internal/bets?user_id=…` y relee las apuestas de ese usuario desde aquí. Esa es la
razón de que el payload no crezca con los campos de la apuesta — así el recálculo siempre
opera sobre el estado actual, y reprocesar un evento antiguo o repetido da el mismo
resultado (idempotencia) en vez de aplicar deltas.

**Publicar no puede tumbar la operación**: si el bus falla se registra y se sigue. La apuesta
ya está persistida y es la fuente de verdad; la proyección perdida se reconstruye con el
backfill de eventos históricos (T-029).

> **Estado**: hasta **T-027** se usa `LoggingBetEventPublisher`, que emite el evento como
> log JSON en vez de publicarlo en RabbitMQ. El circuito es verificable sin levantar el
> broker. Para cablear el exchange `bets.events` basta con cambiar la implementación que
> devuelve `get_event_publisher` en [deps.py](src/bets_service/api/deps.py);
> `BetEvent.as_message()` ya da el dict serializable.

---

## Configuración

Todas las variables tienen valor por defecto salvo `INTERNAL_API_KEY`. Ver
[.env.example](.env.example) para la lista comentada completa.

| Variable | Para qué |
|---|---|
| `MONGO_URI`, `MONGO_DB_NAME` | Base propia del servicio (`bets_db`) |
| `INTERNAL_API_KEY` | Secreto de servicio. **Obligatorio**, el mismo que gateway y auth-service |
| `USERS_SERVICE_TCP_HOST` / `_PORT` | Destino de `users.validate`. Vacío ⇒ validador permisivo |
| `USERS_SERVICE_TIMEOUT_SECONDS` | Timeout de la validación antes de responder `503` |
| `MAX_REQUEST_BODY_BYTES` | 2 MiB por defecto, por los `.xlsx` de importación |
| `DEBUG` | En `true` publica `/docs`. Dejar en `false` fuera de desarrollo |

---

## Cómo encaja con el resto

```
   cliente ──▶ api-gateway ──HTTP──▶ bets-service (A)
                                          │
                            TCP users.validate
                                          ▼
                                    users-service (B)
                                          │
                       HTTP /internal/lock-status
                                          ▼
                                     auth-service (C)

   bets-service ──bet.created/updated/deleted──▶ progression-service
                ◀──GET /internal/bets?user_id=──┘   (relee para recalcular)
```

El `X-Request-Id` que genera el gateway se propaga: se reutiliza si llega en la cabecera,
aparece en cada línea de log JSON y viaja dentro del evento de dominio.

---

## Para el compose global (T-033)

Bloque a pegar en el `docker-compose.yml` que consolida todos los servicios. Aquí **no**
debe publicar puerto en el host: el único servicio público es el gateway.

```yaml
  bets-service:
    build: ./bets-service
    environment:
      MONGO_URI: mongodb://mongo:27017
      MONGO_DB_NAME: bets_db
      INTERNAL_API_KEY: ${INTERNAL_API_KEY}       # el mismo que gateway y auth-service
      USERS_SERVICE_TCP_HOST: users-service
      USERS_SERVICE_TCP_PORT: 3011                # el TCP_PORT de users-service
    depends_on:
      mongo:
        condition: service_healthy
    restart: unless-stopped
```

---

## Estructura

Arquitectura hexagonal, la misma del monolito y de auth-service:

```
src/bets_service/
  api/            router, schemas y dependencias de FastAPI
  application/    casos de uso (BetService, BetImportService) y puertos
  domain/         Bet, BetEvent, UserValidation y el contrato del repositorio
                  — sin Mongo, sin Pydantic, sin FastAPI
  infrastructure/ Mongo, Excel (openpyxl), cliente TCP, publisher de eventos
  core/           config, logging JSON, excepciones
tests/            tests de integración contra un Mongo real
```

Las excepciones de dominio (`core/exceptions.py`) se traducen a códigos HTTP en un único
handler de `main.py`; los casos de uso no conocen FastAPI. Las integraciones externas
(users-service, bus de eventos) son puertos, así que se pueden sustituir por dobles en los
tests y por implementaciones reales en producción sin tocar la lógica de negocio.

**[`tests/test_domain_isolation.py`](tests/test_domain_isolation.py)** hace fallar la suite
si alguien vuelve a importar el dominio de otro servicio (`UserRepository`,
`UserStatistics`, `fijazo_api`…) o si `bets_db` acumula colecciones ajenas. Es la regla que
justifica esta separación, escrita como test en vez de como comentario.

---

## Deuda conocida

- **Con `USERS_SERVICE_TCP_HOST` vacío el servicio acepta a cualquier usuario.** Es modo
  desarrollo y lo deja dicho en el log, pero **no debe desplegarse así**.
- `TcpUserValidator` es un esqueleto hasta T-017; si se configura el host antes de que
  exista, todas las mutaciones responderán `503`.
- `tier` llega en la validación pero todavía no se usa para nada. Se acepta en el contrato
  para no tener que romperlo cuando exista una regla de negocio por tier.
- `delete_bet` no valida al usuario contra users-service, a diferencia de crear y editar:
  un bloqueo por intentos de login fallidos no debería impedirte borrar tus propios datos.
- `distinct_user_ids()` sigue en el repositorio aunque nadie lo llame: lo necesitará el job
  de carga inicial que publica los eventos históricos (T-029).
