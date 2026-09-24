"""Run every CPU test suite separately; no Docker builds, pulls, models, or GPU."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_commands(root, python):
    return [(root / part if part else root, [python, '-m', 'pytest', '-q', 'tests'])
            for part in ('', 'dispatcher', 'gateway', 'mcp')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--log-dir', type=Path)
    args = parser.parse_args()
    if args.log_dir:
        args.log_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for cwd, command in test_commands(ROOT, args.python):
        name = 'reproducibility' if cwd == ROOT else cwd.name
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=300)
        output = result.stdout + result.stderr
        if args.log_dir:
            (args.log_dir / f'{name}.log').write_text(output)
        print(f'=== {name}: exit {result.returncode} ===\n' + '\n'.join(output.splitlines()[-5:]), flush=True)
        results.append({'suite': name, 'exit_code': result.returncode})
    report = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'scope': 'CPU-only',
              'python': args.python, 'production_images_tested': False, 'suites': results}
    if args.log_dir:
        (args.log_dir / 'cpu-checks.json').write_text(json.dumps(report, indent=2) + '\n')
    raise SystemExit(1 if any(r['exit_code'] for r in results) else 0)


if __name__ == '__main__':
    main()
