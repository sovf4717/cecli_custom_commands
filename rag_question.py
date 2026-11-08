"""Custom command: /rag-question"""

import os
import sys
from pathlib import Path
from typing import List

from cecli.commands.utils.base_command import BaseCommand
from cecli.commands.utils.helpers import (
    format_command_result,
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
    NORM_NAME = "rag-question"
    DESCRIPTION = "Ask a question about the RAG objects added via /rag-add"
    show_completion_notification = False

    @classmethod
    async def execute(cls, io, coder, args, **kwargs):
        """Retrieve from the session RAG store and answer, like /help."""
        _ru = _load_rag_utils()
        rag_context_block = _ru.rag_context_block
        _ru = _load_rag_utils()
        rag_context_block = _ru.rag_context_block

        question = (args or "").strip()
        if not question:
            io.tool_output("Usage: /rag-question <your question>")
            return format_command_result(io, "rag-question", "Missing question")

        # Use the module-level session store so RAG state is the same as the one
        # /rag-add wrote into, even after the coder switch caused by
        # SwitchCoderSignal below.
        index = _ru.session_rag_index()
        if not index.get("entries"):
            io.tool_output(
                "No RAG objects in this conversation yet. "
                "Run /rag-add first to register files/folders."
            )
            return format_command_result(
                io, "rag-question", "No RAG objects available"
            )

        import traceback
        from uuid import uuid4 as generate_unique_id

        from cecli.coders.base_coder import Coder
        from cecli.commands import SwitchCoderSignal

        has_args = bool(getattr(coder, "args", None))

        try:
            # Use the editor_model from the main_model if it exists, otherwise use the main_model itself
            editor_model = coder.main_model.editor_model or coder.main_model

            original_coder = coder

            create_kwargs = dict()
            create_kwargs["io"] = io
            create_kwargs["uuid"] = str(generate_unique_id())
            create_kwargs["from_coder"] = coder
            create_kwargs["edit_format"] = "help"
            create_kwargs["summarize_from_coder"] = False
            create_kwargs["map_tokens"] = 0
            create_kwargs["map_mul_no_files"] = 1
            create_kwargs["main_model"] = editor_model
            create_kwargs["args"] = coder.args
            create_kwargs["suggest_shell_commands"] = False
            create_kwargs["cache_prompts"] = False
            create_kwargs["num_cache_warming_pings"] = 0

            rag_coder = await Coder.create(**create_kwargs)
            context = rag_context_block(index, question)
            if context.strip():
                user_msg = context
            else:
                user_msg = "# RAG Context (retrieved chunks)\n\n# No RAG context was retrieved.\n"
            user_msg += f"\n\n# Question: {question}\n"
            user_msg += (
                "\nAnswer the above question using only the RAG context provided above.\n"
                "If the context is insufficient, say so and what additional information you need.\n"
            )
            user_msg += "\n# Announcement lines from when this session of cecli was launched:\n\n"
            user_msg += "\n".join(coder.get_announcements() if has_args else []) + "\n"

            await rag_coder.run(user_msg, preproc=False)
        except Exception as err:
            io.tool_error(f"RAG question failed to initialize: {err}")
            io.tool_error(traceback.format_exc())
            return format_command_result(
                io, "rag-question", f"RAG question failed to initialize: {err}"
            )

        if coder.repo_map:
            map_tokens = coder.repo_map.max_map_tokens
            map_mul_no_files = coder.repo_map.map_mul_no_files
        else:
            map_tokens = 0
            map_mul_no_files = 1

        raise SwitchCoderSignal(
            edit_format=coder.edit_format,
            summarize_from_coder=False,
            from_coder=original_coder,
            map_tokens=map_tokens,
            map_mul_no_files=map_mul_no_files,
            show_announcements=False,
        )

    @classmethod
    def get_completions(cls, io, coder, args) -> List[str]:
        """No completions for the free-form question text."""
        return []

    @classmethod
    def get_help(cls) -> str:
        help_text = super().get_help()
        help_text += "\nUsage:\n"
        help_text += "  /rag-question <your question>\n"
        help_text += "\nRetrieves the most relevant chunks from the RAG objects added via /rag-add\n"
        help_text += "in this conversation, and answers the question the way /help answers\n"
        help_text += "questions about cecli docs.\n"
        return help_text
