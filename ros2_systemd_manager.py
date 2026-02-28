#!/usr/bin/env python3
"""
ROS2 systemd service manager (YAML-driven).

Goals:
1) Read ros2_services.yaml to determine workspace path, service list, and runtime options.
2) Support three actions:
    - install-only           Install unit files only
    - install-start-enable   Install + start + enable on boot
    - uninstall              Uninstall (stop, disable, remove unit files)
3) If no action is provided, use actions.default_action from YAML.

Design notes:
- The current setup runs ros2 launch as root, so runtime.user/group/home defaults to root.
- Each service gets an independent systemd unit for easier troubleshooting.
- systemd daemon-reload runs after install/uninstall to apply changes.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml
except ImportError:
    print("[ERROR] Missing dependency PyYAML. Install it first: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


SUPPORTED_ACTIONS = {"install-only", "install-start-enable", "uninstall"}


def log(message: str) -> None:
    """Unified info output for readable execution progress."""
    print(f"[INFO] {message}")


def err(message: str) -> None:
    """Unified error output."""
    print(f"[ERROR] {message}", file=sys.stderr)


def run_cmd(cmd: List[str]) -> None:
    """Run a system command and raise on failure."""
    subprocess.run(cmd, check=True)


def require_root() -> None:
    """Root privileges are required for /etc/systemd/system and systemctl operations."""
    if os.geteuid() != 0:
        err("Please run this script with sudo/root privileges.")
        sys.exit(1)


def load_yaml_config(config_path: Path) -> Dict[str, Any]:
    """Load and parse YAML configuration."""
    if not config_path.exists():
        err(f"Configuration file does not exist: {config_path}")
        sys.exit(1)

    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        err("Invalid configuration format: top-level must be a mapping.")
        sys.exit(1)

    return data


def validate_config(config: Dict[str, Any]) -> None:
    """
    Validate required top-level fields.
    Purpose: fail fast on missing keys.
    """
    for key in ["actions", "systemd", "runtime", "workspaces"]:
        if key not in config:
            err(f"Missing required config field: {key}")
            sys.exit(1)

    workspaces = config.get("workspaces")
    if not isinstance(workspaces, dict) or not workspaces:
        err("workspaces must be a non-empty mapping.")
        sys.exit(1)


def resolve_action(cli_action: str | None, config: Dict[str, Any]) -> str:
    """
    Resolve action selection:
    - CLI action has priority
    - otherwise use YAML default_action
    """
    default_action = config.get("actions", {}).get(
        "default_action", "install-start-enable")
    action = cli_action or default_action

    if action not in SUPPORTED_ACTIONS:
        err(f"Unsupported action: {action}. Allowed: {sorted(SUPPORTED_ACTIONS)}")
        sys.exit(1)

    return action


def resolve_workspace_key(cli_workspace_key: str | None, config: Dict[str, Any]) -> str:
    """
    Resolve workspace key:
    - use --workspace-key if provided
    - otherwise use the first workspace entry
    """
    workspaces: Dict[str, Any] = config["workspaces"]

    if cli_workspace_key:
        if cli_workspace_key not in workspaces:
            err(f"workspace_key not found: {cli_workspace_key}")
            sys.exit(1)
        return cli_workspace_key

    return next(iter(workspaces.keys()))


def build_unit_content(
    *,
    description: str,
    workspace_path: Path,
    setup_script_rel: str,
    launch_command: str,
    depends_on: List[str],
    runtime: Dict[str, Any],
    wanted_by: str,
) -> str:
    """
    Build systemd unit file content.
    - ExecStart uses bash -lc to ensure setup sourcing and ROS environment are loaded.
    - launch command is started via exec to avoid an extra persistent shell process.
    - depends_on is translated to Requires + After.
    """
    shell = runtime.get("shell", "/bin/bash")
    user = runtime.get("user", "root")
    group = runtime.get("group", "root")
    home = runtime.get("home", "/root")
    restart = runtime.get("restart", "on-failure")
    restart_sec = runtime.get("restart_sec", 3)

    setup_script_abs = workspace_path / setup_script_rel

    after_targets = ["network-online.target", *depends_on]
    after_line = " ".join(after_targets)
    requires_line = f"Requires={' '.join(depends_on)}\n" if depends_on else ""

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
ExecStart={shell} -lc 'source "{setup_script_abs}" && exec {launch_command}'
Restart={restart}
RestartSec={restart_sec}

[Install]
WantedBy={wanted_by}
"""


def validate_workspace_for_install(workspace_path: Path, setup_script_rel: str) -> None:
    """Validate workspace path and setup script before install actions."""
    if not workspace_path.is_dir():
        err(f"Workspace path does not exist: {workspace_path}")
        sys.exit(1)

    setup_script_abs = workspace_path / setup_script_rel
    if not setup_script_abs.is_file():
        err(f"Setup script not found: {setup_script_abs}")
        sys.exit(1)


