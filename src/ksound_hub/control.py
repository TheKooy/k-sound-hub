from __future__ import annotations

import argparse
import json
import socket
import sys

from .config import IPC_SOCKET_PATH


CHANNEL_ALIASES = {
    "all": "all",
    "game": "game",
    "chat": "chat",
    "media": "media",
    "more": "more",
    "micro": "micro",
    "retour": "return-mic",
    "retourmic": "return-mic",
    "return-mic": "return-mic",
    "return_mic": "return-mic",
}


def normalize_channel(value: str) -> str:
    key = value.strip().lower().replace(" ", "-")
    return CHANNEL_ALIASES.get(key, key)


def main() -> int:
    parser = argparse.ArgumentParser(description="Control K-Sound Hub through its IPC socket")
    parser.add_argument("--channel", required=True, help="all/game/chat/media/more/micro/return-mic")
    parser.add_argument("--action", required=True, choices=["volup", "voldown", "mute", "set-volume"])
    parser.add_argument("--volume", type=int, default=None, help="Used with --action set-volume")
    args = parser.parse_args()

    payload = {
        "channel": normalize_channel(args.channel),
        "action": args.action,
    }
    if args.action == "set-volume":
        if args.volume is None:
            parser.error("--volume is required with --action set-volume")
        payload["volume"] = int(args.volume)

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(IPC_SOCKET_PATH)
        sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        sock.close()
        return 0
    except FileNotFoundError:
        print(f"IPC socket not found: {IPC_SOCKET_PATH}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Failed to send command: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
