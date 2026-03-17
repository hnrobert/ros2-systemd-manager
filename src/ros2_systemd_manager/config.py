from pathlib import Path
import sys
from typing import Any, Dict, Optional

import yaml

from .actions import SUPPORTED_ACTIONS, normalize_action
from .runtime import err


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
    """Validate required top-level fields and service-level options."""
    for key in ["actions", "systemd", "runtime", "workspaces"]:
        if key not in config:
            err(f"Missing required config field: {key}")
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
    action_raw = cli_action or default_action
    action = normalize_action(action_raw)

    if action not in SUPPORTED_ACTIONS:
        err(
            f"Unsupported action: {action_raw}. "
            f"Allowed: {sorted(SUPPORTED_ACTIONS)}"
        )
        sys.exit(1)

    return action


def resolve_workspace_key(cli_workspace_key: Optional[str], config: Dict[str, Any]) -> str:
    """Resolve workspace key from CLI or default to first workspace."""
    workspaces: Dict[str, Any] = config["workspaces"]

    if cli_workspace_key:
        if cli_workspace_key not in workspaces:
            err(f"workspace_key not found: {cli_workspace_key}")
            sys.exit(1)
        return cli_workspace_key

    return next(iter(workspaces.keys()))


def resolve_makefile_path(config: Dict[str, Any], config_path: Path) -> Path:
    """Resolve output path for generated Makefile."""
    makefile_cfg = config.get("makefile", {})
    output_path_raw = makefile_cfg.get("output_path", "Makefile")

    if not isinstance(output_path_raw, str) or not output_path_raw.strip():
        err("makefile.output_path must be a non-empty string.")
        sys.exit(1)

    output_path = Path(output_path_raw)
    if not output_path.is_absolute():
        output_path = config_path.parent / output_path

    return output_path.resolve()
