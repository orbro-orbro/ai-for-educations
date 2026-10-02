ARG BASE_IMAGE=mcr.microsoft.com/devcontainers/python:1-3.12-bookworm@sha256:7876580dc67fd460fd962f004cbeb480027e9bbc0657096f1087db11f9eaff39
FROM ${BASE_IMAGE}

ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --gid 10002 controller \
    && useradd --uid 10002 --gid controller --no-create-home --shell /usr/sbin/nologin controller

COPY controller-requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --requirement /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY __init__.py /app/runner/__init__.py
COPY controller /app/runner/controller
COPY worker /app/runner/worker

WORKDIR /app
USER 10002:10002
ENTRYPOINT ["python", "-m", "uvicorn"]
CMD ["runner.controller.app:app", "--host", "0.0.0.0", "--port", "8080"]
