#include <pipewire/pipewire.h>
#include <spa/param/audio/format-utils.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <thread>

namespace {

struct Options {
    std::string target{"easyeffects_source"};
    int seconds{2};
    bool allow_empty{false};
};

struct CaptureState {
    pw_main_loop* loop{nullptr};
    pw_stream* stream{nullptr};
    std::string target;
    std::string target_object;
    bool capture_sink{false};
    bool connected{false};
    bool saw_process{false};
    uint64_t frames{0};
    uint64_t samples{0};
    double peak{0.0};
    long double sum_squares{0.0};
};

void print_usage() {
    std::cerr
        << "usage: ksound_pipewire_capture_probe "
        << "[--target <source-or-sink.monitor>] "
        << "[--seconds <n>] "
        << "[--allow-empty]\n";
}

Options parse_args(int argc, char** argv) {
    Options opts;

    for (int i = 1; i < argc; ++i) {
        const std::string arg(argv[i]);

        if (arg == "--target" && i + 1 < argc) {
            opts.target = argv[++i];
        } else if (arg == "--seconds" && i + 1 < argc) {
            opts.seconds = std::max(1, std::atoi(argv[++i]));
        } else if (arg == "--allow-empty") {
            opts.allow_empty = true;
        } else if (arg == "-h" || arg == "--help") {
            print_usage();
            std::exit(0);
        } else {
            print_usage();
            std::exit(2);
        }
    }

    return opts;
}

bool ends_with(const std::string& text, const std::string& suffix) {
    return text.size() >= suffix.size()
        && text.compare(text.size() - suffix.size(), suffix.size(), suffix) == 0;
}

void on_stream_state_changed(
    void* data,
    pw_stream_state old_state,
    pw_stream_state state,
    const char* error
) {
    auto* capture = static_cast<CaptureState*>(data);

    std::cout
        << "stream-state\t"
        << pw_stream_state_as_string(state);

    if (error != nullptr) {
        std::cout << "\terror=" << error;
    }

    std::cout << "\n";

    if (state == PW_STREAM_STATE_STREAMING || state == PW_STREAM_STATE_PAUSED) {
        capture->connected = true;
    }

    if (state == PW_STREAM_STATE_ERROR) {
        pw_main_loop_quit(capture->loop);
    }

    (void)old_state;
}

void on_stream_process(void* data) {
    auto* capture = static_cast<CaptureState*>(data);
    pw_buffer* pw_buf = pw_stream_dequeue_buffer(capture->stream);

    if (pw_buf == nullptr || pw_buf->buffer == nullptr) {
        return;
    }

    spa_buffer* buffer = pw_buf->buffer;
    if (buffer->n_datas > 0 && buffer->datas[0].data != nullptr && buffer->datas[0].chunk != nullptr) {
        const spa_chunk* chunk = buffer->datas[0].chunk;
        const auto* raw = static_cast<const char*>(buffer->datas[0].data) + chunk->offset;
        const uint32_t size = chunk->size;
        const auto* samples = reinterpret_cast<const float*>(raw);
        const uint32_t sample_count = size / sizeof(float);

        capture->saw_process = true;
        capture->samples += sample_count;
        capture->frames += sample_count / 2;

        for (uint32_t i = 0; i < sample_count; ++i) {
            const double v = std::abs(static_cast<double>(samples[i]));
            capture->peak = std::max(capture->peak, v);
            capture->sum_squares += static_cast<long double>(v * v);
        }
    }

    pw_stream_queue_buffer(capture->stream, pw_buf);
}

pw_stream_events make_stream_events() {
    pw_stream_events events{};
    events.version = PW_VERSION_STREAM_EVENTS;
    events.state_changed = on_stream_state_changed;
    events.process = on_stream_process;
    return events;
}

} // namespace

