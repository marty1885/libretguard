#include "retguard.h"

#include <asm/prctl.h>
#include <csignal>
#include <cstdint>
#include <cstring>
#include <stdexcept>
#include <sys/syscall.h>
#include <unistd.h>

struct gadget_pair { uint64_t first, second; };

extern "C" int plain_function(int);
extern "C" int scope_only(int);
extern "C" int gadget_normal(int);
extern "C" int gadget_recursive(int);
extern "C" void gadget_void(int *);
extern "C" gadget_pair gadget_pair_value(void);
extern "C" double gadget_double_value(void);
extern "C" int gadget_bad_address(void);
extern "C" int gadget_bad_seal(void);
extern "C" int gadget_no_scope(int);
extern "C" int gadget_bad_canary(void);
extern "C" void gadget_bypass(void);
extern "C" int gadget_cpp_workload(void);
extern "C" void gadget_cpp_exception(void);
extern "C" void gadget_cpp_bad_exception(void);

extern "C" void __real___stack_chk_fail() __attribute__((noreturn));
extern "C" __attribute__((noreturn, no_stack_protector)) void
__wrap___stack_chk_fail()
{
    static const char marker[] = "GADGET_STACK_CHK_FAIL\n";
    (void)write(STDERR_FILENO, marker, sizeof(marker) - 1);
    __real___stack_chk_fail();
}

static void control_protection_fault(int, siginfo_t *info, void *)
{
    if (info->si_code == SEGV_CPERR) {
        static const char marker[] = "GADGET_CET_CPERR\n";
        (void)write(STDERR_FILENO, marker, sizeof(marker) - 1);
        _exit(86);
    }
    _exit(87);
}

static volatile sig_atomic_t signal_gap_count;

static void signal_gap_handler(int)
{
    ++signal_gap_count;
    __asm__ volatile ("xor %%r11d, %%r11d" ::: "r11");
}

int main(int argc, char **argv)
{
    if (argc != 2)
        return 2;
    if (std::strcmp(argv[1], "cet_status") == 0) {
        unsigned long features = 0;
        if (syscall(SYS_arch_prctl, ARCH_SHSTK_STATUS, &features) == 0 &&
            (features & ARCH_SHSTK_SHSTK) != 0) {
            static const char marker[] = "GADGET_CET_ACTIVE\n";
            (void)write(STDOUT_FILENO, marker, sizeof(marker) - 1);
        }
        return 0;
    }
    if (std::strcmp(argv[1], "normal") == 0) {
        int void_result = 0;
        gadget_void(&void_result);
        auto pair = gadget_pair_value();
        return void_result == 42 && plain_function(2) == 3 &&
               scope_only(3) == 4 &&
               gadget_normal(4) == 5 &&
               gadget_normal(-1) == -1 && gadget_recursive(5) == 5 &&
               pair.first == UINT64_C(0x123456789abcdef0) &&
               pair.second == UINT64_C(0xfedcba9876543210) &&
               gadget_double_value() == 3.25 && gadget_cpp_workload() ? 0 : 3;
    }
    if (std::strcmp(argv[1], "signal_gap") == 0) {
        struct sigaction action = {};
        action.sa_handler = signal_gap_handler;
        if (sigaction(SIGTRAP, &action, nullptr) != 0)
            return 10;
        return gadget_normal(4) == 5 && signal_gap_count == 1 ? 0 : 11;
    }
    if (std::strcmp(argv[1], "exception") == 0) {
        try {
            gadget_cpp_exception();
        } catch (const std::runtime_error &) {
            return 0;
        }
        return 4;
    }
    if (std::strcmp(argv[1], "bad_exception") == 0) {
        try {
            gadget_cpp_bad_exception();
        } catch (...) {
            return 5;
        }
        return 6;
    }
    if (std::strcmp(argv[1], "bad_address") == 0)
        return gadget_bad_address();
    if (std::strcmp(argv[1], "bad_seal") == 0)
        return gadget_bad_seal();
    if (std::strcmp(argv[1], "no_scope") == 0)
        return gadget_no_scope(7);
    if (std::strcmp(argv[1], "bad_canary") == 0)
        return gadget_bad_canary();
    if (std::strcmp(argv[1], "bypass") == 0) {
        gadget_bypass();
        return 7;
    }
    if (std::strcmp(argv[1], "cet_plain_corrupt") == 0) {
        struct sigaction action = {};
        action.sa_sigaction = control_protection_fault;
        action.sa_flags = SA_SIGINFO;
        if (sigaction(SIGSEGV, &action, nullptr) != 0)
            return 8;
        __asm__ volatile ("xorq $1, 8(%%rbp)" ::: "memory");
        return 9;
    }
    return 2;
}
