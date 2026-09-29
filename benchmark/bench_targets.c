#include "retguard.h"

/* Keep all three functions in the same C translation unit and out of line.
   The benchmark measures a call, one addition, and any guard machinery. */
__attribute__((noinline)) int
bench_plain(int x)
{
    return x + 1;
}

__attribute__((noinline)) int
bench_scope(int x)
{
    RETGUARD_SCOPE();
    return x + 1;
}

__attribute__((noinline)) int
bench_explicit(int x)
{
    RETGUARD_BEGIN();
    RETGUARD_RETURN(x + 1);
}

#ifdef RETGUARD_GADGET_BENCH
RETGUARD_GADGET_FUNCTION
int bench_gadget(int x)
{
    RETGUARD_GADGET_SCOPE();
    return x + 1;
}
#endif
