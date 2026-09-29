#include "retguard.h"

/* A second, C translation unit in the automatic instrumentation target. */
__attribute__((noinline)) int
auto_extra(int value)
{
    RETGUARD_BEGIN();
    RETGUARD_RETURN(value + 1);
}
