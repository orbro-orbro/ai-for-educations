ARG BASE_IMAGE
FROM ${BASE_IMAGE}
USER root
COPY deps /opt/wave3-test-deps
COPY runner /app/runner
COPY contracts /app/contracts
ENV PYTHONPATH=/opt/wave3-test-deps:/app PYTHONDONTWRITEBYTECODE=1 TMPDIR=/work
WORKDIR /work
USER 10001:10001
ENTRYPOINT ["python", "-B", "-m", "pytest"]
