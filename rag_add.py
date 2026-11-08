"""Custom command: /rag-add"""

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
    NORM_NAME = "rag-add"
    DESCRIPTION = "Add files/folders as RAG objects for the current conversation only"
    show_completion_notification = True

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Register the selected files/folders as session-scoped RAG objects."""
        _ru = _load_rag_utils()
        build_rag_index = _ru.build_rag_index
        collect_target_files = _ru.collect_target_files

        root = coder.root
        files, index = _get_rag_state(coder)

        selected = await cls._select_targets(io, coder, args)
        if not selected:
            return format_command_result(io, "rag-add", "No files selected for RAG")

        # Resolve paths into the project root.
        resolved = [cls._resolve(root, p) for p in selected]
        resolved = [p for p in resolved if p is not None]
        if not resolved:
            return format_command_result(
                io, "rag-add", "None of the selected paths exist; nothing to add"
            )

        # Expand directories/globs into concrete files.
        concrete_files = collect_target_files(resolved, root)
        if not concrete_files:
            return format_command_result(
                io, "rag-add", "No indexable files found in selection"
            )

        for f in concrete_files:
            files.add(str(f))

        # Rebuild the in-memory keyword index over the newly added files, then
        # merge it into the session index so previously added files remain.
        new_index_data = build_rag_index(concrete_files)
        seen_ids = {e["id"] for e in index["entries"]}
        for entry in new_index_data["entries"]:
            if entry["id"] not in seen_ids:
                index["entries"].append(entry)
                seen_ids.add(entry["id"])
        for fpath in new_index_data["files"]:
            if fpath not in index["files"]:
                index["files"].append(fpath)

        io.tool_output(
            f"Added {len(concrete_files)} files ({len(new_index_data['entries'])} chunks) to the RAG store."
        )
        io.tool_output(
            "This RAG set is valid for the current conversation only. Use /rag-question to ask questions."
        )
        return format_command_result(
            io, "rag-add", f"RAG objects added: {len(concrete_files)} files"
        )

    @classmethod
    async def _select_targets(cls, io, coder, args):
        """No args -> fuzzy finder; otherwise -> parse file/folder tokens."""
        if not args.strip():
            all_files = coder.get_all_relative_files()
            in_chat = coder.get_inchat_relative_files()
            candidates = sorted(set(all_files) - set(in_chat))
            if not candidates:
                io.tool_output("No files available to add to the RAG set.")
                return []
            selected = run_fzf(candidates, multi=True, coder=coder)
            return selected or []

        # Arguments may include sub-directories and globs; parse quoted names.
        return parse_quoted_filenames(args)

    @staticmethod
    def _resolve(root, pattern):
        pattern = os.path.expanduser(pattern)
        p = Path(pattern)
        if not p.is_absolute():
            p = Path(root) / p
        # Keep it even if the literal path does not exist (it may be a glob).
        return p

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """Complete both directory-based and full-file paths (like /add)."""
        directory_completions = get_file_completions(
            coder,
            args=args,
            completion_type="directory",
            include_directories=True,
            filter_in_chat=False,
        )
        all_completions = get_file_completions(
            coder,
            args=args,
            completion_type="all",
            include_directories=True,
            filter_in_chat=False,
        )
        return sorted(set(directory_completions) | set(all_completions))

    @classmethod
    def get_help(cls) -> str:
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /rag-add              # Open the fuzzy finder to pick files/folders\n"
        help_text += "  /rag-add <path> [...] # Register absolute/relative paths or folders\n"
        help_text += "\nRAG objects are stored for the current conversation only (like /add files).\n"
        help_text += "They disappear when the cecli session ends.\n"
        help_text += "Use /rag-question to ask questions against the registered RAG objects.\n"
        return help_text
