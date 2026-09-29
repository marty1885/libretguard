#include "retguard.h"

#include <stdint.h>

struct gadget_pair { uint64_t first, second; };

__attribute__((noinline)) int
plain_function(int x)
{
    return x + 1;
}

__attribute__((noinline)) int
scope_only(int x)
{
    RETGUARD_SCOPE();
    return x + 1;
}

RETGUARD_GADGET_FUNCTION
int gadget_normal(int x)
{
    RETGUARD_GADGET_SCOPE();
    if (x < 0)
        return -1;
    return x + 1;
}

RETGUARD_GADGET_FUNCTION
int gadget_recursive(int n)
{
    RETGUARD_GADGET_SCOPE();
    if (n == 0)
        return 0;
    return 1 + gadget_recursive(n - 1);
}

RETGUARD_GADGET_FUNCTION
void gadget_void(int *out)
{
    RETGUARD_GADGET_SCOPE();
    *out = 42;
}

RETGUARD_GADGET_FUNCTION
struct gadget_pair gadget_pair_value(void)
{
    RETGUARD_GADGET_SCOPE();
    struct gadget_pair result = { UINT64_C(0x123456789abcdef0),
                                  UINT64_C(0xfedcba9876543210) };
    return result;
}

RETGUARD_GADGET_FUNCTION
double gadget_double_value(void)
{
    RETGUARD_GADGET_SCOPE();
    return 3.25;
}

RETGUARD_GADGET_FUNCTION
int gadget_bad_address(void)
{
    RETGUARD_GADGET_SCOPE();
    __asm__ volatile ("xorq $1, 8(%%rbp)" ::: "memory");
    return 7;
}

RETGUARD_GADGET_FUNCTION
int gadget_bad_seal(void)
{
    RETGUARD_GADGET_SCOPE();
    _retguard_scope.seal ^= 1;
    return 7;
}

/* Without a scope guard, this fixture supplies a known invalid handoff. */
RETGUARD_GADGET_FUNCTION
int gadget_no_scope(int x)
{
    __asm__ volatile ("xor %%r11d, %%r11d" ::: "r11");
    return x + 1;
}

/* The test runner verifies these compiler canary slots in disassembly. */
#if defined(__clang__) || defined(__OPTIMIZE__)
#define GADGET_CANARY_SLOT "-8"
#else
#define GADGET_CANARY_SLOT "-24"
#endif
RETGUARD_GADGET_FUNCTION
int gadget_bad_canary(void)
{
    RETGUARD_GADGET_SCOPE();
    __asm__ volatile ("xorq $1, " GADGET_CANARY_SLOT "(%%rbp)" ::: "memory");
    return 7;
}

/* Enter the shared return path without executing a protected cleanup. */
__attribute__((naked, noinline)) void gadget_bypass(void)
{
    __asm__ volatile ("xor %%r11d, %%r11d\n\t"
                      "jmp __x86_return_thunk" ::: "r11");
}
