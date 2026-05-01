#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstring>
#include <cstdio>
#include <fcntl.h>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <sys/types.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace {
constexpr int RATE = 48000;
constexpr int CHANNELS = 2;
constexpr int CHUNK_FRAMES = 480; // 10 ms @ 48 kHz
constexpr int SAMPLE_BYTES = 4;
constexpr int CHUNK_SAMPLES = CHUNK_FRAMES * CHANNELS;
constexpr int CHUNK_BYTES = CHUNK_SAMPLES * SAMPLE_BYTES;
constexpr float MAX_OUTPUT = 0.98f;

volatile std::sig_atomic_t g_running = 1;

void signal_handler(int) {
    g_running = 0;
}

float clampf(float value, float low, float high) {
    return std::max(low, std::min(high, value));
}

float volume_percent_to_gain(float percent) {
    percent = clampf(percent, 0.0f, 150.0f);
    if (percent <= 100.0f) {
        const float normalized = percent / 100.0f;
        return normalized * normalized;
    }
    return 1.0f + ((percent - 100.0f) / 100.0f);
}

std::vector<std::string> split_tab(const std::string& line) {
    std::vector<std::string> out;
    std::string current;
    for (char c : line) {
        if (c == '\t') {
            out.push_back(current);
            current.clear();
        } else {
            current.push_back(c);
        }
    }
    out.push_back(current);
    return out;
}

struct ChildProcess {
    pid_t pid{-1};
    int fd{-1};
    bool write_mode{false};

    bool running() const {
        if (pid <= 0) {
            return false;
        }
        int status = 0;
        pid_t res = waitpid(pid, &status, WNOHANG);
        return res == 0;
    }

    void stop() {
        if (fd >= 0) {
            ::close(fd);
            fd = -1;
        }

        if (pid > 0) {
            if (running()) {
                ::kill(pid, SIGTERM);
                for (int i = 0; i < 20; ++i) {
                    if (!running()) {
                        break;
                    }
                    std::this_thread::sleep_for(std::chrono::milliseconds(20));
                }
                if (running()) {
                    ::kill(pid, SIGKILL);
                }
            }
            int status = 0;
            waitpid(pid, &status, WNOHANG);
            pid = -1;
        }
    }
};

ChildProcess spawn_process(const std::vector<std::string>& args, bool write_mode) {
    int pipefd[2];
    if (pipe(pipefd) != 0) {
        return {};
    }

    pid_t pid = fork();
    if (pid < 0) {
        ::close(pipefd[0]);
        ::close(pipefd[1]);
        return {};
    }

    if (pid == 0) {
        if (write_mode) {
            dup2(pipefd[0], STDIN_FILENO);
        } else {
            dup2(pipefd[1], STDOUT_FILENO);
        }

        int devnull = ::open("/dev/null", O_WRONLY);
        if (devnull >= 0) {
            dup2(devnull, STDERR_FILENO);
            ::close(devnull);
        }

        ::close(pipefd[0]);
        ::close(pipefd[1]);

        std::vector<char*> argv;
        argv.reserve(args.size() + 1);
        for (const auto& arg : args) {
            argv.push_back(const_cast<char*>(arg.c_str()));
        }
        argv.push_back(nullptr);
        execvp(argv[0], argv.data());
        _exit(127);
    }

    ChildProcess proc;
    proc.pid = pid;
    proc.write_mode = write_mode;

    if (write_mode) {
        ::close(pipefd[0]);
        proc.fd = pipefd[1];
    } else {
        ::close(pipefd[1]);
        proc.fd = pipefd[0];
        int flags = fcntl(proc.fd, F_GETFL, 0);
        if (flags >= 0) {
            fcntl(proc.fd, F_SETFL, flags | O_NONBLOCK);
        }
    }

    return proc;
}

struct SourceSpec {
    std::string key;
    std::string source_name;
    float gain{1.0f};
};

struct MicroState {
    bool enabled{true};
    bool muted{false};
    float volume_percent{100.0f};
    std::string mic_source;
    std::vector<SourceSpec> sends;

    bool return_enabled{false};
    bool return_muted{false};
    float return_volume_percent{100.0f};
    std::string return_target_sink{"retour"};
    std::vector<SourceSpec> return_sources;
};

struct CaptureClient {
    std::string source_name;
    ChildProcess proc;
    std::vector<char> buffer;

    void stop() {
        proc.stop();
        buffer.clear();
    }

