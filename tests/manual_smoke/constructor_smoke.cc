#include "retguard.h"

__attribute__((noinline)) static int guarded(int value)
{
    RETGUARD_SCOPE();
    return value + 1;
}

struct BeforeMain {
    BeforeMain()
    {
        if (guarded(41) != 42)
            __builtin_trap();
    }
};

static BeforeMain before_main __attribute__((init_priority(101)));

int main()
{
    return guarded(1) == 2 ? 0 : 1;
}
