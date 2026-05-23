"""Unit tests for bridge/platoon_dialogue_guard.py (deterministic gate in front of the LLM agents).

These pin existing behavior; no production change was needed.
"""

import json
import subprocess
import sys
from pathlib import Path

import platoon_dialogue_guard as guard

GUARD = Path(__file__).resolve().parents[2] / "bridge" / "platoon_dialogue_guard.py"
A_MENTION = "<@1479297673432399923>"  # TRUCKCLAW2 / platoon_a


def run_guard(*args):
    proc = subprocess.run([sys.executable, str(GUARD), *args], capture_output=True, text=True, timeout=10)
    return proc.returncode, json.loads(proc.stdout)


def test_extracts_vehicle_destinations_from_chat_text():
    text = "Platoon A 목적지\n- platoon_a_truck0: dest_a\n- platoon_a_truck1: dest_b"
    assert guard._destinations(text) == {"platoon_a_truck0": "dest_a", "platoon_a_truck1": "dest_b"}


def test_confirmation_only_message_is_detected():
    assert guard._is_confirmation_only(f"{A_MENTION} 확인")
    assert guard._is_confirmation_only("")


def test_message_with_machine_update_is_not_confirmation_only():
    assert not guard._is_confirmation_only(f"{A_MENTION} 확인 request_id: tr_abc123")


def test_chat_candidate_is_destination_mismatched_follower():
    a = {"platoon_a_truck0": "dest_a", "platoon_a_truck1": "dest_b", "platoon_a_truck2": "dest_a"}
    b = {"platoon_b_truck0": "dest_b", "platoon_b_truck1": "dest_b"}
    assert guard._chat_candidate(a, b) == ["platoon_a_truck1"]


def test_chat_candidate_never_selects_leader_truck0():
    a = {"platoon_a_truck0": "dest_b", "platoon_a_truck1": "dest_a", "platoon_a_truck2": "dest_a"}
    b = {"platoon_b_truck0": "dest_b"}
    assert guard._chat_candidate(a, b) == []


def test_inbound_without_own_mention_is_blocked():
    code, out = run_guard("inbound", "--agent", "platoon_a", "--message", "목적지 공유해줘")
    assert code == 1 and out["allow_response"] is False


def test_inbound_ack_loop_is_blocked():
    code, out = run_guard("inbound", "--agent", "platoon_a", "--message", f"{A_MENTION} 확인")
    assert code == 1 and "confirmation-only" in out["reason"]


def test_inbound_actionable_mention_is_allowed():
    code, out = run_guard("inbound", "--agent", "platoon_a", "--message", f"{A_MENTION} 합류 가능성 확인해줘")
    assert code == 0 and out["allow_response"] is True


def test_validate_request_rejects_vehicle_not_in_chat_candidates():
    code, out = run_guard(
        "validate-request",
        "--a-list", "platoon_a_truck0: dest_a\nplatoon_a_truck1: dest_b\nplatoon_a_truck2: dest_a",
        "--b-list", "platoon_b_truck0: dest_b",
        "--vehicle-id", "platoon_a_truck2",
    )
    assert code == 2 and out["valid"] is False


def test_validate_request_accepts_destination_compatible_vehicle():
    code, out = run_guard(
        "validate-request",
        "--a-list", "platoon_a_truck0: dest_a\nplatoon_a_truck1: dest_b\nplatoon_a_truck2: dest_a",
        "--b-list", "platoon_b_truck0: dest_b",
        "--vehicle-id", "platoon_a_truck1",
    )
    assert code == 0 and out["valid"] is True
