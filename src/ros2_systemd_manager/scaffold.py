from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from .makefile_gen import write_makefile
from .runtime import err, log


def _default_config(workspace_key: str) -> Dict[str, Any]:
    return {
        "actions": {"default_action": "apply"},
        "systemd": {
            "unit_dir": "/etc/systemd/system",
            "wanted_by": "multi-user.target",
        },
        "runtime": {
            "user": "root",
            "group": "root",
            "home": "/root",
            "shell": "/bin/bash",
            "restart": "on-failure",
            "restart_sec": 3,
        },
        "makefile": {
            "output_path": "./Makefile",
            "command": "ros2-systemd-manager",
        },
        "workspaces": {
            workspace_key: {
                "path": "/home/your-user/your-ros2-ws",
                "setup_script": "install/setup.bash",
                "services": [
                    {
                        "unit_name": "ros2-example.service",
                        "description": "ROS2 Example Service",
                        "use_root": False,
                        "launch_command": "ros2 launch your_pkg your_launch.py",
                    }
                ],
            }
        },
    }


def init_defaults(config_path: Path, workspace_key: str, force: bool = False) -> None:
    """Create default YAML + Makefile bootstrap files for packaged CLI usage."""
    config_path = config_path.resolve()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists() and not force:
        err(f"Config already exists: {config_path}. Use --force to overwrite.")
        raise SystemExit(1)

    config = _default_config(workspace_key)
    yaml_text = yaml.safe_dump(config, sort_keys=False, allow_unicode=False)
    config_path.write_text(yaml_text, encoding="utf-8")
    log(f"Default config generated: {config_path}")

    write_makefile(config, config_path, workspace_key)
    log("Default Makefile generated.")
