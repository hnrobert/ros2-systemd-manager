"""Interactive terminal prompts for the ``add`` wizard.

Thin wrappers around `questionary` (pnpm-style checkbox/select/text UI). The
import of `questionary` is lazy so the rest of the package works without the
``[add]`` extra installed; each helper falls back to plain ``input()`` when
`questionary` is unavailable or stdin is not a TTY (keeps it usable in CI /
piped contexts).
"""
import sys
from typing import List, Optional


def _have_questionary() -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        import questionary  # noqa: F401
        return True
    except Exception:
        return False


def _is_interactive() -> bool:
    return sys.stdin.isatty()


# --------------------------------------------------------------------------- #
# multi-select
# --------------------------------------------------------------------------- #
def multi_select(message: str, choices: List[str]) -> List[str]:
    """Return the selected choice strings (possibly empty)."""
    if not choices:
        return []
    if _have_questionary():
        import questionary
        from questionary import Choice
        result = questionary.checkbox(
            message, choices=[Choice(c, value=c) for c in choices]
        ).ask()
        return result or []
    # fallback: numbered, comma-separated indices
    print(message)
    for i, c in enumerate(choices):
        print(f"  [{i}] {c}")
    raw = input("Enter indices (comma-separated), blank for none: ").strip()
    out: List[str] = []
    for tok in raw.replace(";", ",").split(","):
        tok = tok.strip()
        if tok.isdigit() and 0 <= int(tok) < len(choices):
            if choices[int(tok)] not in out:
                out.append(choices[int(tok)])
    return out


# --------------------------------------------------------------------------- #
# single-select
# --------------------------------------------------------------------------- #
def single_select(message: str, choices: List[str], allow_skip: bool = False) -> Optional[str]:
    """Return one choice, or None if the user skips/cancels."""
    opts = list(choices)
    if allow_skip:
        opts = list(opts) + ["(skip)"]
    if not opts:
        return None
    if _have_questionary():
        import questionary
        from questionary import Choice
        result = questionary.select(
            message, choices=[Choice(c, value=c) for c in opts]
        ).ask()
        if result is None or result == "(skip)":
            return None
        return result
    # fallback
    print(message)
    for i, c in enumerate(opts):
        print(f"  [{i}] {c}")
    raw = input("Enter index: ").strip()
    if raw.isdigit() and 0 <= int(raw) < len(opts):
        r = opts[int(raw)]
        return None if r == "(skip)" else r
    return None


# --------------------------------------------------------------------------- #
# confirm
# --------------------------------------------------------------------------- #
def confirm(message: str, default: bool = True) -> bool:
    if _have_questionary():
        import questionary
        return bool(questionary.confirm(message, default=default).ask())
    suffix = "[Y/n]" if default else "[y/N]"
    raw = input(f"{message} {suffix} ").strip().lower()
    if raw == "":
        return default
    return raw in ("y", "yes")


# --------------------------------------------------------------------------- #
# text with default / required
# --------------------------------------------------------------------------- #
def text_with_default(
    name: str,
    default: Optional[str] = None,
    required: bool = False,
    description: str = "",
) -> str:
    """Prompt for a single value. Returns the entered value, or ``default``.

    Re-prompts while the result is empty for a required field with no default.
    """
    hint = ""
    if description:
        hint += f"  ({description})"
    show_default = default if default is not None else ""
    label = f"{name}{hint}"
    if default is not None:
        label += f" [default: {default}]"
    elif required:
        label += " (required)"
    while True:
        raw = input(f"  {label}: ").strip()
        if raw:
            return raw
        if default is not None:
            return default
        if required:
            print(f"    '{name}' is required — please enter a value.")
            continue
        return ""  # optional, no default, left blank


def manual_params_input() -> List[str]:
    """Prompt for ``key:=value`` ROS params/exec args until a blank line."""
    print("  Enter parameters as key:=value (one per line, blank to finish).")
    params: List[str] = []
    while True:
        raw = input("  param> ").strip()
        if not raw:
            break
        if ":=" in raw:
            params.append(raw)
        else:
            print("    expected 'key:=value' — skipped.")
    return params
