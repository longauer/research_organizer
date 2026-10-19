"""Instance data model: artifacts holding notes and questions with candidate answers.

Instance data is a plain JSON-compatible dict::

    {
      "version": 1,
      "artifacts": [
        {
          "name": "FE-002",
          "notes": [{"text": "...", "created": "..."}],
          "questions": [
            {"text": "...", "created": "...", "answers": [{"text": "...", "created": "..."}]}
          ]
        }
      ]
    }

Artifact names are matched case-insensitively, so ``fe-002`` and ``FE-002`` refer to
the same artifact (the spelling used when it was first added is kept).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

SCHEMA_VERSION = 1


class DataError(ValueError):
    """Raised when instance data is malformed or an operation gets invalid input."""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_instance_data() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "artifacts": []}


def to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def from_json(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DataError(f"invalid JSON: {exc}") from exc
    return validate(data)


def _clean_text(text: str, what: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise DataError(f"{what} must not be empty")
    return text.strip()


def _key(name: str) -> str:
    return name.strip().casefold()


def find_artifact(data: dict[str, Any], name: str) -> dict[str, Any] | None:
    key = _key(name)
    for artifact in data["artifacts"]:
        if _key(artifact["name"]) == key:
            return artifact
    return None


def get_or_create_artifact(data: dict[str, Any], name: str) -> dict[str, Any]:
    name = _clean_text(name, "artifact name")
    artifact = find_artifact(data, name)
    if artifact is None:
        artifact = {"name": name, "notes": [], "questions": []}
        data["artifacts"].append(artifact)
    return artifact


def add_note(data: dict[str, Any], artifact_name: str, text: str) -> int:
    """Add a note to the artifact (created if missing); returns the 1-based note number."""
    text = _clean_text(text, "note text")
    artifact = get_or_create_artifact(data, artifact_name)
    artifact["notes"].append({"text": text, "created": now()})
    return len(artifact["notes"])


def add_question(data: dict[str, Any], artifact_name: str, text: str) -> int:
    """Add a question to the artifact (created if missing); returns the 1-based question number."""
    text = _clean_text(text, "question text")
    artifact = get_or_create_artifact(data, artifact_name)
    artifact["questions"].append({"text": text, "created": now(), "answers": []})
    return len(artifact["questions"])


def add_answer(data: dict[str, Any], artifact_name: str, question_number: int, text: str) -> int:
    """Add a candidate answer to an existing question; returns the 1-based answer number."""
    text = _clean_text(text, "answer text")
    artifact = find_artifact(data, artifact_name)
    if artifact is None:
        raise DataError(f"artifact '{artifact_name.strip()}' does not exist")
    questions = artifact["questions"]
    if not 1 <= question_number <= len(questions):
        raise DataError(
            f"artifact '{artifact['name']}' has no question {question_number} "
            f"(it has {len(questions)} question(s))"
        )
    answers = questions[question_number - 1]["answers"]
    answers.append({"text": text, "created": now()})
    return len(answers)


def _validate_entry(entry: Any, where: str) -> None:
    if not isinstance(entry, dict):
        raise DataError(f"{where} must be an object")
    if not isinstance(entry.get("text"), str) or not entry["text"].strip():
        raise DataError(f"{where} must have a non-empty 'text'")
    if "created" in entry and not isinstance(entry["created"], str):
        raise DataError(f"{where}.created must be a string")


def _validate_list(container: dict[str, Any], key: str, where: str) -> list[Any]:
    value = container.setdefault(key, [])
    if not isinstance(value, list):
        raise DataError(f"{where}.{key} must be a list")
    return value


def validate(data: Any) -> dict[str, Any]:
    """Check the structure of instance data, filling in missing optional lists.

    Returns the same (normalized) dict or raises DataError describing the first problem.
    """
    if not isinstance(data, dict):
        raise DataError("instance data must be a JSON object")
    version = data.setdefault("version", SCHEMA_VERSION)
    if version != SCHEMA_VERSION:
        raise DataError(f"unsupported data version {version!r} (expected {SCHEMA_VERSION})")
    artifacts = _validate_list(data, "artifacts", "data")
    seen: set[str] = set()
    for i, artifact in enumerate(artifacts):
        where = f"artifacts[{i}]"
        if not isinstance(artifact, dict):
            raise DataError(f"{where} must be an object")
        name = artifact.get("name")
        if not isinstance(name, str) or not name.strip():
            raise DataError(f"{where} must have a non-empty 'name'")
        if _key(name) in seen:
            raise DataError(f"duplicate artifact name '{name}'")
        seen.add(_key(name))
        for j, note in enumerate(_validate_list(artifact, "notes", where)):
            _validate_entry(note, f"{where}.notes[{j}]")
        for j, question in enumerate(_validate_list(artifact, "questions", where)):
            q_where = f"{where}.questions[{j}]"
            _validate_entry(question, q_where)
            for k, answer in enumerate(_validate_list(question, "answers", q_where)):
                _validate_entry(answer, f"{q_where}.answers[{k}]")
    return data
