# Research Organizer

Collect notes, questions and candidate answers about research artifacts (e.g. `FE-002`, `AOP-036`),
organized in separate named instances. Usable from the command line (PowerShell) or a GUI.

## Installation

Requires Python 3.10+ (with tkinter for the GUI, included in the standard Windows installer).

```powershell
pip install .          # or: pipx install .
```

This installs the commands `rorg` (alias `research-organizer`) and `research-organizer-gui`.

## Data

All instances are stored as JSON files (one per instance) in a single data directory:

- Windows: `%APPDATA%\ResearchOrganizer\instances`
- macOS: `~/Library/Application Support/ResearchOrganizer/instances`
- Linux: `$XDG_DATA_HOME/research-organizer/instances` (default `~/.local/share/...`)

Set `RESEARCH_ORGANIZER_HOME` to use a different directory. `rorg path` prints the current one.

## CLI

```powershell
rorg list                                   # list instances
rorg create thesis                          # new empty instance
rorg create thesis-v2 --from thesis         # copy of an existing instance
rorg rename thesis-v2 draft
rorg delete draft [-y]

rorg add-note thesis FE-002 "The login flow skips validation"
rorg add-question thesis FE-002 "Who owns the validation rules?"
rorg add-answer thesis FE-002 1 "Probably the backend team"   # 1 = question Q1
rorg show thesis [-a FE-002] [--json]

rorg edit thesis [--editor "code --wait"]   # edit the instance JSON in a text editor
rorg export thesis [--dir C:\out] [-f]     # export to <folder>\thesis.md (folder dialog if --dir omitted)
rorg gui                                    # launch the GUI
```

Short aliases: `ls`, `rm`, `note`, `question`, `answer`. Artifact names are matched
case-insensitively; an artifact is created when its first note or question is added.

## Editing in an external editor

`rorg edit` (and *Open in editor* in the GUI) opens a temporary copy of the instance JSON. After the
editor is closed the content is validated and saved; invalid content can be re-opened for fixing.
The editor is taken from `--editor`, `RESEARCH_ORGANIZER_EDITOR`, `VISUAL` or `EDITOR`,
falling back to Notepad (Windows) or `vi`. Editors that return immediately (e.g. `code` without
`--wait`) are detected and you are asked to confirm when you are done.

## Development

```powershell
python -m unittest -v
python -m research_organizer --help
```
