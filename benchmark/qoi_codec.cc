#include <benchmark/benchmark.h>
#include <algorithm>
#include <cstring>
#include "image_fixture.h"
extern "C" void *retguard_qoi_encode(const unsigned char *, unsigned, int *);
extern "C" void *retguard_qoi_decode(const void *, int, unsigned *, unsigned *);
extern "C" void retguard_qoi_free(void *);
static void BM_qoi_codec(benchmark::State &state)
{
    const auto side = static_cast<unsigned>(state.range(0));
    const bool flat = state.range(1) != 0;
    const auto operation = state.range(2); // 0 encode, 1 decode, 2 invalid header
    auto pixels = image_pixels(side, flat);
    int size = 0;
    void *encoded = retguard_qoi_encode(pixels.data(), side, &size);
    if (!encoded) { state.SkipWithError("QOI encode failed"); return; }
    unsigned width = 0, height = 0;
    void *decoded = retguard_qoi_decode(encoded, size, &width, &height);
    bool correct = decoded && width == side && height == side &&
        std::memcmp(decoded, pixels.data(), pixels.size()) == 0;
    retguard_qoi_free(decoded);
    if (operation == 2) {
        static_cast<unsigned char *>(encoded)[0] = 0;
        decoded = retguard_qoi_decode(encoded, size, &width, &height);
        correct = correct && !decoded;
        retguard_qoi_free(decoded);
    }
    if (!correct) { retguard_qoi_free(encoded); state.SkipWithError("QOI correctness check failed"); return; }
    for (auto _ : state) {
        void *result = operation == 0 ? retguard_qoi_encode(pixels.data(), side, &size) :
            retguard_qoi_decode(encoded, size, &width, &height);
        benchmark::DoNotOptimize(result);
        const bool valid_result = operation == 2 ? !result : result &&
            (operation == 0 ? size > 0 : width == side && height == side);
        retguard_qoi_free(result);
        if (!valid_result) { state.SkipWithError("QOI timed result check failed"); break; }
    }
    if (operation == 0) {
        int final_size = 0;
        void *final_encoded = retguard_qoi_encode(pixels.data(), side, &final_size);
        decoded = final_encoded ? retguard_qoi_decode(final_encoded, final_size, &width, &height) : nullptr;
        correct = decoded && width == side && height == side &&
            std::memcmp(decoded, pixels.data(), pixels.size()) == 0;
        retguard_qoi_free(decoded); retguard_qoi_free(final_encoded);
    } else {
        decoded = retguard_qoi_decode(encoded, size, &width, &height);
        correct = operation == 2 ? !decoded : decoded && width == side && height == side &&
            std::memcmp(decoded, pixels.data(), pixels.size()) == 0;
        retguard_qoi_free(decoded);
    }
    if (!correct) state.SkipWithError("QOI post-loop output check failed");
    if (operation == 2) state.SetItemsProcessed(state.iterations());
    else state.SetBytesProcessed(state.iterations() * static_cast<int64_t>(operation == 0 ? pixels.size() : size));
    retguard_qoi_free(encoded);
}
BENCHMARK(BM_qoi_codec)->ArgNames({"side","flat","operation"})->Args({16,0,0})->Args({256,0,0})->Args({1024,0,0})
    ->Args({16,0,1})->Args({256,0,1})->Args({1024,0,1})
    ->Args({16,1,0})->Args({256,1,0})->Args({1024,1,0})
    ->Args({16,1,1})->Args({256,1,1})->Args({1024,1,1})->Args({256,0,2});
BENCHMARK_MAIN();
