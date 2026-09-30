#include <cstdio>
#include <vector>

#ifdef RETGUARD_TEST_QOI
extern "C" int check_qoi(void);
#endif
#ifdef RETGUARD_TEST_JSON
extern "C" int check_json(void);
#endif
#ifdef RETGUARD_TEST_SPDLOG
extern "C" int check_spdlog(void);
#endif
#ifdef RETGUARD_TEST_STB
extern "C" unsigned char *retguard_stb_decode(const unsigned char *, int, int *, int *);
extern "C" void retguard_stb_free(void *);

#ifndef RETGUARD_PNG_PATH
#error RETGUARD_PNG_PATH must name the test PNG
#endif

static int check_stb()
{
    FILE *file = std::fopen(RETGUARD_PNG_PATH, "rb");
    if (!file) return 1;
    if (std::fseek(file, 0, SEEK_END) != 0) return 1;
    const long size = std::ftell(file);
    if (size <= 0 || std::fseek(file, 0, SEEK_SET) != 0) return 1;
    std::vector<unsigned char> bytes(static_cast<size_t>(size));
    const bool read_ok = std::fread(bytes.data(), 1, bytes.size(), file) == bytes.size();
    std::fclose(file);
    if (!read_ok) return 1;
    int width = 0, height = 0;
    unsigned char *pixels = retguard_stb_decode(bytes.data(), static_cast<int>(size),
                                                  &width, &height);
    if (!pixels) return 1;
    const bool bad = width != 256 || height != 256;
    retguard_stb_free(pixels);
    return bad;
}
#endif

int main()
{
#ifdef RETGUARD_TEST_STB
    return check_stb();
#elif defined(RETGUARD_TEST_QOI)
    return check_qoi();
#elif defined(RETGUARD_TEST_JSON)
    return check_json();
#elif defined(RETGUARD_TEST_SPDLOG)
    return check_spdlog();
#endif
}
