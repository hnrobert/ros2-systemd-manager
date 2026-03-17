import argparse
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .actions import normalize_action
from .config import (
    load_yaml_config,
    resolve_action,
    resolve_workspace_key,
    validate_config,
)
from .makefile_gen import write_makefile
from .runtime import err, log, require_root
from .scaffold import init_defaults
from .systemd_ops import install_only, install_start_enable, sync_update, uninstall


def _default_config_path() -> str:
    local_candidate = Path.cwd() / "ros2_services.yaml"
    package_candidate = Path(__file__).resolve(
    ).parents[2] / "ros2_services.yaml"
    if local_candidate.exists():
        return str(local_candidate)
    return str(package_candidate)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ROS2 systemd service manager (YAML-driven).")
    parser.add_argument(
        "action",
        nargs="?",
        help=(
            "Optional: init | install | apply | uninstall | update | makefile; "
            "defaults to YAML action"
        ),
    )
    parser.add_argument(
        "--config",
        default=None,
        help="YAML config file path",
    )
    parser.add_argument(
        "--workspace-key",
        default=None,
        help="Workspace key to operate on (default: first key in workspaces)",
    )
    parser.add_argument(
        "--previous-makefile",
        default=None,
        help="Optional path to previous Makefile for stale-unit detection during update",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite files when used with init",
    )
    return parser.parse_args()


def run() -> None:
    args = parse_args()
    action_arg = normalize_action(args.action) if args.action else None

    if action_arg == "init":
        target_config = Path(args.config) if args.config else (
            Path.cwd() / "ros2_services.yaml")
        target_workspace_key = args.workspace_key or "default_ws"
        init_defaults(target_config, target_workspace_key, force=args.force)
        return

    config_path = Path(args.config) if args.config else Path(
        _default_config_path())
    config = load_yaml_config(config_path)
    validate_config(config)

    action = resolve_action(action_arg, config)
    workspace_key = resolve_workspace_key(args.workspace_key, config)

    if action != "makefile":
        require_root()

    log(f"Config file: {config_path}")
    log(f"Workspace key: {workspace_key}")
    log(f"Action: {action}")

    if action == "install":
        install_only(config, workspace_key)
    elif action == "apply":
        install_start_enable(config, workspace_key)
    elif action == "uninstall":
        uninstall(config, workspace_key)
    elif action == "update":
        previous_makefile: Optional[Path] = (
            Path(args.previous_makefile) if args.previous_makefile else None
        )
        sync_update(config, workspace_key, previous_makefile)
    elif action == "makefile":
        log("Skipping systemd operations; refreshing Makefile only.")

    write_makefile(config, config_path, workspace_key)


def entrypoint() -> int:
    try:
        run()
    except subprocess.CalledProcessError as exc:
        err(f"Command failed: {' '.join(exc.cmd)} (exit={exc.returncode})")
        return exc.returncode
    except KeyError as exc:
        err(f"Missing configuration field: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(entrypoint())
