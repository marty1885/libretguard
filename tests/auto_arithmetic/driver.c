#include "api.h"
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
extern uintptr_t retguard_auto_cookies[16], retguard_auto_masks[16];
extern char arithmetic_return_label[];
struct observations {
    uint64_t encoded, arguments[7], returns[2], vectors[2], corrupt, final_stack;
};
_Static_assert(offsetof(struct observations, corrupt) == 96, "assembly context layout");
_Static_assert(offsetof(struct observations, final_stack) == 104, "assembly context layout");
extern void arithmetic_bridge(struct observations *, void *);
static uint64_t random_word(uint64_t *state)
{
    uint64_t x = *state;
    x ^= x << 13; x ^= x >> 7; x ^= x << 17;
    return *state = x;
}
static int failure(const char *message)
{ fprintf(stderr, "%s\n", message); return 1; }
int main(int argc, char **argv)
{
    if (argc > 2 || (argc == 2 && strcmp(argv[1], "bad-tag"))) return 2;
    void *allocation = NULL;
    if (posix_memalign(&allocation, 4096, 18 * 4096) != 0) return 2;
    uintptr_t base = (uintptr_t)allocation + 4096;
    uint64_t saved_cookies[16], saved_masks[16];
    memcpy(saved_cookies, retguard_auto_cookies, sizeof saved_cookies);
    memcpy(saved_masks, retguard_auto_masks, sizeof saved_masks);
    uint64_t seed = UINT64_C(0x251ce317529ffbad);
    const uint64_t low56 = UINT64_C(0x00ffffffffffffff);
    uintptr_t raw = (uintptr_t)arithmetic_return_label;
    if ((raw & ~low56) != 0) return failure("test return address outside supported low56");
    unsigned checks = 0;
    for (unsigned round = 0; round < 8; ++round) {
        for (unsigned i = 0; i < 16; ++i) {
            retguard_auto_cookies[i] = random_word(&seed) | 1;
            retguard_auto_masks[i] = random_word(&seed) & low56;
        }
        for (unsigned ci = 0; ci < 16; ++ci) for (unsigned mi = 0; mi < 16; ++mi) {
            // Actual page-number bits select the mask slot, independent of cookie slot.
            unsigned page = ((ci ^ mi) - ((base >> 12) & 15)) & 15;
            uintptr_t slot = base + page * 4096 + ci * 16;
            if (((slot >> 4) & 15) != ci || (((slot >> 4) ^ (slot >> 12)) & 15) != mi)
                return failure("slot selection failed");
            uint64_t payload = raw ^ retguard_auto_masks[mi];
            uint64_t tag;
            do {
                tag = ((payload ^ slot) * retguard_auto_cookies[ci]) >> 56;
                if (!tag) retguard_auto_cookies[ci] = random_word(&seed) | 1;
            } while (!tag);
            uint64_t expected = payload | (tag << 56);
            struct observations actual = {0};
            actual.corrupt = argc == 2;
            arithmetic_bridge(&actual, (void *)slot);
            if (actual.encoded != expected) return failure("mask/tag arithmetic differs from independent formula");
            const uint64_t arguments[] = {11,22,33,44,55,66,7};
            if (memcmp(arguments, actual.arguments, sizeof arguments)) return failure("entry clobbered argument registers or AL");
            if (actual.returns[0] != UINT64_C(0x123456789abcdef0) ||
                actual.returns[1] != UINT64_C(0xfedcba9876543210) ||
                actual.vectors[0] != UINT64_C(0x4029000000000000) ||
                actual.vectors[1] != UINT64_C(0xc011000000000000))
                return failure("return thunk clobbered return registers");
            if (*(uint64_t *)slot != raw || actual.final_stack != slot + 8)
                return failure("return thunk did not restore exact raw address/stack");
            ++checks;
        }
    }
    memcpy(retguard_auto_cookies, saved_cookies, sizeof saved_cookies);
    memcpy(retguard_auto_masks, saved_masks, sizeof saved_masks);
    free(allocation);
    if (abi_arguments(1,2,3,4,5,6) != 135) return failure("six argument ABI mismatch");
    uint64_t low = UINT64_C(0x123456789abcdef0), high = UINT64_C(0xfedcba9876543210);
    unsigned __int128 wide = abi_wide(low, high);
    if ((uint64_t)wide != low || (uint64_t)(wide >> 64) != high) return failure("int128 return ABI mismatch");
    struct abi_large large = abi_aggregate(10,20,30);
    if (large.a != 11 || large.b != 22 || large.c != 33) return failure("aggregate sret ABI mismatch");
    if (abi_double(2.5, 1.25) != 6.25) return failure("double ABI mismatch");
    if (abi_variadic(3, 1.25, 2.5, 5.0) != 8.75) return failure("varargs AL/vector ABI mismatch");
    printf("%u arithmetic/register cases plus compiled ABI cases passed\n", checks);
    return 0;
}
