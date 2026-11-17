# How this was built

This project is built **AI-first**: coding agents implement tasks from
[PLAN.md](../PLAN.md) following [CLAUDE.md](../CLAUDE.md); Andrea designs the
architecture, reviews every change and decides what ships.

## Workflow

1. Pick one task from PLAN.md §5 and restate its acceptance criteria.
2. The agent proposes a short plan; anything touching architecture, IAM or
   security waits for approval.
3. Tests first where possible (moto for AWS, fakes for SFTPGo).
4. The agent runs lint and tests and shows the results; nothing is "done" with
   failing tests.
5. Andrea reviews the PR against the checklist below and records the outcome here.

## Review checklist

- [x] Correctness: does it meet the acceptance criteria? Are edge cases tested?
- [x] Security: IAM scope, secrets handling, exposed ports, input validation.
- [x] Idempotency: safe on retries and duplicate events?
- [x] Tests: do they test behaviour, not implementation details?
- [x] Consistency with the ADRs and CLAUDE.md conventions.
- [x] Cost: nothing that could create real AWS resources.

## Log

### 2026-11-15 — Phase 0–5 scaffolding (one agent session)

**Task.** At Andrea's request, one session created the whole first version
instead of one task at a time: repository skeleton, Docker Compose stack, secret
handling, Terraform modules and environments, Lambdas with unit tests, state
machine, `pfg` CLI, dashboard, live tests, CI and documentation. Extra
instructions: run every tool in Docker (the Mac needs only Docker Desktop) and
never write secrets to versioned files.

**Produced.**
- `docker-compose.yml` (LocalStack, SFTPGo, dashboard, optional cloudflared,
  `tools` profile) and a Makefile where every target runs in Docker.
- `make secrets`: `.env` from `.env.example` with generated local secrets;
  `.secrets/` for partner keys and the pinned SFTP host key; pre-commit hook
  (blocks secret files, runs gitleaks).
- Terraform modules `storage`, `registry`, `events`, `pipeline`, `transfer_aws`;
  environments `local` (LocalStack) and `aws` (validate-only).
- Lambdas `extract_metadata`, `validate`, `route`, `quarantine` and the
  `process-transfer` ASL; `pfg` CLI; FastAPI dashboard.
- 106 unit tests, live integration/e2e tests, GitHub Actions workflow, README,
  architecture, ADR-001 to ADR-005.

**Verified in the agent's sandbox (no Docker there).**
- `ruff check` / `ruff format --check`: clean. `pytest tests/unit`: 106 passed.
- `terraform fmt`, `terraform validate` (both environments), `tflint` (AWS
  ruleset): clean. `checkov`: 0 failed checks, every skip commented in the code.
- `terraform apply` of `envs/local` against a moto server standing in for
  LocalStack: 41 resources created (moto needed two small patches for APIs
  LocalStack implements: `ValidateStateMachineDefinition`, `RedriveAllowPolicy`).
- ASL validated with `asl-validator`; workflow checked with `actionlint`;
  `docker compose config` valid; scripts pass `shellcheck`, Dockerfiles pass `hadolint`;
  `gitleaks` finds nothing in the tree or in a test commit.
- Dashboard rendered in headless Chrome with seeded fake data (desktop, dark mode,
  mobile): fixed file names wrapping one letter per line, the mobile page being
  widened by the table, and a missing favicon.
- **Not run yet:** the stack on the Mac (`make demo`), the live e2e tests and the
  real LocalStack apply. These are the Phase 0–2 acceptance checks.

**Agent output corrected by automated checks during the session.**
- DynamoDB GSI used `hash_key`/`range_key`, deprecated in AWS provider 6.x →
  `terraform validate` warned → moved to `key_schema` blocks.
- With an account id, provider 6.x reads bucket tags through S3 Control, whose
  account-id host prefix breaks with a custom endpoint (the smoke apply failed
  with a 403 from real AWS) → `skip_requesting_account_id = true` in
  `envs/local`, which also replaced the `allowed_account_ids` guard there.
- Transfer Family security policy `2024-01` failed checkov's "under 24 months"
  rule → `TransferSecurityPolicy-2025-03` (hybrid post-quantum key exchange).
- The ASL top-level comment contained a `${...}` sample that would break
  Terraform's `templatefile()`, and the failure audit read `$.error.Cause`, which
  is not guaranteed → removed, and `States.JsonToString($.error)` used instead.

**Decisions to review.**
- ADR-004 deviates from PLAN.md: EventBridge cannot set the execution name, so
  idempotency relies on the deterministic transfer id + conditional writes. The
  id also includes the object version, so identical re-sends are not dropped.
- Added a `RecordReceived` state before Validate (PLAN.md listed RecordAudit
  only at the end) so `RECEIVED` exists and duplicates stop early.
- FAILED transfers go to the notifications DLQ (as in PLAN.md) and the
  EventBridge target also dead-letters there.
- New `tools` compose service (profile, not part of the runtime stack), so the
  host needs only Docker.
- The existing host Cloudflare Tunnel is used; the bundled `cloudflared` stays
  optional.
- SFTPGo host key: generated by SFTPGo, pinned by `make up` with `ssh-keyscan`
  over the private network (trust on first use, then strict checking).

