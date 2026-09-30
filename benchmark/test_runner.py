#!/usr/bin/env python3
"""Regression checks for failure reporting and paired timing comparisons."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from run_suite import compare, read_samples


class ReportingTests(unittest.TestCase):
    def test_errors_are_not_timing_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.json'
            path.write_text(json.dumps({'benchmarks': [
                {'name': 'valid', 'cpu_time': 2, 'time_unit': 'us'},
                {'name': 'bad', 'cpu_time': 0, 'time_unit': 'ns',
                 'error_occurred': True, 'error_message': 'wrong pixels'},
                {'name': 'valid_median', 'run_type': 'aggregate',
                 'cpu_time': 9, 'time_unit': 'us'}]}))
            samples, errors, _ = read_samples(path)
            self.assertEqual(samples, {'valid': 2000})
            self.assertEqual(errors, [{'name': 'bad', 'error': 'wrong pixels'}])

    def test_missing_noisy_and_regression(self):
        rows = {r['name']: r for r in compare(
            {'slow': [100, 100, 100], 'noisy': [50, 100, 150], 'missing': [1]},
            {'slow': [150, 150, 150], 'noisy': [100, 100, 100]}, 20)}
        self.assertEqual(rows['slow']['status'], 'regression')
        self.assertEqual(rows['slow']['overhead_percent'], 50)
        self.assertEqual(rows['noisy']['status'], 'noisy')
        self.assertEqual(rows['missing']['status'], 'missing_samples')

    def test_google_benchmark_zero_exit_error_fails_correctness(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / 'fake_benchmark'
            binary.write_text('#!' + sys.executable + '\n'
                              'import json, pathlib, sys\n'
                              'out = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--benchmark_out="))\n'
                              'pathlib.Path(out).write_text(json.dumps({"benchmarks": [{"name": "broken", '
                              '"error_occurred": True, "error_message": "wrong output"}]}))\n')
            binary.chmod(0o755)
            result = subprocess.run([sys.executable, str(Path(__file__).with_name('check_correctness.py')),
                                     str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn('wrong output', result.stderr)


if __name__ == '__main__':
    unittest.main()
