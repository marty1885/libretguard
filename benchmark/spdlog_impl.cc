#include <spdlog/sinks/ostream_sink.h>
#include <spdlog/spdlog.h>
#include <memory>
#include <sstream>
#include <string>
static std::string log_messages(const char *message, std::size_t size, unsigned count)
{
    std::ostringstream stream;
    auto sink = std::make_shared<spdlog::sinks::ostream_sink_mt>(stream);
    spdlog::logger logger("benchmark", sink);
    logger.set_pattern("%v");
    const std::string text(message, size);
    for (unsigned i = 0; i < count; ++i) logger.info("{} {}", text, 42);
    logger.flush();
    return stream.str();
}

extern "C" std::size_t retguard_spdlog_log(const char *message, std::size_t size, unsigned count)
{
    return log_messages(message, size, count).size();
}
extern "C" bool retguard_spdlog_check(const char *message, std::size_t size, unsigned count)
{
    std::string expected;
    for (unsigned i = 0; i < count; ++i) { expected.append(message, size); expected += " 42\n"; }
    return log_messages(message, size, count) == expected;
}
