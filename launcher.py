"""Target of the desktop shortcut: updates from GitHub, starts the server, opens the journal."""
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import urllib.error
import urllib.request
import venv
import webbrowser
from pathlib import Path

from app.gitinfo import git_command, head_commit

ROOT = Path(__file__).resolve().parent
PORT = 8765
URL = f"http://127.0.0.1:{PORT}"
WINDOWS = platform.system() == "Windows"
LOG = ROOT / "data" / "launcher.log"
NO_WINDOW = 0x08000000 if WINDOWS else 0


def log(text: str) -> None:
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a", encoding="utf-8") as file:
        file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text}\n")


def git(*args, timeout=25) -> str:
    result = subprocess.run([*git_command(), *args], cwd=ROOT, capture_output=True, text=True,
                            timeout=timeout, creationflags=NO_WINDOW)
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:300])
    return result.stdout.strip()


def current_commit() -> str:
    return head_commit(ROOT)


def update() -> None:
    """A failed update must never stop the journal from opening."""
    if not (ROOT / ".git").exists():
        log("update skipped: this folder is not linked to git")
        return
    try:
        log(f"update: {git('pull', '--ff-only', 'origin', 'main')[:200]}")
    except Exception as error:
        log(f"update failed: {error}")


def python_path() -> Path:
    return ROOT / ".venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")


def ensure_environment() -> None:
    if not python_path().exists():
        log("creating environment")
        venv.create(ROOT / ".venv", with_pip=True)
    marker = ROOT / ".venv" / "requirements.sha1"
    digest = hashlib.sha1((ROOT / "requirements.txt").read_bytes()).hexdigest()
    if marker.exists() and marker.read_text() == digest:
        return
    result = subprocess.run([str(python_path()), "-m", "pip", "install", "-q", "-r", "requirements.txt"],
                            cwd=ROOT, capture_output=True, text=True, creationflags=NO_WINDOW)
    if result.returncode:
        log(f"package install failed: {result.stderr[-300:]}")
    else:
        marker.write_text(digest)


def get_json(path: str, timeout=1.5):
    with urllib.request.urlopen(URL + path, timeout=timeout) as response:
        return json.load(response)


def server_state():
    """None when nothing answers; otherwise the running server's version information."""
    try:
        return get_json("/api/version")
    except urllib.error.HTTPError:
        return {"commit": None}  # a version from before this launcher existed
    except (OSError, ValueError):
        return None


def stop_server() -> None:
    token = get_json("/api/settings")["token"]
    request = urllib.request.Request(URL + "/api/shutdown", b"{}", method="POST", headers={
        "Content-Type": "application/json", "X-Journal-Token": token})
    urllib.request.urlopen(request, timeout=3).read()
    for _ in range(40):
        if server_state() is None:
            return
        time.sleep(0.25)


def start_server() -> None:
    output = (ROOT / "data" / "server.log").open("a", encoding="utf-8")
    options = {"creationflags": 0x00000008 | NO_WINDOW} if WINDOWS else {"start_new_session": True}
    subprocess.Popen([str(python_path()), "run.py", "--no-browser"], cwd=ROOT, stdout=output,
                     stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, **options)


def wait_until_ready(seconds=30) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if server_state() is not None:
            return True
        time.sleep(0.4)
    return False


def show_error(text: str) -> None:
    log(text)
    if WINDOWS:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "Trade Journal", 0x10)
    elif platform.system() == "Darwin":
        subprocess.run(["osascript", "-e", f'display alert "Trade Journal" message "{text}"'])


def main() -> int:
    LOG.parent.mkdir(exist_ok=True)
    update()
    ensure_environment()
    state = server_state()
    commit = current_commit()
    if state and state.get("commit") is not None and commit and state["commit"] != commit:
        log(f"restarting server for {commit[:7]}")
        try:
            stop_server()
            state = None
        except Exception as error:
            log(f"restart failed: {error}")
    if state is None:
        start_server()
        if not wait_until_ready():
            show_error("The journal did not start. See data/server.log in the project folder.")
            return 1
    webbrowser.open(URL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
