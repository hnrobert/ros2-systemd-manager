#!/usr/bin/env python3
"""
ROS2 systemd 服务管理脚本（YAML 驱动版）

目标：
1) 读取 ros2_services.yaml，决定“工作空间目录 + 服务列表 + 运行参数”。
2) 支持三种动作：
   - install-only           仅安装 unit 文件
   - install-start-enable   安装 + 启动 + 开机自启
   - uninstall              卸载（停止、取消自启、删除 unit 文件）
3) 无 mode 参数时，自动使用 YAML 中 actions.default_action。

设计说明：
- 你当前是在 root 下执行 ros2 launch，因此默认 runtime.user/group/home 也按 root 配置。
- 每个服务都会生成独立的 systemd unit，便于单独排障。
- systemd 的 daemon-reload 在安装/卸载后都会执行，确保配置生效。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

try:
    import yaml
except ImportError:
    print("[ERROR] 缺少依赖 PyYAML。请先安装：pip install pyyaml", file=sys.stderr)
    sys.exit(1)


SUPPORTED_ACTIONS = {"install-only", "install-start-enable", "uninstall"}


def log(message: str) -> None:
    """统一的信息输出，便于终端识别脚本执行进度。"""
    print(f"[INFO] {message}")


def err(message: str) -> None:
    """统一的错误输出。"""
    print(f"[ERROR] {message}", file=sys.stderr)


def run_cmd(cmd: List[str]) -> None:
    """执行系统命令；失败时直接抛出异常，由上层统一处理。"""
    subprocess.run(cmd, check=True)


def require_root() -> None:
    """写 /etc/systemd/system 与 systemctl 操作需要 root 权限。"""
    if os.geteuid() != 0:
        err("请使用 sudo/root 运行此脚本。")
        sys.exit(1)


def load_yaml_config(config_path: Path) -> Dict[str, Any]:
    """加载并解析 YAML 配置。"""
    if not config_path.exists():
        err(f"配置文件不存在: {config_path}")
        sys.exit(1)

    with config_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        err("配置文件格式错误：顶层应为字典（mapping）。")
        sys.exit(1)

    return data


def validate_config(config: Dict[str, Any]) -> None:
    """
    对关键字段做最小必要校验。
    目的：避免运行到一半才因字段缺失失败，提升可维护性。
    """
    for key in ["actions", "systemd", "runtime", "workspaces"]:
        if key not in config:
            err(f"配置缺少字段: {key}")
            sys.exit(1)

    workspaces = config.get("workspaces")
    if not isinstance(workspaces, dict) or not workspaces:
        err("workspaces 不能为空，且必须是对象。")
        sys.exit(1)


def resolve_action(cli_action: str | None, config: Dict[str, Any]) -> str:
    """
    确定要执行的动作：
    - CLI 指定优先
    - 否则使用 YAML 的 default_action
    """
    default_action = config.get("actions", {}).get("default_action", "install-start-enable")
    action = cli_action or default_action

    if action not in SUPPORTED_ACTIONS:
        err(f"不支持的动作: {action}，允许: {sorted(SUPPORTED_ACTIONS)}")
        sys.exit(1)

    return action


def resolve_workspace_key(cli_workspace_key: str | None, config: Dict[str, Any]) -> str:
    """
    选择工作空间：
    - 指定 --workspace-key 时使用指定项
    - 未指定时使用 workspaces 中第一项
    """
    workspaces: Dict[str, Any] = config["workspaces"]

    if cli_workspace_key:
        if cli_workspace_key not in workspaces:
            err(f"未找到 workspace_key: {cli_workspace_key}")
            sys.exit(1)
        return cli_workspace_key

    return next(iter(workspaces.keys()))


def build_unit_content(
    *,
    description: str,
    workspace_path: Path,
    setup_script_rel: str,
    launch_command: str,
    depends_on: List[str],
    runtime: Dict[str, Any],
    wanted_by: str,
) -> str:
    """
    生成 systemd unit 文件内容。
    - ExecStart 使用 bash -lc 以确保 source/setup 与 ROS 环境生效。
    - 使用 exec 启动 ros2 launch，避免多一层 shell 进程驻留。
    - depends_on 会转换为 Requires + After，实现服务依赖顺序。
    """
    shell = runtime.get("shell", "/bin/bash")
    user = runtime.get("user", "root")
    group = runtime.get("group", "root")
    home = runtime.get("home", "/root")
    restart = runtime.get("restart", "on-failure")
    restart_sec = runtime.get("restart_sec", 3)

    setup_script_abs = workspace_path / setup_script_rel

    after_targets = ["network-online.target", *depends_on]
    after_line = " ".join(after_targets)
    requires_line = f"Requires={' '.join(depends_on)}\n" if depends_on else ""

    return f"""[Unit]
Description={description}
{requires_line}After={after_line}
Wants=network-online.target

[Service]
Type=simple
User={user}
Group={group}
WorkingDirectory={workspace_path}
Environment=HOME={home}
ExecStart={shell} -lc 'source "{setup_script_abs}" && exec {launch_command}'
Restart={restart}
RestartSec={restart_sec}

