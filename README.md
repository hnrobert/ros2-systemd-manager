# ROS2 Systemd Manager

A YAML-driven utility to manage ROS2 launch services as systemd units.

## Features

- Install unit files only (`install-only`)
- Install, start, and enable units (`install-start-enable`)
- Uninstall units (`uninstall`)
- Sync update workflow (`sync-update`): stop previous units, remove stale units, then install/start/enable current units
- Regenerate Makefile only (`update-makefile`)
- Per-service dependencies via `depends_on`
- Per-service root override via `use_root`
- Per-service raw systemd service lines via `service_options`
- Auto-generated Makefile with all-service and per-service operations

## Requirements

- Linux with systemd
- Python 3.9+
- PyYAML
- Root privileges (`sudo`) for actions that modify systemd

## Install

```bash
pip install pyyaml
```

Optional (project install):

```bash
pip install -e .
```

## Project Structure

- `ros2_systemd_manager.py`: compatibility launcher (keeps old usage working)
- `src/ros2_systemd_manager/cli.py`: CLI parsing and action dispatch
- `src/ros2_systemd_manager/config.py`: YAML loading and validation
- `src/ros2_systemd_manager/systemd_ops.py`: systemd install/update/uninstall logic
- `src/ros2_systemd_manager/makefile_gen.py`: Makefile generation
- `ros2_services.yaml`: active configuration
- `ros2_services.example.yaml`: reference configuration

## YAML Configuration

Main keys in `ros2_services.yaml`:

- `actions.default_action`: default action when CLI action is omitted
- `systemd.unit_dir`: systemd unit directory (default `/etc/systemd/system`)
- `systemd.wanted_by`: install target (default `multi-user.target`)
- `runtime`: default runtime identity and restart policy for services
- `makefile.output_path`: generated Makefile path (relative to YAML directory)
- `workspaces`: one or more workspace definitions

Service fields:

- `unit_name` (required)
- `description` (optional)
- `launch_command` (required)
- `depends_on` (optional list)
- `use_root` (optional bool): when `true`, force root for this service
- `service_options` (optional list of strings): extra raw lines injected into unit `[Service]` section

Example `service_options`:

```yaml
service_options:
  - CapabilityBoundingSet=CAP_NET_RAW CAP_NET_ADMIN
  - AmbientCapabilities=CAP_NET_RAW CAP_NET_ADMIN
```

## CLI Usage

```bash
sudo python3 ros2_systemd_manager.py [action] [--config PATH] [--workspace-key KEY] [--previous-makefile PATH]
```

Actions:

- `install-only`
- `install-start-enable`
- `uninstall`
- `sync-update`
- `update-makefile`

Notes:

- If `action` is omitted, `actions.default_action` is used.
- `update-makefile` does not require root.
- `sync-update` can use `--previous-makefile` to detect stale/renamed units.

Examples:

```bash
sudo python3 ros2_systemd_manager.py install-only --workspace-key infantry_ws
sudo python3 ros2_systemd_manager.py install-start-enable --workspace-key infantry_ws
sudo python3 ros2_systemd_manager.py uninstall --workspace-key infantry_ws
sudo python3 ros2_systemd_manager.py sync-update --workspace-key infantry_ws --previous-makefile ./Makefile
python3 ros2_systemd_manager.py update-makefile --workspace-key infantry_ws
```

## Generated Makefile

After each successful run, a Makefile is generated at `makefile.output_path`.

Common targets:

- `make install-only`
- `make install-start-enable`
- `make uninstall`
- `make start` / `stop` / `restart` / `status` / `enable` / `disable`
- `make logs` (all services, recent)
- `make logs-follow` (all services, follow)
- `make update` (runs `sync-update` + refresh)
- `make update-makefile` (refresh only)

Per-service targets are auto-generated, for example:

- `make start-ros2-foxglove-bridge`
- `make logs-ros2-foxglove-bridge` (`-n 100 -f`)
- `make logs-recent-ros2-foxglove-bridge` (`-n 200 --no-pager`)
- `make logs-static-ros2-foxglove-bridge` (alias of `logs-recent-*`)

## Troubleshooting

```bash
systemctl status <unit_name>
journalctl -u <unit_name> -f
sudo systemctl daemon-reload
```

## Safety Notes

- Use only trusted launch commands in YAML.
- Validate workspace paths and setup scripts before install/update actions.
- Prefer `install-only` first when introducing new services.
