#define JSMN_STRICT
#include "jsmn.h"

int retguard_jsmn_parse(const char *input, size_t length, jsmntok_t *tokens,
                        unsigned capacity)
{
    jsmn_parser parser;
    jsmn_init(&parser);
    return jsmn_parse(&parser, input, length, tokens, capacity);
}
