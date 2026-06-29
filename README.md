# ROS2 Systemd Manager

ROS2 Systemd Manager is a YAML-driven tool to manage ROS 2 launch tasks as systemd services. Describe your workspaces and services once in `ros2_services.yaml`, then install, start, enable, update, and uninstall them through a single declarative config — with a generated Makefile for everyday `systemctl` shortcuts and an optional helper to write the ROS DDS environment (`ROS_DOMAIN_ID` / `RMW_IMPLEMENTATION` / `ROS_LOCALHOST_ONLY`) into your shell profiles.

## What It Does

- Bootstrap local files with `ros2-systemd-manager init`
- Install units with `install`
- Install + start + enable with `apply`
- Remove units with `uninstall`
- Run synchronized update flow with stale-unit cleanup via `update`
- Regenerate Makefile only with `makefile`
- Upgrade the tool to the latest version via `upgrade`
- Write the ROS DDS environment into all shell rc/profile files with `set`

## Installation

> **Note:** This tool is designed for Linux systems with systemd. Ensure you have Python 3.9+ and pip installed. It is recommended to use sudo for installation to allow systemd unit management.

```bash
sudo pip install ros2-systemd-manager
```

Verify the install:

```bash
ros2-systemd-manager -v
```

## CLI

```bash
ros2-systemd-manager [-v] [-c CONFIG] [-w WORKSPACE_KEY] [-f] [action]
```

Global options:

| Option | Description |
| --- | --- |
| `-v`, `--version` | Show the program's version number and exit. |
| `-c`, `--config PATH` | Path to the YAML config file (default: `./ros2_services.yaml`, then the packaged default). |
| `-w`, `--workspace-key KEY` | Operate on a single workspace key (default: all workspaces defined in the config). |
| `-f`, `--force` | Force overwrite when running `init`. |
| `-d`, `--domain-id N` | `ROS_DOMAIN_ID` value for the `set` action (default: `0`). |
| `-r`, `--rmw NAME` | RMW implementation for the `set` action: `cyclonedds` \| `fastrtps` (default: `cyclonedds`). |
| `-l`, `--localhost-only 0\|1` | `ROS_LOCALHOST_ONLY` value for the `set` action (default: `1`). |

Supported actions:

- `init`
- `install`
- `apply`
- `uninstall`
- `update`
- `makefile`
- `set`
- `upgrade`

### Action reference

