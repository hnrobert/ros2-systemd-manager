"""The ``add`` wizard: discover ROS 2 services interactively and write them.

Run via the CLI ``add`` action. Discovers packages, launch files, executables,
arguments and config files through :mod:`ros_introspect`, prompts the user via
:mod:`tui`, resolves overwrite conflicts, then writes the resulting service
entries into ``ros2_services.yaml`` (comment-preserving) and optionally chains
into ``update`` (``-u``).
"""
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .runtime import err, log


# --------------------------------------------------------------------------- #
# workspace setup-script resolution
# --------------------------------------------------------------------------- #
def _workspace_setup_scripts(workspace_cfg: Dict[str, Any], workspace_path: Path) -> List[Path]:
    """Resolve a workspace's setup_script(s) to absolute paths."""
    scripts: List[Path] = []
    setup_scripts = workspace_cfg.get("setup_scripts")
    setup_script = workspace_cfg.get("setup_script")
    if setup_scripts:
        for s in setup_scripts:
            p = Path(s)
            scripts.append(p if p.is_absolute() else workspace_path / p)
    elif setup_script:
        p = Path(setup_script)
        scripts.append(p if p.is_absolute() else workspace_path / setup_script)
    return scripts


def _collect_all_setup_scripts(
    workspaces: Dict[str, Any], workspace_paths: Dict[str, Path]
) -> List[Path]:
    out: List[Path] = []
    for k, wcfg in workspaces.items():
        for s in _workspace_setup_scripts(wcfg, workspace_paths[k]):
            if s not in out:
                out.append(s)
    return out


# --------------------------------------------------------------------------- #
# main entry
# --------------------------------------------------------------------------- #
def run_add(args, config: Dict[str, Any], config_path) -> None:
    # Lazy imports so the base package works without the [add] extra.
    try:
        from . import config_edit, ros_introspect, tui
    except Exception as exc:  # pragma: no cover - dependency guard
        err(
            "The `add` action needs extra dependencies. "
            "Install them with: pip install 'ros2-systemd-manager[add]'"
        )
        err(f"({exc})")
        sys.exit(1)

    workspaces = config.get("workspaces", {})
    if not workspaces:
        err("No workspaces defined in the config — nothing to add to.")
        sys.exit(1)
    workspace_paths = {k: Path(v["path"]) for k, v in workspaces.items()}

    targets = _resolve_targets(args, workspaces, workspace_paths, ros_introspect, tui)
    if not targets:
        log("Nothing selected.")
        return

    decisions: Dict[str, bool] = {}  # sticky: "overwrite"->True / "skip"->False
    entries: List[Tuple[str, Dict[str, Any], bool]] = []  # (ws_key, service, overwrite)
    for pkg, ws_key in targets:
        svc = _build_service_for_package(
            pkg, ws_key, workspaces[ws_key], workspace_paths[ws_key],
            ros_introspect, tui,
        )
        if svc is None:
            continue
        existing = _existing_unit_names(config, ws_key)
        write = _decide_overwrite(svc["unit_name"], existing, decisions, tui)
        if not write:
            log(f"Skipping {svc['unit_name']} (already exists).")
            continue
        entries.append((ws_key, svc, svc["unit_name"] in existing))

    if not entries:
        log("No services to add.")
        return

    _preview(entries)
    if not tui.confirm("Write these entries to the config?", default=True):
        log("Aborted — no changes written.")
        return

    _write_entries(Path(config_path), entries, config_edit)
    log(f"Wrote {len(entries)} service entry(ies) to {config_path}.")

    if getattr(args, "update", False):
        _run_update_chain(args, Path(config_path), entries)


