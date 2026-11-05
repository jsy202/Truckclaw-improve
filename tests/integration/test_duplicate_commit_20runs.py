"""Independently check all forty real-CARLA artifacts after the batch."""
import json
import os
from pathlib import Path

import pytest


@pytest.mark.parametrize('case', ['vulnerable', 'fixed'])
def test_twenty_physical_runs(case):
    value = os.environ.get('DUPLICATE_COMMIT_BATCH_EVIDENCE')
    if not value:
        pytest.skip('Set DUPLICATE_COMMIT_BATCH_EVIDENCE to the completed forty-case batch')
    root = Path(value)
    summary = root / 'verified_summary.json'
    if not summary.exists():
        summary = root / 'summary.json'
    report = json.loads(summary.read_text())
    rows = [row for row in report['runs'] if row['case'] == case]
    assert len(rows) == 20
    assert sorted(row['run'] for row in rows) == list(range(1, 21))
    for row in rows:
        assert row['status'] == 'ok', row
        folder = root / row['artifact_dir'] / case
        result = json.loads((folder / 'result.json').read_text())
        samples = json.loads((folder / 'telemetry.json').read_text())
        commits = [event for event in result['events'] if event['event'] == 'commit']
        assert len(commits) == 2
        assert commits[0]['request_id'] == commits[1]['request_id']
        assert all(event['frame'] > commits[1]['frame'] for event in result['collision_events'])
        if case == 'vulnerable':
            assert result['physical_starts'] == 2
            assert result['truck_collision_events'] > 0
            assert (folder / 'collision.png').is_file()
        else:
            assert result['physical_starts'] == 1
            assert result['collision_events'] == []
            after = [sample for sample in samples if sample['phase'] == 'after_duplicate']
            assert len(after) == 600
            assert all(sample['brake'] == 1 and sample['throttle'] == 0 for sample in after)
            assert result['final_speed_mps'] < 0.2
