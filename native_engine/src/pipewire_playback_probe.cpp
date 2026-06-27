#include <pipewire/pipewire.h>
#include <pipewire/keys.h>
#include <spa/param/audio/format-utils.h>
#include <spa/param/audio/raw.h>
#include <spa/pod/builder.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>

namespace {

constexpr uint32_t RATE = 48000;
constexpr uint32_t CHANNELS = 2;

struct PlaybackState {
    pw_main_loop* loop{nullptr};
    pw_stream* stream{nullptr};
    spa_hook stream_listener{};
    uint64_t written_frames{0};
    uint64_t max_frames{RATE * 3};
    float volume{0.0f};
    float phase{0.0f};
    float frequency{440.0f};
    bool connected{false};
};

void on_stream_state_changed(
    void* data,
    pw_stream_state old_state,
    pw_stream_state state,
    const char* error
) {
    (void)old_state;
    auto* playback = static_cast<PlaybackState*>(data);
    if (playback == nullptr) {
        return;
    }

    std::cerr << "stream-state\t" << pw_stream_state_as_string(state);
    if (error != nullptr && std::strlen(error) > 0) {
        std::cerr << "\terror=" << error;
    }
    std::cerr << "\n";

    if (state == PW_STREAM_STATE_STREAMING) {
        playback->connected = true;
    }

    if (state == PW_STREAM_STATE_ERROR || state == PW_STREAM_STATE_UNCONNECTED) {
        if (playback->loop != nullptr) {
            pw_main_loop_quit(playback->loop);
        }
    }
}

void on_stream_process(void* data) {
    auto* playback = static_cast<PlaybackState*>(data);
    if (playback == nullptr || playback->stream == nullptr) {
        return;
    }

    pw_buffer* buffer = pw_stream_dequeue_buffer(playback->stream);
    if (buffer == nullptr || buffer->buffer == nullptr) {
        return;
    }

    spa_buffer* spa_buffer = buffer->buffer;
    if (spa_buffer->n_datas == 0 || spa_buffer->datas[0].data == nullptr) {
        pw_stream_queue_buffer(playback->stream, buffer);
        return;
    }

    spa_data& data0 = spa_buffer->datas[0];
    const uint32_t stride = sizeof(float) * CHANNELS;
    uint32_t frames = buffer->requested;
    if (frames == 0) {
        frames = 480;
    }

    const uint32_t max_frames = data0.maxsize / stride;
    frames = std::max<uint32_t>(1, std::min(frames, max_frames));

    auto* samples = static_cast<float*>(data0.data);
    for (uint32_t frame = 0; frame < frames; ++frame) {
        const float value = std::sin(playback->phase) * playback->volume;
        playback->phase += 2.0f * static_cast<float>(M_PI) * playback->frequency / static_cast<float>(RATE);
        if (playback->phase > 2.0f * static_cast<float>(M_PI)) {
            playback->phase -= 2.0f * static_cast<float>(M_PI);
        }

        samples[(frame * CHANNELS) + 0] = value;
        samples[(frame * CHANNELS) + 1] = value;
    }

    data0.chunk->offset = 0;
    data0.chunk->stride = static_cast<int32_t>(stride);
    data0.chunk->size = frames * stride;

    playback->written_frames += frames;

    pw_stream_queue_buffer(playback->stream, buffer);

    if (playback->written_frames >= playback->max_frames && playback->loop != nullptr) {
        pw_main_loop_quit(playback->loop);
    }
}

float parse_float_arg(const std::string& value, float fallback) {
    try {
        return std::stof(value);
    } catch (...) {
        return fallback;
    }
}

int parse_int_arg(const std::string& value, int fallback) {
    try {
        return std::stoi(value);
    } catch (...) {
        return fallback;
    }
}

} // namespace

