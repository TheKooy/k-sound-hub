#include "engine.hpp"

#include "files.hpp"
#include "realtime.hpp"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <csignal>
#include <ctime>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <map>
#include <poll.h>
#include <sstream>
#include <string>
#include <sys/types.h>
#include <sys/wait.h>
#include <thread>
#include <unistd.h>
#include <vector>

namespace ksound::native {

namespace {
constexpr int RATE = 48000;
constexpr int CHANNELS = 2;
constexpr int CHUNK_FRAMES = 960;
constexpr int CAPTURE_LATENCY_MS = 60;
constexpr int PLAYBACK_LATENCY_MS = 120;
constexpr int PLAYBACK_PROCESS_MS = 40;
constexpr int PLAYBACK_MIN_RESTART_MS = 1000;
constexpr int SAMPLE_BYTES = 4;
constexpr int CHUNK_BYTES = CHUNK_FRAMES * CHANNELS * SAMPLE_BYTES;
constexpr float MAX_OUTPUT = 0.98f;
constexpr float MIX_HEADROOM = 0.72f;
constexpr float VOLUME_CURVE_EXPONENT = 2.0f;
constexpr float ACTIVITY_THRESHOLD = 1.0e-4f;
constexpr float GATE_ATTACK_STEP = 0.45f;
constexpr float GATE_RELEASE_STEP = 0.25f;
constexpr int SILENCE_HOLD_CHUNKS = 3;
constexpr float GAP_FILL_DECAY = 0.78f;
constexpr int MAX_GAP_FILL_CHUNKS = 4;
const std::array<const char*, 5> PLAYBACK_KEYS = {"all", "game", "chat", "media", "more"};

volatile std::sig_atomic_t g_running = 1;

std::string now_string() {
    auto now = std::chrono::system_clock::now();
    std::time_t tt = std::chrono::system_clock::to_time_t(now);
    std::tm tm{};
    localtime_r(&tt, &tm);
    std::ostringstream out;
    out << std::put_time(&tm, "%F %T");
    return out.str();
}

void signal_handler(int) {
    g_running = 0;
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

float clampf(float value, float low, float high) {
    return std::max(low, std::min(high, value));
}

float volume_percent_to_gain(float percent) {
    percent = clampf(percent, 0.0f, 150.0f);
    if (percent <= 100.0f) {
        const float normalized = percent / 100.0f;
        return std::pow(normalized, VOLUME_CURVE_EXPONENT);
    }
    return 1.0f + ((percent - 100.0f) / 100.0f);
}

struct Biquad {
    double b0{1.0};
    double b1{0.0};
    double b2{0.0};
    double a1{0.0};
    double a2{0.0};
    double z1[2]{0.0, 0.0};
    double z2[2]{0.0, 0.0};

    void process(std::vector<float>& frames) {
        if (frames.empty()) {
            return;
        }
        for (std::size_t i = 0; i < frames.size(); i += 2) {
            for (int ch = 0; ch < 2; ++ch) {
                const double x = static_cast<double>(frames[i + ch]);
                const double y = b0 * x + z1[ch];
                const double z1_new = b1 * x - a1 * y + z2[ch];
                const double z2_new = b2 * x - a2 * y;
                z1[ch] = z1_new;
                z2[ch] = z2_new;
                frames[i + ch] = static_cast<float>(y);
            }
        }
    }
};

Biquad make_peaking(float freq, float gain_db, float q) {
    freq = clampf(freq, 20.0f, RATE / 2.0f - 100.0f);
    q = std::max(0.05f, q);
    gain_db = clampf(gain_db, -24.0f, 24.0f);
    const double a = std::pow(10.0, gain_db / 40.0);
    const double omega = 2.0 * M_PI * static_cast<double>(freq) / static_cast<double>(RATE);
    const double alpha = std::sin(omega) / (2.0 * static_cast<double>(q));
    const double cosw = std::cos(omega);

    const double b0 = 1.0 + alpha * a;
    const double b1 = -2.0 * cosw;
    const double b2 = 1.0 - alpha * a;
    const double a0 = 1.0 + alpha / a;
    const double a1 = -2.0 * cosw;
    const double a2 = 1.0 - alpha / a;

    Biquad out;
    out.b0 = b0 / a0;
    out.b1 = b1 / a0;
    out.b2 = b2 / a0;
    out.a1 = a1 / a0;
    out.a2 = a2 / a0;
    return out;
}

std::filesystem::path g_child_log_dir;

std::string safe_child_label(const std::string& label) {
    std::string out;
    out.reserve(label.size());
    for (char c : label) {
        const bool ok =
            (c >= 'a' && c <= 'z') ||
            (c >= 'A' && c <= 'Z') ||
            (c >= '0' && c <= '9') ||
            c == '_' ||
            c == '-';
        out.push_back(ok ? c : '_');
    }
    return out.empty() ? "child" : out;
}

std::string join_args(const std::vector<std::string>& args) {
    std::ostringstream out;
    bool first = true;
    for (const auto& arg : args) {
        if (!first) {
            out << ' ';
        }
        first = false;
        out << arg;
    }
    return out.str();
}

std::string child_status_text(int status) {
    std::ostringstream out;
    if (WIFEXITED(status)) {
        out << "exit=" << WEXITSTATUS(status);
    } else if (WIFSIGNALED(status)) {
        out << "signal=" << WTERMSIG(status);
    } else {
        out << "status=" << status;
    }
    return out.str();
}

void log_child_event(const std::string& line) {
    std::cerr << "[" << now_string() << "] " << line << std::endl;
}

struct ChildProcess {
    pid_t pid{-1};
    int fd{-1};
    bool write_mode{false};
    std::string label;

    bool running() {
        if (pid <= 0) {
            return false;
        }

        int status = 0;
        pid_t res = waitpid(pid, &status, WNOHANG);
        if (res == 0) {
            return true;
        }

        if (res == pid) {
            log_child_event(
                "child_exit label=" + label +
                " pid=" + std::to_string(pid) +
                " " + child_status_text(status));
            if (fd >= 0) {
                ::close(fd);
                fd = -1;
            }
            pid = -1;
            return false;
        }

        if (errno == ECHILD) {
            log_child_event(
                "child_exit label=" + label +
                " pid=" + std::to_string(pid) +
                " status=ECHILD");
            if (fd >= 0) {
                ::close(fd);
                fd = -1;
            }
            pid = -1;
        }

        return false;
    }

    void stop() {
        if (fd >= 0) {
            ::close(fd);
            fd = -1;
        }

        if (pid <= 0) {
            return;
        }

        const pid_t target_pid = pid;

        if (running() && pid == target_pid) {
            log_child_event("child_stop label=" + label + " pid=" + std::to_string(target_pid));
            ::kill(target_pid, SIGTERM);

            for (int i = 0; i < 20; ++i) {
                if (pid != target_pid || !running()) {
                    break;
                }
                std::this_thread::sleep_for(std::chrono::milliseconds(20));
            }

            if (pid == target_pid && running()) {
                log_child_event("child_kill label=" + label + " pid=" + std::to_string(target_pid));
                ::kill(target_pid, SIGKILL);
            }
        }

        if (pid == target_pid) {
            int status = 0;
            pid_t res = waitpid(target_pid, &status, WNOHANG);
            if (res == target_pid) {
                log_child_event(
                    "child_reap label=" + label +
                    " pid=" + std::to_string(target_pid) +
                    " " + child_status_text(status));
            }
            pid = -1;
        }
    }
};

ChildProcess spawn_process(const std::vector<std::string>& args, bool write_mode, const std::string& label) {
    int pipefd[2];
    if (pipe(pipefd) != 0) {
        log_child_event("child_spawn_fail label=" + label + " error=pipe");
        return {};
    }

    std::string stderr_path;
    if (!g_child_log_dir.empty()) {
        try {
            std::filesystem::create_directories(g_child_log_dir);
            stderr_path = (g_child_log_dir / (safe_child_label(label) + ".stderr.log")).string();
        } catch (...) {
            stderr_path.clear();
        }
    }

    pid_t pid = fork();
    if (pid < 0) {
        ::close(pipefd[0]);
        ::close(pipefd[1]);
        log_child_event("child_spawn_fail label=" + label + " error=fork");
        return {};
    }

    if (pid == 0) {
        if (write_mode) {
            dup2(pipefd[0], STDIN_FILENO);
        } else {
            dup2(pipefd[1], STDOUT_FILENO);
        }

        int errfd = -1;
        if (!stderr_path.empty()) {
            errfd = ::open(stderr_path.c_str(), O_WRONLY | O_CREAT | O_APPEND, 0644);
        }
        if (errfd < 0) {
            errfd = ::open("/dev/null", O_WRONLY);
        }
        if (errfd >= 0) {
            dup2(errfd, STDERR_FILENO);
            ::close(errfd);
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
    proc.label = label;

    log_child_event(
        "child_start label=" + label +
        " pid=" + std::to_string(pid) +
        " args=" + join_args(args));

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

struct ChannelState {
    std::string key;
    bool enabled{true};
    bool muted{false};
    float volume{1.0f};
    std::string target_label{"ANPW"};
    std::string target_sink{"alsa_output.usb-SteelSeries_Arctis_Nova_Pro_Wireless-00.analog-stereo"};
    std::vector<Biquad> filters;
};

struct CaptureClient {
    std::string key;
    ChildProcess proc;
    std::vector<char> buffer;
    std::array<float, 2> last_level{0.0f, 0.0f};
    std::vector<float> last_chunk;
    int gap_fill_chunks{0};
    float gate_gain{0.0f};
    float output_gain{0.0f};
    int silence_hold_chunks{0};

    void ensure_started() {
        if (proc.running()) {
            return;
        }
        stop();
        proc = spawn_process(
            {
                "parec",
                std::string("--device=") + key + ".monitor",
                "--raw",
                "--format=float32le",
                "--rate=48000",
                "--channels=2",
                std::string("--latency-msec=") + std::to_string(CAPTURE_LATENCY_MS),
            },
            false,
            std::string("capture_") + key);
    }

    void stop() {
        proc.stop();
        buffer.clear();
        last_level = {0.0f, 0.0f};
        last_chunk.clear();
        gap_fill_chunks = 0;
        gate_gain = 0.0f;
        output_gain = 0.0f;
        silence_hold_chunks = 0;
    }

    std::vector<float> read_chunk() {
        ensure_started();
        if (!proc.running() || proc.fd < 0) {
            return std::vector<float>(CHUNK_FRAMES * CHANNELS, 0.0f);
        }

        char tmp[65536];
        for (;;) {
            ssize_t n = ::read(proc.fd, tmp, sizeof(tmp));
            if (n > 0) {
                buffer.insert(buffer.end(), tmp, tmp + n);
                continue;
            }
            if (n == 0) {
                break;
            }
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                break;
            }
            break;
        }

        if (buffer.size() < static_cast<std::size_t>(CHUNK_BYTES)) {
            if (!last_chunk.empty() && gap_fill_chunks < MAX_GAP_FILL_CHUNKS) {
                std::vector<float> out = last_chunk;
                float peak_l = 0.0f;
                float peak_r = 0.0f;
                for (int i = 0; i < CHUNK_FRAMES; ++i) {
                    out[i * 2] *= GAP_FILL_DECAY;
                    out[i * 2 + 1] *= GAP_FILL_DECAY;
                    peak_l = std::max(peak_l, std::abs(out[i * 2]));
                    peak_r = std::max(peak_r, std::abs(out[i * 2 + 1]));
                }
                last_chunk = out;
                ++gap_fill_chunks;
                if (std::max(peak_l, peak_r) < ACTIVITY_THRESHOLD) {
                    last_chunk.clear();
                }
                last_level = {clampf(peak_l, 0.0f, 1.0f), clampf(peak_r, 0.0f, 1.0f)};
                return out;
            }
            return std::vector<float>(CHUNK_FRAMES * CHANNELS, 0.0f);
        }

        std::vector<float> out(CHUNK_FRAMES * CHANNELS, 0.0f);
        std::memcpy(out.data(), buffer.data(), CHUNK_BYTES);
        buffer.erase(buffer.begin(), buffer.begin() + CHUNK_BYTES);
        last_chunk = out;
        gap_fill_chunks = 0;

        float peak_l = 0.0f;
        float peak_r = 0.0f;
        for (int i = 0; i < CHUNK_FRAMES; ++i) {
            peak_l = std::max(peak_l, std::abs(out[i * 2]));
            peak_r = std::max(peak_r, std::abs(out[i * 2 + 1]));
        }
        last_level = {clampf(peak_l, 0.0f, 1.0f), clampf(peak_r, 0.0f, 1.0f)};
        return out;
    }
};

struct PlaybackClient {
    std::string label;
    std::string sink_name;
    ChildProcess proc;
    std::chrono::steady_clock::time_point last_start{};
    int backoff_log_count{0};

    void ensure_started() {
        if (proc.running()) {
            backoff_log_count = 0;
            return;
        }

        const auto now = std::chrono::steady_clock::now();
        if (last_start.time_since_epoch().count() != 0 &&
            now - last_start < std::chrono::milliseconds(PLAYBACK_MIN_RESTART_MS)) {
            if (backoff_log_count < 3) {
                log_child_event(
                    "playback_restart_backoff label=" + label +
                    " sink=" + sink_name +
                    " min_ms=" + std::to_string(PLAYBACK_MIN_RESTART_MS));
                ++backoff_log_count;
            }
            return;
        }

        stop();
        last_start = now;
        backoff_log_count = 0;
        proc = spawn_process(
            {
                "pacat",
                "--playback",
                std::string("--device=") + sink_name,
                "--raw",
                "--format=float32le",
                "--rate=48000",
                "--channels=2",
                std::string("--latency-msec=") + std::to_string(PLAYBACK_LATENCY_MS),
                std::string("--process-time-msec=") + std::to_string(PLAYBACK_PROCESS_MS),
            },
            true,
            std::string("playback_") + label);
    }

    void stop() {
        proc.stop();
    }

    void write(const std::vector<float>& frames) {
        ensure_started();
        if (!proc.running() || proc.fd < 0) {
            return;
        }
        ssize_t total = static_cast<ssize_t>(frames.size() * sizeof(float));
        const char* ptr = reinterpret_cast<const char*>(frames.data());
        while (total > 0) {
            ssize_t n = ::write(proc.fd, ptr, static_cast<std::size_t>(total));
            if (n > 0) {
                ptr += n;
                total -= n;
                continue;
            }
            if (n < 0 && errno == EINTR) {
                continue;
            }
            log_child_event(
                "playback_write_break label=" + label +
                " sink=" + sink_name +
                " errno=" + std::to_string(errno));
            break;
        }
    }
};

std::map<std::string, ChannelState> g_channels;
std::map<std::string, CaptureClient> g_captures;
std::map<std::string, PlaybackClient> g_playbacks;
std::chrono::steady_clock::time_point g_last_levels_write{};

std::string escape_json(const std::string& in) {
    std::string out;
    out.reserve(in.size() + 8);
    for (char c : in) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            default: out.push_back(c); break;
        }
    }
    return out;
}

std::vector<Biquad> parse_bands(const std::string& spec) {
    std::vector<Biquad> out;
    std::stringstream ss(spec);
    std::string item;
    while (std::getline(ss, item, ',')) {
        if (item.empty()) {
            continue;
        }
        std::stringstream bs(item);
        std::string part;
        std::vector<std::string> bits;
        while (std::getline(bs, part, ':')) {
            bits.push_back(part);
        }
        if (bits.size() != 3) {
            continue;
        }
        float freq = 1000.0f;
        float gain = 0.0f;
        float q = 1.0f;
        try {
            freq = std::stof(bits[0]);
            gain = std::stof(bits[1]);
            q = std::stof(bits[2]);
        } catch (...) {
            continue;
        }
        if (std::abs(gain) < 0.01f) {
            continue;
        }
        out.push_back(make_peaking(freq, gain, q));
    }
    return out;
}

bool same_filter_shape(const Biquad& a, const Biquad& b) {
    const double eps = 1.0e-9;
    return std::abs(a.b0 - b.b0) < eps &&
           std::abs(a.b1 - b.b1) < eps &&
           std::abs(a.b2 - b.b2) < eps &&
           std::abs(a.a1 - b.a1) < eps &&
           std::abs(a.a2 - b.a2) < eps;
}

void parse_state_text(const std::string& text) {
    std::map<std::string, ChannelState> parsed;
    for (const auto* key : PLAYBACK_KEYS) {
        ChannelState st;
        st.key = key;
        parsed[st.key] = st;
    }

    std::stringstream ss(text);
    std::string line;
    while (std::getline(ss, line)) {
        if (line.empty()) {
            continue;
        }
        auto parts = split_tab(line);
        if (parts.empty()) {
            continue;
        }
        if (parts[0] != "channel" || parts.size() < 8) {
            continue;
        }
        ChannelState st;
        st.key = parts[1];
        st.enabled = parts[2] == "1";
        st.muted = parts[3] == "1";
        try {
            st.volume = volume_percent_to_gain(std::stof(parts[4]));
        } catch (...) {
            st.volume = 1.0f;
        }
        st.target_label = parts[5];
        st.target_sink = parts[6];
        st.filters = parse_bands(parts[7]);
        parsed[st.key] = st;
    }

    auto old_channels = g_channels;
    for (auto& [key, st] : parsed) {
        auto it = old_channels.find(key);
        if (it == old_channels.end()) {
            continue;
        }
        if (it->second.filters.size() != st.filters.size()) {
            continue;
        }
        bool compatible = true;
        for (std::size_t i = 0; i < st.filters.size(); ++i) {
            if (!same_filter_shape(it->second.filters[i], st.filters[i])) {
                compatible = false;
                break;
            }
        }
        if (!compatible) {
            continue;
        }
        for (std::size_t i = 0; i < st.filters.size(); ++i) {
            st.filters[i].z1[0] = it->second.filters[i].z1[0];
            st.filters[i].z1[1] = it->second.filters[i].z1[1];
            st.filters[i].z2[0] = it->second.filters[i].z2[0];
            st.filters[i].z2[1] = it->second.filters[i].z2[1];
        }
    }

    g_channels = std::move(parsed);
    for (const auto& [key, st] : g_channels) {
        if (!g_captures.contains(key)) {
            g_captures[key] = CaptureClient{key};
        }
    }
}

void parse_volume_state_text(const std::string& text) {
    std::stringstream ss(text);
    std::string line;

    while (std::getline(ss, line)) {
        if (line.empty()) {
            continue;
        }

        auto parts = split_tab(line);
        if (parts.size() < 4 || parts[0] != "volume") {
            continue;
        }

        auto it = g_channels.find(parts[1]);
        if (it == g_channels.end()) {
            continue;
        }

        it->second.muted = parts[2] == "1";
        try {
            it->second.volume = volume_percent_to_gain(std::stof(parts[3]));
        } catch (...) {
            // Keep previous volume on parse errors.
        }
    }
}

std::vector<float> process_channel(CaptureClient& capture, const ChannelState& state, std::vector<float> frames) {
    float peak = 0.0f;
    for (float sample : frames) {
        peak = std::max(peak, std::abs(sample));
    }

    if (peak > ACTIVITY_THRESHOLD) {
        capture.silence_hold_chunks = SILENCE_HOLD_CHUNKS;
    } else if (capture.silence_hold_chunks > 0) {
        --capture.silence_hold_chunks;
    }

    const bool should_play = state.enabled && !state.muted;
    const bool keep_open = should_play && (peak > ACTIVITY_THRESHOLD || capture.silence_hold_chunks > 0);
    const float target_gate = keep_open ? 1.0f : 0.0f;
    const float start_gate = capture.gate_gain;
    float end_gate = start_gate;
    if (target_gate > start_gate) {
        end_gate = std::min(target_gate, start_gate + GATE_ATTACK_STEP);
    } else if (target_gate < start_gate) {
        end_gate = std::max(target_gate, start_gate - GATE_RELEASE_STEP);
    }

    for (auto& filt : const_cast<std::vector<Biquad>&>(state.filters)) {
        filt.process(frames);
    }

    const float base_gain = should_play ? state.volume : 0.0f;
    const float start_output_gain = capture.output_gain;
    const float end_output_gain = base_gain * end_gate;
    const float denom = static_cast<float>(std::max(1, CHUNK_FRAMES - 1));

    for (int i = 0; i < CHUNK_FRAMES; ++i) {
        const float t = static_cast<float>(i) / denom;
        const float gain = start_output_gain + (end_output_gain - start_output_gain) * t;
        frames[i * 2] *= gain;
        frames[i * 2 + 1] *= gain;
    }

    capture.gate_gain = end_gate;
    capture.output_gain = end_output_gain;
    return frames;
}

void write_levels_file(const std::filesystem::path& path) {
    auto now = std::chrono::steady_clock::now();
    if (g_last_levels_write.time_since_epoch().count() != 0) {
        auto delta = std::chrono::duration_cast<std::chrono::milliseconds>(now - g_last_levels_write).count();
        if (delta < 50) {
            return;
        }
    }
    g_last_levels_write = now;

    std::ostringstream json;
    json << "{\n  \"timestamp\": " << std::time(nullptr) << ",\n  \"channels\": {\n";
    bool first = true;
    for (const auto& [key, cap] : g_captures) {
        if (!first) {
            json << ",\n";
        }
        first = false;
        json << "    \"" << escape_json(key) << "\": [" << cap.last_level[0] << ", " << cap.last_level[1] << "]";
    }
    json << "\n  }\n}\n";
    write_text_file(path, json.str());
}

} // namespace

Engine::Engine(EngineConfig config) : config_(std::move(config)) {}
Engine::~Engine() { stop_all(); }

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
    parse_state_text(text);
    log("state_reload bytes=" + std::to_string(text.size()));
}

void Engine::maybe_reload_volume_state() {
    if (config_.volume_state_path.empty()) {
        return;
    }

    auto current = safe_last_write_time(config_.volume_state_path);
    if (current == std::filesystem::file_time_type{}) {
        return;
    }
    if (current == last_volume_state_write_) {
        return;
    }

    last_volume_state_write_ = current;
    auto text = read_text_file(config_.volume_state_path);
    parse_volume_state_text(text);
}

void Engine::tick_once() {
    std::map<std::string, std::vector<float>> mixes;

    for (auto& [key, state] : g_channels) {
        auto& capture = g_captures[key];
        if (!state.enabled) {
            capture.stop();
            continue;
        }
        auto frames = capture.read_chunk();
        auto processed = process_channel(capture, state, std::move(frames));
        auto& mix = mixes[state.target_label.empty() ? state.target_sink : state.target_label];
        if (mix.empty()) {
            mix.assign(CHUNK_FRAMES * CHANNELS, 0.0f);
        }
        for (std::size_t i = 0; i < mix.size(); ++i) {
            mix[i] += processed[i];
        }
    }

    for (auto& [key, mix] : mixes) {
        std::string sink_name;
        for (const auto& [chkey, state] : g_channels) {
            if ((state.target_label.empty() ? state.target_sink : state.target_label) == key) {
                sink_name = state.target_sink;
                break;
            }
        }
        auto& playback = g_playbacks[key];
        if (playback.sink_name != sink_name) {
            playback.stop();
            playback.label = key;
            playback.sink_name = sink_name;
        }
        for (float& sample : mix) {
            sample = std::tanh(sample * MIX_HEADROOM);
            sample = clampf(sample, -MAX_OUTPUT, MAX_OUTPUT);
        }
        playback.write(mix);
    }

    for (auto it = g_playbacks.begin(); it != g_playbacks.end();) {
        if (!mixes.contains(it->first)) {
            it->second.stop();
            it = g_playbacks.erase(it);
        } else {
            ++it;
        }
    }

    write_levels_file(config_.levels_path);
}

void Engine::write_levels() {
    write_levels_file(config_.levels_path);
}

void Engine::stop_all() {
    for (auto& [_, cap] : g_captures) {
        cap.stop();
    }
    for (auto& [_, pb] : g_playbacks) {
        pb.stop();
    }
}

int Engine::run() {
    std::signal(SIGTERM, signal_handler);
    std::signal(SIGINT, signal_handler);

    g_child_log_dir = config_.log_path.parent_path() / "children";
    log("engine_start " + try_enable_realtime());
    log("child_log_dir=" + g_child_log_dir.string());
    log("state=" + config_.state_path.string());
    log("volume_state=" + config_.volume_state_path.string());
    log("levels=" + config_.levels_path.string());
    log("capture_latency_ms=" + std::to_string(CAPTURE_LATENCY_MS) + " playback_latency_ms=" + std::to_string(PLAYBACK_LATENCY_MS) + " playback_process_ms=" + std::to_string(PLAYBACK_PROCESS_MS) + " mix_headroom=" + std::to_string(MIX_HEADROOM));

    const auto period = std::chrono::milliseconds(config_.period_ms);
    auto next = std::chrono::steady_clock::now();

    while (g_running) {
        maybe_reload_state();
        maybe_reload_volume_state();
        tick_once();
        next += period;
        std::this_thread::sleep_until(next);
    }

    stop_all();
    return 0;
}

} // namespace ksound::native
