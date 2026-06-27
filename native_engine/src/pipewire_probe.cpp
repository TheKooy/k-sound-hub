#include <pipewire/pipewire.h>
#include <pipewire/keys.h>
#include <spa/utils/dict.h>
#include <spa/utils/hook.h>

#include <cstring>
#include <iostream>
#include <map>
#include <set>
#include <string>

namespace {

struct ProbeState {
    pw_main_loop* loop{nullptr};
    pw_core* core{nullptr};
    int pending_seq{-1};
    spa_hook core_listener{};
    spa_hook registry_listener{};
    std::set<std::string> required;
    std::set<std::string> found;
    std::map<std::string, std::string> monitor_aliases;
    int node_count{0};
};

const char* dict_lookup(const spa_dict* props, const char* key) {
    if (props == nullptr || key == nullptr) {
        return "";
    }
    const char* value = spa_dict_lookup(props, key);
    return value != nullptr ? value : "";
}

bool ends_with(const std::string& value, const std::string& suffix) {
    return value.size() >= suffix.size()
        && value.compare(value.size() - suffix.size(), suffix.size(), suffix) == 0;
}

void on_core_done(void* data, uint32_t id, int seq) {
    auto* state = static_cast<ProbeState*>(data);
    if (state == nullptr) {
        return;
    }

    if (id == PW_ID_CORE && seq == state->pending_seq && state->loop != nullptr) {
        pw_main_loop_quit(state->loop);
    }
}

void on_registry_global(
    void* data,
    uint32_t id,
    uint32_t permissions,
    const char* type,
    uint32_t version,
    const spa_dict* props
) {
    (void)permissions;
    (void)version;

    auto* state = static_cast<ProbeState*>(data);
    if (state == nullptr || type == nullptr || std::strcmp(type, PW_TYPE_INTERFACE_Node) != 0) {
        return;
    }

    ++state->node_count;

    const std::string name = dict_lookup(props, PW_KEY_NODE_NAME);
    const std::string description = dict_lookup(props, PW_KEY_NODE_DESCRIPTION);
    const std::string media_class = dict_lookup(props, PW_KEY_MEDIA_CLASS);

    const bool print_all = state->required.empty();
    bool should_print = print_all;

    if (state->required.count(name) > 0) {
        state->found.insert(name);
        should_print = true;
    }

    // PipeWire exposes a sink as node "soundboard", while Pulse-style tooling
    // exposes its monitor as "soundboard.monitor". For direct PipeWire capture,
    // the sink node is the object we need to target in monitor/capture mode.
    if (media_class == "Audio/Sink") {
        for (const auto& required : state->required) {
            if (!ends_with(required, ".monitor")) {
                continue;
            }

            const std::string base = required.substr(0, required.size() - std::string(".monitor").size());
            if (base == name) {
                state->found.insert(required);
                state->monitor_aliases[required] = name;
                should_print = true;
            }
        }
    }

    if (should_print) {
        std::cout
            << "node"
            << "\tid=" << id
            << "\tname=" << name
            << "\tmedia_class=" << media_class
            << "\tdescription=" << description;

        for (const auto& [monitor_name, sink_name] : state->monitor_aliases) {
            if (sink_name == name) {
                std::cout << "\tmonitor_alias=" << monitor_name;
            }
        }

        std::cout << "\n";
    }
}

} // namespace

int main(int argc, char** argv) {
    ProbeState state;

    for (int index = 1; index < argc; ++index) {
        const std::string arg = argv[index] != nullptr ? argv[index] : "";
        if (!arg.empty() && arg != "--") {
            state.required.insert(arg);
        }
    }

    pw_init(&argc, &argv);

    state.loop = pw_main_loop_new(nullptr);
    if (state.loop == nullptr) {
        std::cerr << "ERROR: pw_main_loop_new failed\n";
        pw_deinit();
        return 2;
    }

    pw_context* context = pw_context_new(pw_main_loop_get_loop(state.loop), nullptr, 0);
    if (context == nullptr) {
        std::cerr << "ERROR: pw_context_new failed\n";
        pw_main_loop_destroy(state.loop);
        pw_deinit();
        return 2;
    }

    state.core = pw_context_connect(context, nullptr, 0);
    if (state.core == nullptr) {
        std::cerr << "ERROR: pw_context_connect failed\n";
        pw_context_destroy(context);
        pw_main_loop_destroy(state.loop);
        pw_deinit();
        return 2;
    }

    pw_core_events core_events{};
    core_events.version = PW_VERSION_CORE_EVENTS;
    core_events.done = on_core_done;
    pw_core_add_listener(state.core, &state.core_listener, &core_events, &state);

    pw_registry* registry = pw_core_get_registry(state.core, PW_VERSION_REGISTRY, 0);
    if (registry == nullptr) {
        std::cerr << "ERROR: pw_core_get_registry failed\n";
        pw_core_disconnect(state.core);
        pw_context_destroy(context);
        pw_main_loop_destroy(state.loop);
        pw_deinit();
        return 2;
    }

    pw_registry_events registry_events{};
    registry_events.version = PW_VERSION_REGISTRY_EVENTS;
    registry_events.global = on_registry_global;
    pw_registry_add_listener(registry, &state.registry_listener, &registry_events, &state);

    state.pending_seq = pw_core_sync(state.core, PW_ID_CORE, 0);
    pw_main_loop_run(state.loop);

    bool ok = true;
    for (const auto& required : state.required) {
        if (state.found.count(required) == 0) {
            std::cerr << "missing-node\t" << required << "\n";
            ok = false;
        }
    }

    for (const auto& [monitor_name, sink_name] : state.monitor_aliases) {
        std::cout << "monitor-alias\t" << monitor_name << "\tvia-sink\t" << sink_name << "\n";
    }

    std::cout << "summary\tnodes=" << state.node_count
              << "\trequired=" << state.required.size()
              << "\tfound=" << state.found.size()
              << "\n";

    spa_hook_remove(&state.registry_listener);
    spa_hook_remove(&state.core_listener);
    pw_proxy_destroy(reinterpret_cast<pw_proxy*>(registry));
    pw_core_disconnect(state.core);
    pw_context_destroy(context);
    pw_main_loop_destroy(state.loop);
    pw_deinit();

    return ok ? 0 : 3;
}
