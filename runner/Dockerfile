ARG BASE_IMAGE=mcr.microsoft.com/devcontainers/python:1-3.12-bookworm@sha256:7876580dc67fd460fd962f004cbeb480027e9bbc0657096f1087db11f9eaff39
FROM ${BASE_IMAGE} AS sdk

ARG CANGJIE_VERSION=1.2.0
ARG CANGJIE_SDK_SHA256=8c5fd944cd9cc51ee63d4a240e3ecc4f540345dae1468e8b47c927ecf2ba998f
ARG CANGJIE_SDK_URL="https://cangjie-lang.cn/v1/files/auth/downLoad?nsId=142267&fileName=cangjie-sdk-linux-x64-1.2.0.tar.gz&objectKey=6ab1e26eece1f87ff5befa73"

RUN curl --fail --location --retry 3 --output /tmp/cangjie-sdk.tar.gz "${CANGJIE_SDK_URL}" \
    && echo "${CANGJIE_SDK_SHA256}  /tmp/cangjie-sdk.tar.gz" | sha256sum --check --strict \
    && mkdir -p /opt/cangjie \
    && tar --extract --gzip --file /tmp/cangjie-sdk.tar.gz --directory /opt/cangjie --strip-components=1 \
    && rm /tmp/cangjie-sdk.tar.gz

FROM ${BASE_IMAGE}

ENV PATH="/opt/cangjie/bin:/opt/cangjie/tools/bin:${PATH}" \
    LD_LIBRARY_PATH="/opt/cangjie/runtime/lib/linux_x86_64_cjnative:/opt/cangjie/lib/linux_x86_64_cjnative" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RUNNER_TEMP_ROOT=/work

RUN groupadd --gid 10001 runner \
    && useradd --uid 10001 --gid runner --no-create-home --shell /usr/sbin/nologin runner \
    && mkdir -p /app /work \
    && chown runner:runner /work

COPY --from=sdk /opt/cangjie /opt/cangjie
RUN chmod --recursive a+rX /opt/cangjie \
    && cjc -v \
    && cjpm -v
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --requirement /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY __init__.py /app/runner/__init__.py
COPY worker /app/runner/worker

WORKDIR /work
USER 10001:10001
ENTRYPOINT ["python"]
CMD ["-c", "import subprocess; subprocess.run(['cjc', '-v'], check=True)"]
