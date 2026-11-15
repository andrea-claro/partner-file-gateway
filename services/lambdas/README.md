# Lambdas

One folder per function. Each `handler.py` only wires AWS clients and calls
pure functions that the unit tests exercise with moto.

| Function | Input | Output (merged into the state machine state) |
|---|---|---|
| `extract_metadata` | EventBridge "Object Created" event | `$.metadata`: transfer id, partner, size, SHA-256 |
| `validate` | `{metadata}` | `$.validation`: `valid`, `reason` |
| `route` | `{metadata}` | `$.routing`: `status=DELIVERED`, destination key |
| `quarantine` | `{metadata, reason}` | `$.routing`: `status=REJECTED`, destination key |

`pfg_lambda_common` is packaged into every function zip by Terraform
(`infra/modules/pipeline`). The functions rely on the boto3 version shipped with
the Lambda Python 3.12 runtime; there are no third-party dependencies.
