"""Git helpers that keep working when Python runs under Rosetta on Apple Silicon."""
import platform
import subprocess
from pathlib import Path


def git_command() -> list:
    """Under Rosetta, /usr/bin/git picks its Intel half, which Apple's tools cannot load."""
    if platform.system() != "Darwin":
        return ["git"]
    try:
        result = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.optional.arm64"],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ["git"]
    return ["/usr/bin/arch", "-arm64", "git"] if result.stdout.strip() == "1" else ["git"]


def head_commit(root: Path) -> str:
    """Reads the commit from .git directly, so no git process is needed."""
    try:
        head = (root / ".git" / "HEAD").read_text().strip()
        if not head.startswith("ref: "):
            return head
        ref = head[5:]
        path = root / ".git" / ref
        if path.exists():
            return path.read_text().strip()
        for line in (root / ".git" / "packed-refs").read_text().splitlines():
            if line.endswith(" " + ref):
                return line.split()[0]
    except OSError:
        pass
    return ""
