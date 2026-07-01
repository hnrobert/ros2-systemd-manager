import getpass
import os
import pwd
import re
from datetime import datetime
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


def _extract_assignment_value(line: str, key: str) -> Optional[str]:
    """Extract the value assigned to `key` from a single KEY=... line.

    Returns the value with surrounding quotes and any trailing comment removed,
    or None if the line does not assign `key`.
    """
    m = re.match(
        rf"^[ \t]*(?:export[ \t]+)?{re.escape(key)}[ \t]*=[ \t]*(.+?)$",
        line,
    )
    if not m:
        return None
    rest = m.group(1)
    if "#" in rest:
        rest = rest.split("#", 1)[0]
    return rest.strip().strip("'").strip('"')


def _invoking_user() -> str:
    """The user who invoked the command (SUDO_USER under sudo, else current user)."""
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        return sudo_user
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USER") or "unknown"


def _build_annotation() -> str:
    """Trailing comment added to every effective line modified by this tool."""
    user = _invoking_user()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"# modified by {user} on {timestamp} using ros2-systemd-manager"


def _owner_of(path: Path) -> tuple:
    """Return (uid, gid) of `path`, or (-1, -1) if it cannot be stated."""
    try:
        st = path.stat()
        return st.st_uid, st.st_gid
    except OSError:
        return -1, -1


def _update_rc_file(
    rc_file: Path,
    assignments: Dict[str, str],
    annotation: str,
) -> str:
    """Update or append each KEY=VALUE assignment in rc_file.

    Existing assignment lines are updated in place only when their value differs
    (no duplicate appends, no needless rewrites); absent keys are appended under a
    single managed block. Every effective line written by this tool is suffixed
    with `annotation`.

    Files that do not yet exist are created. After writing, ownership is set to
    match the parent (home) directory so the corresponding user can read and edit
    the file — without this, a sudo run would leave a newly created rc/profile
    root-owned and unusable by the user.

    Returns one of:
      "modified"  content changed and written,
      "unchanged" all requested values were already present,
      "skipped"   permission denied (a per-file error is logged).
    """
    from .runtime import err

    existed = rc_file.is_file()
    try:
        text = rc_file.read_text(encoding="utf-8", errors="ignore") if existed else ""
    except PermissionError:
        err(f"Permission denied: {rc_file} (try with sudo)")
        return "skipped"

    new_text = text
    to_append: List[str] = []
    for key, value in assignments.items():
        desired_value = str(value)
        desired_line = f"export {key}={desired_value}  {annotation}"
        pattern = _var_line_pattern(key)
        matches = list(pattern.finditer(new_text))
        if matches:
            # Value already correct everywhere -> leave the line (and any existing
            # annotation) untouched to avoid needless churn.
            if all(
                _extract_assignment_value(m.group(0), key) == desired_value
                for m in matches
            ):
                continue
            new_text = pattern.sub(lambda _m: desired_line, new_text)
        else:
            to_append.append(desired_line)

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
        # Own the file like its parent (home) directory so the corresponding user
        # can read/edit it. This matters for newly created files under sudo, which
        # would otherwise be root-owned.
        owner_uid, owner_gid = _owner_of(rc_file.parent)
        if owner_uid != -1:
            try:
                os.chown(rc_file, owner_uid, owner_gid)
            except OSError:
                pass
        return "modified"
    except PermissionError:
        err(f"Permission denied: {rc_file} (try with sudo)")
        return "skipped"


def set_ros_env(
    *,
    domain_id: Optional[int] = None,
    rmw: Optional[str] = None,
    localhost_only: Optional[int] = None,
) -> List[str]:
    """Write/update the ROS DDS environment in all shell rc/profile files.

    Only the variables whose argument is not None are written: ROS_DOMAIN_ID,
    RMW_IMPLEMENTATION, ROS_LOCALHOST_ONLY. Returns the list of files that
    were modified.
    """
    from .runtime import err, log

    assignments: Dict[str, str] = {}
    if domain_id is not None:
        assignments["ROS_DOMAIN_ID"] = str(domain_id)
    if rmw is not None:
        assignments["RMW_IMPLEMENTATION"] = resolve_rmw(rmw)
    if localhost_only is not None:
        assignments["ROS_LOCALHOST_ONLY"] = str(localhost_only)

    if not assignments:
        err("No ROS DDS variables selected to write; nothing to do.")
        return []

    annotation = _build_annotation()
    modified: List[str] = []
    considered = 0
    skipped = 0
    for rc_file in _rc_files():
        if not rc_file.parent.is_dir():
            continue
        considered += 1
        status = _update_rc_file(rc_file, assignments, annotation)
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
