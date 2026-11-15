# ADR-002: S3 Object Created events through EventBridge

- Status: accepted
- Date: 2026-11-15

## Context

The pipeline must start for every file a partner uploads. Options: S3 event
notifications to Lambda/SQS, Transfer Family's own EventBridge events
("Transfer Family file upload completed"), or S3 events through EventBridge.

## Decision

Enable EventBridge notifications on the bucket and match
`source = aws.s3`, `detail-type = Object Created`, key prefix `inbound/`. The
rule targets the state machine.

## Consequences

- Identical locally and on AWS, independent of the SFTP implementation (SFTPGo
  emits no Transfer Family events).
- Objects written by the pipeline (`processed/`, `quarantine/`) do not match, so
  there are no loops.
- On real AWS, Transfer Family's upload-completed events could replace the S3
  rule: they also carry the user name and session, but only exist for transfers
  through Transfer Family.
- EventBridge delivers at least once: handled by ADR-004.
