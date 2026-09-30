#include <benchmark/benchmark.h>

#include <cstddef>
#include <exception>
#include <string>

extern "C" std::size_t retguard_json_parse(const char *, std::size_t);

// Build the same mixed JSON document before timing either parser variant.
static std::string make_json()
{
    std::string input = "[";
    for (int i = 0; i < 1000; ++i) {
        if (i) input += ',';
        input += "{\"id\":" + std::to_string(i) +
                 R"(,"name":"record\n\u53f0\u7063","active":true,"score":12.75,"tags":["json","benchmark"],"meta":{"count":42,"optional":null}})";
    }
    input += ']';
    return input;
}

static void BM_json_parse(benchmark::State &state)
{
    const auto input = make_json();
    try {
        for (auto _ : state) {
            auto records = retguard_json_parse(input.data(), input.size());
            benchmark::DoNotOptimize(records);
            if (records != 1000) {
                state.SkipWithError("JSON parse returned the wrong record count");
                break;
            }
        }
    } catch (const std::exception &error) {
        state.SkipWithError(error.what());
    }
    state.SetBytesProcessed(state.iterations() * static_cast<int64_t>(input.size()));
}

BENCHMARK(BM_json_parse);
BENCHMARK_MAIN();
