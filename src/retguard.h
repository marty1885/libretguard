#ifndef RETGUARD_H
#define RETGUARD_H

#if !defined(__linux__) || !defined(__x86_64__) || (!defined(__GNUC__) && !defined(__clang__))
#error "This RETGUARD macro requires Linux x86-64 and GCC or Clang"
#endif

#ifdef RETGUARD_AUTO
/* retguard_target() instruments entry and return in every compiled function.
   Manual annotations can remain in shared source without adding a second
   guard or selecting the manual return thunk. */
#define RETGUARD_SCOPE() do { } while (0)
#define RETGUARD_GADGET_SCOPE() do { } while (0)
#define RETGUARD_GADGET_FUNCTION
#define RETGUARD_BEGIN() do { } while (0)
#define RETGUARD_CHECK() do { } while (0)
#define RETGUARD_RETURN(value) do { return (value); } while (0)
#define RETGUARD_RETURN_VOID() do { return; } while (0)

#else

#include <stdint.h>
#include <stdlib.h>

#ifdef __cplusplus
extern "C" {
#endif
/* Both modes select a cookie from the return-address slot's address. */
extern __attribute__((visibility("hidden"))) uintptr_t retguard_auto_cookies[16];
extern __attribute__((visibility("hidden"))) uintptr_t retguard_auto_masks[16];
extern __attribute__((visibility("hidden"))) int retguard_ready;
#ifdef __cplusplus
}
#endif

static inline uintptr_t *
retguard_return_slot(void *frame)
{
    return (uintptr_t *)frame + 1;
}

static inline uintptr_t
retguard_return_address_at(void *frame)
{
    uintptr_t address;
    const uintptr_t *slot = retguard_return_slot(frame);
    __asm__ volatile ("movq (%1), %0" : "=r"(address) : "r"(slot) : "memory");
    return address;
}

static inline uintptr_t
retguard_seal(void *frame)
{
    if (__builtin_expect(!retguard_ready, 0))
        abort();
    uintptr_t slot = (uintptr_t)retguard_return_slot(frame);
    uintptr_t cookie = retguard_auto_cookies[(slot >> 4) & 15];
    return (retguard_return_address_at(frame) ^ slot) * cookie;
}

static inline void
retguard_verify(void *frame, volatile uintptr_t *seal)
{
    if (__builtin_expect(retguard_seal(frame) != *seal, 0))
        abort();
}

struct retguard_scope {
    volatile uintptr_t seal;
};

static inline struct retguard_scope
retguard_scope_start(void *frame)
{
    struct retguard_scope scope = { retguard_seal(frame) };
    return scope;
}

static __attribute__((always_inline)) inline void
retguard_scope_end(struct retguard_scope *scope)
{
    retguard_verify(__builtin_frame_address(0), &scope->seal);
}

/* One declaration at function scope checks every ordinary return and
   fallthrough. Place it directly inside the function's opening brace. */
#define RETGUARD_SCOPE()                                                     \
    struct retguard_scope _retguard_scope                                    \
        __attribute__((cleanup(retguard_scope_end))) =                      \
            retguard_scope_start(__builtin_frame_address(0))

/* Use these two macros together: the gadget scope alone exposes its seal in
   r11 on an ordinary return. GCC translation units need -ffixed-r11. Clang
   has no equivalent switch; its generated epilogues must be audited. */
#if defined(__GNUC__) || defined(__clang__)
static __attribute__((always_inline)) inline void
retguard_scope_end_gadget(struct retguard_scope *scope)
{
    retguard_verify(__builtin_frame_address(0), &scope->seal);
    __asm__ volatile ("movq %0, %%r11" : : "r"(scope->seal) : "r11", "memory");
}

#define RETGUARD_GADGET_SCOPE()                                              \
    struct retguard_scope _retguard_scope                                    \
        __attribute__((cleanup(retguard_scope_end_gadget))) =               \
            retguard_scope_start(__builtin_frame_address(0))

#if defined(__clang__)
/* Clang 22 has no -ffixed-r11. Its zero-call-used-regs pass otherwise
   destroys the r11 handoff before the return thunk. Newer Clang builds can
   define RETGUARD_CLANG_FIXED_R11 while passing -ffixed-r11; then the
   register clearing pass can run and the thunk clears r11 after its check. */
#if defined(RETGUARD_CLANG_FIXED_R11)
#define RETGUARD_GADGET_FUNCTION                                             \
    __attribute__((noinline, function_return("thunk-extern")))
#else
#define RETGUARD_GADGET_FUNCTION                                             \
    __attribute__((noinline, function_return("thunk-extern"),               \
                   zero_call_used_regs("skip")))
#endif
#else
#define RETGUARD_GADGET_FUNCTION                                             \
    __attribute__((noinline, function_return("thunk-extern")))
#endif
#else
#define RETGUARD_GADGET_SCOPE() RETGUARD_GADGET_SCOPE_REQUIRES_GCC
#define RETGUARD_GADGET_FUNCTION RETGUARD_GADGET_FUNCTION_REQUIRES_GCC
#endif

/* Explicit-return API, retained for callers that need a check at a
   particular return site. Do not combine it with either scope macro. */
#define RETGUARD_BEGIN()                                                     \
    volatile uintptr_t _retguard_seal =                                      \
        retguard_seal(__builtin_frame_address(0))

/* Use this immediately before a plain return, or use RETGUARD_RETURN. */
#define RETGUARD_CHECK()                                                     \
    retguard_verify(__builtin_frame_address(0), &_retguard_seal)

/* Evaluate the expression once before checking. */
#ifdef __cplusplus
#define RETGUARD_RESULT_TYPE decltype(auto)
#define RETGUARD_RETURN_RESULT(expression, result)                           \
    static_cast<decltype((expression))>(                                    \
        static_cast<decltype(result) &&>(result))
#else
#define RETGUARD_RESULT_TYPE __auto_type
#define RETGUARD_RETURN_RESULT(expression, result) result
#endif
#define RETGUARD_RETURN(value) do {                                          \
    RETGUARD_RESULT_TYPE _retguard_result = (value);                         \
    RETGUARD_CHECK();                                                         \
    return RETGUARD_RETURN_RESULT(value, _retguard_result);                  \
} while (0)

#define RETGUARD_RETURN_VOID() do {                                          \
    RETGUARD_CHECK();                                                         \
    return;                                                                   \
} while (0)

#endif /* RETGUARD_AUTO */
#endif
