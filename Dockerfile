FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Debe coincidir con la versión que generó poetry.lock: una anterior rechaza el
    # lock-version 2.1 con "pyproject.toml changed significantly".
    POETRY_VERSION=2.3.3 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /app

# Instala Poetry
RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

# Instala dependencias (capa cacheable)
COPY pyproject.toml poetry.lock* README.md ./
COPY src ./src
RUN poetry install --only main --no-interaction --no-ansi

# Puerto propio: 8000 lo ocupa el monolito y 8001 auth-service. El único servicio con
# puerto público es el api-gateway.
EXPOSE 8002

CMD ["uvicorn", "bets_service.main:app", "--host", "0.0.0.0", "--port", "8002"]
