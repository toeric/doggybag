"""macOS 排程：用 launchd 定時執行 `doggybag run`。"""

from __future__ import annotations

import os
import subprocess
import sys
from html import escape
from pathlib import Path

LABEL = "com.doggybag.agent"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def is_installed() -> bool:
    return plist_path().exists()


def build_plist(root: Path, interval_minutes: int, claude: str | None) -> dict:
    # launchd 的 PATH 很短，task 裡的 claude 和其他工具會找不到，所以把現在的 PATH 帶過去
    path_dirs = os.environ.get("PATH", "/usr/bin:/bin").split(os.pathsep)
    if claude:
        claude_dir = str(Path(claude).parent)
        if claude_dir not in path_dirs:
            path_dirs.insert(0, claude_dir)
    env = {"PATH": os.pathsep.join(path_dirs)}
    if os.environ.get("DOGGYBAG_HOME"):
        env["DOGGYBAG_HOME"] = str(root)
    return {
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "doggybag", "run"],
        "StartInterval": max(1, int(interval_minutes)) * 60,
        "RunAtLoad": False,
        "EnvironmentVariables": env,
        "StandardOutPath": str(root / "logs" / "doggybag.log"),
        "StandardErrorPath": str(root / "logs" / "doggybag.log"),
        "ProcessType": "Background",
    }


def _xml(value, indent: str = "  ") -> str:
    if isinstance(value, bool):
        return f"{indent}<{'true' if value else 'false'}/>\n"
    if isinstance(value, int):
        return f"{indent}<integer>{value}</integer>\n"
    if isinstance(value, str):
        return f"{indent}<string>{escape(value, quote=False)}</string>\n"
    if isinstance(value, list):
        inner = "".join(_xml(v, indent + "  ") for v in value)
        return f"{indent}<array>\n{inner}{indent}</array>\n"
    inner = "".join(
        f"{indent}  <key>{escape(k, quote=False)}</key>\n" + _xml(v, indent + "  ")
        for k, v in value.items()
    )
    return f"{indent}<dict>\n{inner}{indent}</dict>\n"


def render_plist(data: dict) -> str:
    """自己產生 plist。不用 plistlib，因為它依賴 expat，在某些 Homebrew Python 上載入會失敗。"""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n' + _xml(data) + "</plist>\n"
    )


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def install(root: Path, interval_minutes: int, claude: str | None) -> None:
    path = plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    path.write_text(render_plist(build_plist(root, interval_minutes, claude)), encoding="utf-8")
    domain = f"gui/{os.getuid()}"
    _launchctl("bootout", f"{domain}/{LABEL}")  # 已經載入過就先卸載，失敗可以忽略
    result = _launchctl("bootstrap", domain, str(path))
    if result.returncode != 0:
        raise RuntimeError(f"launchctl could not load the schedule: {result.stderr.strip()}")


def uninstall() -> bool:
    path = plist_path()
    _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    if path.exists():
        path.unlink()
        return True
    return False
