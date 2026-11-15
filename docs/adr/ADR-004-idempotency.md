# ADR-004: Idempotency

- Status: accepted, with a deviation from PLAN.md to review
- Date: 2026-11-15

## Context

EventBridge delivers events at least once, and an execution may be retried. A
duplicate must not move a file twice, send two notifications or overwrite the
audit trail.

PLAN.md proposed "execution name derived from object key + ETag". An EventBridge
rule that targets Step Functions directly **cannot set the execution name**
(the target only accepts the input and a role), so that alone would need an extra
component (a starter Lambda or a queue) in front of the state machine.

## Decision

- `ExtractMetadata` computes `transfer_id = sha256(bucket, key, version id, ETag)`
  (the S3 sequencer replaces the version id when the bucket is unversioned).
- The first audit write is a conditional `PutItem` (`attribute_not_exists`); a
  duplicate is caught and ends the execution in `AlreadyProcessed` before
  touching S3.
- The final write is a conditional `UpdateItem` (`status = RECEIVED`), so an
  outcome is recorded once.
- The move copies the exact object version from the event, so a newer upload
  under the same name is never moved by the older execution.

The version id is part of the key on purpose: with key + ETag only, a partner
re-sending an identical file would be silently dropped as a duplicate.

## Consequences

- No extra component; duplicates cost one short execution.
- The execution name stays the default (random). If deterministic names are
  wanted, put an SQS queue + small starter Lambda between EventBridge and Step
  Functions (open question for review).
- Covered by unit tests (deterministic ids, conditional writes not retried) and by
  `tests/e2e/test_pipeline.py::test_replayed_event_is_ignored`.
