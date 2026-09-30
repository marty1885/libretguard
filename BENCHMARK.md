# Benchmarks

Measured on an AMD Ryzen 9 7950X3D with GCC 16.2.1, pinned to CPU 0.

## Call overhead

Each benchmark calls an out-of-line function that returns `x + 1`. The added time is the guarded call minus a plain call in the same executable.

| Guard | Plain call | Guarded call | Added per call |
| --- | ---: | ---: | ---: |
| Manual scope | 0.987 ns | 1.38 ns | 0.39 ns |
| Manual explicit check | 0.987 ns | 1.46 ns | 0.47 ns |
| Manual scope + checked return | 0.991 ns | 1.96 ns | 0.97 ns |
| Automatic mode | 0.991 ns | 2.28 ns | 1.29 ns |

## Library workloads

Each pair uses the same library code and input, compiled at `-O2`, with automatic
RETGUARD enabled for the auto variant. Times are median CPU time over five runs.

| Workload | Plain | Auto | Added cost |
| --- | ---: | ---: | ---: |
| stb_image PNG decode | 1.128 ms | 1.638 ms | +0.510 ms (+45%) |
| stb_image PNG decode, `-finline-limit=200` | 0.803 ms | 0.804 ms | Within run variation |
| nlohmann/json 3.12.0 parse | 1.263 ms | 1.925 ms | +0.662 ms (+52%) |

PNG decoding uses `benchmark/data/sample.png` (256 × 256 RGB). JSON parsing uses
a generated 132,891-byte array of 1,000 records with nested objects, arrays,
numbers, booleans, nulls, and escaped text. Both timings include freeing the
result; loading or generating input happens before timing.

The PNG inlining option removes frequent guarded calls in the decoder's inner
loop. Overhead depends on how many calls remain after inlining, so these results
apply to these inputs and compiler settings.

## Run the library benchmarks

Requires Google Benchmark and the nlohmann_json CMake package.

```sh
cmake -S . -B build/bench -G Ninja -DRETGUARD_BUILD_BENCHMARKS=ON
for variant in stb_plain stb_auto stb_inline_plain stb_inline_auto json_plain json_auto; do
  cmake --build build/bench --target retguard_bench_$variant
  taskset -c 0 build/bench/retguard_bench_$variant \
    --benchmark_min_time=0.3s --benchmark_repetitions=5 --benchmark_report_aggregates_only=true
done
```
