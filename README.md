# ROS2 Systemd Manager

A YAML-driven utility for managing ROS2 launch services as `systemd` units.

## Features

- Install unit files only (`install-only`)
- Install, start, and enable units on boot (`install-start-enable`)
- Uninstall units (stop, disable, remove files) (`uninstall`)
- Manage multiple workspaces through a single YAML configuration
- Define per-service dependencies via `depends_on`

## Requirements

- Linux with `systemd`
- Python 3.9+
- Root privileges (`sudo`)
- `PyYAML`

## Install Dependency

```bash
pip install pyyaml
```

## Project Files

- `ros2_systemd_manager.py`: main manager script
- `ros2_services.yaml`: service and runtime configuration

## Configuration Overview

Configure everything in `ros2_services.yaml`:

- `actions.default_action`: action used when CLI action is omitted
- `systemd.unit_dir`: unit file directory (default `/etc/systemd/system`)
- `systemd.wanted_by`: install target (default `multi-user.target`)
- `runtime`: service runtime settings (`user`, `group`, `home`, `shell`, restart policy)
- `workspaces`: one or more workspace definitions
  - `path`: absolute workspace path
  - `setup_script`: relative path from workspace (for example `install/setup.bash`)
  - `services`: list of service definitions
    - `unit_name`: generated systemd unit filename
    - `description`: unit description
    - `launch_command`: ROS2 launch command
    - `depends_on`: optional list of other units in the same workspace

## Usage

Run with root privileges:

```bash
sudo python3 ros2_systemd_manager.py [action] [--config PATH] [--workspace-key KEY]
```

### Actions

- `install-only`
- `install-start-enable`
- `uninstall`

If `action` is omitted, the script uses `actions.default_action` from YAML.

### Examples

Use YAML default action:

```bash
sudo python3 ros2_systemd_manager.py
```

Install only for a specific workspace:

```bash
sudo python3 ros2_systemd_manager.py install-only --workspace-key infantry_ws
```

Install + start + enable:

```bash
sudo python3 ros2_systemd_manager.py install-start-enable --workspace-key infantry_ws
```

Uninstall:

```bash
sudo python3 ros2_systemd_manager.py uninstall --workspace-key infantry_ws
```

Use a custom config path:

```bash
sudo python3 ros2_systemd_manager.py install-only --config /path/to/ros2_services.yaml
```

## Generated Unit Behavior

For each configured service, the script writes a unit file and sets:

- `ExecStart` via `bash -lc 'source <setup> && exec <launch_command>'`
- `WorkingDirectory` to workspace path
- `Environment=HOME=<runtime.home>`
- restart policy from `runtime`
- dependency mapping from `depends_on` to `Requires=` and `After=`

## Troubleshooting

Check service status:

```bash
systemctl status <unit_name>
```

View logs:

```bash
journalctl -u <unit_name> -f
```

Reload unit definitions manually (if needed):

```bash
sudo systemctl daemon-reload
```

## Safety Notes

- Use only trusted launch commands in YAML.
- Keep workspace paths and setup scripts accurate before install actions.
- Prefer testing with `install-only` before enabling services on boot.
