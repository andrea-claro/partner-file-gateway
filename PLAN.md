# partner-file-gateway — Execution plan

> Portfolio project: an AI-first build of a managed file transfer platform.
> Owner: Andrea Claro · Plan date: 15 Nov 2026

## 1. Goal

Build, AI-first, a small B2B managed file transfer (MFT) platform with the architecture of a typical AWS managed file transfer setup:
partners upload over SFTP/FTPS, files land in S3, an event-driven pipeline validates, routes and audits
every file, and a dashboard shows what happened.

Everything runs locally at zero cost. The only public part is a read-only dashboard exposed through Cloudflare Tunnel.

What the project must prove to a reviewer:

1. AWS file-transfer architecture: Transfer Family-style ingress, S3, EventBridge, Step Functions, Lambda, DynamoDB, SQS.
2. Infrastructure as Code with Terraform, including a real-AWS target that is validated but never applied.
3. Automated partner onboarding and key management.
4. Security and compliance built in: key-only auth, encryption, least privilege, full audit trail.
5. CI/CD with tests and policy checks.
6. AI-first engineering: agents implement, Andrea designs, reviews and decides what ships — documented in the repo.

## 2. Constraints

- **Zero cloud cost.** No paid AWS resources; managed services are emulated locally.
- **Host:** MacBook Pro (Intel x64) with Docker Desktop.
- **Exposure:** Cloudflare Tunnel on the existing Cloudflare domain; no inbound ports opened.
- **Public surface:** dashboard only. SFTP, SFTPGo admin and LocalStack stay on localhost.
- **Timeline:** public demo ready by Mon 23 Nov.
- **Neutral branding:** no employer names or logos anywhere in the project.

## 3. Architecture

```
Partner (SFTP/FTPS client)
        │  key-based auth
        ▼
SFTPGo  ── stands in for AWS Transfer Family
        │  S3 backend, one prefix per partner
        ▼
S3 bucket pfg-transfer:  inbound/<partner>/...
        │  Object Created → EventBridge
        ▼
EventBridge rule ──► Step Functions "process-transfer"
                       1. ExtractMetadata (Lambda): partner, size, SHA-256
                       2. Validate (Lambda): partner active, file pattern, size, CSV/JSON schema
                       3a. Route (Lambda): → processed/<partner>/<yyyy>/<mm>/<dd>/
                       3b. Quarantine (Lambda): → quarantine/<partner>/ + reason
                       4. RecordAudit: DynamoDB PutItem (direct SDK integration)
                       5. Notify: SQS SendMessage (direct SDK integration)
                       Catch → audit FAILED + DLQ
        ▼
DynamoDB: partners, transfers        SQS: partner-notifications (+ DLQ)
        ▼
Dashboard (FastAPI) ──► Cloudflare Tunnel ──► https://files.<domain>
```

### AWS service → local stand-in

| Target AWS service | Local stand-in | Notes |
|---|---|---|
| AWS Transfer Family (SFTP, FTPS) | SFTPGo (Docker) | Users via REST API, S3-compatible backend, key auth. AS2 out of scope. |
| S3, EventBridge, Step Functions, Lambda, DynamoDB, SQS | LocalStack (free Hobby tier, auth token) | Fallback: Floci (no account) if LocalStack blocks us. |
| Transfer Family in Terraform | `infra/envs/aws` | `terraform validate` in CI only, never applied. |
| CloudWatch Logs | Structured JSON logs | One JSON line per event, correlation id = transfer id. |

### Design decisions (one short ADR each in `docs/adr/`)

