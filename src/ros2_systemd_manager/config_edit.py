"""Comment-preserving edits to ``ros2_services.yaml`` via ruamel.yaml.

The base package only depends on PyYAML for parsing; this module uses
``ruamel.yaml`` (provided by the ``[add]`` extra) so the ``add`` wizard can
append/replace service entries without destroying the user's comments and
formatting.
"""
from pathlib import Path
from typing import Any, List, Tuple

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


def _yaml() -> YAML:
    y = YAML(typ="rt")  # round-trip: preserves comments and ordering
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    return y


def load_rt(path: Path) -> CommentedMap:
    y = _yaml()
    with path.open("r", encoding="utf-8") as f:
        data = y.load(f)
    if data is None:
        data = CommentedMap()
    return data


def dump_rt(path: Path, data: CommentedMap) -> None:
    y = _yaml()
    with path.open("w", encoding="utf-8") as f:
        y.dump(data, f)


def _to_commented(d: dict) -> CommentedMap:
    cm = CommentedMap()
    for k, v in d.items():
        cm[k] = v
    return cm


def _services_list(data: CommentedMap, workspace_key: str) -> CommentedSeq:
    """Return (creating if absent) the ``services`` list for a workspace."""
    workspaces = data.setdefault("workspaces", CommentedMap())
    ws = workspaces.get(workspace_key)
    if ws is None:
        ws = CommentedMap()
        workspaces[workspace_key] = ws
    services = ws.get("services")
    if services is None:
        services = CommentedSeq()
        ws["services"] = services
    return services


def _find_index(services: CommentedSeq, unit_name: str) -> int:
    for i, svc in enumerate(services):
        if isinstance(svc, dict) and svc.get("unit_name") == unit_name:
            return i
    return -1


def apply_services(
    data: CommentedMap,
    workspace_key: str,
    entries: List[Tuple[dict, bool]],
) -> int:
    """Append/replace service entries.

    ``entries`` is a list of ``(service_dict, overwrite)``. When a service with
    the same ``unit_name`` already exists: it is replaced if ``overwrite`` else
    skipped. Otherwise the entry is appended. Returns the number of entries that
    were written (added or replaced).
    """
    services = _services_list(data, workspace_key)
    written = 0
    for svc_dict, overwrite in entries:
        idx = _find_index(services, svc_dict["unit_name"])
        if idx >= 0:
            if not overwrite:
                continue
            services[idx] = _to_commented(svc_dict)
        else:
            services.append(_to_commented(svc_dict))
        written += 1
    return written
