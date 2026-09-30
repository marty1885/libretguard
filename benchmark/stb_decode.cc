#include <benchmark/benchmark.h>
#include <algorithm>
#include <cstring>
#include <fstream>
#include <iterator>
#include "image_fixture.h"
extern "C" unsigned char *retguard_stb_decode(const unsigned char *, int, int *, int *);
extern "C" void retguard_stb_free(void *);
static void BM_stb_png_decode(benchmark::State &state)
{
    const auto side = static_cast<unsigned>(state.range(0));
    auto png = image_png(side);
    const bool invalid = state.range(1) != 0;
    if (invalid) png.resize(png.size() / 2);
    int width = 0, height = 0;
    auto *check = retguard_stb_decode(png.data(), png.size(), &width, &height);
    const auto expected = image_pixels(side, false);
    const bool correct = invalid ? !check : check && width == static_cast<int>(side) &&
        height == static_cast<int>(side) && std::memcmp(check, expected.data(), expected.size()) == 0;
    retguard_stb_free(check);
    if (!correct) { state.SkipWithError("PNG correctness check failed"); return; }
    for (auto _ : state) {
        auto *pixels = retguard_stb_decode(png.data(), png.size(), &width, &height);
        benchmark::DoNotOptimize(pixels);
        const bool valid_result = invalid ? !pixels : pixels && width == static_cast<int>(side) && height == static_cast<int>(side);
        retguard_stb_free(pixels);
        if (!valid_result) { state.SkipWithError("PNG timed result check failed"); break; }
    }
    check = retguard_stb_decode(png.data(), png.size(), &width, &height);
    const bool after_correct = invalid ? !check : check && width == static_cast<int>(side) &&
        height == static_cast<int>(side) && std::memcmp(check, expected.data(), expected.size()) == 0;
    retguard_stb_free(check);
    if (!after_correct) state.SkipWithError("PNG post-loop output check failed");
    state.SetBytesProcessed(state.iterations() * static_cast<int64_t>(png.size()));
}
BENCHMARK(BM_stb_png_decode)->ArgNames({"side","invalid"})->Args({16,0})->Args({256,0})->Args({1024,0})
    ->Args({16,1})->Args({256,1})->Args({1024,1});
static void BM_stb_compressed_png_decode(benchmark::State &state)
{
    std::ifstream file(RETGUARD_PNG_PATH, std::ios::binary);
    std::vector<unsigned char> png{std::istreambuf_iterator<char>(file), {}};
    if (!file || png.empty()) { state.SkipWithError("Cannot load compressed PNG fixture"); return; }
    int width = 0, height = 0;
    auto *check = retguard_stb_decode(png.data(), png.size(), &width, &height);
    if (!check || width != 256 || height != 256) {
        retguard_stb_free(check); state.SkipWithError("Compressed PNG decode failed"); return;
    }
    // Expected RGBA FNV-1a checksum independently computed with Pillow.
    uint64_t checksum = 14695981039346656037ull;
    for (unsigned i = 0; i < 256 * 256 * 4; ++i) checksum = (checksum ^ check[i]) * 1099511628211ull;
    retguard_stb_free(check);
    if (checksum != 399645179021762021ull) {
        state.SkipWithError("Compressed PNG pixels differ from reference"); return;
    }
    for (auto _ : state) {
        auto *pixels = retguard_stb_decode(png.data(), png.size(), &width, &height);
        benchmark::DoNotOptimize(pixels);
        const bool valid_result = pixels && width == 256 && height == 256;
        retguard_stb_free(pixels);
        if (!valid_result) { state.SkipWithError("Compressed PNG timed result check failed"); break; }
    }
    check = retguard_stb_decode(png.data(), png.size(), &width, &height);
    uint64_t after = 14695981039346656037ull;
    if (check && width == 256 && height == 256) for (unsigned i = 0; i < 256 * 256 * 4; ++i) after = (after ^ check[i]) * 1099511628211ull;
    if (!check || width != 256 || height != 256 || after != checksum) state.SkipWithError("Compressed PNG checksum changed");
    retguard_stb_free(check);
    state.SetBytesProcessed(state.iterations() * static_cast<int64_t>(png.size()));
    state.counters["pixel_checksum"] = static_cast<double>(checksum & ((1ull << 53) - 1));
}
BENCHMARK(BM_stb_compressed_png_decode);
BENCHMARK_MAIN();
