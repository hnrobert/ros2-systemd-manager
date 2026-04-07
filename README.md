# ROS2 Systemd Manager

ROS2 Systemd Manager is a YAML-driven tool to manage ROS2 launch tasks as systemd services.

## What It Does

- Bootstrap local files with `ros2-systemd-manager init`
- Install units with `install`
- Install + start + enable with `apply`
- Remove units with `uninstall`
- Run synchronized update flow with stale-unit cleanup via `update`
- Regenerate Makefile only with `makefile`
- Upgrade tool to latest version via `upgrade`

## Installation

> **Note:** This tool is designed for Linux systems with systemd. Ensure you have Python 3 and pip installed. It is recommended to use sudo for installation to allow systemd unit management.

```bash
sudo pip install ros2-systemd-manager
```

## CLI

`ros2-systemd-manager [action] [--config PATH] [--workspace-key KEY] [--previous-makefile PATH]`

Supported actions:

- `init`
- `install`
- `apply`
- `uninstall`
- `update`
- `makefile`
- `upgrade`

## Init Output

Run in an empty directory:

```bash
ros2-systemd-manager init
```

Generated files:

- `./ros2_services.yaml` (default configuration)
- `./ros2-systemd-manager.mk` (generated makefile targets fragment)
- `./Makefile` (entrypoint that includes the `.mk` file)

> **Note:** The tool places generated makefile targets into `ros2-systemd-manager.mk` to keep your root `Makefile` clean. The root `Makefile` will automatically include the `.mk` fragment.

## YAML Keys

Required:

- `systemd`
- `runtime`
- `workspaces`

Optional:

- `actions` (default action is `apply`)
- `makefile`

## Generated Makefile

Primary targets:

- `make install`
- `make apply`
- `make uninstall`
- `make update`
- `make makefile`
- `make upgrade`
- `make start|stop|restart|status|enable|disable`
- `make logs` / `make logs-recent`
- `make <op>-<service>` (op in start/stop/restart/status/enable/disable/logs/logs-recent)

Config behavior:

- No hardcoded absolute config path.
- **Default auto-discovery strictly looks for `./ros2_services.yaml` in the current running directory.**
- Override manually via `CONFIG` environment variable or `--config` parameter:

```bash
make apply CONFIG=./my_services.yaml
```

## Safety

- Use trusted launch commands only.
- Validate workspace paths and setup scripts before `apply` or `update`.
- Prefer `install` first for new services.
