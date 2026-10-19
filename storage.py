"""Persistence of instances as JSON files in a single per-user data directory."""

from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, TypeVar

from . import model

ENV_HOME = "RESEARCH_ORGANIZER_HOME"
SUFFIX = ".json"

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,63}$")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}

T = TypeVar("T")


class StoreError(Exception):
    """Base error for instance management problems."""


class InvalidNameError(StoreError):
    pass


class InstanceNotFoundError(StoreError):
    pass


class InstanceExistsError(StoreError):
    pass


def default_data_dir() -> Path:
    """Data directory; overridable with the RESEARCH_ORGANIZER_HOME environment variable."""
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "ResearchOrganizer"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ResearchOrganizer"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "research-organizer"


def validate_name(name: str) -> str:
    """Instance names become file names, so only a safe subset of characters is allowed."""
    if (
        not isinstance(name, str)
        or not _NAME_RE.match(name)
        or name.endswith((" ", "."))
        or name.split(".")[0].strip().upper() in _WINDOWS_RESERVED
    ):
        raise InvalidNameError(
            f"invalid instance name {name!r}: use 1-64 letters, digits, spaces, '_', '-' or '.', "
            "starting with a letter or digit"
        )
    return name


class Store:
    def __init__(self, root: str | os.PathLike[str] | None = None) -> None:
        self.root = Path(root) if root is not None else default_data_dir()
        self.instances_dir = self.root / "instances"

    def path_for(self, name: str) -> Path:
        return self.instances_dir / f"{validate_name(name)}{SUFFIX}"

    def exists(self, name: str) -> bool:
        return self.path_for(name).is_file()

    def _require(self, name: str) -> Path:
        path = self.path_for(name)
        if not path.is_file():
            raise InstanceNotFoundError(f"instance '{name}' does not exist")
        return path

    def list_instances(self) -> list[str]:
        if not self.instances_dir.is_dir():
            return []
        return sorted((p.stem for p in self.instances_dir.glob(f"*{SUFFIX}") if p.is_file()), key=str.casefold)

    def create(self, name: str, copy_from: str | None = None) -> None:
        path = self.path_for(name)
        data = self.load(copy_from) if copy_from is not None else model.new_instance_data()
        if path.exists():
            raise InstanceExistsError(f"instance '{name}' already exists")
        self._write(path, data)

    def delete(self, name: str) -> None:
        self._require(name).unlink()

    def rename(self, old: str, new: str) -> None:
        old_path = self._require(old)
        new_path = self.path_for(new)
        # A case-only rename on a case-insensitive file system points at the same file.
        if new_path.exists() and not os.path.samefile(old_path, new_path):
            raise InstanceExistsError(f"instance '{new}' already exists")
        os.replace(old_path, new_path)

    def load(self, name: str) -> dict[str, Any]:
        path = self._require(name)
        try:
            return model.from_json(path.read_text(encoding="utf-8-sig"))
        except model.DataError as exc:
            raise model.DataError(f"instance '{name}' ({path}): {exc}") from exc

    def save(self, name: str, data: dict[str, Any]) -> None:
        self._write(self.path_for(name), model.validate(data))

    def modify(self, name: str, func: Callable[[dict[str, Any]], T]) -> T:
        """Load an instance, apply ``func`` to its data and save it; returns func's result."""
        data = self.load(name)
        result = func(data)
        self.save(name, data)
        return result

    def _write(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(model.to_json(data))
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
