"""Custom command: /rag-ls"""

from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import (
    format_command_result,
)


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
    NORM_NAME = "rag-ls"
    DESCRIPTION = "List all RAG objects registered in the current conversation"
    show_completion_notification = False

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """List the files registered in the session RAG store."""
        files, index = _get_rag_state(coder)

        if not files and not index.get("entries"):
            io.tool_output("\nNo RAG objects in the current conversation. Run /rag-add first.")
            return format_command_result(io, "rag-ls", "No RAG objects listed")

        chunk_count = len(index.get("entries", [])) if index else 0
        io.tool_output(f"RAG files in the current conversation ({len(files)} files, {chunk_count} chunks):")
        for f in sorted(files):
            io.tool_output(f"  {f}")

        return format_command_result(io, "rag-ls", f"Listed {len(files)} RAG files")

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