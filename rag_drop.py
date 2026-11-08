"""Custom command: /rag-drop"""

import importlib.util as _ilu
import os
from pathlib import Path
from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import (
    format_command_result,
    get_file_completions,
    parse_quoted_filenames,
)
from cecli.utils import run_fzf


def _load_rag_utils():
    """Load rag_utils.py from the same directory as this file."""
    import sys
    from pathlib import Path as _Path
    dir_name = _Path(__file__).parent
    if str(dir_name) not in sys.path:
        sys.path.insert(0, str(dir_name))
    import rag_utils as _ru
    return _ru


def _get_rag_state(coder):
    """Return (files, index) for the coder's session-scoped RAG store."""
    files = getattr(coder, "rag_files", None)
    if files is None:
        files = set()
        coder.rag_files = files
    index = getattr(coder, "rag_index", None)
    if index is None:
        index = {"entries": [], "files": []}
        coder.rag_index = index
    return files, index


class CustomCommand(BaseCommand):
    NORM_NAME = "rag-drop"
    DESCRIPTION = "Remove RAG objects added via /rag-add from the current conversation"
    show_completion_notification = False

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Remove the specified (or all) session-scoped RAG objects."""
        files, index = _get_rag_state(coder)

        if not files and not index.get("entries"):
            io.tool_output("No RAG objects in this conversation. Nothing to drop.")
            return format_command_result(io, "rag-drop", "No RAG objects to drop", error=None)

        if not args.strip():
            removed = len(files)
            files.clear()
            index["entries"] = []
            index["files"] = []
            io.tool_output(f"Dropped all {removed} RAG files from the current conversation.")
            return format_command_result(io, "rag-drop", f"Dropped all RAG objects ({removed} files)")

        import fnmatch

        filenames = parse_quoted_filenames(args)
        dropped = []
        for word in filenames:
            expanded_word = os.path.expanduser(word)
            is_glob = any(c in expanded_word for c in "*?[")
            for fpath in list(files):
                if is_glob:
                    if fnmatch.fnmatch(fpath, expanded_word) or fnmatch.fnmatch(os.path.basename(fpath), expanded_word):
                        files.remove(fpath)
                        dropped.append(fpath)
                else:
                    abs_path = cls._resolve(coder.root, expanded_word)
                    if str(abs_path) == fpath or expanded_word in fpath:
                        files.remove(fpath)
                        dropped.append(fpath)

        if not dropped:
            io.tool_output(f"No RAG objects matched: {args.strip()}")
            return format_command_result(io, "rag-drop", "No matching RAG objects", error=None)

        _ru = _load_rag_utils()
        build_rag_index = _ru.build_rag_index
        collect_target_files = _ru.collect_target_files
        index_data = build_rag_index(collect_target_files(list(files), coder.root))
        index["entries"] = index_data["entries"]
        index["files"] = index_data["files"]

        io.tool_output(f"Dropped {len(dropped)} RAG files: " + ", ".join(sorted(dropped)))
        return format_command_result(io, "rag-drop", f"Dropped {len(dropped)} RAG objects")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        files = getattr(coder, "rag_files", None)
        if not files:
            return []
        return sorted(cls._quote_fname(os.path.basename(f)) for f in files)

    @staticmethod
    def _quote_fname(fname):
        if " " in fname and '"' not in fname:
            return f'"{fname}"'
        return fname

    @classmethod
    def get_help(cls) -> str:
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /rag-drop              # Drop all RAG objects from this conversation\n"
        help_text += "  /rag-drop <file> [...] # Drop specific RAG objects\n"
        help_text += "\nExamples:\n"
        help_text += "  /rag-drop              # Remove all RAG objects\n"
        help_text += "  /rag-drop main.py      # Remove main.py from the RAG set\n"
        help_text += "  /rag-drop *.md         # Remove all markdown RAG objects\n"
        return help_text
