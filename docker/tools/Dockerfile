# Toolbox image: every CLI this project needs, so the host only needs Docker.
# Used by the Makefile through `docker compose run --rm tools ...`.
FROM python:3.12-slim-trixie

ARG TARGETARCH
ARG TERRAFORM_VERSION=1.17.2
ARG TFLINT_VERSION=0.66.0
ARG CHECKOV_VERSION=3.4.5

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TFLINT_PLUGIN_DIR=/opt/tflint/plugins \
    TF_PLUGIN_CACHE_DIR=/root/.cache/terraform-plugins

# Fail a RUN step if any command of a pipeline fails (checksum verification).
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Debian package versions move with security updates; the base image tag pins the release.
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git jq make openssh-client unzip \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp

# Terraform, verified against HashiCorp's published checksums.
RUN set -eux; \
    arch="${TARGETARCH:-amd64}"; \
    base="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}"; \
    curl -fsSLO "${base}/terraform_${TERRAFORM_VERSION}_linux_${arch}.zip"; \
    curl -fsSLO "${base}/terraform_${TERRAFORM_VERSION}_SHA256SUMS"; \
    grep " terraform_${TERRAFORM_VERSION}_linux_${arch}.zip\$" "terraform_${TERRAFORM_VERSION}_SHA256SUMS" | sha256sum -c -; \
    unzip -q "terraform_${TERRAFORM_VERSION}_linux_${arch}.zip" terraform -d /usr/local/bin; \
    rm -f /tmp/terraform_*; \
    mkdir -p "${TF_PLUGIN_CACHE_DIR}"; \
    terraform version

# TFLint, verified against the release checksums.
RUN set -eux; \
    arch="${TARGETARCH:-amd64}"; \
    base="https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}"; \
    curl -fsSLO "${base}/tflint_linux_${arch}.zip"; \
    curl -fsSLO "${base}/checksums.txt"; \
    grep " tflint_linux_${arch}.zip\$" checksums.txt | sha256sum -c -; \
    unzip -q "tflint_linux_${arch}.zip" -d /usr/local/bin; \
    rm -f /tmp/tflint_* /tmp/checksums.txt; \
    tflint --version

# Python tooling: hash-pinned (pip enforces hashes when the file has them).
COPY requirements/dev.txt /tmp/requirements-dev.txt
RUN pip install --require-hashes -r /tmp/requirements-dev.txt && rm /tmp/requirements-dev.txt

# checkov pins many libraries of its own, so it lives in a separate venv.
RUN python -m venv /opt/checkov \
 && /opt/checkov/bin/pip install "checkov==${CHECKOV_VERSION}" \
 && ln -s /opt/checkov/bin/checkov /usr/local/bin/checkov

# Bake the TFLint AWS ruleset into the image.
COPY .tflint.hcl /opt/tflint/.tflint.hcl
RUN tflint --init --config /opt/tflint/.tflint.hcl

WORKDIR /workspace
CMD ["bash"]
