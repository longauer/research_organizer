"""Tkinter GUI offering the same functionality as the command line interface."""

from __future__ import annotations

import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont
from typing import Any, Callable

from . import model
from .editor import ConflictError, EditorError, EditSession, resolve_editor
from .export import export_markdown
from .storage import Store, StoreError

POLL_MS = 300
ERRORS = (StoreError, model.DataError, EditorError, OSError)


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _short_time(created: str) -> str:
    return created[:16].replace("T", " ")


class App(ttk.Frame):
    def __init__(self, master: tk.Tk, store: Store) -> None:
        super().__init__(master, padding=8)
        self.store = store
        self.current: str | None = None
        self.data: dict[str, Any] | None = None
        # tree item id -> (kind, artifact index, question index)
        self._items: dict[str, tuple[str, int, int | None]] = {}
        self._sessions: dict[str, EditSession] = {}
        self._export_dir = str(Path.home())
        self._build()
        self.refresh_instances()

    # ----------------------------------------------------------------- layout
    def _build(self) -> None:
        master = self.master
        master.title("Research Organizer")
        master.geometry("1050x650")
        master.minsize(700, 450)
        master.protocol("WM_DELETE_WINDOW", self._on_close)
        master.bind("<F5>", lambda _e: self.reload())
        self.pack(fill="both", expand=True)

        bold = tkfont.nametofont("TkDefaultFont").copy()
        bold.configure(weight="bold")

        self.status_var = tk.StringVar(value=f"Data directory: {self.store.root}")
        ttk.Label(self, textvariable=self.status_var, anchor="w").pack(side="bottom", fill="x", pady=(6, 0))

        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, padding=(0, 0, 8, 0))
        paned.add(left, weight=1)
        ttk.Label(left, text="Instances", font=bold).pack(anchor="w")
        self.instance_list = tk.Listbox(left, exportselection=False, activestyle="none", width=24)
        self.instance_list.pack(fill="both", expand=True, pady=4)
        self.instance_list.bind("<<ListboxSelect>>", self._on_instance_select)
        buttons = ttk.Frame(left)
        buttons.pack(fill="x")
        actions = [
            ("New...", self.new_instance),
            ("Copy...", self.copy_instance),
            ("Rename...", self.rename_instance),
            ("Delete", self.delete_instance),
            ("Open in editor", self.edit_instance),
            ("Export...", self.export_instance),
            ("Refresh (F5)", self.reload),
        ]
        for i, (label, command) in enumerate(actions):
            ttk.Button(buttons, text=label, command=command).grid(row=i // 2, column=i % 2, sticky="ew", padx=1, pady=1)
        buttons.columnconfigure((0, 1), weight=1)

        right = ttk.Frame(paned)
        paned.add(right, weight=4)
        self.title_var = tk.StringVar()
        ttk.Label(right, textvariable=self.title_var, font=bold).pack(anchor="w")

        tree_frame = ttk.Frame(right)
        tree_frame.pack(fill="both", expand=True, pady=4)
        self.tree = ttk.Treeview(tree_frame, columns=("text", "created"), selectmode="browse")
        self.tree.heading("#0", text="Item")
        self.tree.heading("text", text="Text")
        self.tree.heading("created", text="Created")
        self.tree.column("#0", width=170, stretch=False)
        self.tree.column("text", width=500, stretch=True)
        self.tree.column("created", width=130, stretch=False)
        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        form = ttk.LabelFrame(right, text="Add to the selected instance", padding=8)
        form.pack(fill="x", pady=(4, 0))
        ttk.Label(form, text="Artifact:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        self.artifact_var = tk.StringVar()
        self.artifact_box = ttk.Combobox(form, textvariable=self.artifact_var)
        self.artifact_box.grid(row=0, column=1, sticky="ew")
        ttk.Label(form, text="Text:").grid(row=1, column=0, sticky="nw", padx=(0, 6), pady=4)
        self.text = tk.Text(form, height=4, wrap="word", undo=True)
        self.text.grid(row=1, column=1, sticky="ew", pady=4)
        add_buttons = ttk.Frame(form)
        add_buttons.grid(row=2, column=1, sticky="e")
        ttk.Button(add_buttons, text="Add note", command=lambda: self.add("note")).pack(side="left", padx=2)
        ttk.Button(add_buttons, text="Add question", command=lambda: self.add("question")).pack(side="left", padx=2)
        ttk.Button(
            add_buttons, text="Add answer to selected question", command=lambda: self.add("answer")
        ).pack(side="left", padx=2)
        form.columnconfigure(1, weight=1)

    # ------------------------------------------------------------- rendering
    def refresh_instances(self, select: str | None = None) -> None:
        names = self.store.list_instances()
        self.instance_list.delete(0, "end")
        for name in names:
            self.instance_list.insert("end", name)
        target = select if select is not None else self.current
        match = next((n for n in names if target is not None and n.casefold() == target.casefold()), None)
        if match is None:
            self.current, self.data = None, None
            self._render()
            return
        index = names.index(match)
        self.instance_list.selection_set(index)
        self.instance_list.see(index)
        self.load_instance(match)

    def reload(self) -> None:
        self.refresh_instances()

    def load_instance(self, name: str) -> None:
        self.current = name
        try:
            self.data = self.store.load(name)
        except ERRORS as exc:
            self.data = None
            messagebox.showerror("Cannot open instance", str(exc), parent=self)
        self._render()

    def _all_items(self, parent: str = "") -> list[str]:
        result = []
        for iid in self.tree.get_children(parent):
            result.append(iid)
            result.extend(self._all_items(iid))
        return result

    def _render(self) -> None:
        opened = {iid for iid in self._all_items() if self.tree.item(iid, "open")}
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        self._items.clear()
        if self.data is None:
            self.title_var.set(self.current and f"{self.current} (could not be loaded)" or "No instance selected")
            self.artifact_box["values"] = ()
            return
        artifacts = self.data["artifacts"]
        self.title_var.set(f"{self.current} - {len(artifacts)} artifact(s)")
        for ai, artifact in enumerate(artifacts):
            aid = f"a{ai}"
            summary = f"{len(artifact['notes'])} note(s), {len(artifact['questions'])} question(s)"
            self.tree.insert("", "end", iid=aid, text=artifact["name"], values=(summary, ""), open=aid in opened)
            self._items[aid] = ("artifact", ai, None)
            for ni, note in enumerate(artifact["notes"]):
                iid = f"{aid}n{ni}"
                values = (_one_line(note["text"]), _short_time(note.get("created", "")))
                self.tree.insert(aid, "end", iid=iid, text=f"Note {ni + 1}", values=values)
                self._items[iid] = ("note", ai, None)
            for qi, question in enumerate(artifact["questions"]):
                qid = f"{aid}q{qi}"
                values = (_one_line(question["text"]), _short_time(question.get("created", "")))
                self.tree.insert(aid, "end", iid=qid, text=f"Question {qi + 1}", values=values, open=qid in opened)
                self._items[qid] = ("question", ai, qi)
                for ki, answer in enumerate(question["answers"]):
                    iid = f"{qid}a{ki}"
                    values = (_one_line(answer["text"]), _short_time(answer.get("created", "")))
                    self.tree.insert(qid, "end", iid=iid, text=f"Answer {ki + 1}", values=values)
                    self._items[iid] = ("answer", ai, qi)
        self.artifact_box["values"] = [a["name"] for a in artifacts]
        if selected and self.tree.exists(selected[0]):
            self._select(selected[0])

    def _select(self, iid: str) -> None:
        self.tree.see(iid)
        self.tree.selection_set(iid)
        self.tree.focus(iid)

    def status(self, message: str) -> None:
        self.status_var.set(message)

    # --------------------------------------------------------------- events
    def _on_instance_select(self, _event: object) -> None:
        selection = self.instance_list.curselection()
        if selection:
            name = self.instance_list.get(selection[0])
            if name != self.current:
                self.tree.delete(*self.tree.get_children())
                self.load_instance(name)

    def _on_tree_select(self, _event: object) -> None:
        selection = self.tree.selection()
        if selection and self.data is not None:
            _kind, ai, _qi = self._items[selection[0]]
            self.artifact_var.set(self.data["artifacts"][ai]["name"])

    def _on_close(self) -> None:
        if self._sessions and not messagebox.askyesno(
            "Quit",
            "Some instances are still open in an editor; their changes will be lost.\nQuit anyway?",
            parent=self,
        ):
            return
        for session in self._sessions.values():
            session.close()
        self.master.destroy()

    # ----------------------------------------------------------- helpers
    def _require_instance(self) -> str | None:
        if self.current is None:
            messagebox.showinfo("No instance", "Select or create an instance first.", parent=self)
        return self.current

    def _is_editing(self, name: str) -> bool:
        if name in self._sessions:
            messagebox.showinfo(
                "Instance being edited",
                f"'{name}' is open in an editor. Save and close the editor first.",
                parent=self,
            )
            return True
        return False

    def _ask_name(self, title: str, prompt: str, initial: str = "") -> str | None:
        name = simpledialog.askstring(title, prompt, initialvalue=initial, parent=self.master)
        return name.strip() if name and name.strip() else None

    def _run(self, action: Callable[[], None], select: str | None, message: str) -> None:
        try:
            action()
        except ERRORS as exc:
            messagebox.showerror("Error", str(exc), parent=self)
            return
        self.status(message)
        self.refresh_instances(select)

    # ------------------------------------------------- instance operations
    def new_instance(self) -> None:
        name = self._ask_name("New instance", "Name of the new instance:")
        if name:
            self._run(lambda: self.store.create(name), name, f"Created instance '{name}'.")

    def copy_instance(self) -> None:
        source = self._require_instance()
        if not source:
            return
        name = self._ask_name("Copy instance", f"Name of the copy of '{source}':", f"{source} copy")
        if name:
            self._run(lambda: self.store.create(name, copy_from=source), name, f"Copied '{source}' to '{name}'.")

    def rename_instance(self) -> None:
        old = self._require_instance()
        if not old or self._is_editing(old):
            return
        new = self._ask_name("Rename instance", f"New name for '{old}':", old)
        if new and new != old:
            self._run(lambda: self.store.rename(old, new), new, f"Renamed '{old}' to '{new}'.")

    def delete_instance(self) -> None:
        name = self._require_instance()
        if not name or self._is_editing(name):
            return
        if messagebox.askyesno(
            "Delete instance",
            f"Delete instance '{name}' and all its data?\nThis cannot be undone.",
            icon="warning",
            parent=self,
        ):
            self._run(lambda: self.store.delete(name), None, f"Deleted instance '{name}'.")

    def export_instance(self) -> None:
        name = self._require_instance()
        if not name:
            return
        directory = filedialog.askdirectory(
            parent=self.master,
            title=f"Export '{name}' to Markdown - choose the target folder",
            initialdir=self._export_dir,
            mustexist=True,
        )
        if not directory:
            return
        self._export_dir = directory
        try:
            try:
                path = export_markdown(self.store, name, directory)
            except FileExistsError as exc:
                if not messagebox.askyesno("Overwrite", f"'{exc.filename}' already exists.\nOverwrite it?", parent=self):
                    return
                path = export_markdown(self.store, name, directory, overwrite=True)
        except ERRORS as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        self.status(f"Exported '{name}' to {path}")

    # ------------------------------------------------------- adding data
    def add(self, kind: str) -> None:
        name = self._require_instance()
        if not name or self.data is None or self._is_editing(name):
            return
        artifact = self.artifact_var.get().strip()
        text = self.text.get("1.0", "end").strip()
        question_index: int | None = None
        if kind == "answer":
            selection = self.tree.selection()
            item = self._items.get(selection[0]) if selection else None
            if item is None or item[0] not in ("question", "answer"):
                messagebox.showinfo("Add answer", "Select a question (or one of its answers) in the tree first.", parent=self)
                return
            artifact = self.data["artifacts"][item[1]]["name"]
            question_index = item[2]
        operations: dict[str, Callable[[dict[str, Any]], int]] = {
            "note": lambda d: model.add_note(d, artifact, text),
            "question": lambda d: model.add_question(d, artifact, text),
            "answer": lambda d: model.add_answer(d, artifact, (question_index or 0) + 1, text),
        }
        try:
            number = self.store.modify(name, operations[kind])
        except ERRORS as exc:
            messagebox.showerror(f"Cannot add {kind}", str(exc), parent=self)
            return
        self.text.delete("1.0", "end")
        self.reload()
        if self.data is None:
            return
        found = model.find_artifact(self.data, artifact)
        if found is None:
            return
        ai = self.data["artifacts"].index(found)
        iid = {
            "note": f"a{ai}n{number - 1}",
            "question": f"a{ai}q{number - 1}",
            "answer": f"a{ai}q{question_index}a{number - 1}",
        }[kind]
        if self.tree.exists(iid):
            self._select(iid)
        self.status(f"Added {kind} {number} to '{found['name']}'.")

    # ------------------------------------------------- external editor
    def edit_instance(self) -> None:
        name = self._require_instance()
        if not name or self._is_editing(name):
            return
        try:
            session = EditSession(self.store, name, resolve_editor())
        except ERRORS as exc:
            messagebox.showerror("Cannot edit", str(exc), parent=self)
            return
        self._sessions[name] = session
        self._start_editor(session)

    def _start_editor(self, session: EditSession) -> None:
        try:
            process = session.start()
        except EditorError as exc:
            messagebox.showerror("Cannot start editor", f"{exc}\n\nSet RESEARCH_ORGANIZER_EDITOR to choose an editor.", parent=self)
            self._end_session(session, "Editing cancelled.")
            return
        self.status(f"Editing '{session.name}' in {session.command[0]} - save and close the editor to apply changes.")
        self.after(POLL_MS, self._poll_editor, session, process)

    def _poll_editor(self, session: EditSession, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            self.after(POLL_MS, self._poll_editor, session, process)
            return
        name = session.name
        if session.returned_immediately():
            messagebox.showinfo(
                "Editing",
                f"'{name}' was opened in an editor running in the background.\n"
                "Click OK once you have saved your changes and closed the file.",
                parent=self,
            )
        try:
            try:
                changed = session.finish()
            except ConflictError as exc:
                if not messagebox.askyesno("Conflict", f"{exc}.\n\nOverwrite it with your edited version?", parent=self):
                    self._end_session(session, "Changes discarded.")
                    return
                changed = session.finish(overwrite=True)
        except model.DataError as exc:
            if messagebox.askyesno("Invalid data", f"The edited data is invalid:\n{exc}\n\nRe-open the editor to fix it?", parent=self):
                self._start_editor(session)
            else:
                self._end_session(session, "Changes discarded.")
            return
        except ERRORS as exc:
            messagebox.showerror("Cannot save", str(exc), parent=self)
            self._end_session(session, "Changes discarded.")
            return
        self._end_session(session, f"Saved changes to '{name}'." if changed else f"No changes made to '{name}'.")

    def _end_session(self, session: EditSession, message: str) -> None:
        session.close()
        self._sessions.pop(session.name, None)
        self.status(message)
        self.reload()


def _enable_dpi_awareness() -> None:
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass


def ask_directory(title: str, initial: str) -> str | None:
    """Show a standalone folder picker (used by the CLI); returns None if cancelled."""
    _enable_dpi_awareness()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise RuntimeError(f"cannot open a folder dialog ({exc})") from exc
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askdirectory(parent=root, title=title, initialdir=initial, mustexist=True) or None
    finally:
        root.destroy()


def run(store: Store | None = None) -> None:
    _enable_dpi_awareness()
    root = tk.Tk()
    App(root, store or Store())
    root.mainloop()


def main() -> None:
    run()


if __name__ == "__main__":
    main()
