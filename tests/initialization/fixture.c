#include "retguard.h"

#include <assert.h>
#include <stddef.h>
#include <sys/types.h>

/* The linker replaces the runtime's getrandom call before preinit runs.
   The tag-cookie draw contains one zero and fifteen even words; initialization
   makes them odd. A separate draw supplies the address masks. */
static int draws;

ssize_t
__wrap_getrandom(void *buffer, size_t length, unsigned int flags)
{
    unsigned char *bytes = buffer;
    if (flags != 0)
        __builtin_trap();
    if (draws++ == 0) {
        if (length != sizeof(retguard_auto_cookies))
            __builtin_trap();
        for (size_t i = 0; i < length; ++i)
            bytes[i] = 0;
        for (size_t i = 0; i < 16; ++i)
            if (i != 1)
                bytes[i * sizeof(uintptr_t)] = 2;
    } else if (draws == 2) {
        if (length != sizeof(retguard_auto_masks))
            __builtin_trap();
        for (size_t i = 0; i < length; ++i)
            bytes[i] = 0xA5;
    } else {
        __builtin_trap();
    }
    return (ssize_t)length;
}

int
main(void)
{
    assert(retguard_ready == 1);
    assert(draws == 2);
    for (size_t i = 0; i < 16; ++i) {
        assert(retguard_auto_cookies[i] == (i == 1 ? 1u : 3u));
        assert(retguard_auto_masks[i] == UINT64_C(0x00A5A5A5A5A5A5A5));
    }
    return 0;
}