int main(int argc, char** argv) {
    std::string target = "micro_bus";
    int seconds = 3;
    PlaybackState playback;

    for (int index = 1; index < argc; ++index) {
        const std::string arg = argv[index] != nullptr ? argv[index] : "";
        auto next = [&]() -> std::string {
            if (index + 1 >= argc || argv[index + 1] == nullptr) {
                return "";
            }
            ++index;
            return argv[index];
        };

        if (arg == "--target") {
            target = next();
        } else if (arg == "--seconds") {
            seconds = parse_int_arg(next(), seconds);
        } else if (arg == "--volume") {
            playback.volume = std::max(0.0f, std::min(1.0f, parse_float_arg(next(), playback.volume)));
        } else if (arg == "--frequency") {
            playback.frequency = std::max(20.0f, std::min(20000.0f, parse_float_arg(next(), playback.frequency)));
        } else if (arg == "--help" || arg == "-h") {
            std::cout << "Usage: ksound_pipewire_playback_probe [--target micro_bus] [--seconds 3] [--volume 0.0] [--frequency 440]\n";
            return 0;
        }
    }

    if (target.empty()) {
        std::cerr << "ERROR: empty target\n";
        return 2;
    }

    seconds = std::max(1, std::min(20, seconds));
    playback.max_frames = static_cast<uint64_t>(RATE) * static_cast<uint64_t>(seconds);

    pw_init(&argc, &argv);

    playback.loop = pw_main_loop_new(nullptr);
    if (playback.loop == nullptr) {
        std::cerr << "ERROR: pw_main_loop_new failed\n";
        pw_deinit();
        return 2;
    }

    pw_properties* props = pw_properties_new(
        PW_KEY_MEDIA_TYPE, "Audio",
        PW_KEY_MEDIA_CATEGORY, "Playback",
        PW_KEY_MEDIA_ROLE, "DSP",
        PW_KEY_NODE_NAME, "ksound_pipewire_playback_probe",
        PW_KEY_NODE_DESCRIPTION, "K-Sound PipeWire Playback Probe",
        PW_KEY_APP_NAME, "K-Sound Hub",
        PW_KEY_TARGET_OBJECT, target.c_str(),
        PW_KEY_NODE_RATE, "1/48000",
        PW_KEY_NODE_LATENCY, "480/48000",
        nullptr
    );

    pw_stream_events stream_events{};
    stream_events.version = PW_VERSION_STREAM_EVENTS;
    stream_events.state_changed = on_stream_state_changed;
    stream_events.process = on_stream_process;

    playback.stream = pw_stream_new_simple(
        pw_main_loop_get_loop(playback.loop),
        "ksound_pipewire_playback_probe",
        props,
        &stream_events,
        &playback
    );

    if (playback.stream == nullptr) {
        std::cerr << "ERROR: pw_stream_new_simple failed\n";
        pw_main_loop_destroy(playback.loop);
        pw_deinit();
        return 2;
    }

    uint8_t buffer[1024];
    spa_pod_builder builder = SPA_POD_BUILDER_INIT(buffer, sizeof(buffer));

    spa_audio_info_raw audio_info{};
    audio_info.format = SPA_AUDIO_FORMAT_F32;
    audio_info.rate = RATE;
    audio_info.channels = CHANNELS;
    audio_info.position[0] = SPA_AUDIO_CHANNEL_FL;
    audio_info.position[1] = SPA_AUDIO_CHANNEL_FR;

    const spa_pod* params[1];
    params[0] = spa_format_audio_raw_build(&builder, SPA_PARAM_EnumFormat, &audio_info);

    const int connect_result = pw_stream_connect(
        playback.stream,
        PW_DIRECTION_OUTPUT,
        PW_ID_ANY,
        static_cast<pw_stream_flags>(
            PW_STREAM_FLAG_AUTOCONNECT |
            PW_STREAM_FLAG_MAP_BUFFERS |
            PW_STREAM_FLAG_RT_PROCESS
        ),
        params,
        1
    );

    if (connect_result < 0) {
        std::cerr << "ERROR: pw_stream_connect failed: " << connect_result << "\n";
        pw_stream_destroy(playback.stream);
        pw_main_loop_destroy(playback.loop);
        pw_deinit();
        return 2;
    }

    std::cout
        << "playback-probe-start"
        << "\ttarget=" << target
        << "\tseconds=" << seconds
        << "\tvolume=" << playback.volume
        << "\tfrequency=" << playback.frequency
        << "\n";

    pw_main_loop_run(playback.loop);

    std::cout
        << "playback-probe-done"
        << "\twritten_frames=" << playback.written_frames
        << "\tconnected=" << (playback.connected ? 1 : 0)
        << "\n";

    spa_hook_remove(&playback.stream_listener);
    pw_stream_destroy(playback.stream);
    pw_main_loop_destroy(playback.loop);
    pw_deinit();

    return playback.connected ? 0 : 3;
}
