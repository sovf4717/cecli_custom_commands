"""Custom command: /rag-drop"""

import os
import sys
from pathlib import Path
from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import (
    format_command_result,
    parse_quoted_filenames,
)


def _load_rag_utils():
    """Load rag_utils.py from the same directory as this file."""
    dir_name = str(Path(__file__).parent)
    if dir_name not in sys.path:
        sys.path.insert(0, dir_name)
    try:
        import rag_utils as _ru
        return _ru
    except ImportError:
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location("_rag_utils", Path(__file__).parent / "rag_utils.py")
        module = _ilu.module_from_spec(spec)
        spec.loader.exec_module(module)
"""Custom command: /rag-drop"""

import os
import sys
from pathlib import Path
from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import (
    format_command_result,
    parse_quoted_filenames,
)


def _load_rag_utils():
    """Load rag_utils.py from the same directory as this file."""
    dir_name = str(Path(__file__).parent)
    if dir_name not in sys.path:
        sys.path.insert(0, dir_name)
    try:
        import rag_utils as _ru
        return _ru
    except ImportError:
        import importlib.util as _ilu
        spec = _ilu.spec_from_file_location("_rag_utils", Path(__file__).parent / "rag_utils.py")
        module = _ilu.module_from_spec(spec)
        spec.loader.exec_module(module)
        sys.modules["rag_utils"] = module
        return module


class CustomCommand(BaseCommand):
    NORM_NAME = "rag-drop"
    DESCRIPTION = "Remove RAG objects added via /rag-add from the current conversation"
    show_completion_notification = False

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Remove the specified (or all) session-scoped RAG objects."""
        _ru = _load_rag_utils()
        root = coder.root

        # Use the module-level session store so the state survives coder switches.
        file_count, chunk_count, files = _ru.session_rag_list()

        if file_count == 0 and chunk_count == 0:
            io.tool_output("No RAG objects in this conversation. Nothing to drop.")
            return format_command_result(io, "rag-drop", "No RAG objects to drop")

        if not args.strip():
            removed = _ru.session_rag_drop_all()
            io.tool_output(f"Dropped all {removed} RAG files from the current conversation.")
            return format_command_result(io, "rag-drop", f"Dropped all RAG objects ({removed} files)")

        filenames = parse_quoted_filenames(args)
        dropped_count, dropped = _ru.session_rag_drop_matching(filenames, root)

        if not dropped:
            io.tool_output(f"No RAG objects matched: {args.strip()}")
            return format_command_result(io, "rag-drop", "No matching RAG objects")

        io.tool_output(f"Dropped {len(dropped)} RAG files: " + ", ".join(sorted(dropped)))
        return format_command_result(io, "rag-drop", f"Dropped {len(dropped)} RAG objects")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        _ru = _load_rag_utils()
        _, _, files = _ru.session_rag_list()
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
