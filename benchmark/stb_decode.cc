#include <benchmark/benchmark.h>

#include <cstdio>
#include <cstdlib>
#include <vector>

extern "C" unsigned char *retguard_stb_decode(const unsigned char *, int, int *, int *);
extern "C" void retguard_stb_free(void *);

#ifndef RETGUARD_PNG_PATH
#error RETGUARD_PNG_PATH must name the benchmark PNG
#endif

static std::vector<unsigned char> load_png()
{
    FILE *file = std::fopen(RETGUARD_PNG_PATH, "rb");
    if (!file) std::abort();
    if (std::fseek(file, 0, SEEK_END) != 0) std::abort();
    const long size = std::ftell(file);
    if (size <= 0 || std::fseek(file, 0, SEEK_SET) != 0) std::abort();
    std::vector<unsigned char> bytes(static_cast<size_t>(size));
    if (std::fread(bytes.data(), 1, bytes.size(), file) != bytes.size()) std::abort();
    std::fclose(file);
    return bytes;
}

static void BM_stb_png_decode(benchmark::State &state)
{
    const auto png = load_png();
    for (auto _ : state) {
        int width = 0, height = 0;
        unsigned char *pixels = retguard_stb_decode(
            png.data(), static_cast<int>(png.size()), &width, &height);
        if (!pixels || width != 256 || height != 256) {
            state.SkipWithError("PNG decode failed");
            break;
        }
        benchmark::DoNotOptimize(pixels);
        retguard_stb_free(pixels);
    }
    state.SetBytesProcessed(state.iterations() * static_cast<int64_t>(png.size()));
}

BENCHMARK(BM_stb_png_decode);
BENCHMARK_MAIN();
