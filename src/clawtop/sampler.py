"""Install/remove the systemd user timer that records a memory sample every minute."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
from pathlib import Path

SERVICE = "clawtop-sample.service"
TIMER = "clawtop-sample.timer"


def unit_dir() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "systemd" / "user"


def units(exe: str) -> dict[str, str]:
    return {
        SERVICE: f"[Unit]\nDescription=Sample OpenClaw gateway memory per run stack\n\n"
        f"[Service]\nType=oneshot\nExecStart={exe} sample\n",
        TIMER: "[Unit]\nDescription=Sample OpenClaw gateway memory every minute\n\n"
        "[Timer]\nOnBootSec=1min\nOnUnitActiveSec=1min\nAccuracySec=5s\n\n"
        "[Install]\nWantedBy=timers.target\n",
    }


def _systemctl(*args: str) -> None:
    env = {
        **os.environ,
        "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"),
    }
    subprocess.run(["systemctl", "--user", *args], check=True, capture_output=True, text=True, env=env)


def install() -> Path:
    exe = shutil.which("clawtop")
    if not exe:
        raise RuntimeError("`clawtop` is not on PATH; install it with `uv tool install` first")
    d = unit_dir()
    d.mkdir(parents=True, exist_ok=True)
    for name, text in units(exe).items():
        (d / name).write_text(text)
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", TIMER)
    return d


def uninstall() -> None:
    d = unit_dir()
    with contextlib.suppress(subprocess.CalledProcessError):  # not installed / already disabled
        _systemctl("disable", "--now", TIMER)
    for name in (TIMER, SERVICE):
        (d / name).unlink(missing_ok=True)
    _systemctl("daemon-reload")
