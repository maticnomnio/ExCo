"""
Standalone CLI to send messages to running Ex.Co. instance(s).

Reads ~/.exco/pid_list.txt to discover live instances, writes JSON
to each target's inbox file (~/.exco/instance_{PID}.json).

Usage:
    python exco_send_message.py open file1.py file2.py
    python exco_send_message.py open --line 42 main.py
    python exco_send_message.py show
    python exco_send_message.py --raw '{"command":"open","arguments":["f.py"],"line":42}'
    python exco_send_message.py --pid 1234 open file.py
"""

import json
import os
import sys
import argparse

SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".exco")
PID_FILE = os.path.join(SETTINGS_DIR, "pid_list.txt")


def _read_pids() -> list[int]:
    if not os.path.isfile(PID_FILE):
        return []
    pids = []
    with open(PID_FILE, "r") as f:
        for line in f:
            pid = line.strip()
            if pid.isdigit():
                pids.append(int(pid))
    return pids


def send_to_instance(pid: int, message: dict) -> None:
    path = os.path.join(SETTINGS_DIR, f"instance_{pid}.json")
    with open(path, "w+", encoding="utf-8", newline="\n") as f:
        json.dump(message, f, indent=4, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send messages to running Ex.Co. instance(s)"
    )
    parser.add_argument(
        "command",
        nargs="?",
        choices=["open", "show"],
        help="Built-in command: open <files...> or show",
    )
    parser.add_argument(
        "arguments",
        nargs="*",
        help="Arguments for the command (e.g. file paths)",
    )
    parser.add_argument(
        "--line",
        type=int,
        default=None,
        help="Line number to jump to (only for open command)",
    )
    parser.add_argument(
        "--raw",
        type=str,
        metavar="JSON",
        help="Raw JSON message",
    )
    parser.add_argument(
        "--pid",
        type=int,
        default=None,
        help="Target specific PID (default: all)",
    )

    args = parser.parse_args()

    if args.raw:
        try:
            message = json.loads(args.raw)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON: {e}", file=sys.stderr)
            sys.exit(1)
    elif args.command:
        message = {"command": args.command, "arguments": args.arguments}
        if args.line is not None:
            message["line"] = args.line
    else:
        parser.print_help()
        sys.exit(1)

    pids = [args.pid] if args.pid is not None else _read_pids()
    if not pids:
        print("No running Ex.Co. instances found.", file=sys.stderr)
        sys.exit(1)

    for pid in pids:
        send_to_instance(pid, message)
        print(f"Sent to PID {pid}: {json.dumps(message)}")


if __name__ == "__main__":
    main()
