#include <benchmark/benchmark.h>
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

extern "C" int retguard_sprintf_format(char *, int, const char *);

static void BM_sprintf_format(benchmark::State &state)
{
    const auto length = static_cast<std::size_t>(state.range(0));
    const bool truncated = state.range(1) != 0;
    std::string text(length, 'x');
    for (std::size_t i = 0; i < text.size(); ++i) text[i] = 'a' + i % 26;
    const int capacity = truncated ? 32 : static_cast<int>(length + 128);
    std::vector<char> output(capacity), reference(capacity);
    const int expected = std::snprintf(reference.data(), capacity,
        "id=%d hex=%08x value=%.3f text=%s", -42, 0x12abcU, 12.5, text.c_str());
    const int checked = retguard_sprintf_format(output.data(), capacity, text.c_str());
    const std::size_t written = std::min(static_cast<std::size_t>(expected), output.size() - 1);
    if (expected < 0 || checked != expected ||
        std::memcmp(output.data(), reference.data(), written + 1) != 0) {
        state.SkipWithError("stb_sprintf correctness check failed"); return;
    }
    for (auto _ : state) {
        int result = retguard_sprintf_format(output.data(), capacity, text.c_str());
        benchmark::DoNotOptimize(result);
        benchmark::DoNotOptimize(output.data());
        benchmark::ClobberMemory();
        if (result != expected) { state.SkipWithError("stb_sprintf timed length check failed"); break; }
    }
    if (std::memcmp(output.data(), reference.data(), written + 1) != 0)
        state.SkipWithError("stb_sprintf timed output check failed");
    // snprintf still scans the full string to compute its return value when truncated.
    state.SetBytesProcessed(state.iterations() * static_cast<int64_t>(text.size()));
    state.SetItemsProcessed(state.iterations());
}
BENCHMARK(BM_sprintf_format)->ArgsProduct({{16, 1024, 65536}, {0, 1}});
BENCHMARK_MAIN();
