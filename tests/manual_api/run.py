#!/usr/bin/env python3
"""Run manual API cases in separate processes so fatal checks cannot hide one another."""

import argparse
import os
import resource
import signal
import subprocess


def check(binary, mode, expected, environment):
    result = subprocess.run([binary, mode], capture_output=True, text=True,
                            env=environment)
    if result.returncode != expected:
        raise SystemExit(
            f"FAIL {mode}: expected exit {expected}, got {result.returncode}\n"
            f"{result.stdout}{result.stderr}"
        )
    print(f"PASS {mode}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("binary")
    parser.add_argument("--require-cet", action="store_true")
    options = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    environment = os.environ.copy()
    if options.require_cet:
        environment["RETGUARD_REQUIRE_CET"] = "1"

    check(options.binary, "normal", 0, environment)
    check(options.binary, "bad_return", -signal.SIGABRT, environment)
    if options.require_cet:
        check(options.binary, "cet_bad_return", -signal.SIGSEGV, environment)


if __name__ == "__main__":
    main()
