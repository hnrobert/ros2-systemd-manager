import argparse
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

from .config import (get_help_text, load_yaml_config,
                     resolve_workspace_keys, validate_config)
from .domain import set_ros_env
from .makefile_gen import write_makefile
from .runtime import err, log, require_root
from .scaffold import init_defaults
from .systemd_ops import (install_only, install_start_enable, sync_update,
                          uninstall)


def _default_config_path() -> str:
    local_candidate = Path.cwd() / "ros2_services.yaml"
    package_candidate = Path(__file__).resolve(
    ).parents[2] / "ros2_services.yaml"
    if local_candidate.exists():
        return str(local_candidate)
    return str(package_candidate)


def _get_version() -> str:
    try:
        return importlib.metadata.version("ros2-systemd-manager")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def get_help_text() -> str:
    """Return the help text for the CLI."""
    return (
        "SUPPORTED ACTIONS:\n"
        "  init                Create a default YAML template and Makefile\n"
        "  install             Install unit files but do not start them\n"
        "  apply               Install, start, and enable unit files on boot\n"
        "  update              Sync systemd with YAML (stops old/removed, updates tracked hashes)\n"
        "  uninstall           Stop, disable, and securely remove unit files\n"
        "  makefile            Regenerate the local Makefile helper only\n"
        "  upgrade             Self-upgrade this CLI tool remotely via pip\n"
        "  set [options]       Write ROS DDS env into all shell profile/rc files:\n"
        "                      ROS_DOMAIN_ID / RMW_IMPLEMENTATION / ROS_LOCALHOST_ONLY\n"
        "                        -d/--domain-id N          (default 0)\n"
        "                        -r/--rmw cyclonedds|fastrtps (default cyclonedds)\n"
        "                        -l/--localhost-only 0|1   (default 1)\n\n"
        "EXAMPLES:\n"
        "  ros2-systemd-manager init --force\n"
        "  sudo ros2-systemd-manager apply --config ./ros2_services.yaml\n"
        "  sudo ros2-systemd-manager set                       # domain=0, cyclonedds, localhost-only=1\n"
        "  sudo ros2-systemd-manager set -d 42 -r fastrtps     # domain 42 + Fast DDS\n"
        "  sudo ros2-systemd-manager uninstall"
    )


def parse_args() -> argparse.Namespace:
    description = (
        "===========================================================\n"
        "   ROS2 Systemd Manager - Declarative Service Management\n"
        "===========================================================\n\n"
        "Automate the deployment, tracking, and management of systemd\n"
        "services for ROS 2 workspaces using a single YAML file."
    )
    epilog = get_help_text()

    parser = argparse.ArgumentParser(
        prog="ros2-systemd-manager",
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawTextHelpFormatter,
    )

    parser.add_argument(
        "-v", "--version",
        action="version",
        version=f"%(prog)s {_get_version()}",
        help="Show program's version number and exit.",
    )

    parser.add_argument(
        "action",
        nargs="?",
        help="Action to perform (default: actions.default_action in YAML)",
    )
    parser.add_argument(
        "-d", "--domain-id",
        type=int,
        default=None,
        help="ROS_DOMAIN_ID value for the 'set' action (default: 0).",
    )
    parser.add_argument(
        "-r", "--rmw",
        default=None,
        help="RMW implementation for the 'set' action: cyclonedds|fastrtps (default: cyclonedds).",
    )
    parser.add_argument(
        "-l", "--localhost-only",
        type=int,
        default=None,
        help="ROS_LOCALHOST_ONLY value for the 'set' action: 0|1 (default: 1).",
    )
    parser.add_argument(
        "-c", "--config",
        default=None,
        help="Path to YAML config file (default: current dir or pkg default)",
    )
    parser.add_argument(
        "-w", "--workspace-key",
        default=None,
        help="Workspace key to operate on (default: all workspaces defined)",
    )
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="Force overwrite when executing the 'init' action",
    )
    return parser.parse_args()


def _upgrade_self() -> None:
    package_name = "ros2-systemd-manager"
    in_virtual_env = sys.prefix != getattr(sys, "base_prefix", sys.prefix)

    cmd = [sys.executable, "-m", "pip", "install", "--upgrade"]
    if not in_virtual_env and os.geteuid() != 0:
        cmd.append("--user")
    cmd.append(package_name)

    log(f"Upgrading package with: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)
    log("Upgrade completed.")


def run() -> None:
    args = parse_args()
    action_arg = args.action

    if action_arg is None:
        err("No action specified.")
        print("")
        print("To get started, run 'ros2-systemd-manager init' in your workspace directory.")
        print("")
        print(get_help_text())
        sys.exit(1)

    # Actions that don't need a config file
    if action_arg == "init":
        target_config = Path(args.config) if args.config else (
            Path.cwd() / "ros2_services.yaml")
        init_defaults(target_config, force=args.force)
        return

    if action_arg == "upgrade":
        _upgrade_self()
        return

    if action_arg == "set":
        require_root()
        domain = 0 if args.domain_id is None else args.domain_id
        localhost = 1 if args.localhost_only is None else args.localhost_only
        if localhost not in (0, 1):
            err(f"Invalid --localhost-only: {localhost} (must be 0 or 1)")
            sys.exit(1)
        rmw = "cyclonedds" if args.rmw is None else args.rmw
        try:
            set_ros_env(domain_id=domain, rmw=rmw, localhost_only=localhost)
        except ValueError as exc:
            err(str(exc))
            sys.exit(1)
        return

    # Actions that need a config file
    config_path = Path(args.config) if args.config else Path(
        _default_config_path())
    config = load_yaml_config(config_path)
    validate_config(config)

    action = action_arg or config.get("actions", {}).get("default_action", "apply")
    workspace_keys = resolve_workspace_keys(args.workspace_key, config)

    if action in {"install", "apply", "uninstall", "update"}:
        require_root()

    log(f"Config file: {config_path}")
    log(f"Workspace keys: {workspace_keys}")
    log(f"Action: {action}")

    if action == "install":
        install_only(config, workspace_keys)
    elif action == "apply":
        install_start_enable(config, workspace_keys)
    elif action == "uninstall":
        uninstall(config, workspace_keys)
    elif action == "update":
        sync_update(config, workspace_keys)
    elif action == "makefile":
        log("Skipping systemd operations; refreshing Makefile only.")
    else:
        err(f"Unsupported action: {action}")
        print("")
        print(get_help_text())
        sys.exit(1)

    write_makefile(config, config_path)


def entrypoint() -> int:
    try:
        run()
    except subprocess.CalledProcessError as exc:
        err(f"Command failed: {' '.join(exc.cmd)} (exit={exc.returncode})")
        print("")
        print(get_help_text())
        return exc.returncode
    except KeyError as exc:
        err(f"Missing configuration field: {exc}")
        print("")
        print(get_help_text())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(entrypoint())