    void ensure_started() {
        if (proc.running()) {
            return;
        }

        stop();

        proc = spawn_process(
            {
                "parec",
                "--device=" + source_name,
                "--raw",
                "--format=float32le",
                "--rate=48000",
                "--channels=2",
                "--latency-msec=20",
            },
            false
        );
    }

    std::vector<float> read_chunk() {
        ensure_started();

        std::vector<float> silence(CHUNK_SAMPLES, 0.0f);
        if (!proc.running() || proc.fd < 0) {
            return silence;
        }

        for (int i = 0; i < 16; ++i) {
            char tmp[65536];
            ssize_t n = ::read(proc.fd, tmp, sizeof(tmp));
            if (n > 0) {
                buffer.insert(buffer.end(), tmp, tmp + n);
                continue;
            }
            if (n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
                break;
            }
            if (n == 0) {
                break;
            }
            break;
        }

        if (static_cast<int>(buffer.size()) < CHUNK_BYTES) {
            return silence;
        }

        // Keep the newest chunk only. This avoids stale audio after routing changes.
        if (static_cast<int>(buffer.size()) > CHUNK_BYTES * 4) {
            buffer.erase(buffer.begin(), buffer.end() - CHUNK_BYTES);
        }

        std::vector<float> out(CHUNK_SAMPLES, 0.0f);
        std::memcpy(out.data(), buffer.data(), CHUNK_BYTES);
        buffer.erase(buffer.begin(), buffer.begin() + CHUNK_BYTES);
        return out;
    }
};

struct PlaybackClient {
    std::string sink_name;
    ChildProcess proc;

    void set_sink(std::string wanted) {
        if (wanted.empty()) {
            wanted = "micro_bus";
        }
        if (sink_name == wanted) {
            return;
        }
        sink_name = wanted;
        stop();
    }

    void stop() {
        proc.stop();
    }

    bool ensure_started() {
        if (sink_name.empty()) {
            return false;
        }

        if (proc.running() && proc.fd >= 0) {
            return true;
        }

        stop();

        proc = spawn_process(
            {
                "pacat",
                "--playback",
                "--device=" + sink_name,
                "--raw",
                "--format=float32le",
                "--rate=48000",
                "--channels=2",
                "--latency-msec=40",
                "--process-time-msec=10",
            },
            true
        );

        if (!proc.running() || proc.fd < 0) {
            proc = spawn_process(
                {
                    "pw-cat",
                    "--playback",
                    "--target",
                    sink_name,
                    "--rate",
                    "48000",
                    "--channels",
                    "2",
                    "--format",
                    "f32",
                },
                true
            );
        }

        return proc.running() && proc.fd >= 0;
    }

    void write(const std::vector<float>& frames) {
        if (!ensure_started()) {
            return;
        }

        std::vector<float> safe = frames;
        float peak = 0.0f;
        for (float sample : safe) {
            if (std::isfinite(sample)) {
                peak = std::max(peak, std::fabs(sample));
            }
        }

        if (peak > MAX_OUTPUT) {
            const float scale = MAX_OUTPUT / peak;
            for (float& sample : safe) {
                sample = std::isfinite(sample) ? sample * scale : 0.0f;
            }
        } else {
            for (float& sample : safe) {
                sample = std::isfinite(sample) ? sample : 0.0f;
            }
        }

        const char* data = reinterpret_cast<const char*>(safe.data());
        std::size_t total = safe.size() * sizeof(float);
        std::size_t done = 0;

        while (done < total) {
            ssize_t n = ::write(proc.fd, data + done, total - done);
            if (n > 0) {
                done += static_cast<std::size_t>(n);
                continue;
            }
            stop();
            return;
        }
    }
};

