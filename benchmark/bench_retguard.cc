#include <benchmark/benchmark.h>
#include <asm/prctl.h>
#include <cstdio>
#include <cstdlib>
#include <sys/syscall.h>
#include <unistd.h>

extern "C" {
int bench_plain(int);
int bench_scope(int);
int bench_explicit(int);
#ifdef RETGUARD_GADGET_BENCH
int bench_gadget(int);
#endif
#ifdef RETGUARD_AUTO_BENCH
int bench_auto(int);
#endif
}

using BenchFunction = int (*)(int);

static void run(benchmark::State& state, BenchFunction function)
{
    int input = 7;
    for (auto _ : state) {
        benchmark::DoNotOptimize(input);
        int result = function(input);
        benchmark::DoNotOptimize(result);
    }
}

static void BM_plain(benchmark::State& state) { run(state, bench_plain); }
static void BM_scope(benchmark::State& state) { run(state, bench_scope); }
static void BM_explicit(benchmark::State& state) { run(state, bench_explicit); }
#ifdef RETGUARD_GADGET_BENCH
static void BM_gadget(benchmark::State& state) { run(state, bench_gadget); }
#endif
#ifdef RETGUARD_AUTO_BENCH
static void BM_auto(benchmark::State& state) { run(state, bench_auto); }
#endif

BENCHMARK(BM_plain);
BENCHMARK(BM_scope);
BENCHMARK(BM_explicit);
#ifdef RETGUARD_GADGET_BENCH
BENCHMARK(BM_gadget);
#endif
#ifdef RETGUARD_AUTO_BENCH
BENCHMARK(BM_auto);
#endif

int main(int argc, char** argv)
{
    if (std::getenv("RETGUARD_REQUIRE_CET") != nullptr) {
        unsigned long features = 0;
        if (syscall(SYS_arch_prctl, ARCH_SHSTK_STATUS, &features) != 0 ||
            (features & ARCH_SHSTK_SHSTK) == 0) {
            std::fprintf(stderr, "CET shadow stack is not active\n");
            return 2;
        }
    }
    benchmark::Initialize(&argc, argv);
    if (benchmark::ReportUnrecognizedArguments(argc, argv))
        return 1;
    benchmark::RunSpecifiedBenchmarks();
    benchmark::Shutdown();
    return 0;
}
