"""Structural checks of the state machine definition (no AWS needed)."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from quarantine.handler import STATUS as QUARANTINE_STATUS
from route.handler import STATUS as ROUTE_STATUS
from tests.unit.conftest import REPO_ROOT

ASL_PATH = REPO_ROOT / "statemachine" / "process_transfer.asl.json"
PIPELINE_TF = REPO_ROOT / "infra" / "modules" / "pipeline" / "main.tf"
PLACEHOLDER = re.compile(r"\$\{([a-z_]+)\}")
TRANSFER_STATUSES = {"RECEIVED", "DELIVERED", "REJECTED", "FAILED"}


def render() -> dict[str, Any]:
    text = ASL_PATH.read_text()
    rendered = PLACEHOLDER.sub(lambda m: f"arn:aws:test:::{m.group(1)}", text)
    return json.loads(rendered)


@pytest.fixture(scope="module")
def asl() -> dict[str, Any]:
    return render()


def targets(state: dict[str, Any]) -> list[str]:
    found = [state[k] for k in ("Next", "Default") if k in state]
    found += [choice["Next"] for choice in state.get("Choices", [])]
    found += [catcher["Next"] for catcher in state.get("Catch", [])]
    return found


def test_every_transition_points_to_an_existing_state(asl):
    states = asl["States"]
    assert asl["StartAt"] in states
    for name, state in states.items():
        for target in targets(state):
            assert target in states, f"{name} -> unknown state {target}"


def test_every_state_is_reachable(asl):
    states = asl["States"]
    seen, todo = set(), [asl["StartAt"]]
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo.extend(targets(states[name]))
    assert seen == set(states)


def test_non_terminal_states_have_a_way_out(asl):
    for name, state in asl["States"].items():
        if state["Type"] in ("Succeed", "Fail"):
            continue
        assert targets(state) or state.get("End"), name


def test_every_task_except_the_last_resort_catches_all_errors(asl):
    for name, state in asl["States"].items():
        if state["Type"] != "Task" or name == "SendToDeadLetterQueue":
            continue
        catch_all = [c for c in state.get("Catch", []) if "States.ALL" in c["ErrorEquals"]]
        assert catch_all, f"{name} has no States.ALL catcher"
        assert state.get("TimeoutSeconds"), f"{name} has no timeout"


def test_received_record_is_a_conditional_write(asl):
    state = asl["States"]["RecordReceived"]
    assert state["Parameters"]["ConditionExpression"] == "attribute_not_exists(transfer_id)"
    duplicate = state["Catch"][0]
    assert duplicate["ErrorEquals"] == ["DynamoDB.ConditionalCheckFailedException"]
    assert asl["States"][duplicate["Next"]]["Type"] == "Succeed"


@pytest.mark.parametrize("name", ["RecordReceived", "RecordOutcome"])
def test_conditional_writes_are_not_retried_on_generic_errors(asl, name):
    # A retrier on States.ALL/States.TaskFailed would also retry
    # ConditionalCheckFailedException and defeat the idempotency check.
    for retrier in asl["States"][name].get("Retry", []):
        assert not {"States.ALL", "States.TaskFailed"} & set(retrier["ErrorEquals"])


def test_only_known_transfer_statuses_are_written(asl):
    literal_statuses = set(re.findall(r'"S": "([A-Z]+)"', json.dumps(asl, indent=1)))
    assert literal_statuses <= TRANSFER_STATUSES
    assert {ROUTE_STATUS, QUARANTINE_STATUS} <= TRANSFER_STATUSES


def test_placeholders_match_the_terraform_template_variables():
    names = set(PLACEHOLDER.findall(ASL_PATH.read_text()))
    assert names == {
        "extract_metadata_arn",
        "validate_arn",
        "route_arn",
        "quarantine_arn",
        "transfers_table",
        "notifications_queue_url",
        "dead_letter_queue_url",
    }
    terraform = PIPELINE_TF.read_text()
    for name in names:
        assert re.search(rf"\b{name}\s*=", terraform), f"{name} not passed by templatefile()"
