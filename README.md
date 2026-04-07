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

`ros2-systemd-manager [-v] [-c CONFIG] [-w WORKSPACE_KEY] [-f] [action]`

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

```bash
make upgrade                  # self-upgrade ros2-systemd-manager via pip
make install                  # install unit files only
make apply                    # install + start + enable
make start                    # systemctl start all configured units
make stop                     # systemctl stop all configured units
make restart                  # systemctl restart all configured units
make status                   # systemctl status all configured units
make status-long              # systemctl status with 100 log lines
make enable                   # systemctl enable all configured units
make disable                  # systemctl disable all configured units
make logs                     # follow logs for all configured units
make logs-recent              # show last 200 log lines for all configured units
make <op>-<service>           # op in start/stop/restart/status/enable/disable/logs
make <op>-<service>-<sfx>     # e.g., logs-<svc>-recent, status-<svc>-long (100 lines)
make uninstall                # uninstall all configured units
make update                   # stop old + uninstall + install/start/enable + refresh mk
make makefile                 # refresh generated mk only (no systemd changes)
```

Config behavior:

- No hardcoded absolute config path.
- **Default auto-discovery strictly looks for `./ros2_services.yaml` in the current running directory.**
- Override manually via `CONFIG` environment variable or `--config` parameter:

```bash
make apply CONFIG=./my_services.yaml
```

## File Tracking & Safety

- **Automatic Backups**: Whenever files in `/etc/systemd/system/` are modified (via `update`, `install`, or `uninstall`), a copy of the exact deployed file along with its MD5 hash (and a global hash) is stored in `~/.config/ros2-systemd-manager/previous-update/`.
- **Modification Detection**: During `update` or `uninstall` operations, the manager uses `filecmp` and `diff` to check if you have manually modified the systemd service file. If modifications are detected, it presents a diff in the terminal and asks if you want to archive your manual changes to `~/.config/ros2-systemd-manager/archive/` before proceeding with the overwrite/deletion.

## Safety

- Use trusted launch commands only.
- Validate workspace paths and setup scripts before `apply` or `update`.
- Prefer `install` first for new services.
