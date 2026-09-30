#define STB_SPRINTF_IMPLEMENTATION
#include "stb_sprintf.h"

int retguard_sprintf_format(char *output, int capacity, const char *text)
{
    return stbsp_snprintf(output, capacity,
                          "id=%d hex=%08x value=%.3f text=%s", -42, 0x12abcU,
                          12.5, text);
}
