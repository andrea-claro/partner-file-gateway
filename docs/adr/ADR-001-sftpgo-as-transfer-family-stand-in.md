# ADR-001: SFTPGo as the AWS Transfer Family stand-in

- Status: accepted
- Date: 2026-11-15

## Context

Transfer Family is not emulated by LocalStack's free plan and costs money per
endpoint hour. The demo needs a real SFTP endpoint with per-partner users, key
authentication and an S3 backend.

## Decision

Use SFTPGo (open source, Docker image) with its S3 filesystem pointed at
LocalStack. Users are managed through SFTPGo's REST API by the `pfg` CLI. Each
user is jailed to `inbound/<partner>/` with key-only authentication and
upload-only permissions.

## Consequences

- Same partner experience and the same S3 layout as Transfer Family with a
  logical home directory, so everything downstream (EventBridge, Step Functions)
  is identical.
- SFTPGo keeps its own user database. `pfg` treats DynamoDB as the source of truth
  and rebuilds the SFTPGo user on every change. A Transfer Family custom identity
  provider backed by DynamoDB (SFTPGo external auth) is a stretch goal.
- `infra/envs/aws` shows the real Transfer Family configuration and is validated
  in CI.
