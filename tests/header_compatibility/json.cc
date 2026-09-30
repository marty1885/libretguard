#include <nlohmann/json.hpp>

extern "C" int check_json(void)
{
    const auto value = nlohmann::json::parse(
        R"({"name":"retguard","values":[1,2,3],"enabled":true})");
    const auto round_trip = nlohmann::json::parse(value.dump());
    return round_trip.at("name") != "retguard" ||
           round_trip.at("values").get<std::vector<int>>() !=
               std::vector<int>({1, 2, 3}) ||
           !round_trip.at("enabled").get<bool>();
}
