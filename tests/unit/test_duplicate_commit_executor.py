"""Regression contract for the isolated actuator restart experiment."""
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PATH = Path(__file__).resolve().parents[2] / 'experiments/duplicate_commit/executor.py'
spec = importlib.util.spec_from_file_location('duplicate_executor', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_duplicate_preserves_emergency_brake():
    executor = module.TransferExecutor()
    executor.commit('transfer-1')
    executor.emergency_stop()
    executor.commit('transfer-1')
    assert executor.control() == (0.0, 1.0)
    assert executor.starts == 1


def test_concurrent_duplicates_start_once():
    executor = module.TransferExecutor()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(executor.commit, ['transfer-1'] * 32))
    assert executor.starts == 1


def test_different_request_is_not_a_duplicate():
    executor = module.TransferExecutor()
    executor.commit('transfer-1')
    executor.commit('transfer-2')
    assert executor.starts == 2


def test_injected_fault_resets_brake():
    executor = module.TransferExecutor(deduplicate=False)
    executor.commit('transfer-1')
    executor.emergency_stop()
    executor.commit('transfer-1')
    assert executor.control() == (1.0, 0.0)
    assert executor.starts == 2
