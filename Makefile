# partner-file-gateway
#
# Every target runs in Docker: the host only needs Docker Desktop, make and git.
# Run `make help` for the list of targets.

SHELL   := /bin/sh
COMPOSE ?= docker compose
TOOLS   := $(COMPOSE) --profile tools run --rm tools

.DEFAULT_GOAL := help

.PHONY: help secrets hooks build up down restart ps logs pin-host-key \
        infra infra-plan infra-destroy infra-output bootstrap demo \
        test lint fmt security validate scan-secrets e2e pfg shell tunnel tunnel-down

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} /^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

## --- Setup -----------------------------------------------------------------

secrets: ## Create .env and .secrets/ (local only, never committed)
	@./scripts/init-secrets.sh

hooks: ## Install the git pre-commit hook (blocks secrets, runs gitleaks)
	git config core.hooksPath scripts/git-hooks
	@echo "pre-commit hook installed"

build: ## Build the local images (tools, dashboard)
	$(COMPOSE) --profile tools build

## --- Stack -----------------------------------------------------------------

up: secrets ## Start LocalStack, SFTPGo and the dashboard (waits until healthy)
	@./scripts/check-env.sh
	$(COMPOSE) up -d --build --wait localstack sftpgo dashboard
	@$(MAKE) --no-print-directory pin-host-key

down: ## Stop the stack (named volumes are kept)
	$(COMPOSE) --profile public --profile tools down

restart: down up ## Restart the stack

ps: ## Show container status
	$(COMPOSE) --profile public ps

logs: ## Follow logs (e.g. make logs S=sftpgo)
	$(COMPOSE) logs -f $(S)

pin-host-key: ## Pin the SFTP host key into .secrets/sftpgo/known_hosts
	$(TOOLS) ./scripts/pin-sftp-host-key.sh

## --- Infrastructure (LocalStack only) ----------------------------------------

infra: ## terraform apply on infra/envs/local
	$(TOOLS) ./scripts/terraform-local.sh apply

infra-plan: ## terraform plan on infra/envs/local
	$(TOOLS) ./scripts/terraform-local.sh plan

infra-destroy: ## terraform destroy on infra/envs/local
	$(TOOLS) ./scripts/terraform-local.sh destroy

infra-output: ## Show Terraform outputs of infra/envs/local
	$(TOOLS) ./scripts/terraform-local.sh output

bootstrap: ## Onboard the demo partner (idempotent)
	$(TOOLS) ./scripts/bootstrap.sh

demo: up infra bootstrap ## Everything: stack + infrastructure + demo partner

## --- Quality ---------------------------------------------------------------

test: ## Lint + unit tests (no network, no running stack needed)
	$(TOOLS) ./scripts/test.sh

lint: ## ruff, terraform fmt, tflint
	$(TOOLS) ./scripts/lint.sh

fmt: ## Auto-format Python and Terraform
	$(TOOLS) sh -c 'ruff check --fix . && ruff format . && terraform fmt -recursive infra'

security: ## checkov on all Terraform
	$(TOOLS) checkov --directory infra --framework terraform --compact --quiet

validate: ## terraform validate on infra/envs/local and infra/envs/aws (never applied)
	$(TOOLS) ./scripts/validate-tf.sh

scan-secrets: ## gitleaks over the full git history
	docker run --rm -v "$(CURDIR):/repo" -w /repo \
	  -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0=/repo \
	  ghcr.io/gitleaks/gitleaks:v8.30.1 git --redact --no-banner

e2e: ## End-to-end tests against the running stack
	$(TOOLS) pytest -p no:cacheprovider -m live tests/integration tests/e2e

## --- Tools -----------------------------------------------------------------

pfg: ## Partner CLI, e.g. make pfg ARGS="partner list"
	$(TOOLS) python -m pfg $(ARGS)

shell: ## Shell inside the tools container
	$(TOOLS) bash

## --- Public exposure (optional bundled tunnel) --------------------------------

tunnel: ## Start the bundled cloudflared (only if no tunnel runs on the host)
	@./scripts/check-env.sh --tunnel
	$(COMPOSE) --profile public up -d --wait cloudflared

tunnel-down: ## Stop the bundled cloudflared
	$(COMPOSE) --profile public stop cloudflared
