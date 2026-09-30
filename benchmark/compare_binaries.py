#!/usr/bin/env python3
"""Alternate two built benchmark executables to assess a performance change."""
import argparse
import json
import os
from pathlib import Path
import sys

from run_suite import command, compare, inspect_binary, read_samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    parser.add_argument('--filter', default='.*')
    parser.add_argument('--repetitions', type=int, default=7)
    parser.add_argument('--min-time', type=float, default=.2)
    parser.add_argument('--cpu', type=int, default=min(os.sched_getaffinity(0)))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.repetitions < 1 or args.min_time <= 0:
        parser.error('repetitions and min-time must be positive')
    if args.cpu not in os.sched_getaffinity(0):
        parser.error('CPU is outside allowed affinity')
    args.output.mkdir(parents=True, exist_ok=True)
    values = {'before': {}, 'after': {}}
    report = {'cpu': args.cpu, 'filter': args.filter, 'runs': [], 'binaries': {}}
    failed = False
    for name in values:
        path = getattr(args, name).resolve()
        report['binaries'][name] = {'path': str(path), **inspect_binary(path)}
    for repetition in range(args.repetitions):
        order = ('before', 'after') if repetition % 2 == 0 else ('after', 'before')
        for name in order:
            output = args.output / f'{name}.{repetition}.json'
            output.unlink(missing_ok=True)
            result = command([str(getattr(args, name).resolve()),
                              f'--benchmark_filter={args.filter}',
                              f'--benchmark_min_time={args.min_time}s',
                              f'--benchmark_out={output}', '--benchmark_out_format=json'],
                             args.output / f'{name}.{repetition}.log', 120, args.cpu)
            result.update(variant=name, repetition=repetition)
            report['runs'].append(result)
            if result['returncode'] != 0:
                failed = True
                continue
            try:
                samples, errors, context = read_samples(output)
                result.update(errors=errors, context=context)
                if not samples or errors:
                    result['error'] = 'missing timing samples or benchmark correctness error'
                    failed = True
                for workload, value in samples.items():
                    values[name].setdefault(workload, []).append(value)
            except (OSError, ValueError, KeyError) as error:
                result['error'] = str(error)
                failed = True
    report['comparisons'] = []
    for row in compare(values['before'], values['after'], 0):
        for old, new in (('plain_ns', 'before_ns'), ('auto_ns', 'after_ns'),
                         ('plain_samples', 'before_samples'), ('auto_samples', 'after_samples'),
                         ('overhead_percent', 'change_percent')):
            if old in row:
                row[new] = row.pop(old)
        row.pop('status', None)
        row['complete'] = row.get('before_samples') == args.repetitions and row.get('after_samples') == args.repetitions
        failed |= not row['complete']
        report['comparisons'].append(row)
    report['functional_failures'] = failed
    (args.output / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    for row in report['comparisons']:
        print(row)
    print(f'Results: {args.output / "comparison.json"}')
    return int(failed)


if __name__ == '__main__':
    sys.exit(main())
