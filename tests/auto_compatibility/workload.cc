#include "retguard.h"

#include <pthread.h>

#include <atomic>
#include <cstring>
#include <stdexcept>

extern "C" int mixed_manual(int);
extern "C" int auto_extra(int);

__attribute__((noinline)) static int recursive_sum(int value)
{
    RETGUARD_SCOPE();
    if (value == 0)
        return 0;
    return value + recursive_sum(value - 1);
}

struct EarlyProbe {
    EarlyProbe()
    {
        if (recursive_sum(3) != 6 || mixed_manual(41) != 42 ||
            auto_extra(41) != 42)
            __builtin_trap();
    }
};

static EarlyProbe early_probe __attribute__((init_priority(101)));

struct CleanupFlag {
    std::atomic<int> *value;
    ~CleanupFlag() { value->store(1, std::memory_order_relaxed); }
};

__attribute__((noinline)) static void throw_from_protected()
{
    throw std::runtime_error("expected");
}

__attribute__((noinline)) static void corrupt_normal_return()
{
    __asm__ volatile ("xorb $1, 15(%%rbp)" ::: "memory");
}

__attribute__((noinline)) static void corrupt_exception_return()
{
    __asm__ volatile ("xorb $1, 15(%%rbp)" ::: "memory");
    throw std::runtime_error("corrupt");
}

extern "C" __attribute__((noinline)) int auto_canary_probe()
{
    __asm__ volatile ("xorq $1, -8(%%rbp)" ::: "memory");
    return 7;
}

static void *cancel_target(void *argument)
{
    auto *cleaned = static_cast<std::atomic<int> *>(argument);
    CleanupFlag flag{cleaned};
    pthread_setcancelstate(PTHREAD_CANCEL_ENABLE, nullptr);
    pthread_setcanceltype(PTHREAD_CANCEL_DEFERRED, nullptr);
    for (;;)
        pthread_testcancel();
}

struct ExitState {
    std::atomic<int> cleaned{0};
};

static void *exit_target(void *argument)
{
    auto *state = static_cast<ExitState *>(argument);
    CleanupFlag flag{&state->cleaned};
    pthread_exit(reinterpret_cast<void *>(0x1234));
}

struct AsyncState {
    std::atomic<int> ready{0};
};

static void *async_cancel_target(void *argument)
{
    auto *state = static_cast<AsyncState *>(argument);
    pthread_setcancelstate(PTHREAD_CANCEL_ENABLE, nullptr);
    pthread_setcanceltype(PTHREAD_CANCEL_ASYNCHRONOUS, nullptr);
    state->ready.store(1, std::memory_order_release);
    for (;;)
        __asm__ volatile ("" ::: "memory");
}

static int check_returns()
{
    if (mixed_manual(41) != 42 || auto_extra(41) != 42)
        return 23;
    return recursive_sum(10) == 55 ? 0 : 1;
}

static int check_exception()
{
    try {
        throw_from_protected();
        return 2;
    } catch (const std::runtime_error &) {
    }
    return 0;
}

static int check_deferred_cancel()
{
    std::atomic<int> cleaned{0};
    pthread_t thread;
    if (pthread_create(&thread, nullptr, cancel_target, &cleaned) != 0)
        return 3;
    if (pthread_cancel(thread) != 0)
        return 4;
    void *result = nullptr;
    if (pthread_join(thread, &result) != 0)
        return 5;
    if (result != PTHREAD_CANCELED)
        return 6;
    if (cleaned.load(std::memory_order_relaxed) != 1)
        return 7;
    return 0;
}

static int check_thread_exit()
{
    ExitState exit_state;
    pthread_t thread;
    if (pthread_create(&thread, nullptr, exit_target, &exit_state) != 0)
        return 8;
    void *result = nullptr;
    if (pthread_join(thread, &result) != 0)
        return 9;
    if (result != reinterpret_cast<void *>(0x1234))
        return 10;
    if (exit_state.cleaned.load(std::memory_order_relaxed) != 1)
        return 11;
    return 0;
}

static int check_async_cancel()
{
    AsyncState async_state;
    pthread_t thread;
    if (pthread_create(&thread, nullptr, async_cancel_target, &async_state) != 0)
        return 12;
    while (async_state.ready.load(std::memory_order_acquire) == 0)
        __asm__ volatile ("" ::: "memory");
    if (pthread_cancel(thread) != 0)
        return 13;
    void *result = nullptr;
    if (pthread_join(thread, &result) != 0)
        return 14;
    if (result != PTHREAD_CANCELED)
        return 15;
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 2)
        return 2;
    if (std::strcmp(argv[1], "returns") == 0)
        return check_returns();
    if (std::strcmp(argv[1], "exception") == 0)
        return check_exception();
    if (std::strcmp(argv[1], "deferred_cancel") == 0)
        return check_deferred_cancel();
    if (std::strcmp(argv[1], "thread_exit") == 0)
        return check_thread_exit();
    if (std::strcmp(argv[1], "async_cancel") == 0)
        return check_async_cancel();
    if (std::strcmp(argv[1], "bad_return") == 0) {
        corrupt_normal_return();
        return 20;
    }
    if (std::strcmp(argv[1], "bad_exception") == 0) {
        try {
            corrupt_exception_return();
        } catch (...) {
            return 21;
        }
        return 22;
    }
    if (std::strcmp(argv[1], "bad_canary") == 0)
        return auto_canary_probe();
    return 2;
}
