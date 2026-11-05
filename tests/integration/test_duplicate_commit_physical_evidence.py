"""Check actual CARLA artifacts when an evidence directory is supplied."""
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def physical_results():
    path = os.environ.get('DUPLICATE_COMMIT_EVIDENCE')
    if not path:
        pytest.skip('Set DUPLICATE_COMMIT_EVIDENCE after running the offscreen CARLA experiment')
    root = Path(path)
    return root, json.loads((root / 'comparison.json').read_text())


def test_fault_caused_real_truck_collision(physical_results):
    root, (before, after) = physical_results
    assert before['commit_requests'] == after['commit_requests'] == 2
    assert before['physical_starts'] == 2
    assert before['truck_collision_events'] > 0
    assert any(event['other_actor_type'].startswith('vehicle.') and event['impulse'] > 0
               for event in before['collision_events'])
    commits = [event for event in before['events'] if event['event'] == 'commit']
    stop = next(event for event in before['events'] if event['event'] == 'emergency_stop')
    assert commits[0]['frame'] < stop['frame'] < commits[1]['frame']
    assert all(event['frame'] > commits[1]['frame'] for event in before['collision_events'])
    assert (root / 'vulnerable/collision.png').is_file()


def test_duplicate_did_not_release_brake_after_fix(physical_results):
    root, (before, after) = physical_results
    assert after['physical_starts'] == 1
    assert after['truck_collision_events'] == 0
    assert after['final_speed_mps'] < 0.2
    telemetry = json.loads((root / 'fixed/telemetry.json').read_text())
    assert all(row['brake'] == 1.0 and row['throttle'] == 0.0
               for row in telemetry if row['phase'] == 'after_duplicate')
    assert [event['request_id'] for event in before['events'] if event['event'] == 'commit'] == [
        event['request_id'] for event in after['events'] if event['event'] == 'commit']
