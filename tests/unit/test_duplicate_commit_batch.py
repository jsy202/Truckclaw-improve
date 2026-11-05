import importlib.util
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'experiments/duplicate_commit/run_batch.py'
spec = importlib.util.spec_from_file_location('duplicate_batch', PATH)
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def test_summary_separates_errors_from_collision_free_runs():
    rows = [dict(case='fixed', status='ok', collision_events=0, passed=True),
            dict(case='fixed', status='error', passed=False)]
    result = batch.summarize(rows, 2)['fixed']
    assert result['completed'] == 1
    assert result['collision_free_runs'] == 1
    assert result['errors'] == 1
    assert result['all_expected'] is False


def test_summary_requires_every_requested_run():
    rows = [dict(case='vulnerable', status='ok', collision_events=1, passed=True)]
    result = batch.summarize(rows, 20)['vulnerable']
    assert result['collision_runs'] == 1
    assert result['all_expected'] is False
