import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .runtime import err, log, run_cmd
from .version_control import (check_and_prompt_for_modifications,
                              record_uninstall, record_update)


def _resolve_setup_scripts(
    workspace_path: Path,
    setup_script_rel: Optional[str],
    setup_scripts: Optional[List[str]],
) -> List[Path]:
    """Resolve setup script paths, returning absolute paths in source order."""
    if setup_scripts:
        resolved = []
        for s in setup_scripts:
            p = Path(s)
            if not p.is_absolute():
                p = workspace_path / p
            resolved.append(p)
        return resolved
    if setup_script_rel:
        return [workspace_path / setup_script_rel]
    return []


def build_unit_content(
    *,
    description: str,
    workspace_path: Path,
    setup_script_rel: Optional[str],
    setup_scripts: Optional[List[str]],
    launch_command: str,
    depends_on: List[str],
    service_options: List[str],
    use_root: bool,
    runtime: Dict[str, Any],
    wanted_by: str,
    ros_domain_id: Optional[int] = None,
) -> str:
    """Build systemd unit file content for one service."""
    shell = runtime.get("shell", "/bin/bash")
    if use_root:
        user = "root"
        group = "root"
        home = "/root"
    else:
        user = str(runtime.get("user", "root"))
        group = str(runtime.get("group", "root"))
        home = str(runtime.get("home", "/root"))

    restart = runtime.get("restart", "on-failure")
    restart_sec = runtime.get("restart_sec", 3)

    scripts = _resolve_setup_scripts(workspace_path, setup_script_rel, setup_scripts)
    source_chain = " && ".join(f'source "{s}"' for s in scripts)
    exec_prefix = f"{source_chain} && " if source_chain else ""

    after_targets = ["network-online.target", *depends_on]
    after_line = " ".join(after_targets)
    requires_line = f"Requires={' '.join(depends_on)}\n" if depends_on else ""
    service_options_lines = "\n".join(service_options)
    service_options_block = f"{service_options_lines}\n" if service_options_lines else ""
    domain_env = f"Environment=ROS_DOMAIN_ID={ros_domain_id}\n" if ros_domain_id is not None else ""

    return f"""[Unit]
Description={description}
{requires_line}After={after_line}
Wants=network-online.target

[Service]
Type=simple
User={user}
Group={group}
WorkingDirectory={workspace_path}
Environment=HOME={home}
{domain_env}ExecStart={shell} -lc '{exec_prefix}exec {launch_command}'
{service_options_block}Restart={restart}
RestartSec={restart_sec}

[Install]
WantedBy={wanted_by}
"""


def validate_workspace_for_install(
    workspace_path: Path,
    setup_script_rel: Optional[str],
    setup_scripts: Optional[List[str]],
) -> None:
    """Validate workspace path and setup scripts before install actions."""
    if not workspace_path.is_dir():
        err(f"Workspace path does not exist: {workspace_path}")
        sys.exit(1)

    scripts = _resolve_setup_scripts(workspace_path, setup_script_rel, setup_scripts)
    for s in scripts:
        if not s.is_file():
            err(f"Setup script not found: {s}")
            sys.exit(1)


def install_only(config: Dict[str, Any], workspace_keys: List[str]) -> tuple:
    """Install unit files only, without starting or enabling them.

    Returns (all_unit_names, enabled_unit_names).
    """
    systemd_cfg = config["systemd"]
    runtime_cfg = config["runtime"]
    unit_names: List[str] = []
    enabled_unit_names: List[str] = []

    unit_dir = Path(systemd_cfg.get("unit_dir", "/etc/systemd/system"))
    wanted_by = systemd_cfg.get("wanted_by", "multi-user.target")

    log(f"Writing unit files to: {unit_dir}")

    for ws_key in workspace_keys:
        workspace_cfg = config["workspaces"][ws_key]
        workspace_path = Path(workspace_cfg["path"])
        setup_script_rel = workspace_cfg.get("setup_script")
        setup_scripts = workspace_cfg.get("setup_scripts")
        ros_domain_id = workspace_cfg.get("ros_domain_id")
        services = workspace_cfg.get("services", [])

        if not services:
            log(f"Workspace {ws_key} has no services.")
            continue

        validate_workspace_for_install(workspace_path, setup_script_rel, setup_scripts)
        defined_unit_names = {svc["unit_name"] for svc in services}

        for svc in services:
            unit_name = svc["unit_name"]
            description = svc.get("description", unit_name)
            launch_command = svc["launch_command"]
            depends_on = svc.get("depends_on", [])
            service_options = svc.get("service_options", [])
            use_root = bool(svc.get("use_root", False))
            enable = bool(svc.get("enable", True))

            if not isinstance(depends_on, list):
                err(f"Service {unit_name} has invalid depends_on: expected a list.")
                sys.exit(1)

            for dep_unit in depends_on:
                if dep_unit == unit_name:
                    err(f"Service {unit_name} cannot depend on itself in depends_on.")
                    sys.exit(1)
                if dep_unit not in defined_unit_names:
                    err(
                        f"Service {unit_name} depends on undefined service: {dep_unit}. "
                        f"Ensure it exists in the same workspace.services list."
                    )
                    sys.exit(1)

            unit_content = build_unit_content(
                description=description,
                workspace_path=workspace_path,
                setup_script_rel=setup_script_rel,
                setup_scripts=setup_scripts,
                launch_command=launch_command,
                depends_on=depends_on,
                service_options=service_options,
                use_root=use_root,
                runtime=runtime_cfg,
                wanted_by=wanted_by,
                ros_domain_id=ros_domain_id,
            )

            unit_file = unit_dir / unit_name

            if not check_and_prompt_for_modifications(unit_file, unit_name):
                err(f"Operation cancelled during processing of {unit_name}.")
                sys.exit(1)

            unit_file.write_text(unit_content, encoding="utf-8")
            os.chmod(unit_file, 0o644)

            record_update(unit_name, unit_content)

            unit_names.append(unit_name)
            if enable:
                enabled_unit_names.append(unit_name)
            log(f"Written: {unit_file} (enable={enable})")

    run_cmd(["systemctl", "daemon-reload"])
    log("systemd daemon-reload completed.")
    log("Install finished (not started, not enabled).")
    return unit_names, enabled_unit_names