def install_only(config: Dict[str, Any], workspace_key: str) -> List[str]:
    """
    Install unit files only, without starting or enabling them.
    Returns: list of processed unit names.
    """
    systemd_cfg = config["systemd"]
    runtime_cfg = config["runtime"]
    workspace_cfg = config["workspaces"][workspace_key]

    unit_dir = Path(systemd_cfg.get("unit_dir", "/etc/systemd/system"))
    wanted_by = systemd_cfg.get("wanted_by", "multi-user.target")

    workspace_path = Path(workspace_cfg["path"])
    setup_script_rel = workspace_cfg.get("setup_script", "install/setup.bash")
    services = workspace_cfg.get("services", [])

    if not services:
        err(f"workspace {workspace_key} has an empty services list.")
        sys.exit(1)

    validate_workspace_for_install(workspace_path, setup_script_rel)

    unit_names: List[str] = []
    defined_unit_names = {svc["unit_name"] for svc in services}
    log(f"Writing unit files to: {unit_dir}")

    for svc in services:
        unit_name = svc["unit_name"]
        description = svc.get("description", unit_name)
        launch_command = svc["launch_command"]
        depends_on = svc.get("depends_on", [])

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
            launch_command=launch_command,
            depends_on=depends_on,
            runtime=runtime_cfg,
            wanted_by=wanted_by,
        )

        unit_file = unit_dir / unit_name
        unit_file.write_text(unit_content, encoding="utf-8")
        os.chmod(unit_file, 0o644)
        unit_names.append(unit_name)
        log(f"Written: {unit_file}")

    run_cmd(["systemctl", "daemon-reload"])
    log("systemd daemon-reload completed.")
    log("Install finished (not started, not enabled).")
    return unit_names


def install_start_enable(config: Dict[str, Any], workspace_key: str) -> None:
    """Install services, then start and enable them immediately."""
    unit_names = install_only(config, workspace_key)
    log("Enabling and starting services...")
    run_cmd(["systemctl", "enable", "--now", *unit_names])
    log("Completed: services are started and enabled on boot.")
    log(f"Check status with: systemctl status {' '.join(unit_names)}")


def uninstall(config: Dict[str, Any], workspace_key: str) -> None:
    """
    Uninstall services:
    1) stop and disable
    2) remove unit files
    3) run daemon-reload
    """
    systemd_cfg = config["systemd"]
    workspace_cfg = config["workspaces"][workspace_key]

    unit_dir = Path(systemd_cfg.get("unit_dir", "/etc/systemd/system"))
    services = workspace_cfg.get("services", [])
    unit_names = [svc["unit_name"] for svc in services]

    if not unit_names:
        log(f"workspace {workspace_key} has no services to uninstall.")
        return

    log("Stopping and disabling services (if present)...")
    subprocess.run(["systemctl", "disable", "--now", *unit_names], check=False)

    log("Removing unit files...")
    for unit_name in unit_names:
        unit_file = unit_dir / unit_name
        if unit_file.exists():
            unit_file.unlink()
            log(f"Removed: {unit_file}")

    run_cmd(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "reset-failed"], check=False)
    log("Uninstall completed.")


def parse_args() -> argparse.Namespace:
    """
    CLI design:
    - action is an optional positional argument
    - use --config to select YAML path
    - use --workspace-key to select one workspace entry
    """
    parser = argparse.ArgumentParser(
        description="ROS2 systemd service manager (YAML-driven)."
    )
    parser.add_argument(
        "action",
        nargs="?",
        help="Optional: install-only | install-start-enable | uninstall; defaults to YAML action",
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("ros2_services.yaml")),
        help="YAML config file path (default: ros2_services.yaml in script directory)",
    )
    parser.add_argument(
        "--workspace-key",
        default=None,
        help="Workspace key to operate on (default: first key in workspaces)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_root()

    config_path = Path(args.config)
    config = load_yaml_config(config_path)
    validate_config(config)

    action = resolve_action(args.action, config)
    workspace_key = resolve_workspace_key(args.workspace_key, config)

    log(f"Config file: {config_path}")
    log(f"Workspace key: {workspace_key}")
    log(f"Action: {action}")

    if action == "install-only":
        install_only(config, workspace_key)
    elif action == "install-start-enable":
        install_start_enable(config, workspace_key)
    elif action == "uninstall":
        uninstall(config, workspace_key)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        err(f"Command failed: {' '.join(exc.cmd)} (exit={exc.returncode})")
        sys.exit(exc.returncode)
    except KeyError as exc:
        err(f"Missing configuration field: {exc}")
        sys.exit(1)
