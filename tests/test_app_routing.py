from ksound_hub.app_routing import channel_for_media_role, process_display_name_from_cmdline, process_route_rule_from_cmdline, stream_display_name_from_data


def test_prism_minecraft_cmdline_gets_stable_instance_rule() -> None:
    cmdline = (
        "/home/kooy/.local/share/PrismLauncher/java/java-runtime-epsilon/bin/java "
        "-Djava.library.path=/home/kooy/.local/share/PrismLauncher/instances/fabric 26.2/natives "
        "-cp /home/kooy/.local/share/PrismLauncher/libraries/org/lwjgl/lwjgl-openal/3.4.1.jar:"
        "/home/kooy/.local/share/PrismLauncher/libraries/com/mojang/minecraft/26.2/minecraft-26.2-client.jar "
        "org.prismlauncher.EntryPoint"
    )

    assert process_route_rule_from_cmdline(cmdline) == "proc:prismlauncher:minecraft:instance=fabric 26.2"


def test_plain_java_does_not_get_unsafe_route_rule() -> None:
    assert process_route_rule_from_cmdline("/usr/bin/java -jar random-tool.jar") == ""


def test_media_roles_map_to_logical_channels() -> None:
    assert channel_for_media_role("game") == "game"
    assert channel_for_media_role("Music") == "media"
    assert channel_for_media_role("communication") == "chat"
    assert channel_for_media_role("unknown") == ""



def test_prism_minecraft_cmdline_gets_friendly_display_name() -> None:
    cmdline = (
        "/home/kooy/.local/share/PrismLauncher/java/java-runtime-epsilon/bin/java "
        "-Djava.library.path=/home/kooy/.local/share/PrismLauncher/instances/fabric 26.2/natives "
        "-cp /home/kooy/.local/share/PrismLauncher/libraries/org/lwjgl/lwjgl-openal/3.4.1.jar:"
        "/home/kooy/.local/share/PrismLauncher/libraries/com/mojang/minecraft/26.2/minecraft-26.2-client.jar "
        "org.prismlauncher.EntryPoint"
    )

    assert process_display_name_from_cmdline(cmdline) == "Minecraft 26.2"


def test_stream_display_prefers_app_name_over_media_title() -> None:
    assert stream_display_name_from_data(
        app_name="Firefox",
        media_name="Cool video - YouTube",
        display_name="Cool video - YouTube",
    ) == "Firefox — Cool video - YouTube"


def test_stream_display_uses_process_name_over_generic_playback_stream() -> None:
    assert stream_display_name_from_data(
        cmdline="/games/SteamLibrary/steamapps/common/Black Mesa/bms_linux",
        media_name="Playback Stream",
        node_name="java",
    ) == "Black Mesa"



def test_stream_display_prefers_discord_binary_over_webrtc_voiceengine() -> None:
    assert stream_display_name_from_data(
        app_name="WEBRTC VoiceEngine",
        binary_name="Discord",
        media_name="playStream",
        display_name="WEBRTC VoiceEngine — playStream",
    ) == "Discord"
