"""Export of an instance to a Markdown document."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import Any

from .storage import Store, StoreError


def _item(text: str, prefix: str, indent: str = "") -> list[str]:
    """A list item whose continuation lines are indented to stay inside the item."""
    first, *rest = text.splitlines() or [""]
    pad = indent + " " * len(prefix)
    return [f"{indent}{prefix}{first}"] + [f"{pad}{line}" if line.strip() else "" for line in rest]


def to_markdown(name: str, data: dict[str, Any]) -> str:
    """Nested lists only (no headings), so the whole document uses one font size."""
    lines = [f"**{name}**", ""]
    if not data["artifacts"]:
        lines.append("_No artifacts._")
    section = "  "
    entry = "    "
    for artifact in data["artifacts"]:
        lines.append(f"- **{artifact['name']}**")
        if artifact["notes"]:
            lines.append(f"{section}- Notes")
            for i, note in enumerate(artifact["notes"], 1):
                lines += _item(note["text"], f"{i}. ", entry)
        if artifact["questions"]:
            lines.append(f"{section}- Questions")
            for i, question in enumerate(artifact["questions"], 1):
                prefix = f"{i}. "
                lines += _item(question["text"], prefix, entry)
                for answer in question["answers"]:
                    lines += _item(answer["text"], "- ", entry + " " * len(prefix))
        if not artifact["notes"] and not artifact["questions"]:
            lines.append(f"{section}- _No notes or questions._")
    return "\n".join(lines) + "\n"


def export_markdown(
    store: Store, name: str, directory: str | os.PathLike[str], overwrite: bool = False
) -> Path:
    """Write ``<directory>/<name>.md``; raises FileExistsError if it exists and not ``overwrite``."""
    data = store.load(name)
    directory = Path(directory)
    if not directory.is_dir():
        raise StoreError(f"target directory '{directory}' does not exist")
    path = directory / f"{name}.md"
    if path.exists() and not overwrite:
        raise FileExistsError(errno.EEXIST, "file already exists", str(path))
    path.write_text(to_markdown(name, data), encoding="utf-8")
    return path
