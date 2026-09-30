#ifndef RETGUARD_IMAGE_FIXTURE_H
#define RETGUARD_IMAGE_FIXTURE_H
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <vector>

inline std::vector<unsigned char> image_pixels(unsigned side, bool flat)
{
    std::vector<unsigned char> pixels(side * side * 4);
    for (unsigned y = 0; y < side; ++y)
        for (unsigned x = 0; x < side; ++x) {
            const unsigned at = (y * side + x) * 4;
            pixels[at] = flat ? 23 : static_cast<unsigned char>(x * 37 + y * 17);
            pixels[at + 1] = flat ? 51 : static_cast<unsigned char>(x * 13 ^ y * 29);
            pixels[at + 2] = flat ? 91 : static_cast<unsigned char>(x + y * 3);
            pixels[at + 3] = 255;
        }
    return pixels;
}
inline void png_u32(std::vector<unsigned char> &out, uint32_t value)
{
    for (int shift = 24; shift >= 0; shift -= 8) out.push_back(value >> shift);
}
inline void png_chunk(std::vector<unsigned char> &out, const char *type,
                      const std::vector<unsigned char> &data)
{
    png_u32(out, data.size());
    const auto begin = out.size();
    out.insert(out.end(), type, type + 4);
    out.insert(out.end(), data.begin(), data.end());
    uint32_t crc = 0xffffffffu;
    for (auto i = begin; i < out.size(); ++i) {
        crc ^= out[i];
        for (int bit = 0; bit < 8; ++bit) crc = (crc >> 1) ^ (0xedb88320u & (0u - (crc & 1)));
    }
    png_u32(out, crc ^ 0xffffffffu);
}
// Deterministic valid RGBA PNG using stored DEFLATE blocks; fixture construction
// is outside timing and requires no additional image encoder dependency.
inline std::vector<unsigned char> image_png(unsigned side)
{
    const auto pixels = image_pixels(side, false);
    std::vector<unsigned char> raw;
    for (unsigned y = 0; y < side; ++y) {
        raw.push_back(0);
        raw.insert(raw.end(), pixels.begin() + y * side * 4, pixels.begin() + (y + 1) * side * 4);
    }
    std::vector<unsigned char> z = {0x78, 0x01};
    for (size_t at = 0; at < raw.size();) {
        const auto length = static_cast<unsigned>(std::min<size_t>(65535, raw.size() - at));
        z.push_back(at + length == raw.size() ? 1 : 0);
        z.push_back(length & 255); z.push_back(length >> 8);
        z.push_back((~length) & 255); z.push_back((~length >> 8) & 255);
        z.insert(z.end(), raw.begin() + at, raw.begin() + at + length);
        at += length;
    }
    uint32_t a = 1, b = 0;
    for (auto byte : raw) { a = (a + byte) % 65521; b = (b + a) % 65521; }
    png_u32(z, (b << 16) | a);
    std::vector<unsigned char> png = {137,80,78,71,13,10,26,10};
    std::vector<unsigned char> header;
    png_u32(header, side); png_u32(header, side);
    header.insert(header.end(), {8,6,0,0,0});
    png_chunk(png, "IHDR", header); png_chunk(png, "IDAT", z); png_chunk(png, "IEND", {});
    return png;
}
#endif
