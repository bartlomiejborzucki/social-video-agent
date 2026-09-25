"""A stand-in for wsl.exe, for driving the Windows adapter from a test.

It behaves the way the adapter needs WSL to behave -- a UTF-16 distribution
listing, `--exec` running one program with an argv array, a non-interactive
PATH that does not contain ~/.local/bin -- and records every call as the argv
array it received, so a test can assert that nothing was joined into text.

Configured by the JSON file named in FAKE_WSL_CONFIG:

    {"listing": "...", "log": "/path/calls.jsonl",
     "distributions": {"Ubuntu": {"home": "/home/user",
                                  "engines": ["/home/user/.local/bin/social-video-agent"],
                                  "path": ["/usr/bin"],
                                  "real": {"<linux path>": "<program to exec>"}}}}
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path, PurePosixPath


def main() -> int:
    config = json.loads(Path(os.environ["FAKE_WSL_CONFIG"]).read_text(encoding="utf-8"))
    argv = sys.argv[1:]
    passed = {
        name: os.environ.get(name)
        for name in ("SOCIAL_VIDEO_AGENT_PLATFORM", "SOCIAL_VIDEO_WSL_DISTRIBUTION")
    }
    wslenv = os.environ.get("WSLENV", "")
    with Path(config["log"]).open("a", encoding="utf-8") as log:
        log.write(json.dumps({"argv": argv, "env": passed, "wslenv": wslenv}) + "\n")

    if argv[:2] == ["--list", "--verbose"]:
        sys.stdout.buffer.write(config["listing"].encode("utf-16-le"))
        return 0
    if len(argv) < 3 or argv[0] not in ("--distribution", "-d"):
        sys.stderr.write(f"fake wsl: unsupported call {argv!r}\n")
        return 2
    name, rest = argv[1], argv[2:]
    distro = config["distributions"].get(name)
    if distro is None:
        sys.stderr.write(f"There is no distribution with the supplied name. {name}\n")
        return 1
    engines = distro.get("engines", [])
    if rest[0] == "--exec":
        program, args = rest[1], rest[2:]
        if program == "/usr/bin/printenv":
            print(distro["home"] if args == ["HOME"] else "")
            return 0
        if program == "/usr/bin/test":
            return 0 if args[:1] == ["-x"] and args[1:] and args[1] in engines else 1
        if program in engines:
            real = distro.get("real", {}).get(program)
            if real:
                # Hand over to a real engine, argv intact, as wsl.exe --exec does.
                os.execv(real, [real, *args])
            return _engine(args, passed, wslenv)
        sys.stderr.write(f"execvpe({program}) failed: No such file or directory\n")
        return 1
    if rest[0] == "--":
        # Through the default shell, with its non-interactive PATH.
        command = rest[1]
        on_path = [
            engine
            for engine in engines
            if str(PurePosixPath(engine).parent)
            in distro.get("path", ["/usr/local/bin", "/usr/bin"])
        ]
        if command == "social-video-agent" and on_path:
            return _engine(rest[2:], passed, wslenv)
        sys.stderr.write(f"-bash: line 1: {command}: command not found\n")
        return 127
    sys.stderr.write(f"fake wsl: unsupported call {argv!r}\n")
    return 2


def _engine(args: list[str], passed: dict, wslenv: str) -> int:
    if args == ["version"]:
        print("1.0.1")
        return 0
    print(json.dumps({"engine_args": args, "env": passed, "wslenv": wslenv}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
