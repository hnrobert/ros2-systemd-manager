SUPPORTED_ACTIONS = {
    "init",
    "install",
    "apply",
    "uninstall",
    "update",
    "makefile",
}


ACTION_ALIASES = {
    "init-defaults": "init",
    "install-only": "install",
    "install-start-enable": "apply",
    "sync-update": "update",
    "update-makefile": "makefile",
}


def normalize_action(action: str) -> str:
    """Map legacy action names to canonical simplified names."""
    return ACTION_ALIASES.get(action, action)
