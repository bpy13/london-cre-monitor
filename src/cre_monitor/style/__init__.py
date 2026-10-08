"""House style: learn from example reports and apply to briefs. See :mod:`.profile`, :mod:`.editor`."""

from cre_monitor.style.profile import (
    MAX_FILES, SUPPORTED_SUFFIXES, StyleProfile, active_profile, clear_profile, delete_example, examples_dir,
    learn_profile, list_examples, load_profile, resolve_layout, save_example,
)

__all__ = [
    "MAX_FILES", "SUPPORTED_SUFFIXES", "StyleProfile", "active_profile", "clear_profile", "delete_example",
    "examples_dir", "learn_profile", "list_examples", "load_profile", "resolve_layout", "save_example",
]
