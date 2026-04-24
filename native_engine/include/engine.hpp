#pragma once

#include <filesystem>
#include <string>

namespace ksound::native {

struct EngineConfig {
    std::filesystem::path state_path;
    std::filesystem::path levels_path;
    std::filesystem::path log_path;
    int period_ms{20};
};

class Engine {
  public:
    explicit Engine(EngineConfig config);
    int run();

  private:
    void log(const std::string& line);
    void maybe_reload_state();
    void write_levels();

    EngineConfig config_;
    std::filesystem::file_time_type last_state_write_{};
    unsigned long long tick_{0};
};

} // namespace ksound::native
