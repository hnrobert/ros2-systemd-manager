import os
import pwd
import re
from pathlib import Path
from typing import Dict, List, Optional

# Per-user rc files touched within each considered home directory. Both .profile
# and .bash_profile are included because a login bash reads only the FIRST of
# (.bash_profile, .bash_login, .profile) — writing .profile alone is silently
# skipped when .bash_profile exists.
_PER_USER_RC_NAMES = (".bashrc", ".bash_profile", ".zshrc", ".profile")


def _candidate_homes() -> List[Path]:
    """Home directories whose rc files we should touch.

    Under sudo, Path.home() resolves to /root, which would silently skip the
    real invoking user's ~/.bashrc. We therefore prefer SUDO_USER's home,
    then the effective user's home, and always include /root.
    """
    homes: List[Path] = []
    seen: set = set()

    def _add(home: object) -> None:
        try:
            p = Path(str(home))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return
        if str(p) and p not in seen:
            seen.add(p)
            homes.append(p)

    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        try:
            _add(pwd.getpwnam(sudo_user).pw_dir)
        except KeyError:
            pass
    _add(Path.home())     # effective user (root under sudo)
    _add("/root")         # ensure root is always covered
    return homes


def _rc_files() -> List[Path]:
    """All rc/profile files to read or write (deduped, order-preserving)."""
    files: List[Path] = []
    seen: set = set()
    for home in _candidate_homes():
        if home.is_dir():
            for name in _PER_USER_RC_NAMES:
                f = home / name
                if f not in seen:
                    seen.add(f)
                    files.append(f)
    for f in (Path("/etc/profile"), Path("/etc/environment")):
        if f not in seen:
            seen.add(f)
            files.append(f)
    return files

# Short alias -> full rmw package identifier written to RMW_IMPLEMENTATION.
_RMW_ALIASES: Dict[str, str] = {
    "cyclonedds": "rmw_cyclonedds_cpp",
    "fastrtps": "rmw_fastrtps_cpp",
}

_DOMAIN_PATTERN = re.compile(
    r"""(?:^|\n)\s*"""
    r"""(?:export\s+)?"""
    r"""ROS_DOMAIN_ID\s*=\s*['"]?(\d+)['"]?"""
)


def _var_line_pattern(key: str) -> "re.Pattern[str]":
    """Regex matching an existing `export KEY=...` (or bare `KEY=...`) line."""
    return re.compile(
        rf"^[ \t]*(?:export[ \t]+)?{re.escape(key)}[ \t]*=[ \t]*['\"]?.*?['\"]?[ \t]*$",
        re.MULTILINE,
    )


def detect_domain_id() -> Optional[int]:
    """Scan known shell rc/profile files for an existing ROS_DOMAIN_ID setting."""
    for rc_file in _rc_files():
        try:
            if not rc_file.is_file():
                continue
            text = rc_file.read_text(encoding="utf-8", errors="ignore")
        except PermissionError:
            continue
        m = _DOMAIN_PATTERN.search(text)
        if m:
            return int(m.group(1))
    return None


def resolve_rmw(value: str) -> str:
    """Normalize a short rmw alias (cyclonedds/fastrtps) to its full rmw_*_cpp id.

    Full rmw_*_cpp identifiers pass through unchanged. Unknown values raise
    ValueError so the CLI can surface a friendly error.
    """
    if value in _RMW_ALIASES:
        return _RMW_ALIASES[value]
    if value.startswith("rmw_"):
        return value
    raise ValueError(
        f"Unknown RMW value: {value!r}. Use one of: {', '.join(_RMW_ALIASES)} "
        f"(or a full rmw_*_cpp name)."
    )


def _update_rc_file(rc_file: Path, assignments: Dict[str, str]) -> str:
    """Update or append each KEY=VALUE assignment in rc_file.

    Existing assignment lines are replaced in place; keys that are absent are
    appended together under a single managed block. Returns one of:
    "modified" (content changed and written), "unchanged" (already at target
    values), or "skipped" (permission denied — a per-file error is logged).
    """
    from .runtime import err

    try:
        text = rc_file.read_text(encoding="utf-8", errors="ignore") if rc_file.is_file() else ""
    except PermissionError:
        err(f"Permission denied: {rc_file} (try with sudo)")
        return "skipped"

    new_text = text
    to_append: List[str] = []
    for key, value in assignments.items():
        pattern = _var_line_pattern(key)
        if pattern.search(new_text):
            new_text = pattern.sub(f"export {key}={value}", new_text)
        else:
            to_append.append(f"export {key}={value}")

    if to_append:
        block = (
            "\n\n# ROS DDS environment (managed by ros2-systemd-manager)\n"
            + "\n".join(to_append)
            + "\n"
        )
        new_text = (new_text.rstrip() + block) if new_text.strip() else block.lstrip()

    if new_text == text:
        return "unchanged"
    try:
        rc_file.parent.mkdir(parents=True, exist_ok=True)
        rc_file.write_text(new_text, encoding="utf-8")
        return "modified"
    except PermissionError:
        err(f"Permission denied: {rc_file} (try with sudo)")
        return "skipped"


def set_ros_env(*, domain_id: int, rmw: str, localhost_only: int) -> List[str]:
    """Write/update the ROS DDS environment in all shell rc/profile files.

    Always writes all three variables: ROS_DOMAIN_ID, RMW_IMPLEMENTATION,
    ROS_LOCALHOST_ONLY. Returns the list of files that were modified.
    """
    from .runtime import err, log

    assignments = {
        "ROS_DOMAIN_ID": str(domain_id),
        "RMW_IMPLEMENTATION": resolve_rmw(rmw),
        "ROS_LOCALHOST_ONLY": str(localhost_only),
    }

    modified: List[str] = []
    considered = 0
    skipped = 0
    for rc_file in _rc_files():
        if not rc_file.parent.is_dir():
            continue
        considered += 1
        status = _update_rc_file(rc_file, assignments)
        if status == "modified":
            modified.append(str(rc_file))
        elif status == "skipped":
            skipped += 1

    if modified:
        log("ROS DDS environment written to shell rc/profile files:")
        for key, value in assignments.items():
            log(f"  {key}={value}")
        log("Updated files:")
        for p in modified:
            log(f"  {p}")
    elif considered and skipped == considered:
        err("No profile/rc files could be written (all permission denied). Try with sudo.")
    elif considered:
        log("ROS DDS environment already up to date in all shell rc/profile files.")
    else:
        err("No profile/rc files found to write into.")

    return modified
