# Final overhead result

The non-compiler-pass approach works on tested cases, but does not provide consistently low overhead. This investigation is closed: do not repeat flag sweeps or add assembly-rewriting optimizers to try to make it production-ready. Further work should start with an explicitly approved GCC/Clang compiler pass, where control flow, register liveness, ABI details, and unwind state are available. A compiler pass is a prerequisite for that direction, not a guarantee of success.

Measurements: AMD Ryzen 9 7950X3D, GCC 16.2.1 / Clang 22.1.8, pinned CPU, medians of five alternating process samples of at least 0.1 seconds. All table values below are from the same updated suite run. The standard matrix includes compiler defaults and an explicit inline setting of 200 for both GCC and Clang, at O2/O3. Plain and protected implementations use matching optimization, inlining, stack-protection, frame-pointer, and sibling-call settings. GCC uses `-finline-limit=200`; Clang uses `-mllvm -inline-threshold=200`. These are different compiler heuristics despite the shared numeric setting. Overhead is relative to the matched plain build, not an unrestricted stock build; differences near zero are noise.

| Workload / setting | Plain | Protected | Overhead |
| --- | ---: | ---: | ---: |
| GCC O2 JSON, 1000 records, default | 1.077 ms | 1.380 ms | +28.1% |
| GCC O2 JSON, 1000 records, inline 200 | 1.111 ms | 1.348 ms | +21.4% |
| GCC O2 compressed PNG, default | 1.001 ms | 1.468 ms | +46.6% |
| GCC O2 compressed PNG, inline 200 | 0.676 ms | 0.675 ms | -0.2% |
| GCC O2 QOI, 1024² patterned decode, default | 2.137 ms | 2.139 ms | +0.1% |
| GCC O2 QOI, 1024² patterned decode, inline 200 | 2.138 ms | 2.138 ms | -0.0% |
| GCC O2 jsmn, 65536 flat elements, default | 0.625 ms | 0.625 ms | -0.0% |
| GCC O2 jsmn, 65536 flat elements, inline 200 | 0.625 ms | 0.625 ms | -0.0% |
| GCC O2 spdlog, 128 bytes × 100, default | 12.419 µs | 13.343 µs | +7.4% |
| GCC O2 spdlog, 128 bytes × 100, inline 200 | 12.408 µs | 13.200 µs | +6.4% |
| GCC O2 stb_sprintf, 65536 bytes, default | 12.154 µs | 12.486 µs | +2.7% |
| GCC O2 stb_sprintf, 65536 bytes, inline 200 | 12.133 µs | 12.494 µs | +3.0% |
| GCC O3 JSON, 1000 records, default | 1.057 ms | 1.334 ms | +26.2% |
| GCC O3 JSON, 1000 records, inline 200 | 1.055 ms | 1.307 ms | +23.9% |
| GCC O3 compressed PNG, default | 0.776 ms | 1.126 ms | +45.1% |
| GCC O3 compressed PNG, inline 200 | 0.683 ms | 0.687 ms | +0.6% |
| Clang O2 JSON, 1000 records, default | 1.155 ms | 1.931 ms | +67.2% |
| Clang O2 JSON, 1000 records, inline 200 | 1.165 ms | 2.005 ms | +72.1% |
| Clang O2 compressed PNG, default | 0.860 ms | 1.145 ms | +33.1% |
| Clang O2 compressed PNG, inline 200 | 0.857 ms | 1.143 ms | +33.3% |
| Clang O2 QOI, 1024² patterned decode, default | 2.432 ms | 2.467 ms | +1.5% |
| Clang O2 QOI, 1024² patterned decode, inline 200 | 2.431 ms | 2.466 ms | +1.5% |
| Clang O2 jsmn, 65536 flat elements, default | 0.565 ms | 0.605 ms | +7.1% |
| Clang O2 jsmn, 65536 flat elements, inline 200 | 0.565 ms | 0.630 ms | +11.6% |
| Clang O2 spdlog, 128 bytes × 100, default | 9.959 µs | 11.144 µs | +11.9% |
| Clang O2 spdlog, 128 bytes × 100, inline 200 | 10.052 µs | 11.238 µs | +11.8% |
| Clang O2 stb_sprintf, 65536 bytes, default | 14.237 µs | 14.634 µs | +2.8% |
| Clang O2 stb_sprintf, 65536 bytes, inline 200 | 14.388 µs | 14.673 µs | +2.0% |
| Clang O3 JSON, 1000 records, default | 1.093 ms | 1.570 ms | +43.6% |
| Clang O3 JSON, 1000 records, inline 200 | 1.040 ms | 1.551 ms | +49.1% |
| Clang O3 compressed PNG, default | 0.860 ms | 1.133 ms | +31.7% † |
| Clang O3 compressed PNG, inline 200 | 0.858 ms | 1.131 ms | +31.8% |

Frequent small protected calls pay masking, tag arithmetic, and authentication at each boundary. Inlining helps by removing boundaries, but is not a general solution: in earlier Clang experiments, threshold 4800 grows JSON implementation code from 62 KB to 220 KB versus threshold 600, takes 2.6× longer to compile, and makes the smallest malformed-input case about 3× slower. Threshold 600 also made a small stb_sprintf workload about 21% slower in absolute protected execution time.

At setting 200, GCC JSON overhead is 21.4% at O2 and 23.9% at O3, while its compressed PNG overhead is within about 1%. Clang JSON overhead is 72.1% at O2 and 49.1% at O3; its compressed PNG overhead remains about 32–33%. Standardizing on 200 does not make it an improvement for both compilers.

Native CPU tuning, loop unrolling, frame-pointer omission, targeted inlining, and PGO did not materially solve the remaining JSON overhead. Small equivalent runtime changes helped PNG about 1.7% and left JSON effectively unchanged.

The updated matrix completed 96 builds, 480 benchmark processes, and 424 paired comparisons with no build or correctness failures and no source changes during measurement. Five comparisons were flagged noisy (CV above 10%); † marks any such row shown here. The retained suite and regression tests record the working baseline, not a production-readiness claim. Raw results are in `build/suite-inline200/report.json`; run the standard matrix with `python3 benchmark/run_suite.py --optimizations O2 O3 --output build/suite-inline200`.
