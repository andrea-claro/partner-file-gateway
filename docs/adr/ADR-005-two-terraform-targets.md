# ADR-005: Two Terraform targets sharing the same modules

- Status: accepted
- Date: 2026-11-15

## Context

The demo must run on LocalStack at zero cost, yet show infrastructure that would
deploy to real AWS.

## Decision

- Modules in `infra/modules` (`storage`, `registry`, `events`, `pipeline`,
  `transfer_aws`) take names, settings and an optional KMS
  key as variables.
- `infra/envs/local` points every provider endpoint at LocalStack (the variable
  only accepts LocalStack addresses) with dummy credentials.
- `infra/envs/aws` adds Transfer Family and a customer managed KMS key. It is
  only ever validated (`make validate`, CI). Its provider sets
  `allowed_account_ids` to a placeholder that matches no real account, so an
  accidental apply fails before creating anything.

## Consequences

- One code path for the pipeline; differences are explicit in two small
  environment folders.
- Some checks only matter on AWS (KMS, deletion protection, log retention) and are
  enabled there through module variables; checkov skips in the modules document why.
- `terraform validate` cannot catch everything a real `plan` would; the local
  apply on LocalStack covers the shared modules end to end.
