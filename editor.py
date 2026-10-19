"""Editing an instance's JSON in an external text editor (Notepad, vim, VS Code, ...)."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Sequence

from . import model
from .storage import InstanceNotFoundError, Store

ENV_EDITOR = "RESEARCH_ORGANIZER_EDITOR"

# Editors such as the Windows 11 Notepad or `code` without `--wait` hand the file over to an
# already running process and return immediately; below this many seconds we assume that.
DETACHED_THRESHOLD = 1.0


class EditorError(Exception):
    pass


class ConflictError(Exception):
    """The instance was changed by someone else while it was being edited."""


def split_command(command: str) -> list[str]:
    if os.name == "nt":
        parts = shlex.split(command, posix=False)
        return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] == '"' else p for p in parts]
    return shlex.split(command)


def resolve_editor(command: str | None = None) -> list[str]:
    """Editor command: explicit argument, then $RESEARCH_ORGANIZER_EDITOR, $VISUAL, $EDITOR."""
    command = command or os.environ.get(ENV_EDITOR) or os.environ.get("VISUAL") or os.environ.get("EDITOR")
    if not command:
        return ["notepad.exe"] if os.name == "nt" else ["vi"]
    parts = split_command(command)
    if not parts:
        raise EditorError("empty editor command")
    return parts


class EditSession:
    """Copies an instance to a temporary file, lets an editor change it and saves the result."""

    def __init__(self, store: Store, name: str, editor_command: Sequence[str]) -> None:
        self.store = store
        self.name = name
        self.command = list(editor_command)
        self.original_text = model.to_json(store.load(name))
        self._dir = tempfile.mkdtemp(prefix="research_organizer_")
        self.path = Path(self._dir) / f"{name}.json"
        self.path.write_text(self.original_text, encoding="utf-8")
        self._started = 0.0

    def start(self) -> subprocess.Popen[bytes]:
        executable = shutil.which(self.command[0]) or self.command[0]
        self._started = time.monotonic()
        try:
            return subprocess.Popen([executable, *self.command[1:], str(self.path)])
        except OSError as exc:
            raise EditorError(f"cannot start editor {self.command[0]!r}: {exc}") from exc

    def returned_immediately(self) -> bool:
        return time.monotonic() - self._started < DETACHED_THRESHOLD

    def _modified_elsewhere(self) -> bool:
        try:
            return model.to_json(self.store.load(self.name)) != self.original_text
        except (InstanceNotFoundError, model.DataError):
            return True

    def finish(self, overwrite: bool = False) -> bool:
        """Save the edited data; returns False if nothing changed.

        Raises model.DataError if the edited text is invalid and ConflictError if the instance
        was modified elsewhere in the meantime (unless ``overwrite`` is set).
        """
        text = self.path.read_text(encoding="utf-8-sig")
        if text == self.original_text:
            return False
        data = model.from_json(text)
        if not overwrite and self._modified_elsewhere():
            raise ConflictError(f"instance '{self.name}' was changed or removed while it was being edited")
        self.store.save(self.name, data)
        return True

    def close(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def __enter__(self) -> EditSession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
