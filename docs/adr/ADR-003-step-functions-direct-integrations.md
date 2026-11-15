# ADR-003: Step Functions direct SDK integrations for DynamoDB and SQS

- Status: accepted
- Date: 2026-11-15

## Context

Each transfer needs audit writes (DynamoDB) and a notification (SQS). These
could be done inside the Lambdas or by the state machine.

## Decision

The state machine writes the audit trail (`dynamodb:putItem`,
`dynamodb:updateItem`) and sends notifications (`sqs:sendMessage`) itself.
Lambdas only do work that needs code: hashing, validation and moving objects.

## Consequences

- Smaller Lambdas with narrower IAM roles (no Lambda can write the audit trail).
- Retries, timeouts and failure handling live in one visible place, the ASL.
- The ASL is more verbose (typed DynamoDB attribute values) and is tested
  structurally in `tests/unit/statemachine`.
