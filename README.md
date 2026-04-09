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

Run in your desired config directory (e.g., ROS2 workspace root) to generate the default YAML config and Makefile targets:

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

## Example YAML Configuration

Below is a sample `ros2_services.yaml` demonstrating common fields and layout.

```yaml
systemd:
  unit_dir: /etc/systemd/system
  wanted_by: multi-user.target

runtime:
  user: user
  group: user
  home: /home/user
  shell: /bin/bash
  restart: on-failure
  restart_sec: 3

workspaces:
  default_ws: # Workspace key, selectable via --workspace-key
    path: /home/user/default_ws
    setup_script: install/setup.bash
    services:
      - unit_name: ros2-foxglove-bridge.service
        description: ROS2 Foxglove Bridge
        use_root: false # Optional: default false. When true, force this service to run as root.
        launch_command: ros2 launch foxglove_bridge foxglove_bridge_launch.xml

      - unit_name: ros2-soem-bringup.service
        description: ROS2 Simple Open EtherCAT Master Bringup (https://github.com/AIMEtherCAT/EcatV2_Master)
        use_root: false
        service_options: # Example of granting specific capabilities to a service without running as root
          - CapabilityBoundingSet=CAP_NET_RAW CAP_NET_ADMIN
          - AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN
        launch_command: ros2 launch soem_bringup bringup.launch.py

      - unit_name: ros2-infantry-chassis.service
        description: ROS2 Infantry Chassis Controller
        depends_on:
          - ros2-soem-bringup.service
        launch_command: ros2 launch infantry_controller infantry_chassis.launch.py

      - unit_name: ros2-sp-vision-autoaim.service
        description: TongjiSuperPower/sp_vision_25 Auto Aim (via self defined sp_vision_launch)
        service_options:
          - CPUAffinity=1 2 3 # Example of setting CPU affinity for a service
        launch_command: ros2 launch sp_vision_launch sp_vision.launch.py config:=sentry.yaml
```

This example shows how to define:

- `systemd` settings for unit placement and installation behavior
- `runtime` defaults shared by all services
- one or more `workspaces`, each with its own `services` list
- `depends_on` relationships between services
- optional `service_options` for extra systemd directives

## Generated Makefile

> **Note:** The generated Makefile targets are designed to be intuitive and cover common systemd management tasks. You can customize the generated targets by modifying the `workspaces` section in your YAML config.

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
# Using Makefile with custom config
make apply CONFIG=./my_services.yaml

# or
ros2-systemd-manager apply --config ./my_services.yaml
```

## File Tracking & Safety

- **Automatic Backups**: Whenever files in `/etc/systemd/system/` are modified (via `update`, `install`, or `uninstall`), a copy of the exact deployed file along with its MD5 hash (and a global hash) is stored in `~/.config/ros2-systemd-manager/previous-update/`.
- **Modification Detection**: During `update` or `uninstall` operations, the manager uses `filecmp` and `diff` to check if you have manually modified the systemd service file. If modifications are detected, it presents a diff in the terminal and asks if you want to archive your manual changes to `~/.config/ros2-systemd-manager/archive/` before proceeding with the overwrite/deletion.

## Safety

- Use trusted launch commands only.
- Validate workspace paths and setup scripts before `apply` or `update`.
- Prefer `install` first for new services.

## Contributing

Contributions are welcome! Please open issues or submit pull requests for bug fixes, improvements, or new features.
