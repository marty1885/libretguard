#include <benchmark/benchmark.h>
#include <cstddef>
#include <nlohmann/json.hpp>
#include <string>
extern "C" std::size_t retguard_json_parse(const char *, std::size_t);
static std::string make_json(int records, bool invalid)
{
    std::string input = "[";
    for (int i = 0; i < records; ++i) {
        if (i) input += ',';
        input += "{\"id\":" + std::to_string(i) +
            R"(,"name":"record\n\u53f0\u7063","active":true,"score":12.75,"tags":["json","benchmark"],"meta":{"count":42,"optional":null}})";
    }
    input += invalid ? ",]" : "]";
    return input;
}
static void BM_json_parse(benchmark::State &state)
{
    const auto records = static_cast<std::size_t>(state.range(0));
    const bool invalid = state.range(1) != 0;
    const auto input = make_json(records, invalid);
    bool correct = false;
    try { const auto count = retguard_json_parse(input.data(), input.size()); correct = !invalid && count == records; }
    catch (const nlohmann::json::parse_error &) { correct = invalid; }
    if (!correct) { state.SkipWithError("JSON correctness check failed"); return; }
    for (auto _ : state) {
        try { auto count = retguard_json_parse(input.data(), input.size()); benchmark::DoNotOptimize(count);
            if (invalid || count != records) { state.SkipWithError("Unexpected JSON parse result"); break; } }
        catch (const nlohmann::json::parse_error &error) {
            if (!invalid) { state.SkipWithError(error.what()); break; }
            auto message = error.what(); benchmark::DoNotOptimize(message);
        }
    }
    state.SetBytesProcessed(state.iterations() * static_cast<int64_t>(input.size()));
}
BENCHMARK(BM_json_parse)->ArgNames({"records","invalid"})->Args({1,0})->Args({100,0})->Args({1000,0})
    ->Args({1,1})->Args({100,1})->Args({1000,1});
BENCHMARK_MAIN();
