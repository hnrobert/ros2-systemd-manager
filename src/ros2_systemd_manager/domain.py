import re
from pathlib import Path
from typing import List, Optional

_SHELL_RC_FILES = [
    Path.home() / ".bashrc",
    Path.home() / ".zshrc",
    Path.home() / ".profile",
    Path("/root/.bashrc"),
    Path("/root/.zshrc"),
    Path("/root/.profile"),
    Path("/etc/profile"),
    Path("/etc/environment"),
]

_DOMAIN_PATTERN = re.compile(
    r"""(?:^|\n)\s*"""
    r"""(?:export\s+)?"""
    r"""ROS_DOMAIN_ID\s*=\s*['"]?(\d+)['"]?"""
)

_DOMAIN_LINE_PATTERN = re.compile(
    r"""^\s*(?:export\s+)?ROS_DOMAIN_ID\s*=\s*['"]?\d+['"]?""",
    re.MULTILINE,
)


def detect_domain_id() -> Optional[int]:
    """Scan known shell rc/profile files for an existing ROS_DOMAIN_ID setting."""
    for rc_file in _SHELL_RC_FILES:
        if not rc_file.is_file():
            continue
        try:
            text = rc_file.read_text(encoding="utf-8", errors="ignore")
        except PermissionError:
            continue
        m = _DOMAIN_PATTERN.search(text)
        if m:
            return int(m.group(1))
    return None


def set_domain_id(domain_id: int) -> None:
    """Write or update ROS_DOMAIN_ID in all existing shell rc/profile files."""
    from .runtime import err, log

    export_line = f"export ROS_DOMAIN_ID={domain_id}\n"
    marker = "export ROS_DOMAIN_ID="
    modified: List[str] = []

    for rc_file in _SHELL_RC_FILES:
        if not rc_file.parent.is_dir():
            continue
        try:
            if rc_file.is_file():
                text = rc_file.read_text(encoding="utf-8", errors="ignore")
            else:
                text = ""
        except PermissionError:
            continue

        if marker in text:
            new_text = _DOMAIN_LINE_PATTERN.sub(export_line.rstrip("\n"), text)
            if new_text != text:
                try:
                    rc_file.write_text(new_text, encoding="utf-8")
                    modified.append(str(rc_file))
                except PermissionError:
                    err(f"Permission denied: {rc_file} (try with sudo)")
        else:
            block = f"\n# ROS Domain ID\n{export_line}"
            try:
                with rc_file.open("a", encoding="utf-8") as f:
                    f.write(block)
                modified.append(str(rc_file))
            except PermissionError:
                err(f"Permission denied: {rc_file} (try with sudo)")

    if modified:
        log(f"ROS_DOMAIN_ID={domain_id} set in:")
        for p in modified:
            log(f"  {p}")
    else:
        err("No profile/rc files could be written. Try running with sudo.")
