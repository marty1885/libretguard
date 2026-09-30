#define QOI_IMPLEMENTATION
#define QOI_NO_STDIO
#include "qoi.h"

#include <stdlib.h>
#include <string.h>

int check_qoi(void)
{
    unsigned char pixels[16 * 16 * 4];
    for (unsigned i = 0; i < sizeof pixels; ++i)
        pixels[i] = (unsigned char)((i * 37u) ^ (i >> 2));
    qoi_desc input = {16, 16, 4, QOI_SRGB};
    int encoded_size = 0;
    void *encoded = qoi_encode(pixels, &input, &encoded_size);
    if (!encoded) return 1;
    qoi_desc output;
    void *decoded = qoi_decode(encoded, encoded_size, &output, 4);
    int result = !decoded || output.width != 16 || output.height != 16 ||
                 memcmp(pixels, decoded, sizeof pixels) != 0;
    free(decoded);
    free(encoded);
    return result;
}
