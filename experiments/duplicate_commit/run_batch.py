"""Run and audit repeated offscreen CARLA cases."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time


def summarize(rows, requested):
    summary = {}
    for case in ('vulnerable', 'fixed'):
        selected = [row for row in rows if row['case'] == case]
        completed = [row for row in selected if row['status'] == 'ok']
        summary[case] = {
            'requested': requested, 'attempted': len(selected), 'completed': len(completed),
            'errors': len(selected) - len(completed),
            'collision_runs': sum(row['collision_events'] > 0 for row in completed),
            'collision_free_runs': sum(row['collision_events'] == 0 for row in completed),
            'expected_passes': sum(row['passed'] for row in selected),
            'all_expected': len(selected) == requested and all(row['passed'] for row in selected)}
    return summary


def audit_result(root, case):
    result = json.loads((root / case / 'result.json').read_text())
    telemetry = json.loads((root / case / 'telemetry.json').read_text())
    commits = [event for event in result['events'] if event['event'] == 'commit']
    assert len(commits) == 2 and commits[0]['request_id'] == commits[1]['request_id']
    assert result['commit_requests'] == 2
    assert all(event['frame'] > commits[1]['frame'] for event in result['collision_events'])
    after = [row for row in telemetry if row['phase'] == 'after_duplicate']
    assert after
    if case == 'vulnerable':
        passed = result['physical_starts'] == 2 and result['truck_collision_events'] > 0
        if result['truck_collision_events']:
            assert (root / case / 'collision.png').is_file()
    else:
        passed = (result['physical_starts'] == 1 and not result['collision_events']
                  and len(after) == 600 and result['final_speed_mps'] < 0.2
                  and all(row['brake'] == 1 and row['throttle'] == 0 for row in after))
    return {'collision_events': result['truck_collision_events'],
            'physical_starts': result['physical_starts'], 'passed': passed,
            'final_speed_mps': result['final_speed_mps'],
            'final_distance_m': result['final_distance_m']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs', type=int, default=20)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.runs < 1:
        parser.error('--runs must be positive')
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    here = Path(__file__).resolve().parent
    env = dict(os.environ)
    env['PYTHONPATH'] = '/home/jsy202/carla-0.9.13/PythonAPI/carla/dist/carla-0.9.13-py3.7-linux-x86_64.egg'
    manifest = {'started_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'runs_per_case': args.runs, 'prior_observation':
                '사용자가 직접 수행한 사전 테스트 20회 중 에이전트 중복 호출이 1회 발생하여 이번 검증을 제안함.',
                'batch_input': 'Identical HTTP request sent twice in every case; no live LLM calls.',
                'rendering': 'RenderOffScreen', 'server_isolation': 'fresh server for each case'}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
    for case in ('vulnerable', 'fixed'):
        for number in range(1, args.runs + 1):
            root = args.output / case / ('run%03d' % number)
            root.mkdir(parents=True)
            row = {'case': case, 'run': number, 'status': 'error', 'passed': False,
                   'artifact_dir': str(root.relative_to(args.output))}
            started = time.monotonic()
            try:
                with socket.socket() as probe:
                    if probe.connect_ex(('127.0.0.1', 2000)) == 0:
                        raise RuntimeError('CARLA port occupied before case')
                with (root / 'runner.log').open('w') as log:
                    process = subprocess.Popen(['python3.7', '-u', str(here / 'run_carla.py'),
                        '--case', case, '--output', str(root)], env=env,
                        stdout=log, stderr=subprocess.STDOUT)
                    try:
                        code = process.wait(timeout=240)
                    except subprocess.TimeoutExpired:
                        process.send_signal(signal.SIGINT)
                        process.wait(timeout=90)
                        raise RuntimeError('case exceeded 240 seconds')
                if code:
                    raise RuntimeError('runner exited %s; see runner.log' % code)
                row.update(audit_result(root, case))
                row['status'] = 'ok'
            except Exception as error:
                row['error'] = str(error)
            row['wall_seconds'] = round(time.monotonic() - started, 2)
            rows.append(row)
            with (args.output / 'runs.jsonl').open('a') as ledger:
                ledger.write(json.dumps(row) + '\n')
            report = {'summary': summarize(rows, args.runs), 'runs': rows}
            temporary = args.output / 'summary.tmp'
            temporary.write_text(json.dumps(report, indent=2))
            temporary.replace(args.output / 'summary.json')
            print(json.dumps(row), flush=True)
    return 0 if all(item['all_expected'] for item in summarize(rows, args.runs).values()) else 1


if __name__ == '__main__':
    sys.exit(main())