**Human review.** I asked for the whole first version in one session instead of
task by task, with two constraints: every tool runs in Docker and no secret ever
lands in a versioned file. I reviewed the decisions listed above and accepted
all six as proposed. The one I weighed longest was ADR-004: deterministic
execution names would need an SQS queue and a starter Lambda in front of the
state machine, while a deterministic transfer id plus conditional writes gives
the same protection against duplicates with no extra component, and keeping the
object version in the id means an identical re-send is processed instead of
silently dropped. In the code I read the IAM policies in
`infra/modules/pipeline` (one role per Lambda, scoped to the bucket prefixes and
tables that step needs; the only `Resource "*"` is the Step Functions log
delivery statement, which AWS requires and which is commented) and the SFTPGo
user that `pfg` creates (public key only, home limited to `inbound/<partner>/`,
upload and list but no download, rename or delete).

### 2026-11-15 — First run on the Mac: uploads failed

**Symptom.** `make demo` came up healthy, but the dashboard simulator reported
"The SFTP upload failed" and `make e2e` failed 12 of 14 tests with
`failure: open no such file or directory` on every SFTP write. Key-based login
worked (the rotate-key and disable tests passed).

**Root cause (agent mistake).** `pfg` created SFTPGo users with
`disable_fs_checks: true` to "save S3 calls". Reading SFTPGo's source showed that
S3 users buffer uploads in their *local* home directory, and that directory is
only created by the login-time fs check. With the check disabled, every upload
failed before reaching S3. The unit tests used a fake SFTPGo, so only the live
e2e suite could catch it.

**Fix.** `disable_fs_checks: false` (with a comment explaining why), a unit test
that pins the setting, `make bootstrap` to reconcile the existing demo user. The
e2e suite now also deletes its throwaway `e2e-*` partners before and after each
run, so they never show up on the public dashboard.

**Human review.** I ran `make demo` and `make e2e` on the Mac: 12 of 14 tests
failed and the dashboard simulator reported an upload error, while key-based
login worked. I sent the output back to the agent, which traced the cause to
`disable_fs_checks` in SFTPGo's source. After the fix and `make bootstrap`, the
e2e suite passed and the simulator worked. Takeaway: unit tests with a fake
SFTPGo cannot catch a configuration error in the real one; the live e2e suite is
the gate before anything is published.
### 2026-11-16 — Published repository and live demo

**Task.** Prepare the repository to be shared publicly with the live demo.

**Produced.**
- Andrea renamed the project to `partner-file-gateway`, published it on GitHub
  and routed `file-gtw-lab.clarotech.net` to the dashboard through the
  Cloudflare Tunnel that already runs on the host.
- `PLAN.md` became a public copy without personal details; the original stays
  local as `PLAN.md.example` (gitignored and blocked by the pre-commit hook).
- README: CI badge, live demo link, a "Try the live demo" walkthrough,
  screenshots (sample data), a "What this project shows" map and operating notes.
- Dashboard footer links to the source; the "not reachable" page tells visitors
  the demo is restarting instead of showing a developer command.
- PLAN.md progress ticked for every task whose acceptance criteria were met on
  the Mac (`make demo`, `make e2e` green, public URL loading over HTTPS).

**Decision.** An agent proposal to add a "reconciler" service that re-applies
Terraform after a restart was rejected by Andrea: the project is a lab and must
not grow in complexity. The restart procedure (`make demo`) is documented in the
README instead.

**Human review.** I kept my personal planning notes out of the public repository
(PLAN.md.example stays local), renamed the project and published only the
dashboard on my existing Cloudflare Tunnel. I rejected the agent's proposal to add
a reconciler service: a documented `make demo` after a restart is enough for a lab
and keeps the stack simple. I reviewed PR #1 commit by commit: the README
walkthrough against the live demo, the screenshots (sample data only), the
PLAN.md ticks against what had actually run on the Mac, and the gitleaks version
in CI matching the pre-commit hook. CI was green on the PR, and I merged it
keeping the four commits separate.

### 2026-11-17 — Final checks before sharing

**Task.** Close the open items in PLAN.md before sharing the repository link.

**Produced.**
- Human review notes for the two entries above, written up from the repository
  history (ADR status, the merged PR, CI runs) and checked by Andrea.
- PLAN.md 4.5, 5.1, 5.4 and 6.2 ticked. CI on `main` is green (lint, security, unit,
  validate); the e2e job is wired but skips without the `LOCALSTACK_AUTH_TOKEN`
  secret, so e2e stays a local gate (`make e2e`), as the cut line in PLAN.md §6
  allows.
- GitHub About: a one-line description of the project.

**Human review.** I read every sentence of the review notes above before
committing them, and checked the CI results on GitHub myself.

### 2026-11-17 — Public demo retired

**Decision.** Andrea stopped exposing the dashboard: the laptop that runs the
whole stack could not sustain the load of a public URL. Only the repository is
shared now; the dashboard runs locally after the quickstart.

**Produced.**
- README: the live demo link and walkthrough replaced by a local walkthrough
  (`http://localhost:8000`); publishing the dashboard is documented as optional.
- PLAN.md: 4.5 reduced to the restart policy, 6.2 dropped, an update note under
  Phase 4. CLAUDE.md, the architecture page, the compose file and
  `.env.example` no longer describe the dashboard as published.
- The "not reachable" page tells the developer to run `make demo` again,
  instead of addressing public visitors.
- Kept: the optional `cloudflared` profile, `make tunnel`, the dashboard's rate
  limiting and CSP. They cost nothing and keep the dashboard safe to publish.

**Human review.** I stopped exposing the service because my laptop could not
handle the load, and I share only the repository, which explains what was built.