- **ADR-001** SFTPGo as the Transfer Family stand-in.
- **ADR-002** S3 Object Created events via EventBridge (same pattern on real AWS; mapping to Transfer Family's own EventBridge events documented).
- **ADR-003** Step Functions direct SDK integrations for DynamoDB and SQS, to keep Lambdas small.
- **ADR-004** Idempotency: execution name derived from object key + ETag; conditional DynamoDB writes.
- **ADR-005** Two Terraform targets (`local`, `aws`) sharing the same modules.

## 4. Repository layout

```
partner-file-gateway/
├── PLAN.md                  this file
├── CLAUDE.md                instructions for coding agents
├── README.md
├── Makefile                 up, down, infra, test, e2e, demo
├── docker-compose.yml       localstack, sftpgo, dashboard, cloudflared
├── .env.example             LOCALSTACK_AUTH_TOKEN, TUNNEL_TOKEN, SFTPGO admin creds
├── infra/
│   ├── modules/             storage, registry, events, pipeline, transfer_aws
│   └── envs/
│       ├── local/           providers pointed at LocalStack
│       └── aws/             real Transfer Family, validate-only
├── services/
│   ├── lambdas/             extract_metadata, validate, route, quarantine
│   └── dashboard/           FastAPI + Jinja2 + HTMX
├── statemachine/            process_transfer.asl.json
├── cli/                     pfg (partner onboarding)
├── samples/                 valid/ and invalid/ files
├── tests/                   unit/, integration/, e2e/
└── docs/                    architecture.md, adr/, how-this-was-built.md
```

## 5. Phases and schedule

Every task is implemented by an AI coding agent from this plan, reviewed by Andrea and merged via PR.
"Done" means: acceptance criteria met and tests green.

### Phase 0 — Foundations (Mon 16 Nov)

- [ ] 0.1 **Prerequisites on the Mac (Andrea, manual):** Docker Desktop, `make`, `git`; LocalStack Hobby account and `LOCALSTACK_AUTH_TOKEN`. Terraform, Python, AWS CLI and the linters run in the `tools` container; the Cloudflare Tunnel already runs on the host.
- [ ] 0.2 Repo skeleton (§4), `git init`, public GitHub repo, MIT licence, `.gitignore`, `.env.example`.
- [ ] 0.3 `CLAUDE.md`: stack, conventions, commands, review rules, "never commit secrets".
- [ ] 0.4 `docker-compose.yml` with LocalStack and SFTPGo; `Makefile` targets.
- **Acceptance:** `make up` starts LocalStack and SFTPGo healthy; `awslocal s3 ls` works; SFTPGo admin reachable on localhost only.

### Phase 1 — Ingestion (Tue 17 Nov)

- [ ] 1.1 Terraform `storage`: bucket `pfg-transfer`, versioning, encryption, public access blocked, EventBridge notifications on.
- [ ] 1.2 Terraform `registry`: DynamoDB tables `partners` and `transfers`.
- [ ] 1.3 Terraform `events`: SQS `partner-notifications` + DLQ; EventBridge rule for Object Created under `inbound/`.
- [ ] 1.4 SFTPGo with S3 backend pointed at LocalStack; one demo partner.
- **Acceptance:** SFTP upload as `demo` → object in `inbound/demo/` → event reaches EventBridge (debug target: SQS).

### Phase 2 — Processing pipeline (Wed 18 – Thu 19 Nov)

- [ ] 2.1 Unit tests first (pytest + moto) for each Lambda: happy path, wrong pattern, oversize, bad schema, unknown or disabled partner.
- [ ] 2.2 Lambdas `extract_metadata`, `validate`, `route`, `quarantine` (Python 3.12, boto3, structured logs).
- [ ] 2.3 State machine with retries; Catch → DLQ + `FAILED` audit.
- [ ] 2.4 Terraform `pipeline`: Lambdas, state machine, least-privilege IAM roles, EventBridge target.
- [ ] 2.5 Idempotency (ADR-004).
- **Acceptance:** e2e test — `samples/valid/*` → `processed/` + audit `DELIVERED` + SQS message; `samples/invalid/*` → `quarantine/` + audit `REJECTED` with reason.

### Phase 3 — Partner onboarding & key management (Fri 20 Nov)

- [ ] 3.1 CLI `pfg` (Typer): `partner create --name --pubkey | --generate-key`, `partner rotate-key`, `partner disable`, `partner list`.
- [ ] 3.2 `create`: DynamoDB record + S3 prefix + SFTPGo user via REST API (home = `inbound/<partner>/`, key auth only, SFTP/FTPS only).
- [ ] 3.3 `disable`: blocks login and makes Validate reject new files.
- **Acceptance:** a new partner can upload after one command; after `rotate-key` the old key is refused; tests cover every command.

### Phase 4 — Dashboard & public exposure (Sat 21 Nov)

- [ ] 4.1 FastAPI + Jinja2 + HTMX: overview (counts by status, last 24 h), transfers list and detail (audit trail), partners.
- [ ] 4.2 "Simulate a partner upload" button: server-side SFTP upload (paramiko) of a random valid or invalid sample; rate-limited per IP.
- [ ] 4.3 Read-only by design; `/healthz`.
- [ ] 4.4 Cloudflare Tunnel (already running on the host, remotely managed) → route `files.<domain>` → `http://localhost:8000` (dashboard only). Bundled `cloudflared` container optional.
- [ ] 4.5 Keep the Mac awake during the application window; `restart: unless-stopped` in compose.
- **Acceptance:** public URL loads over HTTPS; a simulated upload appears within seconds; nothing else reachable from outside.

### Phase 5 — CI/CD, docs, polish (Sun 22 – Mon 23 Nov)

- [ ] 5.1 GitHub Actions: `lint` (ruff, terraform fmt, tflint), `security` (checkov), `unit` (pytest + moto), `validate-aws` (terraform validate on `envs/aws`), `e2e` (LocalStack, token as secret).
- [ ] 5.2 `infra/envs/aws`: Transfer Family SFTP server, users with SSH keys and scoped IAM role; reuses the other modules.
- [ ] 5.3 README: what it is, architecture diagram, AWS → local mapping, 3-command quickstart, live demo link, screenshots.
- [ ] 5.4 `docs/how-this-was-built.md`: agent workflow, review checklist, concrete examples of AI output corrected or rejected and why.
- [ ] 5.5 ADR-001 to ADR-005.
- **Acceptance:** all CI jobs green on `main`; a reviewer understands the project in two minutes from the README.

### Phase 6 — Publish (Tue 24 – Wed 25 Nov)

- [ ] 6.1 Publish the repository on GitHub and add the live demo link to the README.
- [ ] 6.2 Final check of the public demo.

## 6. Cut line

- **Must have:** Phases 0–2, README, tunnel with a minimal dashboard.
- **Cut first, in this order:** FTPS, `rotate-key`, HTMX polish, `envs/aws`, e2e in CI (keep it local).
- **Never cut:** tests, "how this was built", security basics.

## 7. Stretch goals (after the first release)

- SFTPGo external HTTP auth backed by DynamoDB (mirrors a Transfer Family custom identity provider).
- Malware scan step (ClamAV) before routing.
- SFTPGo Prometheus metrics + Grafana dashboard.
- Kafka sink for processed-file events.
- Outbound delivery to partner SFTP servers (Transfer Family SFTP connectors equivalent).

## 8. Risks

| Risk | Mitigation |
|---|---|
| LocalStack auth or feature gap | Floci as fallback; provider endpoints configurable in one place |
| Lambdas in LocalStack need the Docker socket | Mount `/var/run/docker.sock`; documented in `CLAUDE.md` |
| Mac asleep or offline while reviewers look | Keep-awake during the window, restart policies, status note in README |
| Limited time (full-time job) | Cut line §6; small tasks with clear acceptance criteria |
| Abuse of the public demo | Read-only, rate-limited simulate button, Cloudflare rate limiting, no real data |

## 9. AI-first workflow

- Agents work one task at a time from §5, on a branch, tests first where possible.
- Andrea reviews every PR against a checklist: correctness, security (IAM scope, secrets), idempotency, meaningful tests, consistency with ADRs.
- Every session is logged in `docs/how-this-was-built.md`: task, what the agent produced, what was changed or rejected, and why.