int main(int argc, char** argv) {
    const Options opts = parse_args(argc, argv);

    CaptureState capture;
    capture.target = opts.target;
    capture.target_object = opts.target;

    if (ends_with(capture.target, ".monitor")) {
        capture.capture_sink = true;
        capture.target_object = capture.target.substr(0, capture.target.size() - std::strlen(".monitor"));
    }

    pw_init(&argc, &argv);

    capture.loop = pw_main_loop_new(nullptr);
    if (capture.loop == nullptr) {
        std::cerr << "pw_main_loop_new failed\n";
        return 1;
    }

    pw_properties* props = pw_properties_new(
        PW_KEY_MEDIA_TYPE, "Audio",
        PW_KEY_MEDIA_CATEGORY, "Capture",
        PW_KEY_MEDIA_ROLE, "DSP",
        PW_KEY_NODE_NAME, "ksound_pipewire_capture_probe",
        PW_KEY_NODE_DESCRIPTION, "K-Sound PipeWire Capture Probe",
        PW_KEY_APP_NAME, "K-Sound Hub",
        PW_KEY_TARGET_OBJECT, capture.target_object.c_str(),
        PW_KEY_NODE_RATE, "1/48000",
        PW_KEY_NODE_LATENCY, "480/48000",
        nullptr
    );

    if (capture.capture_sink) {
        pw_properties_set(props, "stream.capture.sink", "true");
    }

    pw_stream_events stream_events = make_stream_events();

    capture.stream = pw_stream_new_simple(
        pw_main_loop_get_loop(capture.loop),
        "ksound_pipewire_capture_probe",
        props,
        &stream_events,
        &capture
    );

    if (capture.stream == nullptr) {
        std::cerr << "pw_stream_new_simple failed\n";
        pw_main_loop_destroy(capture.loop);
        return 1;
    }

    uint8_t pod_buffer[1024];
    spa_pod_builder builder = SPA_POD_BUILDER_INIT(pod_buffer, sizeof(pod_buffer));

    spa_audio_info_raw audio_info{};
    audio_info.format = SPA_AUDIO_FORMAT_F32;
    audio_info.rate = 48000;
    audio_info.channels = 2;
    audio_info.position[0] = SPA_AUDIO_CHANNEL_FL;
    audio_info.position[1] = SPA_AUDIO_CHANNEL_FR;

    const spa_pod* params[1];
    params[0] = spa_format_audio_raw_build(&builder, SPA_PARAM_EnumFormat, &audio_info);

    const int connect_result = pw_stream_connect(
        capture.stream,
        PW_DIRECTION_INPUT,
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
        std::cerr << "pw_stream_connect failed: " << connect_result << "\n";
        pw_stream_destroy(capture.stream);
        pw_main_loop_destroy(capture.loop);
        return 1;
    }

    std::cout
        << "capture-probe-start"
        << "\ttarget=" << capture.target
        << "\ttarget_object=" << capture.target_object
        << "\tcapture_sink=" << (capture.capture_sink ? 1 : 0)
        << "\tseconds=" << opts.seconds
        << "\n";

    std::thread timer([&capture, seconds = opts.seconds]() {
        std::this_thread::sleep_for(std::chrono::seconds(seconds));
        pw_main_loop_quit(capture.loop);
    });

    pw_main_loop_run(capture.loop);
    timer.join();

    const double rms = capture.samples > 0
        ? std::sqrt(static_cast<double>(capture.sum_squares / capture.samples))
        : 0.0;

    std::cout
        << "capture-probe-done"
        << "\ttarget=" << capture.target
        << "\ttarget_object=" << capture.target_object
        << "\tcapture_sink=" << (capture.capture_sink ? 1 : 0)
        << "\tconnected=" << (capture.connected ? 1 : 0)
        << "\tsaw_process=" << (capture.saw_process ? 1 : 0)
        << "\tframes=" << capture.frames
        << "\tpeak=" << capture.peak
        << "\trms=" << rms
        << "\n";

    pw_stream_disconnect(capture.stream);
    pw_stream_destroy(capture.stream);
    pw_main_loop_destroy(capture.loop);
    pw_deinit();

    if (!capture.connected) {
        return 3;
    }

    if (!opts.allow_empty && capture.frames == 0) {
        return 4;
    }

    return 0;
}
