import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .actions import SUPPORTED_ACTIONS
from .runtime import err


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
        "  set-domain-id <N>   Set ROS_DOMAIN_ID in all shell profile/rc files\n\n"
        "EXAMPLES:\n"
        "  ros2-systemd-manager init --force\n"
        "  sudo ros2-systemd-manager apply --config ./ros2_services.yaml\n"
        "  sudo ros2-systemd-manager set-domain-id 42\n"
        "  sudo ros2-systemd-manager uninstall"
    )


def load_yaml_config(config_path: Path) -> Dict[str, Any]:
    """Load and parse YAML configuration."""
    if not config_path.exists():
        err("Configuration file (ros2_services.yaml) does not found in current directory.")
        print("")
        print("To get started, run the following command in your workspace directory:")
        print("  ros2-systemd-manager init")
        print("")
        print("This will create a default ros2_services.yaml config and makefiles.")
        sys.exit(1)

    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        err("Invalid configuration format: top-level must be a mapping.")
        sys.exit(1)

    return data


def validate_config(config: Dict[str, Any]) -> None:
    """Validate required top-level fields and service-level options."""
    for key in ["systemd", "runtime", "workspaces"]:
        if key not in config:
            err(f"Missing required config field: {key}")
            sys.exit(1)

    actions_cfg = config.get("actions")
    if actions_cfg is not None and not isinstance(actions_cfg, dict):
        err("actions must be a mapping when provided.")
        sys.exit(1)

    workspaces = config.get("workspaces")
    if not isinstance(workspaces, dict) or not workspaces:
        err("workspaces must be a non-empty mapping.")
        sys.exit(1)

    makefile_cfg = config.get("makefile", {})
    if makefile_cfg and not isinstance(makefile_cfg, dict):
        err("makefile must be a mapping when provided.")
        sys.exit(1)

    if isinstance(makefile_cfg, dict) and "command" in makefile_cfg:
        command = makefile_cfg.get("command")
        if not isinstance(command, str) or not command.strip():
            err("makefile.command must be a non-empty string when provided.")
            sys.exit(1)

    for workspace_key, workspace_cfg in workspaces.items():
        if not isinstance(workspace_cfg, dict):
            err(f"workspace '{workspace_key}' must be a mapping.")
            sys.exit(1)

        setup_scripts = workspace_cfg.get("setup_scripts")
        if setup_scripts is not None:
            if not isinstance(setup_scripts, list) or not all(
                isinstance(s, str) and s.strip() for s in setup_scripts
            ):
                err(f"workspace '{workspace_key}' setup_scripts must be a list of non-empty strings.")
                sys.exit(1)

        ros_domain_id = workspace_cfg.get("ros_domain_id")
        if ros_domain_id is not None:
            if not isinstance(ros_domain_id, int):
                err(f"workspace '{workspace_key}' ros_domain_id must be an integer.")
                sys.exit(1)

        services = workspace_cfg.get("services", [])
        if not isinstance(services, list):
            err(f"workspace '{workspace_key}' services must be a list.")
            sys.exit(1)

        for svc in services:
            if not isinstance(svc, dict):
                err(f"workspace '{workspace_key}' service entries must be mappings.")
                sys.exit(1)

            if "use_root" in svc and not isinstance(svc["use_root"], bool):
                unit_name = svc.get("unit_name", "<unknown>")
                err(f"Service {unit_name} has invalid use_root: expected true/false.")
                sys.exit(1)

            if "enable" in svc and not isinstance(svc["enable"], bool):
                unit_name = svc.get("unit_name", "<unknown>")
                err(f"Service {unit_name} has invalid enable: expected true/false.")
                sys.exit(1)

            service_options = svc.get("service_options")
            if service_options is not None:
                unit_name = svc.get("unit_name", "<unknown>")
                valid = isinstance(service_options, list) and all(
                    isinstance(item, str) and item.strip() for item in service_options
                )
                if not valid:
                    err(
                        f"Service {unit_name} has invalid service_options: expected a string list."
                    )
                    sys.exit(1)


def resolve_action(cli_action: Optional[str], config: Dict[str, Any]) -> str:
    """Resolve action from CLI or YAML defaults."""
    default_action = config.get("actions", {}).get("default_action", "apply")
    action = cli_action or default_action

    if action not in SUPPORTED_ACTIONS:
        err(f"Unsupported action: {action}")
        print(f"Allowed actions: {', '.join(sorted(SUPPORTED_ACTIONS))}")
        print("")
        print(get_help_text())
        sys.exit(1)

    return action


def resolve_workspace_keys(cli_workspace_key: Optional[str], config: Dict[str, Any]) -> list[str]:
    """Resolve workspace keys from CLI or default to all workspaces."""
    workspaces: Dict[str, Any] = config.get("workspaces", {})

    if cli_workspace_key:
        if cli_workspace_key not in workspaces:
            err(f"Workspace key not found: {cli_workspace_key}")
            print(f"Available workspace keys: {', '.join(workspaces.keys())}")
            print("")
            print(get_help_text())
            sys.exit(1)
        return [cli_workspace_key]

    return list(workspaces.keys())


def resolve_makefile_path(config: Dict[str, Any], config_path: Path) -> Path:
    """Resolve output path for generated Makefile."""
    makefile_cfg = config.get("makefile", {})
    output_path_raw = makefile_cfg.get(
        "output_path", "ros2-systemd-manager.mk")

    if not isinstance(output_path_raw, str) or not output_path_raw.strip():
        err("makefile.output_path must be a non-empty string.")
        sys.exit(1)

    output_path = Path(output_path_raw)
    if not output_path.is_absolute():
        output_path = config_path.parent / output_path

    return output_path.resolve()
