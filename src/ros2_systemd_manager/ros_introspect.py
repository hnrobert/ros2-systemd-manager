"""ROS 2 package/launch/executable introspection (shells out to ``ros2``).

All ``ros2`` commands are run inside a shell that first sources the workspace's
setup script(s), so the caller only needs to pass the resolved absolute setup
script paths. Everything raises :class:`RosIntrospectError` with a clear message
on failure (``ros2`` missing, workspace not built, package unknown, ...).

The ``parse_*`` helpers are pure (no subprocess) so they can be unit-tested
without a ROS environment.
"""
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .runtime import err

LAUNCH_GLOBS = ("*.launch.py", "*.launch.xml", "*.launch.yaml")


class RosIntrospectError(RuntimeError):
    """Raised when ROS introspection cannot proceed (clear, user-facing message)."""


# --------------------------------------------------------------------------- #
# Pure parsers (testable without ROS)
# --------------------------------------------------------------------------- #
def parse_executables(output: str, package: Optional[str] = None) -> List[str]:
    """Parse ``ros2 pkg executables [pkg]`` output.

    Output lines look like ``<package> <executable>``. Returns the executable
    names (right-hand column), de-duplicated, order-preserved.
    """
    exe: List[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        # `ros2 pkg executables <pkg>` prints "<pkg> <exe>"; without a pkg arg
        # it prints "<pkg> <exe>" too. Take the last token as the executable.
        name = parts[-1] if len(parts) >= 2 else parts[0]
        if name not in exe:
            exe.append(name)
    return exe


# Matches an argument header: an indented (or not) 'name' (single or double quoted).
_ARG_HEADER_RE = re.compile(r"^\s*['\"]([A-Za-z0-9_\.]+)['\"]\s*(.*)$")
# A default value, tolerant across ROS 2 versions / quoting:
#   (default: 'x') | default value: 'x' | default='x'
_DEFAULT_RE = re.compile(
    r"default(?:\s+value)?\s*[:=]\s*['\"]?(.*?)['\"]?\s*(?:\)|$)",
    re.IGNORECASE,
)


def parse_show_args(output: str) -> List[Dict[str, object]]:
    """Parse ``ros2 launch <pkg> <file> --show-args`` output.

    Returns a list of ``{name, default, required, description}`` dicts. An
    argument is ``required`` when no default is declared. Tolerant of the
    formatting differences across ROS 2 distributions.
    """
    lines = output.splitlines()
    args: List[Dict[str, object]] = []
    i = 0
    while i < len(lines):
        m = _ARG_HEADER_RE.match(lines[i])
        if not m:
            i += 1
            continue
        name, rest = m.group(1), m.group(2).strip()
        desc_lines: List[str] = []
        if rest:
            desc_lines.append(rest)
        i += 1
        # Collect indented description lines that follow (and aren't themselves arg headers).
        while i < len(lines):
            nxt = lines[i]
            if _ARG_HEADER_RE.match(nxt):
                break
            if nxt.startswith(" ") or nxt.startswith("\t"):
                desc_lines.append(nxt.strip())
                i += 1
            else:
                break
        body = " ".join(desc_lines).strip()
        dm = _DEFAULT_RE.search(rest + " " + body)
        default: Optional[str] = dm.group(1).strip() if dm else None
        # Strip a trailing parenthesis/whitespace artifact from the captured default.
        if default:
            default = default.rstrip(")").strip()
        args.append(
            {
                "name": name,
                "default": default,
                "required": default is None,
                "description": body,
            }
        )
    return args


# --------------------------------------------------------------------------- #
# subprocess-backed introspection
# --------------------------------------------------------------------------- #
def _source_prefix(setup_scripts: List[Path]) -> str:
    """Build the `source "a" && source "b" && ` shell prefix."""
    parts = []
    for s in setup_scripts:
        parts.append(f"source {shlex.quote(str(s))}")
    prefix = " && ".join(parts)
    return (prefix + " && ") if prefix else ""


def run_ros(setup_scripts: List[Path], cmd: List[str]) -> str:
    """Source the workspace setup scripts and run a ROS 2 command.

    Returns stdout. Raises :class:`RosIntrospectError` on a missing ``ros2``,
    a non-zero exit, or a missing setup script.
    """
    missing = [s for s in setup_scripts if not Path(s).is_file()]
    if missing:
        raise RosIntrospectError(
            "Workspace setup script not found: "
            + ", ".join(str(m) for m in missing)
            + ". Is the workspace built? (run `colcon build`)"
        )
    sh = "bash"
    full = ["-lc", _source_prefix(setup_scripts) + "exec " + " ".join(shlex.quote(c) for c in cmd)]
    try:
        proc = subprocess.run([sh, *full], capture_output=True, text=True, check=False)
    except FileNotFoundError:
        raise RosIntrospectError(
            f"Could not run '{sh}' to source the workspace and invoke ros2."
        )
    if proc.returncode != 0:
        msg = proc.stderr.strip() or proc.stdout.strip()
        raise RosIntrospectError(
            f"`{' '.join(cmd)}` failed (exit {proc.returncode}): {msg[:400]}"
        )
    # ros2 itself may be missing (command not found surfaces in stderr/returncode).
    if "ros2: not found" in (proc.stderr + proc.stdout) or "ros2: command not found" in (
        proc.stderr + proc.stdout
    ):
        raise RosIntrospectError(
            "`ros2` was not found after sourcing the workspace setup. "
            "Is ROS 2 installed and the workspace built?"
        )
    return proc.stdout


def package_prefix(setup_scripts: List[Path], pkg: str) -> Path:
    out = run_ros(setup_scripts, ["ros2", "pkg", "prefix", pkg]).strip()
    if not out:
        raise RosIntrospectError(f"`ros2 pkg prefix {pkg}` returned no path.")
    return Path(out.splitlines()[0])


def list_packages(setup_scripts: List[Path]) -> List[str]:
    out = run_ros(setup_scripts, ["ros2", "pkg", "list"])
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def list_workspace_packages(
    setup_scripts: List[Path], workspace_path: Path
) -> List[str]:
    """Packages whose install prefix is under ``workspace_path`` (workspace-local)."""
    ws = str(workspace_path).rstrip("/")
    local: List[str] = []
    for pkg in list_packages(setup_scripts):
        try:
            prefix = package_prefix(setup_scripts, pkg)
        except RosIntrospectError:
            continue
        if str(prefix).rstrip("/").startswith(ws):
            local.append(pkg)
    return local


def list_launch_files(setup_scripts: List[Path], pkg: str) -> List[Path]:
    share = package_prefix(setup_scripts, pkg) / "share" / pkg / "launch"
    if not share.is_dir():
        return []
    files: List[Path] = []
    for glob in LAUNCH_GLOBS:
        files.extend(sorted(share.glob(glob)))
    # de-dup, preserve order
    seen = set()
    unique: List[Path] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            unique.append(f)
    return unique


def list_executables(setup_scripts: List[Path], pkg: str) -> List[str]:
    out = run_ros(setup_scripts, ["ros2", "pkg", "executables", pkg])
    return parse_executables(out, pkg)


def launch_arguments(
    setup_scripts: List[Path], pkg: str, launchfile: str
) -> List[Dict[str, object]]:
    out = run_ros(setup_scripts, ["ros2", "launch", pkg, launchfile, "--show-args"])
    return parse_show_args(out)


def list_config_files(setup_scripts: List[Path], pkg: str) -> List[Path]:
    cfg = package_prefix(setup_scripts, pkg) / "share" / pkg / "config"
    if not cfg.is_dir():
        return []
    return sorted(p for p in cfg.iterdir() if p.is_file())


# --------------------------------------------------------------------------- #
# target resolution (path or package name -> (pkg, workspace_key))
# --------------------------------------------------------------------------- #
def _read_package_name(pkg_dir: Path) -> Optional[str]:
    xml = pkg_dir / "package.xml"
    if not xml.is_file():
        return None
    try:
        root = ET.parse(xml).getroot()
    except ET.ParseError:
        return None
    name_el = root.find("name")
    if name_el is not None and name_el.text:
        return name_el.text.strip()
    return None


def _find_owning_workspace(
    workspace_paths: Dict[str, Path], target: Path
) -> Optional[str]:
    tgt = str(target).rstrip("/")
    for key, wpath in workspace_paths.items():
        ws = str(wpath).rstrip("/")
        if tgt == ws or tgt.startswith(ws + "/"):
            return key
    return None


def resolve_target(
    setup_scripts: List[Path],
    workspace_paths: Dict[str, Path],
    target: str,
) -> Tuple[str, str]:
    """Resolve a path-or-package-name argument to ``(package, workspace_key)``.

    Aborts (via ``err`` + ``sys.exit``) if the target does not belong to one of
    the configured workspaces.
    """
    is_path = "/" in target or Path(target).exists()
    if is_path:
        p = Path(target).expanduser()
        p = p if p.is_absolute() else (Path.cwd() / p)
        p = p.resolve()
        # The path may point at the package dir, or somewhere inside it.
        owner = _find_owning_workspace(workspace_paths, p)
        if not owner:
            err(
                f"Path '{target}' does not belong to any workspace in this config "
                f"({', '.join(str(w) for w in workspace_paths.values())})."
            )
            sys.exit(1)
        # Walk up to find package.xml.
        pkg_name: Optional[str] = None
        cur = p if p.is_dir() else p.parent
        for candidate in [cur, *cur.parents]:
            nm = _read_package_name(candidate)
            if nm:
                pkg_name = nm
                break
            if candidate == Path(workspace_paths[owner]).resolve():
                break
        if not pkg_name:
            err(f"Could not find a package (package.xml) at or above '{target}'.")
            sys.exit(1)
        return pkg_name, owner

    # Treat as a package name: confirm it exists and belongs to a workspace.
    try:
        all_pkgs = list_packages(setup_scripts)
    except RosIntrospectError as exc:
        err(str(exc))
        sys.exit(1)
    if target not in all_pkgs:
        err(f"'{target}' is not a known ROS 2 package (`ros2 pkg list`).")
        sys.exit(1)
    try:
        prefix = package_prefix(setup_scripts, target)
    except RosIntrospectError as exc:
        err(str(exc))
        sys.exit(1)
    owner = _find_owning_workspace(workspace_paths, prefix)
    if not owner:
        err(
            f"Package '{target}' (prefix {prefix}) does not belong to any workspace "
            f"in this config."
        )
        sys.exit(1)
    return target, owner
