#!/usr/bin/env python3
"""Make Google Benchmark SkipWithError failures visible to CTest."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    if len(sys.argv) != 2:
        print('usage: check_correctness.py BENCHMARK_EXECUTABLE', file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix='retguard-correctness-') as directory:
        output = Path(directory) / 'results.json'
        try:
            result = subprocess.run([sys.argv[1], '--benchmark_min_time=0.001s',
                                     f'--benchmark_out={output}', '--benchmark_out_format=json'],
                                    timeout=60, capture_output=True, text=True)
            if result.returncode:
                print(result.stdout + result.stderr, file=sys.stderr)
                return 1
            data = json.loads(output.read_text())
            rows = data.get('benchmarks', [])
            if not rows:
                print('No benchmark correctness cases ran', file=sys.stderr)
                return 1
            errors = [f"{row['name']}: {row.get('error_message', 'unknown error')}"
                      for row in rows if row.get('error_occurred')]
            if errors:
                print('\n'.join(errors), file=sys.stderr)
                return 1
            print(f'{len(rows)} benchmark correctness cases passed')
            return 0
        except (subprocess.TimeoutExpired, OSError, ValueError) as error:
            print(str(error), file=sys.stderr)
            return 1


if __name__ == '__main__':
    sys.exit(main())
