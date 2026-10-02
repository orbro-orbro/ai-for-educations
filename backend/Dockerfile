ARG BASE_IMAGE=mcr.microsoft.com/devcontainers/python:1-3.12-bookworm@sha256:7876580dc67fd460fd962f004cbeb480027e9bbc0657096f1087db11f9eaff39
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN groupadd --gid 10003 api \
    && useradd --uid 10003 --gid api --no-create-home --shell /usr/sbin/nologin api \
    && mkdir -p /app \
    && chown api:api /app

WORKDIR /app
COPY . /app
COPY --from=course_seed . /data/course_seed
RUN pip install --no-cache-dir .

USER 10003:10003
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python -m app.persistence.bootstrap && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