def install_start_enable(config: Dict[str, Any], workspace_keys: List[str]) -> None:
    """Install services, then start and enable them (respecting per-service enable flag)."""
    unit_names, enabled_unit_names = install_only(config, workspace_keys)

    not_enabled = [u for u in unit_names if u not in enabled_unit_names]

    if enabled_unit_names:
        log("Enabling and starting services...")
        run_cmd(["systemctl", "enable", "--now", *enabled_unit_names])

    if not_enabled:
        log(f"Starting without enable: {', '.join(not_enabled)}")
        run_cmd(["systemctl", "start", *not_enabled])

    log("Completed: services are started.")
    if not_enabled:
        log(f"Note: {', '.join(not_enabled)} will NOT auto-start on boot (enable=false).")
    log(f"Check status with: systemctl status {' '.join(unit_names)}")


def get_workspace_unit_names(config: Dict[str, Any], workspace_keys: List[str]) -> List[str]:
    """Get configured unit names for the selected workspace."""
    unit_names = []
    for ws_key in workspace_keys:
        workspace_cfg = config["workspaces"][ws_key]
        services = workspace_cfg.get("services", [])
        unit_names.extend(svc["unit_name"] for svc in services)
    return unit_names


def parse_units_from_makefile(makefile_path: Path) -> List[str]:
    """Parse the UNITS variable from an existing Makefile."""
    if not makefile_path.exists():
        return []

    for raw_line in makefile_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("UNITS :="):
            units_text = line.split(":=", 1)[1].strip()
            return [item for item in units_text.split() if item]

    return []


def remove_units(unit_dir: Path, unit_names: List[str]) -> None:
    """Disable/stop and remove specified unit files if they exist."""
    if not unit_names:
        return

    log(f"Disabling and stopping removed units: {' '.join(unit_names)}")
    subprocess.run(["systemctl", "disable", "--now", *unit_names], check=False)

    for unit_name in unit_names:
        unit_file = unit_dir / unit_name

        if not check_and_prompt_for_modifications(unit_file, unit_name):
            err(f"Operation cancelled during processing of {unit_name}.")
            sys.exit(1)

        if unit_file.exists():
            unit_file.unlink()
            log(f"Removed stale unit file: {unit_file}")

        record_uninstall(unit_name)

    run_cmd(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "reset-failed"], check=False)


def sync_update(config: Dict[str, Any], workspace_keys: List[str]) -> None:
    """Stop old units, remove stale units, then install/start/enable current units."""
    from .version_control import PREVIOUS_UPDATE_DIR
    
    systemd_cfg = config["systemd"]
    unit_dir = Path(systemd_cfg.get("unit_dir", "/etc/systemd/system"))

    current_units = get_workspace_unit_names(config, workspace_keys)
    
    previous_units = []
    if PREVIOUS_UPDATE_DIR.exists():
        for f in PREVIOUS_UPDATE_DIR.iterdir():
            if f.is_file() and not f.name.endswith(".md5"):
                previous_units.append(f.name)

    if previous_units:
        log(f"Stopping previous units before update: {' '.join(previous_units)}")
        subprocess.run(["systemctl", "stop", *previous_units], check=False)

    stale_units = sorted(set(previous_units) - set(current_units))
    if stale_units:
        remove_units(unit_dir, stale_units)
    else:
        log("No stale units detected from previous tracking directory.")

    install_start_enable(config, workspace_keys)


def uninstall(config: Dict[str, Any], workspace_keys: List[str]) -> None:
    """Uninstall services for workspace."""
    systemd_cfg = config["systemd"]
    unit_dir = Path(systemd_cfg.get("unit_dir", "/etc/systemd/system"))
    
    unit_names = get_workspace_unit_names(config, workspace_keys)

    if not unit_names:
        log("No services to uninstall.")
        return

    log("Stopping and disabling services (if present)...")
    subprocess.run(["systemctl", "disable", "--now", *unit_names], check=False)

    log("Removing unit files...")
    for unit_name in unit_names:
        unit_file = unit_dir / unit_name

        if not check_and_prompt_for_modifications(unit_file, unit_name):
            err(f"Operation cancelled during processing of {unit_name}.")
            sys.exit(1)

        if unit_file.exists():
            unit_file.unlink()
            log(f"Removed: {unit_file}")

        record_uninstall(unit_name)

    run_cmd(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "reset-failed"], check=False)
    log("Uninstall completed.")
