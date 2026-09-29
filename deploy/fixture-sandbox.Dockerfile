# Intentionally no floating default. Operator supplies an audited Python image digest.
# Example command after selecting/caching YOUR base (not executed by TraceForge):
# docker build --build-arg PYTHON_BASE=<your-reviewed-python-image@sha256:digest> -f deploy/fixture-sandbox.Dockerfile -t my-reviewed-fixture:local .
ARG PYTHON_BASE
FROM ${PYTHON_BASE}
USER 65534:65534
WORKDIR /tmp
ENV HOME=/tmp LANG=C.UTF-8
ENTRYPOINT ["python3"]
