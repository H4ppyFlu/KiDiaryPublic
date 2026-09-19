# syntax=docker/dockerfile:1

# The frontend is built here and copied into the API image as plain static files, so
# that Node and node_modules never reach the running container (ADR-0007).
FROM node:22-alpine AS web-build
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.13-slim AS api-base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app


# Carries pytest and the suite. The runtime image below gets neither.
FROM api-base AS dev
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY backend/tests ./tests
CMD ["pytest"]


FROM api-base AS runtime
COPY --from=web-build /web/dist ./static
RUN useradd --system --create-home kidiary && chown -R kidiary /app
USER kidiary
EXPOSE 8000
# Migrate and seed before serving. Both are idempotent, so a restart is cheap and a
# rebuilt Pi comes up with a usable Prompt bank.
CMD ["sh", "-c", "python -m app.bootstrap && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
