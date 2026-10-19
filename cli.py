"""Command line interface (entry points ``research-organizer`` and ``rorg``)."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Sequence

from . import __version__, model
from .editor import ConflictError, EditorError, EditSession, resolve_editor
from .export import export_markdown
from .storage import InstanceNotFoundError, Store, StoreError

PROG = "rorg"


def _confirm(prompt: str, default: bool = False) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        answer = input(prompt + suffix).strip().lower()
    except EOFError:
        return default
    return default if not answer else answer in ("y", "yes")


def _text(parts: Sequence[str]) -> str:
    return " ".join(parts)


def _block(text: str, prefix: str, indent: str) -> str:
    """First line gets ``prefix``; continuation lines of multi-line text are aligned under it."""
    first, *rest = text.splitlines() or [""]
    lines = [f"{indent}{prefix}{first}"]
    lines += [f"{indent}{' ' * len(prefix)}{line}" for line in rest]
    return "\n".join(lines)


def format_artifact(artifact: dict[str, Any]) -> str:
    out = [f"[{artifact['name']}]"]
    if artifact["notes"]:
        out.append("  Notes:")
        for i, note in enumerate(artifact["notes"], 1):
            out.append(_block(note["text"], f"N{i}. ", "    "))
    if artifact["questions"]:
        out.append("  Questions:")
        for i, question in enumerate(artifact["questions"], 1):
            out.append(_block(question["text"], f"Q{i}. ", "    "))
            for j, answer in enumerate(question["answers"], 1):
                out.append(_block(answer["text"], f"A{j}. ", "        "))
    if len(out) == 1:
        out.append("  (empty)")
    return "\n".join(out)


def cmd_path(store: Store, args: argparse.Namespace) -> int:
    print(store.root)
    return 0


def cmd_list(store: Store, args: argparse.Namespace) -> int:
    names = store.list_instances()
    if not names:
        print(f"No instances yet. Create one with: {PROG} create NAME")
    for name in names:
        print(name)
    return 0


def cmd_create(store: Store, args: argparse.Namespace) -> int:
    store.create(args.name, copy_from=args.source)
    origin = f" as a copy of '{args.source}'" if args.source else ""
    print(f"Created instance '{args.name}'{origin}.")
    return 0


def cmd_rename(store: Store, args: argparse.Namespace) -> int:
    store.rename(args.old, args.new)
    print(f"Renamed instance '{args.old}' to '{args.new}'.")
    return 0


def cmd_delete(store: Store, args: argparse.Namespace) -> int:
    if not store.exists(args.name):
        raise InstanceNotFoundError(f"instance '{args.name}' does not exist")
    if not args.yes and not _confirm(f"Delete instance '{args.name}' and all its data?"):
        print("Aborted.")
        return 1
    store.delete(args.name)
    print(f"Deleted instance '{args.name}'.")
    return 0


def cmd_show(store: Store, args: argparse.Namespace) -> int:
    data = store.load(args.name)
    if args.artifact:
        artifact = model.find_artifact(data, args.artifact)
        if artifact is None:
            raise model.DataError(f"artifact '{args.artifact}' does not exist in '{args.name}'")
        artifacts = [artifact]
    else:
        artifacts = data["artifacts"]
    if args.json:
        payload = {**data, "artifacts": artifacts}
        sys.stdout.write(model.to_json(payload))
        return 0
    if not artifacts:
        print(f"Instance '{args.name}' is empty.")
        return 0
    print("\n\n".join(format_artifact(a) for a in artifacts))
    return 0


def cmd_add_note(store: Store, args: argparse.Namespace) -> int:
    number = store.modify(args.name, lambda d: model.add_note(d, args.artifact, _text(args.text)))
    print(f"Added note N{number} to '{args.artifact}'.")
    return 0


def cmd_add_question(store: Store, args: argparse.Namespace) -> int:
    number = store.modify(args.name, lambda d: model.add_question(d, args.artifact, _text(args.text)))
    print(f"Added question Q{number} to '{args.artifact}'.")
    return 0


def cmd_add_answer(store: Store, args: argparse.Namespace) -> int:
    number = store.modify(
        args.name, lambda d: model.add_answer(d, args.artifact, args.question, _text(args.text))
    )
    print(f"Added answer A{number} to question Q{args.question} of '{args.artifact}'.")
    return 0


def cmd_edit(store: Store, args: argparse.Namespace) -> int:
    with EditSession(store, args.name, resolve_editor(args.editor)) as session:
        print(f"Opening '{args.name}' in {session.command[0]} ...")
        while True:
            session.start().wait()
            if session.returned_immediately():
                input("The editor returned immediately. Press Enter once you have saved and closed the file...")
            try:
                changed = session.finish()
            except model.DataError as exc:
                print(f"error: the edited data is invalid: {exc}", file=sys.stderr)
                if _confirm("Re-open the editor to fix it?", default=True):
                    continue
                print("Changes discarded.")
                return 1
            except ConflictError as exc:
                print(f"warning: {exc}", file=sys.stderr)
                if not _confirm("Overwrite it with your edited version?"):
                    print("Changes discarded.")
                    return 1
                changed = session.finish(overwrite=True)
            print(f"Saved changes to '{args.name}'." if changed else "No changes made.")
            return 0


def cmd_export(store: Store, args: argparse.Namespace) -> int:
    store.load(args.name)  # fail before showing the folder dialog
    directory = args.dir
    if directory is None:
        try:
            from .gui import ask_directory

            directory = ask_directory(f"Export '{args.name}' to Markdown - choose the target folder", os.getcwd())
        except (ImportError, RuntimeError) as exc:
            print(f"error: {exc}; pass the target folder with --dir", file=sys.stderr)
            return 1
        if not directory:
            print("Export cancelled.")
            return 1
    try:
        path = export_markdown(store, args.name, directory, overwrite=args.force)
    except FileExistsError as exc:
        if not _confirm(f"'{exc.filename}' already exists. Overwrite it?"):
            print("Export cancelled.")
            return 1
        path = export_markdown(store, args.name, directory, overwrite=True)
    print(f"Exported '{args.name}' to {path}")
    return 0


def cmd_gui(store: Store, args: argparse.Namespace) -> int:
    from .gui import run

    run(store)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Collect and organize research notes and questions about artifacts.",
        epilog=f"Data directory: set the RESEARCH_ORGANIZER_HOME environment variable to override. "
        f"Run '{PROG} COMMAND -h' for help on a command.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    p = sub.add_parser("list", aliases=["ls"], help="list instances")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("create", help="create an empty instance or a copy of an existing one")
    p.add_argument("name")
    p.add_argument("--from", dest="source", metavar="SOURCE", help="copy data from this instance")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("rename", help="rename an instance")
    p.add_argument("old")
    p.add_argument("new")
    p.set_defaults(func=cmd_rename)

    p = sub.add_parser("delete", aliases=["rm"], help="delete an instance")
    p.add_argument("name")
    p.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("show", help="show the contents of an instance")
    p.add_argument("name")
    p.add_argument("-a", "--artifact", help="show only this artifact")
    p.add_argument("--json", action="store_true", help="print raw JSON")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("add-note", aliases=["note"], help="add a note to an artifact")
    p.add_argument("name", help="instance name")
    p.add_argument("artifact", help="artifact name, e.g. FE-002 (created if missing)")
    p.add_argument("text", nargs="+", help="note text")
    p.set_defaults(func=cmd_add_note)

    p = sub.add_parser("add-question", aliases=["question"], help="add a question to an artifact")
    p.add_argument("name", help="instance name")
    p.add_argument("artifact", help="artifact name, e.g. FE-002 (created if missing)")
    p.add_argument("text", nargs="+", help="question text")
    p.set_defaults(func=cmd_add_question)

    p = sub.add_parser("add-answer", aliases=["answer"], help="add a candidate answer to a question")
    p.add_argument("name", help="instance name")
    p.add_argument("artifact", help="artifact name")
    p.add_argument("question", type=int, help="question number as shown by 'show' (Q1 -> 1)")
    p.add_argument("text", nargs="+", help="answer text")
    p.set_defaults(func=cmd_add_answer)

    p = sub.add_parser("edit", help="open an instance in a text editor and save the result")
    p.add_argument("name")
    p.add_argument(
        "-e",
        "--editor",
        help="editor command, e.g. vim or \"code --wait\" "
        "(default: $RESEARCH_ORGANIZER_EDITOR, $VISUAL, $EDITOR, then notepad/vi)",
    )
    p.set_defaults(func=cmd_edit)

    p = sub.add_parser("export", help="export an instance to a Markdown file")
    p.add_argument("name")
    p.add_argument("-d", "--dir", help="target folder (default: choose it in a folder dialog)")
    p.add_argument("-f", "--force", action="store_true", help="overwrite an existing file without asking")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("gui", help="launch the graphical interface")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("path", help="print the data directory")
    p.set_defaults(func=cmd_path)

    return parser


def main(argv: Sequence[str] | None = None, store: Store | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(store or Store(), args)
    except (StoreError, model.DataError, EditorError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