- **`init`** — Create a default `ros2_services.yaml` template and Makefile in the current directory. Auto-fills `user`/`group` with the current user, `home` with the current home directory, and sets the workspace key/path to the current directory. Also auto-detects an existing `ROS_DOMAIN_ID` from your shell rc/profile files and injects it as `ros_domain_id`. Use `--force` to overwrite an existing config, or `--config PATH` to write elsewhere.
- **`install`** — Write the unit files to the systemd unit directory and run `daemon-reload`, without starting or enabling them. **Requires root.**
- **`apply`** — Install units, then start and enable them on boot (services with `enable: false` are started but not enabled). **Requires root.**
- **`update`** — Synchronize systemd with the YAML: stop previously tracked units, remove stale units (tracked but no longer present in the config), then install/start/enable the current units and refresh the Makefile. **Requires root.**
- **`uninstall`** — Stop, disable, and remove the configured unit files, then run `daemon-reload` and `reset-failed`. **Requires root.**
- **`makefile`** — Regenerate the local Makefile helper only; no systemd changes are made.
- **`set`** — Write the ROS DDS environment into all shell rc/profile files. See [ROS DDS Environment](#ros-dds-environment-set) below. **Requires root.**
- **`upgrade`** — Self-upgrade this CLI tool via `pip install --upgrade`. Adds `--user` automatically when not in a virtual environment and not running as root.

## ROS DDS Environment (`set`)

The `set` action writes (or updates) three ROS DDS variables into **all** relevant shell rc/profile files:

- `ROS_DOMAIN_ID`
- `RMW_IMPLEMENTATION` (resolved from `-r`: `cyclonedds` → `rmw_cyclonedds_cpp`, `fastrtps` → `rmw_fastrtps_cpp`; full `rmw_*_cpp` names pass through unchanged)
- `ROS_LOCALHOST_ONLY`

Files considered include the per-user `.bashrc`, `.bash_profile`, `.zshrc`, and `.profile` (for the invoking user under `sudo`, the effective user, and `/root`), plus `/etc/profile` and `/etc/environment`. Existing assignments are updated in place; missing variables are appended under a single managed block. When run under `sudo`, it targets `SUDO_USER`'s home so the real user's rc files are updated (not just `/root`).

```bash
sudo ros2-systemd-manager set                          # domain=0, cyclonedds, localhost-only=1
sudo ros2-systemd-manager set -d 42 -r fastrtps        # domain 42 + Fast DDS
sudo ros2-systemd-manager set -d 7 -l 0                # domain 7, allow multicast/remote
```

> **Note:** `set` does not change the per-service `ROS_DOMAIN_ID` set via the `ros_domain_id` workspace option — that one is injected directly into each unit's `Environment=`. Use `set` for the interactive shell environment used when you run `ros2 ...` manually.

## Init Output

Run in your desired config directory (e.g., ROS 2 workspace root) to generate the default YAML config and Makefile targets:

```bash
ros2-systemd-manager init
```

Generated files:

- `./ros2_services.yaml` (default configuration)
- `./ros2-systemd-manager.mk` (generated makefile targets fragment)
- `./Makefile` (entrypoint that includes the `.mk` file)

> **Note:** The tool places generated makefile targets into `ros2-systemd-manager.mk` to keep your root `Makefile` clean. The root `Makefile` will automatically include the `.mk` fragment.

## YAML Keys

Required top-level sections:

- `systemd`
- `runtime`
- `workspaces`

Optional top-level sections:

- `actions` (e.g. `default_action`; default action is `apply`)
- `makefile`

### `systemd`

Controls unit placement and install behavior.

| Key | Default | Description |
| --- | --- | --- |
| `unit_dir` | `/etc/systemd/system` | Directory where unit files are written. |
| `wanted_by` | `multi-user.target` | `[Install] WantedBy=` target (auto-start on boot). |

### `runtime`

Defaults shared by all services unless overridden per service.

| Key | Default | Description |
| --- | --- | --- |
| `user` | `user` | User the service runs as (ignored for `use_root: true` services). |
| `group` | `user` | Group the service runs as. |
| `home` | `/home/user` | Used for `Environment=HOME=`. |
| `shell` | `/bin/bash` | Shell used for `ExecStart` (`-lc`). |
| `restart` | `on-failure` | systemd `Restart=` policy. |
| `restart_sec` | `3` | systemd `RestartSec=` (seconds). |

### `workspaces`

A mapping of workspace keys (selectable via `--workspace-key`). Each workspace supports:

| Key | Required | Description |
| --- | --- | --- |
| `path` | yes | Absolute path to the ROS 2 workspace (used as `WorkingDirectory`). |
| `setup_script` | no | Relative/absolute script sourced before launch (e.g. `install/setup.bash`). |
| `setup_scripts` | no | List of scripts sourced in order (alternative to `setup_script` for multi-source). |
| `ros_domain_id` | no | Integer injected as `Environment=ROS_DOMAIN_ID=` for this workspace's services. |
| `services` | no | List of service entries (see below). |

### Service entries (`workspaces.<key>.services[]`)

| Key | Required | Default | Description |
| --- | --- | --- | --- |
| `unit_name` | yes | — | systemd unit file name (e.g. `ros2-foo.service`). |
| `launch_command` | yes | — | Command run after sourcing setup scripts (e.g. `ros2 launch ...`). |
| `description` | no | `unit_name` | `[Unit] Description=`. |
| `depends_on` | no | `[]` | List of unit names; emits `Requires=` and `After=`. Must exist in the same workspace. |
| `service_options` | no | `[]` | List of raw `[Service]` lines (e.g. `CapabilityBoundingSet=`, `CPUAffinity=`). |
| `use_root` | no | `false` | When `true`, force this service to run as `root`/`root` with `HOME=/root`. |
| `enable` | no | `true` | When `false`, the service is started but not enabled on boot. |

### `makefile`

| Key | Default | Description |
| --- | --- | --- |
| `output_path` | `ros2-systemd-manager.mk` | Output path for the generated Makefile fragment (relative to the config file). |
| `command` | `ros2-systemd-manager` | CLI command the Makefile invokes. |

### Generated unit structure

For each service, a unit file is generated roughly like:

```ini
[Unit]
Description=<description>
Requires=<depends_on ...>          # only when depends_on is set
After=network-online.target <depends_on ...>
Wants=network-online.target

[Service]
Type=simple
User=<user|root>
Group=<group|root>
WorkingDirectory=<workspace path>
Environment=HOME=<home>
Environment=ROS_DOMAIN_ID=<id>     # only when ros_domain_id is set
ExecStart=<shell> -lc 'source "<setup>" && ... && exec <launch_command>'
<service_options ...>              # only when service_options is set
Restart=<restart>
RestartSec=<restart_sec>

[Install]
WantedBy=<wanted_by>
```

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
    # ros_domain_id: 0 # Optional: set ROS_DOMAIN_ID to isolate DDS traffic per workspace
    services:
      - unit_name: ros2-foxglove-bridge.service
        description: ROS2 Foxglove Bridge
        use_root: false # Optional: default false. When true, force this service to run as root.
        enable: true # Optional: default true. Set false to start without auto-start on boot.
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
        enable: false # Example: start on demand, do not auto-start on boot
        service_options:
          - CPUAffinity=1 2 3 # Example of setting CPU affinity for a service
        launch_command: ros2 launch sp_vision_launch sp_vision.launch.py config:=sentry.yaml

  # Multi-source example with domain isolation:
  # another_ws:
  #   path: /home/user/another_ws
  #   ros_domain_id: 42
  #   setup_scripts:
  #     - /opt/ros/humble/setup.bash
  #     - install/setup.bash
  #   services:
  #     - unit_name: ros2-another.service
  #       description: Another workspace service
  #       launch_command: ros2 run pkg node
```

This example shows how to define:

- `systemd` settings for unit placement and installation behavior
- `runtime` defaults shared by all services
- one or more `workspaces`, each with its own `services` list
- `depends_on` relationships between services
- optional `service_options` for extra systemd directives
- optional `enable: false` to start a service without enabling it on boot
- optional `ros_domain_id` to isolate DDS traffic per workspace
- optional `setup_scripts` (list) to source multiple scripts before launching

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

- Operate on a single workspace via `--workspace-key`:

```bash
sudo ros2-systemd-manager apply --workspace-key default_ws
```

## File Tracking & Safety

- **Automatic Backups**: Whenever files in `/etc/systemd/system/` are modified (via `update`, `install`, or `uninstall`), a copy of the exact deployed file along with its MD5 hash (and a global `total.md5` hash) is stored in `~/.config/ros2-systemd-manager/previous-update/`.
- **Modification Detection**: During `update` or `uninstall` operations, the manager uses `filecmp` and `diff` to check if you have manually modified the systemd service file. If modifications are detected, it presents a diff in the terminal and asks if you want to archive your manual changes to `~/.config/ros2-systemd-manager/archive/` before proceeding with the overwrite/deletion. Choices: archive + proceed (`Y`), proceed without archiving (`u`), or cancel (`c`).
- **Stale-unit Cleanup**: `update` compares the previously tracked units against the current config and removes any unit that is no longer defined.

## Safety

- Use trusted launch commands only.
- Validate workspace paths and setup scripts before `apply` or `update`.
- Prefer `install` first for new services.

## Contributing

Licensed under the Apache License 2.0. See [LICENSE](./LICENSE) for details.

Contributions are welcome! Please open issues or submit pull requests for bug fixes, improvements, or new features.
