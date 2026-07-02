import difflib
import filecmp
import hashlib
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import List

from .runtime import err, log

CONFIG_DIR = Path.home() / ".config" / "ros2-systemd-manager"
PREVIOUS_UPDATE_DIR = CONFIG_DIR / "previous-update"
ARCHIVE_DIR = CONFIG_DIR / "archive"


def md5_string(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()


def _archive_modified_unit(systemd_unit_path: Path, unit_name: str) -> None:
    """Archive a manually-modified unit file before it is overwritten/removed."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = ARCHIVE_DIR / f"{unit_name}_{timestamp}.archive"
    try:
        shutil.copy2(systemd_unit_path, archive_path)
        log(f"Archived to {archive_path}")
    except OSError as e:
        err(f"Failed to archive: {e}")


def check_and_prompt_for_modifications(systemd_unit_path: Path, unit_name: str, force: bool = False) -> bool:
    """
    Checks if the systemd file differs from our tracked version.
    Prompts the user if it differs, unless force=True (then it auto-archives the
    manual change and proceeds without prompting).
    Returns True to proceed, False to cancel.
    """
    tracked_file = PREVIOUS_UPDATE_DIR / unit_name

    if not systemd_unit_path.exists():
        return True  # Nothing deployed, so no manual modifications

    tracked_lines: List[str] = []
    if tracked_file.exists():
        try:
            if filecmp.cmp(str(systemd_unit_path), str(tracked_file), shallow=False):
                return True  # File matches exactly, proceed
        except OSError:
            pass
        tracked_lines = tracked_file.read_text(
            encoding="utf-8").splitlines(keepends=True)

    systemd_lines = systemd_unit_path.read_text(
        encoding="utf-8").splitlines(keepends=True)

    if force:
        # --force: skip the prompt and take the safe default (archive, then proceed).
        _archive_modified_unit(systemd_unit_path, unit_name)
        return True

    print(f"\n[Warning] Manual modifications detected for {unit_name}:")
    diff = difflib.unified_diff(
        tracked_lines, systemd_lines,
        fromfile=f"Tracked ({tracked_file.name})" if tracked_file.exists(
        ) else "Tracked (None)",
        tofile=f"Systemd ({systemd_unit_path.name})"
    )
    sys.stdout.writelines(diff)
    print("\nOptions:")
    print("  [Y] Archive the modified systemd file and proceed (default)")
    print("  [u] Proceed without archiving")
    print("  [c] Cancel the operation")

    while True:
        choice = input(
            f"Choose an action for {unit_name} [Y/u/c]: ").strip().lower()
        if choice in ('', 'y'):
            _archive_modified_unit(systemd_unit_path, unit_name)
            return True
        elif choice == 'u':
            return True
        elif choice == 'c':
            log("Operation cancelled by user.")
            return False
        else:
            print("Invalid choice, please enter Y, u, or c.")


def _recalculate_total_hash() -> None:
    if not PREVIOUS_UPDATE_DIR.exists():
        return

    overall_md5 = hashlib.md5()
    files_to_hash = sorted([
        f for f in PREVIOUS_UPDATE_DIR.iterdir()
        if f.is_file() and f.name != "total.md5"
    ], key=lambda x: x.name)

    for f in files_to_hash:
        try:
            overall_md5.update(f.read_bytes())
        except OSError:
            pass

    total_md5_path = PREVIOUS_UPDATE_DIR / "total.md5"
    try:
        total_md5_path.write_text(overall_md5.hexdigest(), encoding="utf-8")
    except OSError:
        pass


def record_update(unit_name: str, content: str, config_path: str = "") -> None:
    PREVIOUS_UPDATE_DIR.mkdir(parents=True, exist_ok=True)
    tracked_file = PREVIOUS_UPDATE_DIR / unit_name
    try:
        tracked_file.write_text(content, encoding="utf-8")

        md5_hash = md5_string(content)
        md5_file = PREVIOUS_UPDATE_DIR / f"{unit_name}.md5"
        md5_file.write_text(md5_hash, encoding="utf-8")

        # Remember which config installed this unit so update/uninstall can be
        # scoped per-directory instead of touching units from other configs.
        if config_path:
            origin_file = PREVIOUS_UPDATE_DIR / f"{unit_name}.origin"
            origin_file.write_text(config_path, encoding="utf-8")

        _recalculate_total_hash()
    except OSError as e:
        err(f"Failed to record update for {unit_name}: {e}")


def record_uninstall(unit_name: str) -> None:
    if not PREVIOUS_UPDATE_DIR.exists():
        return

    tracked_file = PREVIOUS_UPDATE_DIR / unit_name
    md5_file = PREVIOUS_UPDATE_DIR / f"{unit_name}.md5"
    origin_file = PREVIOUS_UPDATE_DIR / f"{unit_name}.origin"

    try:
        if tracked_file.exists():
            tracked_file.unlink()
        if md5_file.exists():
            md5_file.unlink()
        if origin_file.exists():
            origin_file.unlink()

        _recalculate_total_hash()
    except OSError as e:
        err(f"Failed to record uninstall for {unit_name}: {e}")


def _is_unit_file(name: str) -> bool:
    """True for a tracking-store entry that represents a unit (not a sidecar)."""
    return not (
        name.endswith(".md5") or name.endswith(".origin") or name == "total.md5"
    )


def all_tracked_units() -> List[str]:
    """Every tracked unit name across all configs (legacy originless units included)."""
    if not PREVIOUS_UPDATE_DIR.exists():
        return []
    return sorted(
        f.name for f in PREVIOUS_UPDATE_DIR.iterdir()
        if f.is_file() and _is_unit_file(f.name)
    )


def tracked_units_for_config(config_path: str) -> List[str]:
    """Unit names installed by the given config, matched via the .origin sidecar."""
    if not PREVIOUS_UPDATE_DIR.exists():
        return []
    units: List[str] = []
    for f in PREVIOUS_UPDATE_DIR.iterdir():
        if not (f.is_file() and _is_unit_file(f.name)):
            continue
        origin_file = PREVIOUS_UPDATE_DIR / f"{f.name}.origin"
        if not origin_file.exists():
            continue
        try:
            if origin_file.read_text(encoding="utf-8").strip() == config_path:
                units.append(f.name)
        except OSError:
            pass
    return sorted(units)


def all_config_paths() -> List[str]:
    """Distinct config yaml paths (that still exist) the tool has installed for."""
    if not PREVIOUS_UPDATE_DIR.exists():
        return []
    paths: List[str] = []
    seen: set = set()
    for f in PREVIOUS_UPDATE_DIR.iterdir():
        if not (f.is_file() and f.name.endswith(".origin")):
            continue
        try:
            cp = f.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if cp and cp not in seen and Path(cp).is_file():
            seen.add(cp)
            paths.append(cp)
    return sorted(paths)
