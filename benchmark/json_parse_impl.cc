#include <nlohmann/json.hpp>

#include <cstddef>

extern "C" std::size_t retguard_json_parse(const char *data, std::size_t size)
{
    const auto value = nlohmann::json::parse(data, data + size);
    return value.size();
}
