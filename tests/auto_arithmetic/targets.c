#include "api.h"
#include <stdarg.h>
__attribute__((noinline)) uint64_t abi_arguments(uint64_t a, uint64_t b, uint64_t c,
                                               uint64_t d, uint64_t e, uint64_t f)
{ return a + 2*b + 3*c + 5*d + 7*e + 11*f; }
__attribute__((noinline)) unsigned __int128 abi_wide(uint64_t low, uint64_t high)
{ return ((unsigned __int128)high << 64) | low; }
__attribute__((noinline)) struct abi_large abi_aggregate(uint64_t a, uint64_t b, uint64_t c)
{ return (struct abi_large){a + 1, b + 2, c + 3}; }
__attribute__((noinline)) double abi_double(double a, double b)
{ return a * 2 + b; }
__attribute__((noinline)) double abi_variadic(unsigned count, ...)
{
    va_list args;
    va_start(args, count);
    double sum = 0;
    for (unsigned i = 0; i < count; ++i) sum += va_arg(args, double);
    va_end(args);
    return sum;
}
