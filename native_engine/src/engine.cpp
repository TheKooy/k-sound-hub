#include "engine.hpp"

#include "files.hpp"
#include "realtime.hpp"

#include <chrono>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <thread>
#include <fstream>

namespace ksound::native {

namespace {
std::string now_string() {
    auto now = std::chrono::system_clock::now();
    std::time_t tt = std::chrono::system_clock::to_time_t(now);
    std::tm tm{};
    localtime_r(&tt, &tm);
    std::ostringstream out;
    out << std::put_time(&tm, "%F %T");
    return out.str();
}
} // namespace

Engine::Engine(EngineConfig config) : config_(std::move(config)) {}

void Engine::log(const std::string& line) {
    std::filesystem::create_directories(config_.log_path.parent_path());
    std::ofstream out(config_.log_path, std::ios::app);
    out << "[" << now_string() << "] " << line << "\n";
}

void Engine::maybe_reload_state() {
    auto current = safe_last_write_time(config_.state_path);
    if (current == std::filesystem::file_time_type{}) {
        return;
    }
    if (current == last_state_write_) {
        return;
    }
    last_state_write_ = current;
    auto text = read_text_file(config_.state_path);
    log("state_reload bytes=" + std::to_string(text.size()));
}

void Engine::write_levels() {
    std::ostringstream json;
    json << "{\n"
         << "  \"engine\": \"ksound_native_engine\",\n"
         << "  \"tick\": " << tick_ << ",\n"
         << "  \"periodMs\": " << config_.period_ms << "\n"
         << "}\n";
    write_text_file(config_.levels_path, json.str());
}

int Engine::run() {
    log("engine_start " + try_enable_realtime());
    log("state=" + config_.state_path.string());
    log("levels=" + config_.levels_path.string());

    while (true) {
        ++tick_;
        maybe_reload_state();
        write_levels();
        std::this_thread::sleep_for(std::chrono::milliseconds(config_.period_ms));
    }

    return 0;
}

} // namespace ksound::native
