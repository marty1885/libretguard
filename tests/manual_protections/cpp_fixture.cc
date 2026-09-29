#include "retguard.h"

#include <asm/prctl.h>
#include <algorithm>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>
#include <sys/syscall.h>
#include <unistd.h>

#if TEST_CET
# if !defined(__CET__) || (__CET__ & 3) != 3
#  error "C++ CET fixture must have branch and return protection"
# endif
#endif

extern "C" void __real___stack_chk_fail() __attribute__((noreturn));

extern "C" __attribute__((noreturn, no_stack_protector)) void
__wrap___stack_chk_fail()
{
    static const char marker[] = "CPP_STACK_CHK_FAIL_HOOK\n";
    (void)write(STDERR_FILENO, marker, sizeof(marker) - 1);
    __real___stack_chk_fail();
}

extern "C" __attribute__((noinline)) int cpp_ssp_guarded()
{
    RETGUARD_SCOPE();
    __asm__ volatile ("xorq $1, -8(%%rbp)" ::: "memory");
    return 7;
}

__attribute__((noinline)) static int before_main_guarded()
{
    RETGUARD_SCOPE();
    return 42;
}

struct BeforeMainProbe {
    BeforeMainProbe()
    {
        if (before_main_guarded() != 42)
            __builtin_trap();
    }
};

static BeforeMainProbe before_main_probe __attribute__((init_priority(101)));

struct Account {
    std::string name;
    int balance;
};

class Ledger {
public:
    explicit Ledger(std::vector<Account> accounts)
        : accounts_(std::move(accounts)) {}

    __attribute__((noinline)) int balance(const std::string &name) const
    {
        RETGUARD_SCOPE();
        auto found = std::find_if(accounts_.begin(), accounts_.end(),
                                  [&](const Account &account) {
                                      return account.name == name;
                                  });
        if (found == accounts_.end())
            throw std::out_of_range("unknown account");
        return found->balance;
    }

    __attribute__((noinline)) void transfer(const std::string &from,
                                             const std::string &to, int amount)
    {
        RETGUARD_SCOPE();
        if (amount < 0 || balance(from) < amount)
            throw std::invalid_argument("invalid transfer");
        auto source = std::find_if(accounts_.begin(), accounts_.end(),
                                   [&](const Account &a) { return a.name == from; });
        auto destination = std::find_if(accounts_.begin(), accounts_.end(),
                                        [&](const Account &a) { return a.name == to; });
        if (destination == accounts_.end())
            throw std::out_of_range("unknown destination");
        source->balance -= amount;
        destination->balance += amount;
    }

private:
    std::vector<Account> accounts_;
};

template <typename T>
__attribute__((noinline)) T add(T a, T b)
{
    RETGUARD_SCOPE();
    return a + b;
}

__attribute__((noinline)) std::unique_ptr<int> make_value(int value)
{
    RETGUARD_BEGIN();
    RETGUARD_RETURN(std::make_unique<int>(value));
}

__attribute__((noinline)) std::unique_ptr<int> move_value(int value)
{
    RETGUARD_BEGIN();
    auto result = std::make_unique<int>(value);
    RETGUARD_RETURN(std::move(result));
}

__attribute__((noinline)) const int &identity(const int &value)
{
    RETGUARD_BEGIN();
    RETGUARD_RETURN(value);
}

__attribute__((noinline)) void throw_after_guard()
{
    RETGUARD_SCOPE();
    throw std::runtime_error("expected");
}

/* A failed seal during C++ unwinding proves cleanup runs on that path. */
__attribute__((noinline)) void throw_with_bad_seal()
{
    RETGUARD_SCOPE();
    _retguard_scope.seal ^= 1;
    throw std::runtime_error("must not reach catch");
}

int main(int argc, char **argv)
{
#if TEST_CET
    unsigned long features = 0;
    if (syscall(SYS_arch_prctl, ARCH_SHSTK_STATUS, &features) != 0 ||
        (features & ARCH_SHSTK_SHSTK) == 0)
        return 12;
#endif
    if (argc == 2 && std::string(argv[1]) == "bad_canary")
        return cpp_ssp_guarded();
    if (argc == 2 && std::string(argv[1]) == "bad_seal") {
        try {
            throw_with_bad_seal();
        } catch (...) {
            return 10;
        }
        return 11;
    }

    Ledger ledger({{"alice", 50}, {"bob", 10}});
    ledger.transfer("alice", "bob", 20);
    if (ledger.balance("alice") != 30 || ledger.balance("bob") != 30)
        return 1;
    try {
        ledger.transfer("alice", "bob", 100);
        return 2;
    } catch (const std::invalid_argument &) {
    }
    try {
        throw_after_guard();
        return 3;
    } catch (const std::runtime_error &) {
    }
    auto value = make_value(add(20, 22));
    auto moved = move_value(21);
    if (!value || *value != 42 || &identity(*value) != value.get() ||
        !moved || *moved != 21)
        return 4;
    return 0;
}
