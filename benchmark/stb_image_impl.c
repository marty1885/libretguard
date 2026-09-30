#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_PNG
#define STBI_NO_STDIO
#include "stb_image.h"

unsigned char *retguard_stb_decode(const unsigned char *png, int size,
                                   int *width, int *height)
{
    int channels = 0;
    return stbi_load_from_memory(png, size, width, height, &channels, 4);
}

void retguard_stb_free(void *pixels)
{
    stbi_image_free(pixels);
}
