#define _GNU_SOURCE
#include "retguard.h"

#include <asm/prctl.h>
#include <signal.h>
#include <stdint.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

#if TEST_CET
# if !defined(__CET__) || (__CET__ & 3) != 3
#  error "CET fixture must be compiled with branch and return protection"
# endif
#endif

/* The linker wraps compiler-emitted calls. The marker identifies the
   stack-protector failure path; calling the real handler then checks that
   the process still gets glibc's normal fatal response. */
extern void __real___stack_chk_fail(void) __attribute__((noreturn));

__attribute__((noreturn, no_stack_protector)) void
__wrap___stack_chk_fail(void)
{
    static const char marker[] = "STACK_CHK_FAIL_HOOK\n";
    (void)write(STDERR_FILENO, marker, sizeof(marker) - 1);
    __real___stack_chk_fail();
}

__attribute__((noinline)) int
normal_unguarded(int x)
{
    return x + 1;
}

__attribute__((noinline)) int
normal_scope(int x)
{
    RETGUARD_SCOPE();
    return x + 1;
}

__attribute__((noinline)) int
normal_explicit(int x)
{
    RETGUARD_BEGIN();
    RETGUARD_RETURN(x + 1);
}

/* The test runner verifies in disassembly that -8(%rbp) contains the
   compiler canary in each stack-protected variant. These probes never run
   when stack protection is disabled. */
__attribute__((noinline)) int
ssp_unguarded(void)
{
    __asm__ volatile ("xorq $1, -8(%%rbp)" ::: "memory");
    return 7;
}

__attribute__((noinline)) int
ssp_guarded(void)
{
    RETGUARD_SCOPE();
    __asm__ volatile ("xorq $1, -8(%%rbp)" ::: "memory");
    return 7;
}

__attribute__((noinline)) int
ssp_before_cet(void)
{
    __asm__ volatile ("xorq $1, -8(%%rbp)\n\t"
                      "xorq $1, 8(%%rbp)" ::: "memory");
    return 7;
}

__attribute__((noinline)) int
cet_unguarded(void)
{
    __asm__ volatile ("xorq $1, 8(%%rbp)" ::: "memory");
    return 7;
}

static int
shadow_stack_active(void)
{
    unsigned long features = 0;
    return syscall(SYS_arch_prctl, ARCH_SHSTK_STATUS, &features) == 0 &&
           (features & ARCH_SHSTK_SHSTK) != 0;
}

static void
control_protection_fault(int signal_number, siginfo_t *info, void *context)
{
    (void)signal_number;
    (void)context;
    if (info->si_code == SEGV_CPERR) {
        static const char marker[] = "CET_CPERR\n";
        (void)write(STDERR_FILENO, marker, sizeof(marker) - 1);
        _exit(86);
    }
    _exit(87);
}

int
main(int argc, char **argv)
{
    if (argc != 2)
        return 2;
    if (strcmp(argv[1], "cet_status") == 0) {
        if (shadow_stack_active()) {
            static const char marker[] = "CET_ACTIVE\n";
            (void)write(STDOUT_FILENO, marker, sizeof(marker) - 1);
        }
        return 0;
    }

    if (strcmp(argv[1], "normal") == 0)
        return normal_unguarded(7) == 8 &&
               normal_scope(7) == 8 && normal_explicit(7) == 8 ? 0 : 3;
    if (strcmp(argv[1], "ssp_unguarded") == 0)
        return ssp_unguarded();
    if (strcmp(argv[1], "ssp_guarded") == 0)
        return ssp_guarded();
    if (strcmp(argv[1], "ssp_before_cet") == 0)
        return ssp_before_cet();
    if (strcmp(argv[1], "cet_unguarded") == 0) {
        struct sigaction action = { 0 };
        action.sa_sigaction = control_protection_fault;
        action.sa_flags = SA_SIGINFO;
        if (sigaction(SIGSEGV, &action, NULL) != 0)
            return 4;
        return cet_unguarded();
    }
    return 2;
}
