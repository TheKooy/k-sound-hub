from __future__ import annotations

import re


def _compact_spaces(value: str) -> str:
    return " ".join(str(value or "").replace("\x00", " ").split())


def _safe_instance_name(value: str) -> str:
    cleaned = _compact_spaces(value)
    cleaned = cleaned.replace("\\", "/").strip("/")
    cleaned = cleaned.split("/")[-1].strip()
    cleaned = re.sub(r"[^A-Za-z0-9._ +@-]+", "_", cleaned).strip(" ._-")
    return cleaned[:96]


def process_route_rule_from_cmdline(cmdline: str) -> str:
    """Return a stable manual-routing rule from a process command line.

    The rule must be stable across launches and must not include PID/client ids.
    Empty string means "no safe process fingerprint".
    """
    text = _compact_spaces(cmdline)
    lowered = text.casefold()

    if (
        "prismlauncher" in lowered
        and (
            "minecraft-" in lowered
            or "minecraft/" in lowered
            or "org.prismlauncher.entrypoint" in lowered
            or "lwjgl-openal" in lowered
        )
    ):
        instance = ""
        match = re.search(r"PrismLauncher/instances/([^/]+)/", text, re.IGNORECASE)
        if match:
            instance = _safe_instance_name(match.group(1))

        if instance:
            return f"proc:prismlauncher:minecraft:instance={instance}"
        return "proc:prismlauncher:minecraft"

    match = re.search(r"steamapps/compatdata/(\d+)/", text, re.IGNORECASE)
    if match and ("proton" in lowered or "steamapps" in lowered):
        return f"proc:steam:compatdata:{match.group(1)}"

    return ""


def channel_for_media_role(role: str) -> str:
    normalized = str(role or "").strip().casefold()

    if normalized == "game":
        return "game"

    if normalized in {"music", "movie", "video", "media", "multimedia", "production"}:
        return "media"

    if normalized in {"communication", "phone", "voip", "chat"}:
        return "chat"

    return ""



def _clean_display_part(value: str) -> str:
    cleaned = _compact_spaces(value)
    cleaned = cleaned.replace("\\", "/").strip()
    if "/" in cleaned:
        cleaned = cleaned.rsplit("/", 1)[-1]
    cleaned = re.sub(r"\.(exe|jar|appimage)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("_", " ").strip()
    return cleaned[:140]


def _is_generic_stream_text(value: str) -> bool:
    normalized = _compact_spaces(value).casefold()
    return normalized in {
        "",
        "audio",
        "audio stream",
        "playback",
        "playback stream",
        "playstream",
        "webrtc voiceengine",
        "chromium input",
        "voiceengine",
        "output",
        "stream",
        "java",
        "pipewire",
        "pulse",
        "pulseaudio",
    }


def process_display_name_from_cmdline(cmdline: str) -> str:
    """Return a friendly app/game name from a process command line.

    This is best-effort and stable across launches. It intentionally avoids PID,
    PipeWire client ids, and machine-specific absolute paths in the display name.
    """
    text = _compact_spaces(cmdline)
    lowered = text.casefold()

    if not text:
        return ""

    if (
        "prismlauncher" in lowered
        and (
            "minecraft-" in lowered
            or "minecraft/" in lowered
            or "org.prismlauncher.entrypoint" in lowered
            or "lwjgl-openal" in lowered
        )
    ):
        instance = ""
        version = ""

        instance_match = re.search(r"PrismLauncher/instances/([^/]+)/", text, re.IGNORECASE)
        if instance_match:
            instance = _safe_instance_name(instance_match.group(1))

        version_match = re.search(r"/com/mojang/minecraft/([^/]+)/minecraft-[^/\s]+-client\.jar", text, re.IGNORECASE)
        if version_match:
            version = _clean_display_part(version_match.group(1))
        else:
            version_match = re.search(r"minecraft-([0-9][A-Za-z0-9._-]*)-client\.jar", text, re.IGNORECASE)
            if version_match:
                version = _clean_display_part(version_match.group(1))

        if version and instance and version.casefold() not in instance.casefold():
            return f"Minecraft {version} — {instance}"
        if version and instance:
            return f"Minecraft {version}"
        if version:
            return f"Minecraft {version}"
        if instance:
            return f"Minecraft — {instance}"
        return "Minecraft"

    common_match = re.search(r"steamapps[/\\]common[/\\]([^/\\]+)", text, re.IGNORECASE)
    if common_match:
        title = _clean_display_part(common_match.group(1))
        if title:
            return title

    compat_match = re.search(r"steamapps[/\\]compatdata[/\\](\d+)", text, re.IGNORECASE)
    if compat_match and ("proton" in lowered or "steamapps" in lowered):
        return f"Steam game {compat_match.group(1)}"

    wine_match = re.search(r"(?:^|\s)(?:[A-Za-z]:)?[^ \t\n\r]*[/\\]([^/\\\s]+\.exe)(?:\s|$)", text, re.IGNORECASE)
    if wine_match and ("wine" in lowered or ".exe" in lowered):
        title = _clean_display_part(wine_match.group(1))
        if title:
            return title

    jar_match = re.search(r"(?:^|\s)-jar\s+([^ \t\n\r]+\.jar)(?:\s|$)", text, re.IGNORECASE)
    if jar_match:
        title = _clean_display_part(jar_match.group(1))
        if title:
            return title

    return ""


def stream_display_name_from_data(
    *,
    cmdline: str = "",
    display_name: str = "",
    app_name: str = "",
    binary_name: str = "",
    media_name: str = "",
    node_name: str = "",
) -> str:
    """Build the best human display name for an audio stream.

    App/process identity is preferred over generic stream labels like
    "Playback Stream".
    """
    proc_name = process_display_name_from_cmdline(cmdline)
    if proc_name:
        return proc_name

    display = _clean_display_part(display_name)
    app = _clean_display_part(app_name)
    binary = _clean_display_part(binary_name)
    media = _clean_display_part(media_name)
    node = _clean_display_part(node_name)

    if app and not _is_generic_stream_text(app):
        if media and not _is_generic_stream_text(media) and media.casefold() != app.casefold():
            return f"{app} — {media}"
        return app

    if binary and not _is_generic_stream_text(binary):
        if media and not _is_generic_stream_text(media) and media.casefold() != binary.casefold():
            return f"{binary} — {media}"
        return binary

    if media and not _is_generic_stream_text(media):
        return media

    if node and not _is_generic_stream_text(node):
        return node

    return display or media or app or binary or node
