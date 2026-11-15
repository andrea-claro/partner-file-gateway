# CLAUDE.md

## What this project is

**partner-file-gateway** is a small B2B managed file transfer (MFT) platform modelled on AWS Transfer Family,
running entirely on a local machine at zero cost.

Partners upload files over SFTP/FTPS. Files land in S3. An event-driven pipeline
(EventBridge → Step Functions → Lambda) validates every file, routes it to `processed/` or `quarantine/`,
writes an audit trail to DynamoDB and notifies through SQS. A read-only FastAPI dashboard shows transfers,
partners and audit history, and is published on the internet through Cloudflare Tunnel.

It is a portfolio project for a DevOps Engineer (AI-first) role. Clarity, correctness, security and tests
matter more than the number of features.

The full plan, phases and acceptance criteria are in **PLAN.md**. Work only on the task you are given.

## Hard rules

- **Zero cloud cost.** Never create real AWS resources, never run `terraform apply` on `infra/envs/aws`,
  never use real AWS credentials. All AWS calls go to LocalStack at `http://localhost:4566`
  (credentials `test`/`test`, region `eu-central-2`).
- **Never commit secrets.** `.env` and `.secrets/` (partner keys, pinned SFTP host key) are gitignored;
  add every new variable to `.env.example` with a placeholder. `make hooks` installs a pre-commit hook
  that blocks secret files and runs gitleaks.
- **Public surface = dashboard only.** SFTP, SFTPGo admin and LocalStack bind to `127.0.0.1`.
- **English only** in code, comments, docs and commit messages.
- **No employer names or branding** anywhere in the repo.
- **Ask before** adding a new service, a new major dependency or changing the architecture in PLAN.md §3.

## Stack

- **Python 3.12:** Lambdas, CLI (`pfg`, Typer), dashboard (FastAPI + Jinja2 + HTMX), boto3, paramiko.
- **Tests and quality:** pytest + moto, ruff.
- **IaC:** Terraform ≥ 1.6, AWS provider; modules in `infra/modules`, environments `infra/envs/local` and `infra/envs/aws` (validate only).
- **Runtime:** Docker Compose with `localstack`, `sftpgo`, `dashboard`; `tools` (profile `tools`) holds every CLI;
  `cloudflared` is optional (profile `public`).
- **Stand-ins:** SFTPGo for AWS Transfer Family; LocalStack for S3, EventBridge, Step Functions, Lambda, DynamoDB, SQS.

## Domain model

- Bucket `pfg-transfer`: `inbound/<partner>/…` → `processed/<partner>/<yyyy>/<mm>/<dd>/…` or `quarantine/<partner>/…`.
- DynamoDB tables: `partners` (id, name, status, allowed patterns, key fingerprint), `transfers` (audit trail).
- SQS: `partner-notifications` with a DLQ.
- State machine: `process-transfer` — ExtractMetadata → Validate → Route | Quarantine → RecordAudit → Notify; Catch → `FAILED` audit + DLQ.
- Transfer status values: `RECEIVED`, `DELIVERED`, `REJECTED`, `FAILED`.

## Conventions

- **Lambdas:** one folder per function; keep pure logic separate from AWS I/O so it can be unit tested;
  structured JSON logs carrying `transfer_id`.
- **Tests first** for Lambda and CLI logic. Unit tests use moto and no network; e2e tests run against the live stack.
- **Terraform:** endpoints and names as variables; least-privilege IAM (no `*` actions on `*` resources);
  tags on every resource; `terraform fmt` and `validate` clean; checkov clean or a commented, justified skip.
- **Idempotency:** Step Functions execution name derived from object key + ETag; conditional DynamoDB writes.
- **Commits:** small, conventional prefixes (`feat:`, `fix:`, `test:`, `infra:`, `docs:`, `ci:`).

## Commands

Created in Phase 0; keep this list up to date. Every target runs in Docker (`make help` lists all).

- `make secrets` — create `.env` and `.secrets/` (local only); put `LOCALSTACK_AUTH_TOKEN` in `.env`
- `make up` / `make down` — start or stop the stack (`up` also pins the SFTP host key)
- `make infra` — apply Terraform on `infra/envs/local`
- `make bootstrap` — onboard the demo partner (idempotent); `make demo` = up + infra + bootstrap
- `make test` — lint (ruff, terraform fmt, tflint) + unit tests
- `make security` — checkov; `make validate` — terraform validate on `local` and `aws`
- `make e2e` — end-to-end tests against the running stack
- `make pfg ARGS="partner list"` — partner CLI; `make shell` — shell in the tools container
- `make hooks` — install the pre-commit hook

## Environment notes

- Host: macOS (Intel x64) with Docker Desktop. Terraform, Python, AWS CLI, ruff, pytest, tflint and checkov run
  in the `tools` container: never require host installs beyond Docker, make and git.
- LocalStack needs `LOCALSTACK_AUTH_TOKEN` and the Docker socket (`/var/run/docker.sock`) mounted to run Lambdas.
- If LocalStack does not support something, stop and report it. Switching to Floci needs Andrea's approval.
- Public exposure uses the Cloudflare Tunnel already running on the host: route `files.<domain>` to
  `http://localhost:8000` (dashboard only).

## How we work (AI-first)

1. Restate the task and its acceptance criteria from PLAN.md, then propose a short plan.
   Wait for approval on anything that touches architecture, IAM or security.
2. Implement in small steps, tests first where possible.
3. Before saying a task is done: run lint and tests and show the results. Never mark a task done with failing tests.
4. Summarise what changed, the assumptions you made and any open questions.
5. Tick the task in PLAN.md and append an entry to `docs/how-this-was-built.md`:
   date, task, what you produced, and a "Human review" placeholder for Andrea to fill in.
