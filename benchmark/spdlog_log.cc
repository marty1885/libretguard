#include <benchmark/benchmark.h>
#include <cstddef>
#include <string>
extern "C" std::size_t retguard_spdlog_log(const char *, std::size_t, unsigned);
extern "C" bool retguard_spdlog_check(const char *, std::size_t, unsigned);
static void BM_spdlog_log(benchmark::State &state)
{
    const std::string text(static_cast<std::size_t>(state.range(0)), 'x');
    const auto count = static_cast<unsigned>(state.range(1));
    if (!retguard_spdlog_check(text.data(), text.size(), count)) {
        state.SkipWithError("spdlog output content check failed"); return;
    }
    for (auto _ : state) {
        auto bytes = retguard_spdlog_log(text.data(), text.size(), count);
        benchmark::DoNotOptimize(bytes);
        if (bytes != (text.size() + 4) * count) { state.SkipWithError("spdlog timed output size check failed"); break; }
    }
    if (!retguard_spdlog_check(text.data(), text.size(), count))
        state.SkipWithError("spdlog post-loop output check failed");
    state.SetBytesProcessed(state.iterations() * static_cast<int64_t>(text.size() * count));
}
BENCHMARK(BM_spdlog_log)->ArgNames({"message_bytes","batch"})->Args({8,1})->Args({128,1})->Args({4096,1})
    ->Args({8,100})->Args({128,100})->Args({4096,100});
BENCHMARK_MAIN();
