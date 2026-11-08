"""Custom command: /rag-ls"""

from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import (
    format_command_result,
)


def _load_rag_utils():
    """Load rag_utils.py from the same directory as this file."""
    import sys
    from pathlib import Path
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
    NORM_NAME = "rag-ls"
    DESCRIPTION = "List all RAG objects registered in the current conversation"
    show_completion_notification = False

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """List the files registered in the session RAG store."""
        _ru = _load_rag_utils()
        file_count, chunk_count, files = _ru.session_rag_list()

        if file_count == 0 and chunk_count == 0:
            io.tool_output("\nNo RAG objects in the current conversation. Run /rag-add first.")
            return format_command_result(io, "rag-ls", "No RAG objects listed")

        io.tool_output(f"RAG files in the current conversation ({file_count} files, {chunk_count} chunks):")
        for f in files:
            io.tool_output(f"  {f}")

        return format_command_result(io, "rag-ls", f"Listed {file_count} RAG files")

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """No completions for the list command."""
        return []

    @classmethod
    def get_help(cls) -> str:
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /rag-ls   # List all RAG objects registered in this conversation\n"
        return help_text