#include "retguard.h"

#include <errno.h>
#include <sys/random.h>

/* glibc's early initialization runs before executable preinit functions. */
static void
retguard_random_bytes(void *buffer, size_t length)
{
    unsigned char *bytes = buffer;
    size_t done = 0;
    while (done < length) {
        ssize_t n = getrandom(bytes + done, length - done, 0);
        if (n > 0)
            done += (size_t)n;
        else if (n == -1 && errno == EINTR)
            continue;
        else
            __builtin_trap();
    }
}

/* Manual seals and automatic tags share this table and slot index. Automatic
   mode uses a separate table and a different slot index to mask the word. */
__attribute__((visibility("hidden"))) uintptr_t retguard_auto_cookies[16];
__attribute__((visibility("hidden"))) uintptr_t retguard_auto_masks[16];
__attribute__((visibility("hidden"))) int retguard_ready;

static void
retguard_init(void)
{
    if (retguard_ready)
        return;

    retguard_random_bytes(retguard_auto_cookies, sizeof(retguard_auto_cookies));
    retguard_random_bytes(retguard_auto_masks, sizeof(retguard_auto_masks));
    /* Odd multipliers are units modulo 2^64, so multiplication remains a
       permutation and cannot introduce avoidable seal collisions. */
    for (size_t i = 0; i < 16; ++i) {
        retguard_auto_cookies[i] |= 1;
        /* The tag replaces this byte, so keep masked addresses canonical. */
        retguard_auto_masks[i] &= UINT64_C(0x00FFFFFFFFFFFFFF);
    }
    retguard_ready = 1;
}

/* Keep this entry in the same archive member as the cookies.  Any consumer
   of the runtime symbols then pulls the initializer into the executable. */
static void (*const retguard_preinit)(void)
    __attribute__((used, section(".preinit_array"))) = retguard_init;
