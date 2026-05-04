#pragma once

#include <filesystem>
#include <string>

namespace ksound::native {

struct EngineConfig {
    std::filesystem::path state_path;
    std::filesystem::path volume_state_path;
    std::filesystem::path levels_path;
    std::filesystem::path log_path;
    int period_ms{20};
};

class Engine {
  public:
    explicit Engine(EngineConfig config);
    ~Engine();
    int run();

  private:
    void log(const std::string& line);
    void maybe_reload_state();
    void maybe_reload_volume_state();
    void tick_once();
    void write_levels();
    void stop_all();

    EngineConfig config_;
    std::filesystem::file_time_type last_state_write_{};
    std::filesystem::file_time_type last_volume_state_write_{};
};

} // namespace ksound::native
