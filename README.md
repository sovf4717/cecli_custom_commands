# cecli-custom-commands: RAG

A set of [cecli](https://cecli.dev) **custom commands** that give the agent a
lightweight, dependency-free RAG (Retrieval-Augmented Generation) system:
add files/folders as context, query them, list and drop them. No external
packages required — everything is stdlib.

Commands provided:

| Command | Purpose |
|---|---|
| `/rag-add <path> [...]` | Index files/folders into the session RAG store |
| `/rag-question <question>` | Ask a question against the indexed context |
| `/rag-ls` | List all RAG objects in the current conversation |
| `/rag-drop [file] [...]` | Remove specific (or all) RAG objects |

---

## How it works

Cecli loads custom commands from the paths listed under the `custom:` key in
its YAML config. Each `.py` file found there is imported and any class named
`CustomCommand` (inheriting `cecli.commands.utils.base_command.BaseCommand`)
is registered automatically. These commands follow that exact convention:

```python
NORM_NAME = "rag-add"   # registered name
DESCRIPTION = "Add files/folders as RAG objects for the current conversation only"
show_completion_notification = True
```

Two important properties:

* **Session-scoped** — RAG state lives in a module-level store inside
`rag_utils.py` (the `_SESSION_RAG` dict). It persists across coder switches
(e.g. the child coder that `/rag-question` spawns via `SwitchCoderSignal`)
and is cleared when the cecli process exits.
* **Self-contained** — all tokenizing, chunking and keyword-retrieval logic
is pure stdlib, so the commands work in any cecli environment without
installing anything.

---

## 1. Install

```bash
git clone https://github.com/sovf4717/cecli_custom_commands
# or download the folder and place the .py files anywhere on disk
```

The four command files (`rag_add.py`, `rag_drop.py`, `rag_ls.py`,
`rag_question.py`) plus the shared `rag_utils.py` must all sit in the **same
directory**, because each command loads `rag_utils.py` from its own folder at
runtime.

---

## 2. Configure cecli

Add the directory to your cecli config (`.cecli.conf.yml` in your project, or
`~/.cecli.conf.yml` globally):

```yaml
custom:
  command-paths:
    - "E:/cecli_custom_commands"
```

For a directory, cecli scans every `.py` file for `CustomCommand` classes and
registers them. (You can also list individual files instead of the whole
directory.)

Restart cecli. The new commands now appear in tab completion and `/help`.

---

## 3. Usage

### 3.1 Add context — `/rag-add`

```bash
/rag-add ./src                      # index a whole directory
/rag-add notes.md docs/             # mix files and folders
```

* **No arguments** (`/rag-add` alone) opens cecli's fuzzy finder so you can
select files interactively.
* **Paths** may be absolute or relative to the project root. Directories are
walked recursively (skipping `.git`, `node_modules`, `__pycache__`, etc.).
* **Globs** are supported: `/rag-add "src/**/*.py"`.

### 3.2 Paths with spaces

cecli's argument parser splits on unquoted whitespace, so any path containing a
space **must be wrapped in quotes**, otherwise it gets split into separate
tokens (the most common cause of "wrong file got indexed" bugs).

```bash
/rag-add "C:\Users\me\Obsidian Vault\notes.md"   # correct
/rag-add  C:\Users\me\Obsidian Vault\notes.md    # wrong — becomes two paths
```

If a path with spaces is not quoted, `/rag-add` will warn you with a hint to
add quotes.

### 3.3 Ask a question — `/rag-question`

```bash
/rag-question  how does the auth middleware handle token expiry?
```

The command retrieves the most relevant chunks (by keyword overlap, top-8 by
default) and feeds them to the model together with your question. It works
with both English and Chinese content (the tokenizer handles CJK character +
bigram tokens), so for example:

```bash
/rag-question  我该如何自学
```

### 3.4 List — `/rag-ls`

```bash
/rag-ls
```

Output:

```
RAG files in the current conversation (3 files, 12 chunks):
  E:/project/notes.md
  E:/project/docs/api.md
  E:/project/docs/faq.md
```

### 3.5 Drop — `/rag-drop`

```bash
/rag-drop                # drop everything
/rag-drop notes.md       # drop one specific object
/rag-drop *.md           # drop all markdown objects
```

---

## 4. Configuration knobs (optional)

These live in `rag_utils.py` and `rag_question.py` if you want to tune
behaviour:

* `_CHUNK_CHARS` (default `1500`) — chunk size in characters.
* `top_k` (default `8`) in `rag_context_block` — how many chunks are retrieved
per question.
* `_SKIP_DIRS` — extra directories to ignore when walking folders.
* `_TEXT_EXTS` — which file extensions are eligible for indexing.

---

## 5. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No RAG objects` right after `/rag-add` | You typed a space in the path without quotes — re-run with quotes. |
| Retrieved chunks are irrelevant / wrong language | CJK + Latin tokenizer is used; make sure the question shares vocabulary with the content. |
| Command missing after install | The directory in `command-paths` must contain all 5 `.py` files together; restart cecli. |
| `No module named 'cecli.rag'` (older logs) | Fixed — these commands no longer import any `cecli.rag` module; all logic is in `rag_utils.py`. |
| State lost after `/rag-question` | Fixed — RAG state is module-level now and survives coder switches; only `/rag-drop` or process exit clears it. |

---

## 6. Repository layout

```
cecli_custom_commands/
├── rag_add.py        # /rag-add
├── rag_drop.py       # /rag-drop
├── rag_ls.py         # /rag-ls
├── rag_question.py   # /rag-question
├── rag_utils.py      # shared store + index/retrieval helpers
└── .gitignore
```

---

## License

MIT (or choose what you prefer).