# --------------------------------------------------------------------------- #
# target resolution
# --------------------------------------------------------------------------- #
def _resolve_targets(args, workspaces, workspace_paths, ros_introspect, tui):
    targets: List[Tuple[str, str]] = []
    if getattr(args, "target", None):
        setup = _collect_all_setup_scripts(workspaces, workspace_paths)
        pkg, ws_key = ros_introspect.resolve_target(setup, workspace_paths, args.target)
        return [(pkg, ws_key)]
    if getattr(args, "all", False):  # add: -a means all packages
        for ws_key, wcfg in workspaces.items():
            setup = _workspace_setup_scripts(wcfg, workspace_paths[ws_key])
            try:
                pkgs = ros_introspect.list_workspace_packages(setup, workspace_paths[ws_key])
            except ros_introspect.RosIntrospectError as exc:
                err(str(exc))
                sys.exit(1)
            log(f"Workspace {ws_key}: {len(pkgs)} package(s).")
            targets.extend((p, ws_key) for p in pkgs)
        return targets
    # interactive
    ws_key = _choose_workspace(workspaces, tui)
    wcfg = workspaces[ws_key]
    setup = _workspace_setup_scripts(wcfg, workspace_paths[ws_key])
    try:
        pkgs = ros_introspect.list_workspace_packages(setup, workspace_paths[ws_key])
    except ros_introspect.RosIntrospectError as exc:
        err(str(exc))
        sys.exit(1)
    if not pkgs:
        log(f"No workspace-local packages found in {ws_key}.")
        return []
    selected = tui.multi_select(f"Select packages to add ({ws_key})", pkgs)
    return [(p, ws_key) for p in selected]


def _choose_workspace(workspaces, tui) -> str:
    keys = list(workspaces.keys())
    if len(keys) == 1:
        return keys[0]
    return tui.single_select("Which workspace?", keys)


# --------------------------------------------------------------------------- #
# per-package service construction
# --------------------------------------------------------------------------- #
def _build_service_for_package(
    pkg, ws_key, wcfg, ws_path, ros_introspect, tui
) -> Optional[Dict[str, Any]]:
    setup = _workspace_setup_scripts(wcfg, ws_path)
    try:
        launch_files = ros_introspect.list_launch_files(setup, pkg)
        execs = ros_introspect.list_executables(setup, pkg)
    except ros_introspect.RosIntrospectError as exc:
        err(f"Could not introspect {pkg}: {exc}")
        return None

    choices: List[str] = []
    kind: Dict[str, str] = {}  # choice-label -> "launch:basename" | "exec:name"
    for lf in launch_files:
        label = f"launch: {lf.name}"
        choices.append(label)
        kind[label] = f"launch:{lf.name}"
    for ex in execs:
        label = f"run: {ex}"
        choices.append(label)
        kind[label] = f"exec:{ex}"
    if not choices:
        err(f"Package {pkg} has no launch files or executables; skipping.")
        return None

    chosen = tui.single_select(f"[{pkg}] choose how to run it", choices, allow_skip=True)
    if not chosen:
        return None
    sel = kind[chosen]

    if sel.startswith("launch:"):
        basename = sel.split(":", 1)[1]
        launch_command = _build_launch_command(setup, pkg, basename, ros_introspect, tui)
        default_unit = f"ros2-{pkg}.service"
        default_desc = pkg
    else:
        exec_name = sel.split(":", 1)[1]
        launch_command = _build_run_command(setup, pkg, exec_name, ros_introspect, tui)
        default_unit = f"ros2-{pkg}-{exec_name}.service"
        default_desc = f"{pkg} ({exec_name})"

    unit_name = tui.text_with_default("unit_name", default=default_unit)
    description = tui.text_with_default("description", default=default_desc)
    return {"unit_name": unit_name, "description": description, "launch_command": launch_command}


