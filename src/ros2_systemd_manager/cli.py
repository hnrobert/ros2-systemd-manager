import argparse
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from .config import (get_help_text, load_yaml_config,
                     resolve_workspace_keys, validate_config)
from .domain import preview_ros_env, resolve_rmw, set_ros_env
from .makefile_gen import write_makefile
from .runtime import err, log, require_root
from .scaffold import init_defaults
from .systemd_ops import (get_workspace_unit_names, install_only,
                          install_start_enable, sync_update, uninstall)
from .version_control import all_config_paths, all_tracked_units


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


# Sentinel stored by argparse when -d/-r/-l is given without a value (bare flag).
_BARE = object()

# Default values applied when a `set` option is requested without a value.
_SET_DEFAULTS = {"domain_id": 0, "rmw": "cyclonedds", "localhost_only": 1}


def _confirm(prompt: str, default_yes: bool = False) -> bool:
    """Yes/no confirmation prompt. Defaults to No unless default_yes is True."""
    suffix = "[Y/n]" if default_yes else "[y/N]"
    while True:
        choice = input(f"{prompt} {suffix} ").strip().lower()
        if choice == "":
            return default_yes
        if choice in ("y", "yes"):
            return True
        if choice in ("n", "no"):
            return False
        print("Please answer y or n.")


def get_help_text() -> str:
    """Return the help text for the CLI."""
    return (
        "SUPPORTED ACTIONS:\n"
        "  init                Create a default YAML template and Makefile\n"
        "  install             Install unit files but do not start them\n"
        "  apply               Install, start, and enable unit files on boot\n"
        "  update              Sync systemd with YAML for THIS config (scoped per directory)\n"
        "  uninstall           Stop, disable, and securely remove unit files\n"
        "  makefile            Regenerate the local Makefile helper only\n"
        "  list                Print this config's unit names (add --global for every tracked config)\n"
        "  upgrade             Self-upgrade this CLI tool remotely via pip\n"
        "  set [options]       Write ROS DDS env into shell profile/rc files (only keys you pass):\n"
        "                      ROS_DOMAIN_ID / RMW_IMPLEMENTATION / ROS_LOCALHOST_ONLY\n"
        "                        -d/--domain-id [N]             (default 0)\n"
        "                        -r/--rmw [cyclonedds|fastrtps] (default cyclonedds)\n"
        "                        -l/--localhost-only [0|1]      (default 1)\n"
        "                      No options, or a bare flag (-d/-r/-l without a value), prompts for\n"
        "                      confirmation before applying the default value(s).\n"
        "                      Add -n/--dry-run to preview which files would change (no write).\n\n"
        "GLOBAL FLAGS (compose freely, e.g. `apply -g -a -f`):\n"
        "  -g/--global   operate across EVERY tracked config (every dir you have applied)\n"
        "  -a/--all      include explicit_start/explicit_stop services (override the guards)\n"
        "  -f/--force    skip all confirmation prompts (assume yes)\n\n"
        "EXAMPLES:\n"
        "  ros2-systemd-manager init --force\n"
        "  sudo ros2-systemd-manager apply --config ./ros2_services.yaml\n"
        "  sudo ros2-systemd-manager update                    # current directory only\n"
        "  sudo ros2-systemd-manager update -g                 # every tracked config\n"
        "  sudo ros2-systemd-manager apply -a                  # also start explicit_start services\n"
        "  sudo ros2-systemd-manager uninstall -g -a -f        # everywhere, everything, no prompts\n"
        "  sudo ros2-systemd-manager set -d 42                 # write only ROS_DOMAIN_ID=42\n"
        "  sudo ros2-systemd-manager set -d 42 -r fastrtps     # write domain 42 + Fast DDS only\n"
        "  sudo ros2-systemd-manager set                       # confirm, then write all defaults\n"
        "  ros2-systemd-manager set -d 42 --dry-run            # preview files/lines, change nothing\n"
        "  ros2-systemd-manager list --global                  # print every tracked unit"
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
        nargs="?", const=_BARE, type=int, default=None,
        help="ROS_DOMAIN_ID for 'set' (default 0). Bare -d applies the default after confirmation.",
    )
    parser.add_argument(
        "-r", "--rmw",
        nargs="?", const=_BARE, default=None,
        help="RMW for 'set': cyclonedds|fastrtps (default cyclonedds). Bare -r applies the default after confirmation.",
    )
    parser.add_argument(
        "-l", "--localhost-only",
        nargs="?", const=_BARE, type=int, default=None,
        help="ROS_LOCALHOST_ONLY for 'set': 0|1 (default 1). Bare -l applies the default after confirmation.",
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
        help="Skip all confirmation prompts (assume yes): the manual-modification archive "
             "prompt, the 'set' defaults-confirmation, and 'init' overwrite.",
    )
    parser.add_argument(
        "-a", "--all",
        action="store_true",
        help="Include services marked explicit_start/explicit_stop in the operation "
             "(override the per-service guards). Applies to install/apply/update/uninstall.",
    )
    parser.add_argument(
        "-g", "--global",
        action="store_true", dest="global_",
        help="Operate across ALL tracked configs (every directory ever installed), not just "
             "the current one. Applies to install/apply/update/uninstall/list.",
    )
    parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="With 'set': list the rc/profile files that would be changed (and the lines "
             "that would be written) without modifying anything. Does not require root.",
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


