#!/usr/bin/env python3
"""Build and compare matched RETGUARD header-library benchmarks.

Every build and execution is isolated and retained, including unsuccessful ones.
Timing comparisons use alternating plain/auto process order and CPU time.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
LIBRARIES = ('stb', 'qoi', 'json', 'spdlog', 'jsmn', 'sprintf')


def command(args, log, timeout, cpu=None):
    started = time.monotonic()
    def pin():
        os.sched_setaffinity(0, {cpu})
    record = {'command': [str(x) for x in args], 'log': str(log)}
    try:
        with log.open('w') as stream:
            process = subprocess.Popen(args, stdout=stream, stderr=subprocess.STDOUT,
                                       start_new_session=True,
                                       preexec_fn=pin if cpu is not None else None)
            try:
                record['returncode'] = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                # Kill compiler/benchmark descendants too, so they cannot leak
                # into subsequent timing runs after their parent times out.
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
                record.update(returncode=None, error='timeout')
    except KeyboardInterrupt:
        if 'process' in locals() and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        raise
    except OSError as error:
        record.update(returncode=None, error=str(error))
    record['seconds'] = time.monotonic() - started
    return record



def inspect_binary(binary):
    """Static size/call-site evidence; not dynamic call counts or attribution."""
    evidence = {'file_bytes': binary.stat().st_size}
    for tool, args in [('size', ['size', '-A', str(binary)]),
                       ('objdump', ['objdump', '-d', str(binary)])]:
        if not shutil.which(tool):
            continue
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode:
            continue
        if tool == 'size':
            evidence['sections'] = {}
            for line in result.stdout.splitlines():
                fields = line.split()
                if len(fields) == 3 and fields[0].startswith('.'):
                    evidence['sections'][fields[0]] = int(fields[1])
        else:
            evidence['entry_hook_call_sites'] = sum(
                'call' in line and '<__retguard_fentry>' in line
                for line in result.stdout.splitlines())
    return evidence


def read_samples(path):
    document = json.loads(path.read_text())
    samples, errors = {}, []
    factors = {'ns': 1, 'us': 1000, 'ms': 1000000, 's': 1000000000}
    for row in document.get('benchmarks', []):
        if row.get('error_occurred'):
            errors.append({'name': row.get('name'), 'error': row.get('error_message')})
        elif row.get('run_type', 'iteration') == 'iteration':
            name = row.get('run_name', row['name'])
            value = row.get('cpu_time')
            if isinstance(value, (int, float)) and math.isfinite(value) and value > 0 and row.get('time_unit') in factors:
                samples[name] = value * factors[row['time_unit']]
            else:
                errors.append({'name': name, 'error': 'invalid CPU-time sample'})
    return samples, errors, document.get('context', {})


def compare(plain, auto, threshold):
    rows = []
    for name in sorted(set(plain) | set(auto)):
        p, a = plain.get(name, []), auto.get(name, [])
        if not p or not a:
            rows.append({'name': name, 'status': 'missing_samples',
                         'plain_samples': len(p), 'auto_samples': len(a)})
            continue
        pm, am = statistics.median(p), statistics.median(a)
        noise = max((statistics.stdev(v) / statistics.mean(v)
                     if len(v) > 1 and statistics.mean(v) else 0) for v in (p, a))
        overhead = (am / pm - 1) * 100
        rows.append({'name': name, 'plain_ns': pm, 'auto_ns': am,
                     'added_ns': am - pm, 'overhead_percent': overhead,
                     'plain_samples': len(p), 'auto_samples': len(a),
                     'max_cv_percent': noise * 100,
                     'status': 'noisy' if noise > .10 else
                               'regression' if overhead > threshold else 'ok'})
    return rows



def package_metadata(build):
    packages = {}
    cache = (build / 'CMakeCache.txt').read_text()
    for name in ('nlohmann_json', 'spdlog', 'fmt', 'benchmark'):
        match = re.search(r'^' + name + r'_DIR:PATH=(.+)$', cache, re.MULTILINE)
        if not match or not Path(match[1]).is_dir():
            continue
        directory = Path(match[1])
        item = {'cmake_directory': str(directory), 'config_hashes': {}}
        for path in sorted(directory.glob('*.cmake')):
            content = path.read_bytes()
            item['config_hashes'][path.name] = hashlib.sha256(content).hexdigest()
            version = re.search(rb'set\(PACKAGE_VERSION\s+"?([0-9][0-9.]+)', content)
            if version:
                item['version'] = version[1].decode('ascii')
        packages[name] = item
    return packages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compilers', nargs='+', choices=['gcc', 'clang'], default=['gcc', 'clang'])
    parser.add_argument('--optimizations', nargs='+', choices=['O2', 'O3'], default=['O2'])
    parser.add_argument('--libraries', nargs='+', choices=LIBRARIES, default=list(LIBRARIES))
    parser.add_argument('--profiles', nargs='+', choices=['default', 'inline'], default=['default', 'inline'])
    parser.add_argument('--inline-limit', type=int, default=200,
                        help='Inline profile setting for both compilers (default: 200)')
    parser.add_argument('--output', type=Path, default=ROOT / 'build' / 'suite')
    parser.add_argument('--repetitions', type=int, default=5)
    parser.add_argument('--min-time', type=float, default=.1, help='Seconds per benchmark per repetition')
    parser.add_argument('--timeout', type=float, default=180, help='Timeout per build or benchmark process')
    parser.add_argument('--jobs', type=int, default=2)
    parser.add_argument('--cpu', type=int, default=None, help='Default: first CPU allowed by affinity')
    parser.add_argument('--filter', default='.*', help='Google Benchmark regex')
    parser.add_argument('--regression-percent', type=float, default=20)
    parser.add_argument('--fail-on-regression', action='store_true')
    args = parser.parse_args()
    if args.repetitions < 1 or args.min_time <= 0 or args.timeout <= 0 or args.jobs < 1:
        parser.error('repetitions, min-time, timeout, and jobs must be positive')
    if args.inline_limit is not None and args.inline_limit < 1:
        parser.error('inline-limit must be positive')
    allowed = sorted(os.sched_getaffinity(0))
    cpu = allowed[0] if args.cpu is None else args.cpu
    if cpu not in allowed:
        parser.error(f'CPU {cpu} is outside allowed affinity {allowed}')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {'started_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'platform': platform.platform(), 'cpu': cpu, 'allowed_cpus': allowed,
              'settings': {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
              'dependencies': {}, 'source_hashes': {}, 'configurations': []}
    for source in [ROOT / 'CMakeLists.txt'] + sorted((ROOT / 'benchmark').glob('*.*')) + sorted((ROOT / 'src').glob('*')) + sorted((ROOT / 'tools').glob('*.py')):
        if source.is_file():
            report['source_hashes'][str(source.relative_to(ROOT))] = hashlib.sha256(source.read_bytes()).hexdigest()
    for header in list((ROOT / 'third_party').glob('*/*.h')) + list((ROOT / 'benchmark' / 'data').glob('*')):
        report['dependencies'][str(header.relative_to(ROOT))] = hashlib.sha256(header.read_bytes()).hexdigest()
    cpuinfo = Path('/proc/cpuinfo').read_text()
    report['cpu_model'] = next((line.split(':', 1)[1].strip() for line in cpuinfo.splitlines()
                                if line.startswith('model name')), 'unknown')
    failures = False
    regressions = False
    for compiler in args.compilers:
        for optimization in args.optimizations:
            directory = output / f'{compiler}-{optimization}'
            directory.mkdir(exist_ok=True)
            config = {'compiler': compiler, 'optimization': optimization, 'builds': [],
                      'runs': [], 'comparisons': [], 'skipped': []}
            report['configurations'].append(config)
            cc, cxx = compiler, 'g++' if compiler == 'gcc' else 'clang++'
            if not shutil.which(cc) or not shutil.which(cxx):
                config['error'] = 'compiler unavailable'
                failures = True
                continue
            config['compiler_version'] = subprocess.check_output([cc, '--version'], text=True).splitlines()[0]
            build = directory / 'build'
            inline_limit = args.inline_limit
            config['inline_limit'] = inline_limit
            configure = command(['cmake', '-S', str(ROOT), '-B', str(build), '-G', 'Ninja',
                                 '-DRETGUARD_BUILD_BENCHMARKS=ON', '-DBUILD_TESTING=OFF',
                                 f'-DRETGUARD_BENCH_OPTIMIZATION={optimization}',
                                 f'-DRETGUARD_BENCH_INLINE_LIMIT={inline_limit}',
                                 f'-DCMAKE_C_COMPILER={shutil.which(cc)}',
                                 f'-DCMAKE_CXX_COMPILER={shutil.which(cxx)}',
                                 '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON'],
                                directory / 'configure.log', args.timeout)
            config['configure'] = configure
            if configure['returncode'] != 0:
                failures = True
                continue
            config['packages'] = package_metadata(build)
            targets = subprocess.check_output(['ninja', '-C', str(build), '-t', 'targets', 'all'], text=True)
            for library in args.libraries:
                for profile in args.profiles:
                    prefix = 'inline_' if profile == 'inline' else ''
                    names = {mode: f'retguard_bench_{library}_{prefix}{mode}' for mode in ('plain', 'auto')}
                    available = True
                    for mode, target in names.items():
                        if target + ':' not in targets:
                            config['skipped'].append({'target': target, 'reason': 'optional dependency/target unavailable'})
                            available = False
                            continue
                        result = command(['cmake', '--build', str(build), '--target', target,
                                          '--parallel', str(args.jobs)], directory / f'{target}.build.log', args.timeout)
                        result['target'] = target
                        binary = build / target
                        if result['returncode'] == 0 and binary.exists():
                            result['binary'] = inspect_binary(binary)
                        else:
                            available = False
                            failures = True
                        config['builds'].append(result)
                    if not available:
                        continue
                    values = {'plain': {}, 'auto': {}}
                    for repetition in range(args.repetitions):
                        # Alternate order to reduce systematic first/second process bias.
                        order = ('plain', 'auto') if repetition % 2 == 0 else ('auto', 'plain')
                        for mode in order:
                            target = names[mode]
                            raw = directory / f'{target}.{repetition}.json'
                            raw.unlink(missing_ok=True)
                            result = command([str(build / target), f'--benchmark_min_time={args.min_time}s',
                                              f'--benchmark_filter={args.filter}',
                                              f'--benchmark_out={raw}', '--benchmark_out_format=json'],
                                             directory / f'{target}.{repetition}.log', args.timeout, cpu)
                            result.update(target=target, repetition=repetition, raw_json=str(raw))
                            config['runs'].append(result)
                            if result['returncode'] != 0:
                                failures = True
                                continue
                            try:
                                samples, errors, context = read_samples(raw)
                                result['errors'] = errors
                                result['context'] = context
                                if not samples:
                                    errors.append({'name': args.filter, 'error': 'no matching benchmark timing samples'})
                                if errors:
                                    failures = True
                                for name, value in samples.items():
                                    values[mode].setdefault(name, []).append(value)
                            except (OSError, ValueError, KeyError) as error:
                                result['error'] = str(error)
                                failures = True
                    rows = compare(values['plain'], values['auto'], args.regression_percent)
                    for row in rows:
                        row.update(library=library, profile=profile,
                                   inline_limit=inline_limit if profile == 'inline' else None)
                        if row.get('plain_samples', 0) != args.repetitions or row.get('auto_samples', 0) != args.repetitions:
                            row['status'] = 'incomplete'
                            failures = True
                        regressions |= row['status'] == 'regression'
                        config['comparisons'].append(row)
            # Checkpoint so interrupted matrices retain completed configurations.
            (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    report['completed_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    tracked = {**report['source_hashes'], **report['dependencies']}
    changed_sources = [name for name, digest in tracked.items()
                       if not (ROOT / name).is_file() or
                       hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest]
    report['changed_sources_during_run'] = changed_sources
    failures |= bool(changed_sources)
    report['functional_failures'] = failures
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    lines = ['# RETGUARD library benchmark report', '',
             f"CPU: {report['cpu_model']}; pinned CPU {cpu}. Medians of {args.repetitions} CPU-time samples.", '',
             '| Compiler | Opt | Library/profile | Workload | Plain ns | Auto ns | Overhead % | CV % | Status |',
             '| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |']
    for config in report['configurations']:
        for row in config['comparisons']:
            numbers = [f"{row[key]:.2f}" if key in row else '—'
                       for key in ('plain_ns', 'auto_ns', 'overhead_percent', 'max_cv_percent')]
            lines.append(f"| {config['compiler']} | {config['optimization']} | {row['library']}/{row['profile']}"
                         f"{('(' + str(row['inline_limit']) + ')') if row.get('inline_limit') else ''} | "
                         f"{row['name']} | {' | '.join(numbers)} | {row['status']} |")
    lines += ['', 'Timing flags are screening signals, not proof of a cause. CV above 10% is marked noisy.',
              'Static hook call sites and ELF section sizes are recorded per binary in report.json.', '',
              '## Failures and skips', '']
    if changed_sources:
        lines.append(f'- Sources changed during measurement; rerun required: {changed_sources}')
    for config in report['configurations']:
        label = f"{config['compiler']}/{config['optimization']}"
        if config.get('error'):
            lines.append(f"- {label}: {config['error']}")
        for item in [config.get('configure', {})] + config['builds'] + config['runs']:
            if item and (item.get('returncode') != 0 or item.get('errors') or item.get('error')):
                lines.append(f"- {label}: {item.get('target', 'configure')}: returncode={item.get('returncode')}; "
                             f"{item.get('errors') or item.get('error', '')}; log: {item['log']}")
        for skip in config['skipped']:
            lines.append(f"- {label}: skipped {skip}")
    (output / 'report.md').write_text('\n'.join(lines) + '\n')
    print(f"Report: {output / 'report.md'}")
    print(f"Raw results: {output / 'report.json'}")
    return 1 if failures or (args.fail_on_regression and regressions) else 0


if __name__ == '__main__':
    sys.exit(main())
