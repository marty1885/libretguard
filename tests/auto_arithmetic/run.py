#!/usr/bin/env python3
"""Check actual automatic hooks against independent arithmetic and SysV ABI cases."""
import argparse
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent


def command(args):
    result = subprocess.run(list(map(str, args)), text=True, capture_output=True)
    if result.returncode:
        raise AssertionError(f"command failed ({result.returncode}): {args}\n{result.stdout}{result.stderr}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--build-dir", type=Path, required=True)
    args = parser.parse_args()
    cc = shutil.which(args.cc)
    if not cc:
        raise AssertionError(f"compiler unavailable: {args.cc}")
    clang = "clang" in command([cc, "--version"]).lower()
    linker = "lld" if shutil.which("ld.lld") else "gold" if shutil.which("ld.gold") else None
    if linker is None:
        raise AssertionError("automatic tests require ld.lld or ld.gold for GAS unwind expressions")
    directory = args.build_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    for opt in ("O2", "O3"):
        common = [f"-{opt}", "-g", "-Wall", "-Wextra", "-Werror", "-fPIE",
                  "-fno-omit-frame-pointer", "-fno-optimize-sibling-calls", "-fstack-protector-strong"]
        runtime = directory / f"runtime_{opt}.o"
        thunks = directory / f"thunks_{opt}.o"
        bridge = directory / f"bridge_{opt}.o"
        driver = directory / f"driver_{opt}.o"
        targets = directory / f"targets_{opt}.o"
        command([cc, *common, "-I", ROOT / "src", "-c", ROOT / "src/retguard.c", "-o", runtime])
        command([cc, "-c", ROOT / "src/retguard_thunks.S", "-o", thunks])
        command([cc, "-c", FIXTURES / "bridge.S", "-o", bridge])
        command([cc, *common, "-c", FIXTURES / "driver.c", "-o", driver])
        auto = ["-pg", "-mfentry", "-mfunction-return=thunk-extern", "-fasynchronous-unwind-tables"]
        if clang:
            auto += ["-mllvm", "-force-attribute=fn_ret_thunk_extern", "-fno-addrsig"]
        else:
            auto += ["-mfentry-name=__retguard_fentry"]
        command([sys.executable, ROOT / "tools/retguard_asm_compiler.py", cc,
                 *common, *auto, "-c", FIXTURES / "targets.c", "-o", targets])
        executable = directory / f"auto_arithmetic_{opt}"
        command([cc, "-fPIE", "-pie", f"-fuse-ld={linker}", driver, targets, bridge, runtime, thunks,
                 "-o", executable])
        print(f"{Path(cc).name} {opt}: {command([executable]).strip()}")
        result = subprocess.run([str(executable), "bad-tag"], capture_output=True)
        if result.returncode != -signal.SIGILL:
            raise AssertionError(f"corrupt tag did not trap with SIGILL: {result.returncode}\n{result.stderr!r}")
        print(f"{Path(cc).name} {opt}: corrupted tag rejected with SIGILL")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, OSError) as error:
        print(error, file=sys.stderr)
        sys.exit(1)
