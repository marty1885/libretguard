#include "retguard.h"
#include <unistd.h>

extern void __real___stack_chk_fail(void) __attribute__((noreturn));
__attribute__((noreturn, no_stack_protector)) void
__wrap___stack_chk_fail(void)
{
    static const char marker[] = "AUTO_STACK_CHK_FAIL\n";
    (void)write(STDERR_FILENO, marker, sizeof(marker) - 1);
    __real___stack_chk_fail();
}

__attribute__((noinline)) int
mixed_manual(int value)
{
    RETGUARD_SCOPE();
    return value + 1;
}
