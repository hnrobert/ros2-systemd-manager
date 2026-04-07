from __future__ import annotations

import getpass
import re
from importlib import resources
from pathlib import Path

import yaml

from .makefile_gen import write_makefile
from .runtime import err, log


def _load_example_template_text() -> str:
    """Load YAML template text from packaged data, with repo fallback."""
    packaged_template = resources.files("ros2_systemd_manager").joinpath(
        "ros2_services.example.yaml"
    )
    if packaged_template.is_file():
        return packaged_template.read_text(encoding="utf-8")

    repo_candidate = Path(__file__).resolve(
    ).parents[2] / "ros2_services.example.yaml"
    if repo_candidate.exists():
        return repo_candidate.read_text(encoding="utf-8")

    err(
        "Example template not found in package data or repository root. "
        "Expected ros2_services.example.yaml to be bundled."
    )
    raise SystemExit(1)


def _replace_first_yaml_line_value(template_text: str, key: str, value: str) -> str:
    pattern = rf"^(\s*{re.escape(key)}:\s*).*$"
    return re.sub(pattern, rf"\1{value}", template_text, count=1, flags=re.MULTILINE)


def init_defaults(config_path: Path, force: bool = False) -> None:
    """Create default YAML + Makefile bootstrap files for packaged CLI usage."""
    config_path = config_path.resolve()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists() and not force:
        err(f"Config already exists: {config_path}. Use --force to overwrite.")
        raise SystemExit(1)

    yaml_text = _load_example_template_text()
    current_user = getpass.getuser()
    current_home = str(Path.home())

    yaml_text = _replace_first_yaml_line_value(yaml_text, "user", current_user)
    yaml_text = _replace_first_yaml_line_value(
        yaml_text, "group", current_user)
    yaml_text = _replace_first_yaml_line_value(yaml_text, "home", current_home)

    # Dynamically set workspace key to current directory name and path to current path.
    template_cfg = yaml.safe_load(yaml_text)
    if isinstance(template_cfg, dict):
        template_workspaces = template_cfg.get("workspaces", {})
        if isinstance(template_workspaces, dict) and template_workspaces:
            template_workspace_key = next(iter(template_workspaces.keys()))
            
            current_dir = Path.cwd()
            ws_name = current_dir.name
            ws_path = str(current_dir)
            
            yaml_text = re.sub(
                rf"^(\s*){re.escape(template_workspace_key)}:", 
                rf"\1{ws_name}:", 
                yaml_text, 
                count=1, 
                flags=re.MULTILINE
            )
            yaml_text = _replace_first_yaml_line_value(
                yaml_text, "path", ws_path)

    config = yaml.safe_load(yaml_text)
    if not isinstance(config, dict):
        err("Invalid internal template: expected top-level mapping.")
        raise SystemExit(1)

    workspaces = config.get("workspaces", {})
    if not isinstance(workspaces, dict) or not workspaces:
        err("Invalid internal template: workspaces must be a non-empty mapping.")
        raise SystemExit(1)

    existing_workspace_key = next(iter(workspaces.keys()))

    config_path.write_text(yaml_text, encoding="utf-8")
    log(f"Default config generated: {config_path}")

    write_makefile(config, config_path)
    log("Default Makefile generated.")
