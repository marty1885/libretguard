#include "retguard.h"

#include <asm/prctl.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/syscall.h>
#include <string.h>
#include <unistd.h>

__attribute__((noinline)) static int
sum_to(int n)
{
    RETGUARD_SCOPE();
    if (n <= 0)
        return 0;
    return n + sum_to(n - 1);
}

__attribute__((noinline)) static void
set_value(int *out)
{
    RETGUARD_SCOPE();
    if (*out < 0)
        return;
    *out = 42;
}

__attribute__((noinline)) static int
explicit_return(int value)
{
    RETGUARD_BEGIN();
    RETGUARD_RETURN(value + 1);
}

__attribute__((noinline)) static int
corrupt_return_address(void)
{
    RETGUARD_SCOPE();
    __asm__ volatile ("xorq $1, 8(%%rbp)" ::: "memory");
    return 7;
}

/* No RETGUARD check: CET alone should reject this altered return address. */
__attribute__((noinline)) static void
corrupt_unchecked_return_address(void)
{
    __asm__ volatile ("xorq $1, 8(%%rbp)" ::: "memory");
}

int
main(int argc, char **argv)
{
    if (argc != 2)
        return 2;

    if (getenv("RETGUARD_REQUIRE_CET") != NULL) {
        unsigned long features = 0;
        assert(syscall(SYS_arch_prctl, ARCH_SHSTK_STATUS, &features) == 0);
        assert((features & ARCH_SHSTK_SHSTK) != 0);
    }

    if (strcmp(argv[1], "normal") == 0) {
        /* The archive's preinit entry must seed cookies before main. */
        assert(sum_to(10) == 55);
        assert(explicit_return(9) == 10);
        int value = 0;
        set_value(&value);
        assert(value == 42);
        value = -1;
        set_value(&value);
        assert(value == -1);
        puts("manual API: recursion, explicit return, and void return passed");
        return 0;
    }
    if (strcmp(argv[1], "bad_return") == 0) {
        (void)corrupt_return_address();
        return 3;
    }
    if (strcmp(argv[1], "cet_bad_return") == 0) {
        corrupt_unchecked_return_address();
        return 3;
    }
    return 2;
}