MicroState parse_state_file(const std::string& path) {
    MicroState state;
    std::ifstream in(path);
    if (!in) {
        return state;
    }

    std::string line;
    while (std::getline(in, line)) {
        if (line.empty()) {
            continue;
        }

        auto parts = split_tab(line);
        if (parts.empty()) {
            continue;
        }

        if (parts[0] == "enabled" && parts.size() >= 2) {
            state.enabled = parts[1] == "1";
        } else if (parts[0] == "muted" && parts.size() >= 2) {
            state.muted = parts[1] == "1";
        } else if (parts[0] == "volume" && parts.size() >= 2) {
            try {
                state.volume_percent = std::stof(parts[1]);
            } catch (...) {
                state.volume_percent = 100.0f;
            }
        } else if (parts[0] == "source" && parts.size() >= 2) {
            state.mic_source = parts[1];
        } else if (parts[0] == "send" && parts.size() >= 4) {
            if (parts[2] != "1") {
                continue;
            }

            SourceSpec spec;
            spec.key = parts[1];
            spec.source_name = parts[3];

            if (parts.size() >= 5) {
                try {
                    spec.gain = std::stof(parts[4]);
                } catch (...) {
                    spec.gain = 1.0f;
                }
            }

            if (!spec.source_name.empty()) {
                state.sends.push_back(spec);
            }
        } else if (parts[0] == "return_enabled" && parts.size() >= 2) {
            state.return_enabled = parts[1] == "1";
        } else if (parts[0] == "return_muted" && parts.size() >= 2) {
            state.return_muted = parts[1] == "1";
        } else if (parts[0] == "return_volume" && parts.size() >= 2) {
            try {
                state.return_volume_percent = std::stof(parts[1]);
            } catch (...) {
                state.return_volume_percent = 100.0f;
            }
        } else if (parts[0] == "return_target" && parts.size() >= 2) {
            state.return_target_sink = parts[1].empty() ? "retour" : parts[1];
        } else if (parts[0] == "return_source" && parts.size() >= 4) {
            if (parts[2] != "1") {
                continue;
            }

            SourceSpec spec;
            spec.key = parts[1];
            spec.source_name = parts[3];

            if (parts.size() >= 5) {
                try {
                    spec.gain = std::stof(parts[4]);
                } catch (...) {
                    spec.gain = 1.0f;
                }
            }

            if (!spec.source_name.empty()) {
                state.return_sources.push_back(spec);
            }
        }
    }

    state.volume_percent = clampf(state.volume_percent, 0.0f, 150.0f);
    state.return_volume_percent = clampf(state.return_volume_percent, 0.0f, 150.0f);
    if (state.return_target_sink.empty()) {
        state.return_target_sink = "retour";
    }
    return state;
}

std::string state_signature(const MicroState& state) {
    std::ostringstream out;
    out << state.enabled << "\n";
    out << state.muted << "\n";
    out << state.volume_percent << "\n";
    out << state.mic_source << "\n";
    for (const auto& send : state.sends) {
        out << "send\t" << send.key << "\t" << send.source_name << "\t" << send.gain << "\n";
    }
    out << state.return_enabled << "\n";
    out << state.return_muted << "\n";
    out << state.return_volume_percent << "\n";
    out << state.return_target_sink << "\n";
    for (const auto& source : state.return_sources) {
        out << "return\t" << source.key << "\t" << source.source_name << "\t" << source.gain << "\n";
    }
    return out.str();
}

void mix_add(std::vector<float>& mix, const std::vector<float>& chunk, float gain) {
    const float safe_gain = clampf(gain, 0.0f, 2.5f);
    const int count = std::min(static_cast<int>(mix.size()), static_cast<int>(chunk.size()));
    for (int i = 0; i < count; ++i) {
        mix[i] += chunk[i] * safe_gain;
    }
}


float peak_level(const std::vector<float>& frames, int channel) {
    float peak = 0.0f;
    for (int i = channel; i < static_cast<int>(frames.size()); i += CHANNELS) {
        const float sample = frames[i];
        if (std::isfinite(sample)) {
            peak = std::max(peak, std::fabs(sample));
        }
    }
    return clampf(peak, 0.0f, 1.0f);
}

void write_levels_file(
    const std::string& path,
    const std::vector<float>& micro_mix,
    const std::vector<float>& return_mix
) {
    if (path.empty()) {
        return;
    }

    static auto last_write = std::chrono::steady_clock::time_point{};
    const auto now = std::chrono::steady_clock::now();

    if (last_write.time_since_epoch().count() != 0) {
        const auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - last_write).count();
        if (elapsed < 25) {
            return;
        }
    }

    last_write = now;

    const float micro_l = peak_level(micro_mix, 0);
    const float micro_r = peak_level(micro_mix, 1);
    const float return_l = peak_level(return_mix, 0);
    const float return_r = peak_level(return_mix, 1);

    const std::string tmp_path = path + ".tmp";
    std::ofstream out(tmp_path);
    if (!out) {
        return;
    }

    out << "{"
        << "\"channels\":{"
        << "\"micro\":[" << micro_l << "," << micro_r << "],"
        << "\"return-mic\":[" << return_l << "," << return_r << "]"
        << "}"
        << "}\n";
    out.close();

    std::rename(tmp_path.c_str(), path.c_str());
}

} // namespace

