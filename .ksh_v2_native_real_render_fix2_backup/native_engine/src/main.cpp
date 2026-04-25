#include "engine.hpp"

#include <iostream>
#include <string>

using namespace ksound::native;

int main(int argc, char** argv) {
    EngineConfig config;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) {
                throw std::runtime_error("missing value for " + arg);
            }
            return argv[++i];
        };

        if (arg == "--state") {
            config.state_path = next();
        } else if (arg == "--levels") {
            config.levels_path = next();
        } else if (arg == "--log") {
            config.log_path = next();
        } else if (arg == "--period-ms") {
            config.period_ms = std::stoi(next());
        } else {
            std::cerr << "Unknown arg: " << arg << "\n";
            return 2;
        }
    }

    if (config.state_path.empty() || config.levels_path.empty() || config.log_path.empty()) {
        std::cerr << "Usage: ksound_native_engine --state <path> --levels <path> --log <path> [--period-ms <n>]\n";
        return 2;
    }

    try {
        Engine engine(config);
        return engine.run();
    } catch (const std::exception& e) {
        std::cerr << "Fatal: " << e.what() << "\n";
        return 1;
    }
}
