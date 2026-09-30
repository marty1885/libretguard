#include <benchmark/benchmark.h>
#include <algorithm>
#include <cstdint>
#include <string>
#include <vector>
#define JSMN_HEADER
#define JSMN_STRICT
#include "../third_party/jsmn/jsmn.h"

extern "C" int retguard_jsmn_parse(const char *, std::size_t, jsmntok_t *, unsigned);

static bool same_tokens(const std::vector<jsmntok_t> &actual,
                        const std::vector<jsmntok_t> &expected)
{
    return std::equal(actual.begin(), actual.end(), expected.begin(),
        [](const jsmntok_t &a, const jsmntok_t &b) {
            return a.type == b.type && a.start == b.start && a.end == b.end && a.size == b.size;
        });
}

// jsmn tokenizes JSON; strict mode is not a full JSON grammar validator.
// Each element has one token, with one additional token for the root array.
static void BM_jsmn_parse(benchmark::State &state)
{
    const auto elements = static_cast<unsigned>(state.range(0));
    const auto mode = static_cast<int>(state.range(1));
    std::string input = "[";
    for (unsigned i = 0; i < elements; ++i) {
        if (i) input += ',';
        input += i % 2 ? R"("record\n\u53f0\u7063")" : "12345";
    }
    input += ']';
    if (mode == 1) input.pop_back(); // Incomplete array, detected after scanning input.
    if (mode == 2) input[input.rfind("\\n") + 1] = 'q'; // Unsupported escape near the end.
    const unsigned capacity = mode == 3 ? elements / 2 : elements + 1;
    std::vector<jsmntok_t> tokens(capacity);
    const int expected = mode == 1 ? JSMN_ERROR_PART : mode == 2 ? JSMN_ERROR_INVAL :
                         mode == 3 ? JSMN_ERROR_NOMEM : static_cast<int>(elements + 1);
    const int checked = retguard_jsmn_parse(input.data(), input.size(), tokens.data(), capacity);
    bool correct = checked == expected;
    if (mode == 0 && correct) {
        correct = tokens[0].type == JSMN_ARRAY && tokens[0].start == 0 &&
                  tokens[0].end == static_cast<int>(input.size()) &&
                  tokens[0].size == static_cast<int>(elements);
        for (unsigned i = 0; i < elements; ++i) {
            const auto &token = tokens[i + 1];
            correct = correct && token.type == (i % 2 ? JSMN_STRING : JSMN_PRIMITIVE) &&
                      token.start >= 0 && token.end > token.start &&
                      static_cast<std::size_t>(token.end) <= input.size();
            if (correct) {
                correct = input.compare(static_cast<std::size_t>(token.start),
                                        static_cast<std::size_t>(token.end - token.start),
                                        i % 2 ? R"(record\n\u53f0\u7063)" : "12345") == 0;
            }
        }
    }
    if (!correct) { state.SkipWithError("jsmn correctness check failed"); return; }
    const auto expected_tokens = tokens;
    for (auto _ : state) {
        int result = retguard_jsmn_parse(input.data(), input.size(), tokens.data(), capacity);
        benchmark::DoNotOptimize(result);
        benchmark::DoNotOptimize(tokens.data());
        benchmark::ClobberMemory();
        if (result != expected) { state.SkipWithError("jsmn timed return check failed"); break; }
    }
    if (!same_tokens(tokens, expected_tokens)) state.SkipWithError("jsmn timed token check failed");
    // Capacity errors stop early, so bytes/s would exaggerate their throughput.
    if (mode != 3) state.SetBytesProcessed(state.iterations() * static_cast<int64_t>(input.size()));
    state.SetItemsProcessed(state.iterations());
}
BENCHMARK(BM_jsmn_parse)->ArgsProduct({{16, 1024, 65536}, {0, 1, 2, 3}});

static void BM_jsmn_nested(benchmark::State &state)
{
    const auto depth = static_cast<unsigned>(state.range(0));
    const std::string input = std::string(depth, '[') + "0" + std::string(depth, ']');
    std::vector<jsmntok_t> tokens(depth + 1);
    const int checked = retguard_jsmn_parse(input.data(), input.size(), tokens.data(), depth + 1);
    bool correct = checked == static_cast<int>(depth + 1);
    for (unsigned i = 0; i < depth && correct; ++i) {
        correct = tokens[i].type == JSMN_ARRAY && tokens[i].start == static_cast<int>(i) &&
                  tokens[i].end == static_cast<int>(input.size() - i) && tokens[i].size == 1;
    }
    correct = correct && tokens[depth].type == JSMN_PRIMITIVE &&
              tokens[depth].start == static_cast<int>(depth) &&
              tokens[depth].end == static_cast<int>(depth + 1);
    if (!correct) { state.SkipWithError("jsmn nested correctness check failed"); return; }
    const auto expected_tokens = tokens;
    for (auto _ : state) {
        int result = retguard_jsmn_parse(input.data(), input.size(), tokens.data(), depth + 1);
        benchmark::DoNotOptimize(result);
        benchmark::DoNotOptimize(tokens.data());
        benchmark::ClobberMemory();
        if (result != static_cast<int>(depth + 1)) {
            state.SkipWithError("jsmn nested timed return check failed"); break;
        }
    }
    if (!same_tokens(tokens, expected_tokens)) state.SkipWithError("jsmn nested timed token check failed");
    state.SetBytesProcessed(state.iterations() * static_cast<int64_t>(input.size()));
    state.SetItemsProcessed(state.iterations());
}
// Without JSMN_PARENT_LINKS, closing each nested array scans past closed tokens.
BENCHMARK(BM_jsmn_nested)->Arg(16)->Arg(256)->Arg(4096);
BENCHMARK_MAIN();