def _build_launch_command(setup, pkg, basename, ros_introspect, tui) -> str:
    cmd = f"ros2 launch {pkg} {basename}"
    try:
        args_list = ros_introspect.launch_arguments(setup, pkg, basename)
    except ros_introspect.RosIntrospectError as exc:
        err(f"Could not read launch arguments for {basename}: {exc}")
        args_list = []
    tokens: List[str] = []
    for a in args_list:
        name = a["name"]
        default = a.get("default")
        required = a.get("required", False)
        desc = a.get("description", "")
        value = tui.text_with_default(name, default=default, required=required, description=desc)
        if value:
            tokens.append(f"{name}:={value}")
    return cmd + (" " + " ".join(tokens) if tokens else "")


def _build_run_command(setup, pkg, exec_name, ros_introspect, tui) -> str:
    params = tui.manual_params_input()
    config_file = _choose_config_file(setup, pkg, ros_introspect, tui)
    parts = [f"ros2 run {pkg} {exec_name}"]
    ros_args: List[str] = []
    for p in params:
        ros_args.append(f"-p {p}")
    if config_file:
        ros_args.append(f"--params-file {config_file}")
    if ros_args:
        parts.append("--ros-args " + " ".join(ros_args))
    return " ".join(parts)


def _choose_config_file(setup, pkg, ros_introspect, tui) -> Optional[str]:
    try:
        files = ros_introspect.list_config_files(setup, pkg)
    except ros_introspect.RosIntrospectError:
        return None
    if not files:
        return None
    labels = [f.name for f in files]
    chosen = tui.single_select(
        f"[{pkg}] add a config file? (optional)", ["(none)", *labels]
    )
    if not chosen or chosen == "(none)":
        return None
    match = next((f for f in files if f.name == chosen), None)
    if match is None:
        return None
    return str(match)


# --------------------------------------------------------------------------- #
# conflict resolution
# --------------------------------------------------------------------------- #
def _existing_unit_names(config: Dict[str, Any], ws_key: str) -> set:
    services = config.get("workspaces", {}).get(ws_key, {}).get("services", []) or []
    return {s.get("unit_name") for s in services if isinstance(s, dict)}


def _decide_overwrite(unit_name, existing: set, decisions: Dict[str, bool], tui) -> bool:
    if unit_name not in existing:
        return True  # new entry, no conflict
    if "mode" in decisions:
        return decisions["mode"]
    choice = tui.single_select(
        f"'{unit_name}' already exists. What now?",
        ["Overwrite this", "Always overwrite", "Skip this", "Always skip"],
    )
    if choice == "Overwrite this":
        return True
    if choice == "Always overwrite":
        decisions["mode"] = True
        return True
    if choice == "Always skip":
        decisions["mode"] = False
        return False
    return False  # Skip this


# --------------------------------------------------------------------------- #
# preview / write / update chain
# --------------------------------------------------------------------------- #
def _preview(entries) -> None:
    print("\nPlanned services:")
    for ws_key, svc, _ in entries:
        print(f"  [{ws_key}] {svc['unit_name']}")
        print(f"      description: {svc.get('description', '')}")
        print(f"      launch_command: {svc['launch_command']}")


def _write_entries(config_path: Path, entries, config_edit) -> None:
    data = config_edit.load_rt(config_path)
    by_ws: Dict[str, List[Tuple[dict, bool]]] = {}
    for ws_key, svc, overwrite in entries:
        by_ws.setdefault(ws_key, []).append((svc, overwrite))
    for ws_key, svcs in by_ws.items():
        config_edit.apply_services(data, ws_key, svcs)
    config_edit.dump_rt(config_path, data)


def _run_update_chain(args, config_path: Path, entries) -> None:
    from .runtime import require_root
    from .systemd_ops import sync_update
    from .config import load_yaml_config, validate_config

    require_root()
    cfg = load_yaml_config(config_path)
    validate_config(cfg)
    config_id = str(config_path.resolve())
    affected: List[str] = []
    for ws_key, _, _ in entries:
        if ws_key not in affected:
            affected.append(ws_key)
    for ws_key in affected:
        log(f"--update: syncing workspace {ws_key}")
        sync_update(cfg, [ws_key], config_id, include_explicit=False, force=getattr(args, "force", False))
