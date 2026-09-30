#include <spdlog/sinks/ostream_sink.h>
#include <spdlog/spdlog.h>

#include <memory>
#include <sstream>

extern "C" int check_spdlog(void)
{
    std::ostringstream stream;
    auto sink = std::make_shared<spdlog::sinks::ostream_sink_mt>(stream);
    spdlog::logger logger("retguard_compatibility", sink);
    logger.set_pattern("%v");
    logger.info("answer {}", 42);
    logger.flush();
    return stream.str() != "answer 42\n";
}
