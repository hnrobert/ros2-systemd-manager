# ROS2 Systemd Manager

[![PyPI version](https://img.shields.io/pypi/v/ros2-systemd-manager)](https://pypi.org/project/ros2-systemd-manager/)
[![Python](https://img.shields.io/pypi/pyversions/ros2-systemd-manager)](https://pypi.org/project/ros2-systemd-manager/)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](./LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20systemd-blue)](#installation)

> Turn scattered `ros2 launch ...` commands into reliable, boot-safe systemd services — described in one YAML file.

If you've ever lost a robot stack to a reboot, juggled a dozen terminal tabs, or hand-written `systemctl` unit files only to watch them drift out of sync with reality, this is for you. **ROS2 Systemd Manager** takes a single declarative `ros2_services.yaml` and turns it into real systemd services that:

- **Start on boot** and **restart on crash** — no babysitting required.
- **Track dependencies** (`depends_on`) so your bringup ordering is correct every time.
- **Stay in sync** with your config — `update` reconciles reality with your YAML, and cleans up only what *this* project owns.
- **Give you a `Makefile`** of shortcuts — `make logs`, `make status`, `make restart` …
- Optionally **stamp the ROS DDS environment** (`ROS_DOMAIN_ID` / `RMW_IMPLEMENTATION` / `ROS_LOCALHOST_ONLY`) into your shell profiles.

---

## Highlights

- **One YAML, many services** — workspaces, dependencies, capabilities, CPU affinity, per-service users, all declarative.
- **Easy to use** — for example, `init` scaffolds a config + Makefile, `apply` deploys it, and `set` aligns your shell's DDS environment with your services; the generated Makefile gives you `make <op>-<service>` for every service, and `make <op>-all` for every tracked config.
- **Reconcile, don't replace** — `update` stops old units, removes stale ones, and brings the current set online — scoped to the current directory so you never nuke a *different* project's services.
- **Multi-project friendly** — keep a separate `ros2_services.yaml` per project directory; `--all` reaches across all of them when you really mean it.
- **Safe by default** — MD5-tracked unit files, manual-edit detection with diffing + archiving, and a confirmation prompt before overwriting anything you touched by hand.
- **Zero magic** — it writes ordinary systemd unit files you can read, `systemctl status`, and debug like any other service.

## Table of contents

- [ROS2 Systemd Manager](#ros2-systemd-manager)
  - [Highlights](#highlights)
  - [Table of contents](#table-of-contents)
  - [Quick start](#quick-start)
  - [Installation](#installation)
  - [CLI](#cli)
    - [Action reference](#action-reference)
    - [Scoping: current directory vs. `--global`](#scoping-current-directory-vs---global)
  - [ROS DDS Environment (`set`)](#ros-dds-environment-set)
    - [When to use it](#when-to-use-it)
    - [What gets written](#what-gets-written)
    - [Files touched \& safety](#files-touched--safety)
  - [Init](#init)
  - [YAML reference](#yaml-reference)
    - [`systemd` — unit placement](#systemd--unit-placement)
    - [`runtime` — defaults shared by all services (unless overridden per service)](#runtime--defaults-shared-by-all-services-unless-overridden-per-service)
    - [`workspaces` — a mapping of workspace keys (selectable via `--workspace-key`)](#workspaces--a-mapping-of-workspace-keys-selectable-via---workspace-key)
    - [Service entries (`workspaces.<key>.services[]`)](#service-entries-workspaceskeyservices)
    - [`makefile`](#makefile)
    - [Example YAML configuration](#example-yaml-configuration)
    - [Generated unit structure](#generated-unit-structure)
  - [Generated Makefile](#generated-makefile)
  - [File tracking \& safety](#file-tracking--safety)
    - [General safety](#general-safety)
  - [FAQ](#faq)
    - [Foxglove shows topics, but `ros2 topic list` doesn't](#foxglove-shows-topics-but-ros2-topic-list-doesnt)
    - [I ran `set`, but `ros2 topic list` is still empty](#i-ran-set-but-ros2-topic-list-is-still-empty)
    - [Does `update` or `uninstall` touch my *other* projects?](#does-update-or-uninstall-touch-my-other-projects)
    - [How do I run an action across every project at once?](#how-do-i-run-an-action-across-every-project-at-once)
    - [Where does the tool store its data?](#where-does-the-tool-store-its-data)
    - [A root-owned rc/profile file appeared in my home after a `sudo` run](#a-root-owned-rcprofile-file-appeared-in-my-home-after-a-sudo-run)
  - [Contributing](#contributing)

## Quick start

```bash
# 1. install
sudo pip install ros2-systemd-manager

# 2. in your ROS 2 workspace, generate a config + Makefile
ros2-systemd-manager init

# 3. edit ros2_services.yaml to match your stack, then deploy
sudo make apply

# 4. live happily ever after
make status          # how is everything doing?
make logs            # tail all services
```

That's it. Your launch tasks now survive reboots and restart themselves on failure.

## Installation

> **Note:** Designed for **Linux with systemd**. Requires Python 3.9+ and pip. Use `sudo` for installation so it can manage systemd units.

```bash
sudo pip install ros2-systemd-manager
ros2-systemd-manager -v          # sanity check
```

## CLI

```bash
ros2-systemd-manager [-v] [-c CONFIG] [-w WORKSPACE_KEY] [-f] [-a] [-g] [-n] [-d [N]] [-r [NAME]] [-l [0|1]] [action]
```

| Option | Description |
| --- | --- |
| `-v`, `--version` | Show the program's version number and exit. |
| `-c`, `--config PATH` | Path to the YAML config (default: `./ros2_services.yaml`, then the packaged default). |
| `-w`, `--workspace-key KEY` | Operate on a single workspace key (default: all workspaces in the config). |
| `-f`, `--force` | **Skip all confirmation prompts** (assume yes): the manual-modification archive prompt, the `set` defaults-confirmation, and `init` overwrite. |
| `-a`, `--all` | Include services marked `explicit_start`/`explicit_stop` in the operation (override the per-service guards). Applies to `install`/`apply`/`update`/`uninstall`. |
| `-g`, `--global` | Operate across **all** tracked configs (every directory ever installed), not just the current one. Applies to `install`/`apply`/`update`/`uninstall`/`list`. |
| `-n`, `--dry-run` | With `set`: list the rc/profile files that would change (and the exact lines that would be written) **without modifying anything**. Does not require root. |
| `-d`, `--domain-id [N]` | `ROS_DOMAIN_ID` for `set` (default `0`). Bare `-d` applies the default after confirmation. |
| `-r`, `--rmw [NAME]` | RMW for `set`: `cyclonedds` \| `fastrtps` (default `cyclonedds`). Bare `-r` applies the default after confirmation. |
| `-l`, `--localhost-only [0\|1]` | `ROS_LOCALHOST_ONLY` for `set` (default `1`). Bare `-l` applies the default after confirmation. |

These three flags are **orthogonal and compose freely**, e.g. `apply -g -a -f` = every config, every service (including explicit ones), no prompts.

**Actions:** `init` · `install` · `apply` · `uninstall` · `update` · `makefile` · `list` · `set` · `upgrade`

### Action reference

- **`init`** — Scaffold a default `ros2_services.yaml` and Makefile in the current directory. Auto-fills `user`/`group`/`home`, sets the workspace key/path to the current directory, and even auto-detects an existing `ROS_DOMAIN_ID` from your shell profiles. Use `--force` to overwrite, or `--config PATH` to write elsewhere.
- **`install`** — Write unit files + `daemon-reload`, **without** starting or enabling. **Requires root.** Current config only (`-g` = every tracked config).
- **`apply`** — Install, then start and enable on boot (`enable: false` services start but won't auto-start; `explicit_start` services aren't started unless `-a`). **Requires root.** Current config only (`-g` = every tracked config).
- **`update`** — Reconcile systemd with your YAML: stop this config's previously tracked units (skipping `explicit_stop` ones unless `-a`), remove stale ones (tracked for **this** config but no longer defined in it), then bring the current set online and refresh the Makefile. Stale cleanup is **scoped per directory** — updating one project never touches another's units. **Requires root.** `-g` updates every tracked config.
- **`uninstall`** — Stop, disable, remove unit files, `daemon-reload`, `reset-failed`. `explicit_stop` services are left running unless `-a`. **Requires root.** Current config only; `-g` repeats across every tracked config.
- **`makefile`** — Regenerate the Makefile helper only; no systemd changes.
- **`list`** — Print this config's unit names (one per line). `list --global` prints every tracked unit across all configs. Handy on its own and used by the Makefile `-global` targets.
- **`set`** — Write selected ROS DDS env vars into shell rc/profile files (only the keys you pass). See [ROS DDS Environment](#ros-dds-environment-set). **Requires root.**
- **`upgrade`** — Self-upgrade via `pip install --upgrade` (adds `--user` automatically when not in a venv and not root).

### Scoping: current directory vs. `--global`

Keep a **separate `ros2_services.yaml` in each project directory**, and every action defaults to the **current directory only**. The tool remembers which config installed each unit (an `.origin` sidecar in its tracking store), so:

- no flag → only the current directory's config.
- **`-g` / `--global`** → every config the tool has ever installed (every directory you've `apply`-ed from).

```bash
sudo ros2-systemd-manager update           # only this project
sudo ros2-systemd-manager update -g        # every tracked project
sudo ros2-systemd-manager uninstall -g     # every tracked project
ros2-systemd-manager list --global         # see everything the tool manages
```

> **Migration:** units tracked before this feature have no recorded origin. They're left untouched by default `update`/`uninstall` (safe) and still swept by `--global`. Origins attach the next time you `apply`/`update` each config.

## ROS DDS Environment (`set`)

A focused helper that writes (or updates) the ROS DDS variables into **all** relevant shell rc/profile files:

- `ROS_DOMAIN_ID`
- `RMW_IMPLEMENTATION` (resolved from `-r`: `cyclonedds` → `rmw_cyclonedds_cpp`, `fastrtps` → `rmw_fastrtps_cpp`; full `rmw_*_cpp` names pass through)
- `ROS_LOCALHOST_ONLY`

### When to use it

`set` solves the classic "Foxglove shows topics but `ros2 topic list` doesn't" mismatch by aligning your interactive shell's DDS environment with your services'. See the [FAQ](#faq) for the full explanation and one-command fix.

### What gets written

Only the keys you actually request are touched — the rest are left alone.

| Invocation | Behavior |
| --- | --- |
| `set` (no flags) | Prompts to confirm, then writes **all three** defaults. Declining aborts with no changes. |
| `set -d 42 -r fastrtps` | Writes **only** the keys you passed; `ROS_LOCALHOST_ONLY` untouched. No prompt. |
| `set -d` (bare) | Prompts to confirm, then writes **only** that key's default. |
| `set -d 42 -r` | `ROS_DOMAIN_ID=42` (explicit, no prompt) + prompt to confirm the `RMW` default. |

In short: **no flags** → confirm all defaults; **any flag** → only those keys; **bare flag** → confirm that key's default; **explicit value** → applied directly.

```bash
sudo ros2-systemd-manager set                          # confirm, then write all defaults
sudo ros2-systemd-manager set -d 42                    # write only ROS_DOMAIN_ID=42
sudo ros2-systemd-manager set -d 42 -r fastrtps        # domain 42 + Fast DDS only
sudo ros2-systemd-manager set -d 7 -l 0                # domain 7, allow multicast/remote
ros2-systemd-manager set -d 42 --dry-run               # preview which files/lines change, write nothing
```

`--dry-run` (`-n`) is a safe preview: it reports each rc/profile file that would be created or updated and the exact effective line (with annotation) it would receive — without touching the filesystem, and without needing `sudo`. Example output:

```text
[INFO] Dry run — no files will be changed.
  [update ] /home/alice/.bashrc
           update: export ROS_DOMAIN_ID=42  # modified by alice on 2026-07-03 10:00:00 using ros2-systemd-manager
  [create ] /home/alice/.bash_profile
           append: export ROS_DOMAIN_ID=42  # modified by alice on 2026-07-03 10:00:00 using ros2-systemd-manager
```

### Files touched & safety

Considered files: per-user `.bashrc`, `.bash_profile`, `.zshrc`, `.profile` (for the invoking user under `sudo`, the effective user, and `/root`), plus `/etc/profile` and `/etc/environment`. Under `sudo` it targets `SUDO_USER`'s home so *your* rc files are updated (not just `/root`).

- **New files are created and owned by the right user.** rc/profile files that don't yet exist are created, then `chown`ed to match their parent (home) directory's owner — so a `sudo` run never leaves a root-owned file in your home you can't read or edit. (`/etc/` files stay root-owned, correctly.)
- **Ownership follows the home directory** — whether created or updated, every file stays readable/writable by its user.
- **Existing settings update in place** — values change on the original line (never duplicated); re-running with the same values is a no-op.
- **Every effective line is annotated** with who/when, e.g.:

  ```bash
  export ROS_DOMAIN_ID=0  # modified by alice on 2026-06-30 12:34:56 using ros2-systemd-manager
  ```

> **Note:** `set` only affects the interactive shell environment. The per-service `ros_domain_id` workspace option is injected directly into each unit's `Environment=` instead.

## Init

Run in your desired config directory (e.g. your ROS 2 workspace root):

```bash
ros2-systemd-manager init
```

Generates:

- `./ros2_services.yaml` — default configuration
- `./ros2-systemd-manager.mk` — generated makefile targets fragment
- `./Makefile` — entrypoint that includes the `.mk` fragment

> **Note:** Targets live in `ros2-systemd-manager.mk` to keep your root `Makefile` clean; the root `Makefile` auto-includes the fragment.

## YAML reference

**Required top-level sections:** `systemd`, `runtime`, `workspaces`.
**Optional:** `actions` (e.g. `default_action`; default `apply`), `makefile`.

### `systemd` — unit placement

| Key | Default | Description |
| --- | --- | --- |
| `unit_dir` | `/etc/systemd/system` | Directory where unit files are written. |
| `wanted_by` | `multi-user.target` | `[Install] WantedBy=` target (auto-start on boot). |

### `runtime` — defaults shared by all services (unless overridden per service)

| Key | Default | Description |
| --- | --- | --- |
| `user` | `user` | User the service runs as (ignored for `use_root: true` services). |
| `group` | `user` | Group the service runs as. |
| `home` | `/home/user` | Used for `Environment=HOME=`. |
| `shell` | `/bin/bash` | Shell used for `ExecStart` (`-lc`). |
| `restart` | `on-failure` | systemd `Restart=` policy. |
| `restart_sec` | `3` | systemd `RestartSec=` (seconds). |

### `workspaces` — a mapping of workspace keys (selectable via `--workspace-key`)

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
| `depends_on` | no | `[]` | Unit names; emits `Requires=` + `After=`. Must exist in the same workspace. |
| `service_options` | no | `[]` | Raw `[Service]` lines (e.g. `CapabilityBoundingSet=`, `CPUAffinity=`). |
| `use_root` | no | `false` | When `true`, force this service to run as `root` with `HOME=/root`. |
| `enable` | no | `true` | When `false`, the service starts but isn't enabled on boot. |
| `explicit_start` | no | `false` | When `true`, the service is **installed** but **not** auto-started/enabled by `apply`, `make start`/`enable`/`restart`. Start it on demand (`make start-<svc>`) or include it with `-a`/`--all`. |
| `explicit_stop` | no | `false` | When `true`, the service is **not** auto-stopped/disabled/removed by `make stop`/`disable`, `uninstall`, or `update`'s stop-previous. Keeps critical services running. Override with `-a`/`--all`. |

#### On-demand & keep-running services

Two independent guards let a service opt out of the default group lifecycle:

- **`explicit_start: true`** — "start this on demand." The unit is still installed (so `make start-<svc>` / `systemctl start` work), but `apply` and `make start`/`enable`/`restart` skip it. Bring it up with `make start-ros2-foxglove-bridge`, or include it via `-a`/`--all`.
- **`explicit_stop: true`** — "keep this running." `make stop`/`disable`, `uninstall`, and `update`'s stop-previous skip it, so a critical service survives stopping/restarting the rest of the stack.

Both are overridden by `-a`/`--all`, and they compose with `enable` and `-g`/`--global` (e.g. `apply -g -a` starts on-demand services across every project).

### `makefile`

| Key | Default | Description |
| --- | --- | --- |
| `output_path` | `ros2-systemd-manager.mk` | Output path for the generated fragment (relative to the config file). |
| `command` | `ros2-systemd-manager` | CLI command the Makefile invokes. |

### Example YAML configuration

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
    # ros_domain_id: 0 # Optional: isolate DDS traffic per workspace
    services:
      - unit_name: ros2-foxglove-bridge.service
        description: ROS2 Foxglove Bridge
        use_root: false # Optional: default false. When true, force this service to run as root.
        enable: true # Optional: default true. Set false to start without auto-start on boot.
        launch_command: ros2 launch foxglove_bridge foxglove_bridge_launch.xml

      - unit_name: ros2-soem-bringup.service
        description: ROS2 Simple Open EtherCAT Master Bringup (https://github.com/AIMEtherCAT/EcatV2_Master)
        use_root: false
        service_options: # Grant capabilities without running as root
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
        enable: false # Start on demand, do not auto-start on boot
        service_options:
          - CPUAffinity=1 2 3 # Pin to specific cores
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

This demonstrates: `systemd` placement, shared `runtime` defaults, multiple `workspaces`, `depends_on` ordering, `service_options` for capabilities/CPU affinity, `enable: false`, `ros_domain_id` DDS isolation, and multi-source `setup_scripts`.

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

## Generated Makefile

Every project gets an intuitive Makefile of `systemctl` shortcuts, derived from its `workspaces`:

```bash
# This project only:
make apply                    # install + start + enable
make install                  # install unit files only
make start / stop / restart   # control configured units (respects explicit_start/explicit_stop)
make status                   # systemctl status all configured units
make status-long              # status with 100 log lines
make enable / disable
make logs                     # follow logs for all configured units
make logs-recent              # last 200 log lines
make <op>-<service>           # op in start/stop/restart/status/enable/disable/logs (always works, even for explicit services)
make <op>-<service>-<sfx>     # e.g. logs-<svc>-recent, status-<svc>-long
make update                   # reconcile + refresh generated mk
make uninstall                # remove configured units (skips explicit_stop)
make upgrade                  # self-upgrade via pip
make makefile                 # refresh generated mk only
make list                     # print this config's unit names
```

Per-target flags (set on the command line):

```bash
make start ALL=1              # also start explicit_start services
make apply ALL=1 FORCE=1      # include explicit services + skip prompts
```

`-global` targets reach across **every tracked config** (every directory you've `apply`-ed from), via `list --global`:

```bash
make start-global / stop-global / restart-global / status-global / status-global-long
make enable-global / disable-global
make logs-global / logs-recent-global
make install-global / apply-global / update-global / uninstall-global
make list-global              # print every tracked unit
```

**Config discovery:** no hardcoded path — it looks for `./ros2_services.yaml` in the current directory. Override with `CONFIG=` or `--config`:

```bash
make apply CONFIG=./my_services.yaml      # or:
ros2-systemd-manager apply --config ./my_services.yaml
sudo ros2-systemd-manager apply --workspace-key default_ws   # single workspace
```

## File tracking & safety

- **Automatic backups** — whenever unit files in `/etc/systemd/system/` change (`update`/`install`/`uninstall`), the exact deployed file plus its MD5 hash (and a global `total.md5`) is stored under `~/.config/ros2-systemd-manager/previous-update/`, tagged with the originating config.
- **Modification detection** — during `update`/`uninstall`, the tool uses `filecmp` + `diff` to detect manual edits. If found, it shows the diff and asks whether to archive your changes to `~/.config/ros2-systemd-manager/archive/` before proceeding. Choices: archive + proceed (`Y`), proceed without archiving (`u`), or cancel (`c`).
- **Stale-unit cleanup** — `update` removes units no longer defined in the config, **scoped to the current config** so other projects are never affected.

### General safety

- Use trusted launch commands only.
- Validate workspace paths and setup scripts before `apply`/`update`.
- Prefer `install` first for brand-new services.

## FAQ

### Foxglove shows topics, but `ros2 topic list` doesn't

A classic ROS 2 symptom, and the main reason `set` exists. It's almost always a **DDS environment mismatch**:

- Your systemd services run with a specific `ROS_DOMAIN_ID` / `RMW_IMPLEMENTATION` / `ROS_LOCALHOST_ONLY`.
- **Foxglove Studio** reaches the data *through the Foxglove Bridge service*, so it sees whatever the bridge sees — regardless of your terminal's settings.
- Your **interactive shell** uses its *own* DDS settings. If those differ from the services', your `ros2` CLI ends up on a different DDS domain/participant than your stack, so topics look missing even though they're plainly visible in Foxglove.

`set` aligns your shell with your services in one shot:

```bash
sudo ros2-systemd-manager set -d 42     # match the domain your services use
ros2 topic list                         # ← run this in a NEW terminal afterwards
```

Use the same `ROS_DOMAIN_ID` as your workspace's `ros_domain_id`, the RMW your stack was built against, and a `ROS_LOCALHOST_ONLY` consistent with your discovery needs.

### I ran `set`, but `ros2 topic list` is still empty

`set` writes to rc/profile files, which only affects **new** shells. Open a fresh terminal or run `source ~/.bashrc` (and `source ~/.profile` for login shells) so the new DDS variables are loaded. Preview first with `set --dry-run` to confirm which files were touched.

### Does `update` or `uninstall` touch my *other* projects?

No — by default every action is scoped to the **current directory's** `ros2_services.yaml`. The tool records which config installed each unit (an `.origin` sidecar), so `update` only removes stale units that *this* config owned. Other directories' units are never touched unless you explicitly pass `-g`/`--global`.

### How do I run an action across every project at once?

Add `-g`/`--global` — it operates on every config the tool has ever installed:

```bash
sudo ros2-systemd-manager apply -g       # apply every tracked project
sudo ros2-systemd-manager update -g      # reconcile every tracked project
sudo ros2-systemd-manager uninstall -g   # uninstall every tracked project
ros2-systemd-manager list --global       # see everything the tool manages
```

The generated Makefile offers the same as `make apply-global`, `make update-global`, `make uninstall-global`, etc. Add `-a` to also include `explicit_start`/`explicit_stop` services, and `-f` to skip prompts.

### How do I keep a service running when I stop the rest?

Set `explicit_stop: true` on it. Then `make stop`/`disable`, `uninstall`, and `update`'s stop-previous all skip it, so it survives stopping or restarting the rest of the stack. To stop it anyway, target it directly (`make stop-<svc>`) or pass `-a`/`--all`. (The mirror option `explicit_start: true` does the same for starting — useful for on-demand services like Foxglove.)

### Where does the tool store its data?

- **Unit files**: `/etc/systemd/system/<unit_name>` (configurable via `systemd.unit_dir`).
- **Tracking store**: `~/.config/ros2-systemd-manager/previous-update/` — a copy of each deployed unit, its MD5, and the `.origin` config tag.
- **Archived manual edits**: `~/.config/ros2-systemd-manager/archive/`.

### A root-owned rc/profile file appeared in my home after a `sudo` run

That shouldn't happen anymore — after writing, each rc/profile file is `chown`ed to match its parent (home) directory's owner, so a `sudo` run never leaves a file you can't read or edit. If you have a leftover root-owned file from an older version, re-running `set` will fix its ownership.

## Contributing

Licensed under the **Apache License 2.0** — see [LICENSE](./LICENSE).

Contributions are welcome! Please open issues or submit pull requests for bug fixes, improvements, or new features.
