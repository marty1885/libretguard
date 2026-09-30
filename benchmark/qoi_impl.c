#define QOI_IMPLEMENTATION
#define QOI_NO_STDIO
#include "qoi.h"
#include <stdlib.h>
void *retguard_qoi_encode(const unsigned char *pixels, unsigned side, int *size)
{
    qoi_desc desc = {side, side, 4, QOI_SRGB};
    return qoi_encode(pixels, &desc, size);
}
void *retguard_qoi_decode(const void *input, int size, unsigned *width, unsigned *height)
{
    qoi_desc desc = {0};
    void *pixels = qoi_decode(input, size, &desc, 4);
    *width = desc.width; *height = desc.height;
    return pixels;
}
void retguard_qoi_free(void *data) { free(data); }