[Install]
WantedBy={wanted_by}
"""


def validate_workspace_for_install(workspace_path: Path, setup_script_rel: str) -> None:
    """安装类动作前检查工作空间和 setup 脚本是否存在。"""
    if not workspace_path.is_dir():
        err(f"工作空间不存在: {workspace_path}")
        sys.exit(1)

    setup_script_abs = workspace_path / setup_script_rel
    if not setup_script_abs.is_file():
        err(f"未找到 setup 脚本: {setup_script_abs}")
        sys.exit(1)


def install_only(config: Dict[str, Any], workspace_key: str) -> List[str]:
    """
    仅安装服务文件，不启动、不设置开机自启。
    返回值：本次处理的 unit 名称列表。
    """
    systemd_cfg = config["systemd"]
    runtime_cfg = config["runtime"]
    workspace_cfg = config["workspaces"][workspace_key]

    unit_dir = Path(systemd_cfg.get("unit_dir", "/etc/systemd/system"))
    wanted_by = systemd_cfg.get("wanted_by", "multi-user.target")

    workspace_path = Path(workspace_cfg["path"])
    setup_script_rel = workspace_cfg.get("setup_script", "install/setup.bash")
    services = workspace_cfg.get("services", [])

    if not services:
        err(f"workspace {workspace_key} 下 services 为空。")
        sys.exit(1)

    validate_workspace_for_install(workspace_path, setup_script_rel)

    unit_names: List[str] = []
    defined_unit_names = {svc["unit_name"] for svc in services}
    log(f"开始写入 unit 文件到: {unit_dir}")

    for svc in services:
        unit_name = svc["unit_name"]
        description = svc.get("description", unit_name)
        launch_command = svc["launch_command"]
        depends_on = svc.get("depends_on", [])

        if not isinstance(depends_on, list):
            err(f"服务 {unit_name} 的 depends_on 必须是列表。")
            sys.exit(1)

        for dep_unit in depends_on:
            if dep_unit == unit_name:
                err(f"服务 {unit_name} 的 depends_on 不能依赖自身。")
                sys.exit(1)
            if dep_unit not in defined_unit_names:
                err(
                    f"服务 {unit_name} 依赖了未定义服务: {dep_unit}，"
                    f"请确认它存在于同一 workspace.services 中。"
                )
                sys.exit(1)

        unit_content = build_unit_content(
            description=description,
            workspace_path=workspace_path,
            setup_script_rel=setup_script_rel,
            launch_command=launch_command,
            depends_on=depends_on,
            runtime=runtime_cfg,
            wanted_by=wanted_by,
        )

        unit_file = unit_dir / unit_name
        unit_file.write_text(unit_content, encoding="utf-8")
        os.chmod(unit_file, 0o644)
        unit_names.append(unit_name)
        log(f"已写入: {unit_file}")

    run_cmd(["systemctl", "daemon-reload"])
    log("systemd daemon-reload 完成。")
    log("安装完成（未启动、未设置开机自启）。")
    return unit_names


def install_start_enable(config: Dict[str, Any], workspace_key: str) -> None:
    """安装服务后，立即启动并设置开机自启。"""
    unit_names = install_only(config, workspace_key)
    log("开始启用并启动服务...")
    run_cmd(["systemctl", "enable", "--now", *unit_names])
    log("完成：服务已启动并设置开机自启。")
    log(f"可查看状态: systemctl status {' '.join(unit_names)}")


def uninstall(config: Dict[str, Any], workspace_key: str) -> None:
    """
    卸载服务：
    1) 停止并取消自启
    2) 删除 unit 文件
    3) daemon-reload
    """
    systemd_cfg = config["systemd"]
    workspace_cfg = config["workspaces"][workspace_key]

    unit_dir = Path(systemd_cfg.get("unit_dir", "/etc/systemd/system"))
    services = workspace_cfg.get("services", [])
    unit_names = [svc["unit_name"] for svc in services]

    if not unit_names:
        log(f"workspace {workspace_key} 没有服务可卸载。")
        return

    log("停止并取消开机自启（若已存在）...")
    subprocess.run(["systemctl", "disable", "--now", *unit_names], check=False)

    log("删除 unit 文件...")
    for unit_name in unit_names:
        unit_file = unit_dir / unit_name
        if unit_file.exists():
            unit_file.unlink()
            log(f"已删除: {unit_file}")

    run_cmd(["systemctl", "daemon-reload"])
    subprocess.run(["systemctl", "reset-failed"], check=False)
    log("卸载完成。")


def parse_args() -> argparse.Namespace:
    """
    CLI 设计：
    - action 是可选位置参数，留空则读取 YAML 默认动作
    - 通过 --config 指定 YAML 路径
    - 通过 --workspace-key 选择配置中的某个工作空间
    """
    parser = argparse.ArgumentParser(
        description="ROS2 systemd 服务管理器（读取 YAML 配置）。"
    )
    parser.add_argument(
        "action",
        nargs="?",
        help="可选：install-only | install-start-enable | uninstall；不传则用 YAML 默认动作",
    )
    parser.add_argument(
        "--config",
        default=str(Path(__file__).with_name("ros2_services.yaml")),
        help="YAML 配置文件路径（默认同目录 ros2_services.yaml）",
    )
    parser.add_argument(
        "--workspace-key",
        default=None,
        help="要操作的工作空间键名（默认取 workspaces 第一项）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    require_root()

    config_path = Path(args.config)
    config = load_yaml_config(config_path)
    validate_config(config)

    action = resolve_action(args.action, config)
    workspace_key = resolve_workspace_key(args.workspace_key, config)

    log(f"配置文件: {config_path}")
    log(f"工作空间键: {workspace_key}")
    log(f"执行动作: {action}")

    if action == "install-only":
        install_only(config, workspace_key)
    elif action == "install-start-enable":
        install_start_enable(config, workspace_key)
    elif action == "uninstall":
        uninstall(config, workspace_key)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        err(f"命令执行失败: {' '.join(exc.cmd)} (exit={exc.returncode})")
        sys.exit(exc.returncode)
    except KeyError as exc:
        err(f"配置字段缺失: {exc}")
        sys.exit(1)
