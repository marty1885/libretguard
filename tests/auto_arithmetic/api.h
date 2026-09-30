#ifndef RETGUARD_AUTO_ARITHMETIC_API_H
#define RETGUARD_AUTO_ARITHMETIC_API_H
#include <stdint.h>
struct abi_large { uint64_t a, b, c; };
uint64_t abi_arguments(uint64_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);
unsigned __int128 abi_wide(uint64_t, uint64_t);
struct abi_large abi_aggregate(uint64_t, uint64_t, uint64_t);
double abi_double(double, double);
double abi_variadic(unsigned, ...);
#endif
