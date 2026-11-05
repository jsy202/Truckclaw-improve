"""Audit the batch, retaining original environment errors and separate reruns."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

from run_batch import audit_result, summarize


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('--rerun-errors', action='store_true')
    args = parser.parse_args()
    original = json.loads((args.root / 'summary.json').read_text())
    rows = [dict(row) for row in original['runs']]
    errors = [dict(row) for row in rows if row['status'] == 'error']
    reruns = []
    env = dict(os.environ)
    env['PYTHONPATH'] = '/home/jsy202/carla-0.9.13/PythonAPI/carla/dist/carla-0.9.13-py3.7-linux-x86_64.egg'
    if args.rerun_errors:
        for row in rows:
            if row['status'] != 'error':
                continue
            case = row['case']
            root = args.root / 'reruns' / case / ('run%03d' % row['run'])
            root.mkdir(parents=True, exist_ok=False)
            started = time.monotonic()
            with (root / 'runner.log').open('w') as log:
                completed = subprocess.run(['python3.7', '-u', str(Path(__file__).with_name('run_carla.py')),
                    '--case', case, '--output', str(root)], env=env,
                    stdout=log, stderr=subprocess.STDOUT, timeout=330)
            record = {'case': case, 'run': row['run'], 'exit_code': completed.returncode,
                      'artifact_dir': str(root.relative_to(args.root)),
                      'wall_seconds': round(time.monotonic() - started, 2)}
            if completed.returncode == 0:
                audited = audit_result(root, case)
                row.update(audited)
                row.update(status='ok', artifact_dir=record['artifact_dir'],
                           original_error=row.pop('error'), rerun=True)
                record.update(audited)
            reruns.append(record)
            (args.root / 'reruns.json').write_text(json.dumps(reruns, indent=2))
            print(json.dumps(record), flush=True)
    for row in rows:
        if row['status'] == 'ok':
            audited = audit_result(args.root / row['artifact_dir'], row['case'])
            assert audited['passed'], row
            row.update(audited)
    result = {'summary': summarize(rows, 20), 'runs': rows,
              'original_environment_errors': errors, 'reruns': reruns,
              'total_attempts': len(original['runs']) + len(reruns)}
    (args.root / 'verified_summary.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result['summary'], indent=2), flush=True)
    assert all(item['all_expected'] for item in result['summary'].values())


if __name__ == '__main__':
    main()