int main(int argc, char** argv) {
    std::signal(SIGTERM, signal_handler);
    std::signal(SIGINT, signal_handler);

    std::string state_path;
    std::string log_path;
    std::string levels_path;
    int period_ms = 20;

    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) {
                return {};
            }
            return argv[++i];
        };

        if (arg == "--state") {
            state_path = next();
        } else if (arg == "--log") {
            log_path = next();
        } else if (arg == "--levels") {
            levels_path = next();
        } else if (arg == "--period-ms") {
            try {
                period_ms = std::stoi(next());
            } catch (...) {
                period_ms = 20;
            }
        }
    }

    if (state_path.empty()) {
        std::cerr << "usage: ksound_native_micro_engine --state <path> [--levels <path>] [--log <path>] [--period-ms 10]\n";
        return 2;
    }

    std::ofstream log;
    if (!log_path.empty()) {
        log.open(log_path, std::ios::app);
        if (log) {
            log << "native micro engine start v2 micro_bus+retour\n";
        }
    }

    PlaybackClient micro_playback;
    micro_playback.set_sink("micro_bus");

    PlaybackClient return_playback;
    return_playback.set_sink("retour");

    std::map<std::string, CaptureClient> captures;
    std::string last_signature;

    while (g_running) {
        MicroState state = parse_state_file(state_path);
        const std::string signature = state_signature(state);

        std::set<std::string> wanted_sources;

        if (state.enabled && !state.muted && !state.mic_source.empty()) {
            wanted_sources.insert(state.mic_source);
        }

        if (state.enabled && !state.muted) {
            for (const auto& send : state.sends) {
                wanted_sources.insert(send.source_name);
            }
        }

        if (state.return_enabled && !state.return_muted) {
            for (const auto& source : state.return_sources) {
                wanted_sources.insert(source.source_name);
            }
        }

        if (signature != last_signature) {
            for (auto it = captures.begin(); it != captures.end();) {
                if (!wanted_sources.count(it->first)) {
                    it->second.stop();
                    it = captures.erase(it);
                } else {
                    ++it;
                }
            }

            return_playback.set_sink(state.return_target_sink.empty() ? "retour" : state.return_target_sink);

            last_signature = signature;
            if (log) {
                log << "state reload:"
                    << " mic_enabled=" << state.enabled
                    << " mic_muted=" << state.muted
                    << " mic_source=" << state.mic_source
                    << " sends=" << state.sends.size()
                    << " return_enabled=" << state.return_enabled
                    << " return_muted=" << state.return_muted
                    << " return_sources=" << state.return_sources.size()
                    << " return_target=" << state.return_target_sink
                    << "\n";
            }
        }

        std::map<std::string, std::vector<float>> chunks;
        std::vector<float> silence(CHUNK_SAMPLES, 0.0f);

        auto chunk_for = [&](const std::string& source_name) -> const std::vector<float>& {
            if (source_name.empty()) {
                return silence;
            }

            auto found = chunks.find(source_name);
            if (found != chunks.end()) {
                return found->second;
            }

            auto& client = captures[source_name];
            client.source_name = source_name;
            auto chunk = client.read_chunk();
            auto inserted = chunks.emplace(source_name, std::move(chunk));
            return inserted.first->second;
        };

        std::vector<float> micro_mix(CHUNK_SAMPLES, 0.0f);
        std::vector<float> return_mix(CHUNK_SAMPLES, 0.0f);

        if (state.enabled && !state.muted) {
            const float mic_gain = volume_percent_to_gain(state.volume_percent);

            if (!state.mic_source.empty()) {
                mix_add(micro_mix, chunk_for(state.mic_source), mic_gain);
            }

            for (const auto& send : state.sends) {
                mix_add(micro_mix, chunk_for(send.source_name), clampf(send.gain, 0.0f, 2.0f));
            }
        }

        micro_playback.write(micro_mix);

        if (state.return_enabled && !state.return_muted && !state.return_sources.empty()) {
            const float return_gain = volume_percent_to_gain(state.return_volume_percent);
            for (const auto& source : state.return_sources) {
                mix_add(return_mix, chunk_for(source.source_name), clampf(source.gain, 0.0f, 2.0f) * return_gain);
            }
            return_playback.write(return_mix);
        } else {
            return_playback.stop();
        }

        write_levels_file(levels_path, micro_mix, return_mix);

        std::this_thread::sleep_for(std::chrono::milliseconds(std::max(5, period_ms)));
    }

    for (auto& [_, client] : captures) {
        client.stop();
    }
    micro_playback.stop();
    return_playback.stop();

    if (log) {
        log << "native micro engine stop\n";
    }

    return 0;
}
