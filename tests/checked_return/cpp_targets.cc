#include "retguard.h"

#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

class GadgetLedger {
public:
    RETGUARD_GADGET_FUNCTION
    GadgetLedger(int first, int second) : amounts_{first, second}
    {
        RETGUARD_GADGET_SCOPE();
    }

    RETGUARD_GADGET_FUNCTION
    int total() const
    {
        RETGUARD_GADGET_SCOPE();
        int sum = 0;
        for (int value : amounts_)
            sum += value;
        return sum;
    }

    RETGUARD_GADGET_FUNCTION
    void throw_bad_seal()
    {
        RETGUARD_GADGET_SCOPE();
        _retguard_scope.seal ^= 1;
        throw std::runtime_error("bad seal");
    }

private:
    std::vector<int> amounts_;
};

RETGUARD_GADGET_FUNCTION
std::unique_ptr<int> gadget_cpp_move(int value)
{
    RETGUARD_GADGET_SCOPE();
    auto result = std::make_unique<int>(value);
    return result;
}

extern "C" RETGUARD_GADGET_FUNCTION
int gadget_cpp_workload()
{
    RETGUARD_GADGET_SCOPE();
    GadgetLedger ledger(20, 22);
    auto result = gadget_cpp_move(ledger.total());
    return result && *result == 42;
}

extern "C" RETGUARD_GADGET_FUNCTION
void gadget_cpp_exception()
{
    RETGUARD_GADGET_SCOPE();
    GadgetLedger ledger(1, 2);
    if (ledger.total() == 3)
        throw std::runtime_error("expected");
}

extern "C" RETGUARD_GADGET_FUNCTION
void gadget_cpp_bad_exception()
{
    RETGUARD_GADGET_SCOPE();
    GadgetLedger ledger(1, 2);
    ledger.throw_bad_seal();
}