def _run_set(args: argparse.Namespace) -> None:
    """Implement the `set` action with partial application + confirmation.

    Rules:
      - No options at all        -> confirm before applying all three defaults.
      - Any option present       -> write ONLY the requested keys.
      - Bare flag (-d/-r/-l)     -> confirm before applying that key's default.
    A flag with an explicit value is applied directly without confirmation.
    """
    domain_state = args.domain_id
    rmw_state = args.rmw
    localhost_state = args.localhost_only
    none_specified = (
        domain_state is None and rmw_state is None and localhost_state is None
    )

    # Final values to write; None means "leave this variable untouched".
    domain: Optional[int] = None
    rmw: Optional[str] = None
    localhost: Optional[int] = None
    confirm_items: List[tuple] = []  # (var_name, display_value) needing confirmation

    if none_specified:
        # Rule 1: confirm all defaults.
        domain = _SET_DEFAULTS["domain_id"]
        rmw = _SET_DEFAULTS["rmw"]
        localhost = _SET_DEFAULTS["localhost_only"]
        confirm_items = [
            ("ROS_DOMAIN_ID", str(domain)),
            ("RMW_IMPLEMENTATION", resolve_rmw(_SET_DEFAULTS["rmw"])),
            ("ROS_LOCALHOST_ONLY", str(localhost)),
        ]
    else:
        # Rule 2 & 3: only requested keys; bare flags need confirmation.
        if domain_state is not None:
            if domain_state is _BARE:
                domain = _SET_DEFAULTS["domain_id"]
                confirm_items.append(("ROS_DOMAIN_ID", str(domain)))
            else:
                domain = int(domain_state)
        if rmw_state is not None:
            if rmw_state is _BARE:
                rmw = _SET_DEFAULTS["rmw"]
                confirm_items.append(
                    ("RMW_IMPLEMENTATION", resolve_rmw(_SET_DEFAULTS["rmw"])))
            else:
                rmw = rmw_state
        if localhost_state is not None:
            if localhost_state is _BARE:
                localhost = _SET_DEFAULTS["localhost_only"]
                confirm_items.append(("ROS_LOCALHOST_ONLY", str(localhost)))
            else:
                localhost = int(localhost_state)
                if localhost not in (0, 1):
                    err(f"Invalid --localhost-only: {localhost} (must be 0 or 1)")
                    sys.exit(1)

    if getattr(args, "dry_run", False):
        preview_ros_env(domain_id=domain, rmw=rmw, localhost_only=localhost)
        return

    if confirm_items:
        header = (
            "No options specified. The following defaults will be written:"
            if none_specified
            else "These options were given without a value; their defaults will be written:"
        )
        print(header)
        for var, value in confirm_items:
            print(f"  {var}={value}")
        if args.force:
            log("--force: applying without prompting.")
        elif not _confirm("Proceed?"):
            log("Aborted: nothing was changed.")
            return

    try:
        set_ros_env(domain_id=domain, rmw=rmw, localhost_only=localhost)
    except ValueError as exc:
        err(str(exc))
        sys.exit(1)


def _run_list(args: argparse.Namespace) -> None:
    """Print unit names, one per line. --global spans every tracked config."""
    if args.global_:
        units = all_tracked_units()
    else:
        config_path = Path(args.config) if args.config else Path(
            _default_config_path())
        config = load_yaml_config(config_path)
        validate_config(config)
        workspace_keys = resolve_workspace_keys(args.workspace_key, config)
        units = get_workspace_unit_names(config, workspace_keys)
    for unit in units:
        print(unit)


def _run_global(args: argparse.Namespace) -> None:
    """Run install/apply/update/uninstall across every tracked config (--global)."""
    action = args.action
    config_paths = all_config_paths()
    if not config_paths:
        log("No tracked configs found. Run `apply` in each project directory first.")
        return

    log(f"--global: {action} across {len(config_paths)} tracked config(s) "
        f"(include_explicit={args.all}, force={args.force}).")

    for cp in config_paths:
        log(f"== {action}: {cp} ==")
        try:
            cfg = load_yaml_config(Path(cp))
            validate_config(cfg)
        except SystemExit:
            log(f"Skipping {cp}: config not readable/invalid (will be cleaned by update).")
            continue
        workspace_keys = list(cfg.get("workspaces", {}).keys())
        if action == "install":
            install_only(cfg, workspace_keys, cp, include_explicit=args.all, force=args.force)
        elif action == "apply":
            install_start_enable(cfg, workspace_keys, cp, include_explicit=args.all, force=args.force)
        elif action == "update":
            sync_update(cfg, workspace_keys, cp, include_explicit=args.all, force=args.force)
        elif action == "uninstall":
            uninstall(cfg, workspace_keys, include_explicit=args.all, force=args.force)
        write_makefile(cfg, Path(cp))


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
        if not args.dry_run:
            require_root()
        _run_set(args)
        return

    if action_arg == "list":
        _run_list(args)
        return

    # install / apply / update / uninstall / makefile require a config (unless --global)
    if action_arg in {"install", "apply", "update", "uninstall"}:
        require_root()

    if args.global_ and action_arg in {"install", "apply", "update", "uninstall"}:
        _run_global(args)
        return

    config_path = Path(args.config) if args.config else Path(
        _default_config_path())
    config = load_yaml_config(config_path)
    validate_config(config)

    action = action_arg or config.get("actions", {}).get("default_action", "apply")
    workspace_keys = resolve_workspace_keys(args.workspace_key, config)
    config_id = str(config_path.resolve())

    log(f"Config file: {config_path}")
    log(f"Workspace keys: {workspace_keys}")
    log(f"Action: {action} (include_explicit={args.all}, force={args.force})")

    if action == "install":
        install_only(config, workspace_keys, config_id,
                     include_explicit=args.all, force=args.force)
    elif action == "apply":
        install_start_enable(config, workspace_keys, config_id,
                             include_explicit=args.all, force=args.force)
    elif action == "uninstall":
        uninstall(config, workspace_keys,
                  include_explicit=args.all, force=args.force)
    elif action == "update":
        sync_update(config, workspace_keys, config_id,
                    include_explicit=args.all, force=args.force)
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
