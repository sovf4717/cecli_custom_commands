"""Shared RAG utilities for cecli custom commands.

Provides:
- collect_target_files(paths, root): expand directories/globs into concrete files
- build_rag_index(file_paths): build a lightweight keyword index (in-memory)
- rag_context_block(index, question, top_k): retrieve relevant chunks

All functions are pure / have no external dependencies beyond the stdlib.
"""

import fnmatch
import hashlib
import os
import re
from pathlib import Path
from typing import Dict, List, Set

_SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules",
    ".cecli", "venv", ".venv", "dist", "build",
}

_TEXT_EXTS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".rst", ".txt",
    ".json", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".conf",
    ".html", ".css", ".scss", ".sql", ".sh", ".bat", ".ps1",
    ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs",
    ".rb", ".php", ".pl", ".lua", ".swift", ".kt", ".scala",
    ".xml", ".csv", ".tex", ".vue", ".svelte",
}


def collect_target_files(paths, root):
    """Expand a list of paths (files, dirs, globs) into concrete, indexable files."""
    result = []
    seen = set()
    for p in paths:
        p = Path(p)
        if any(c in str(p) for c in "*?["):
            if not p.is_absolute():
                p = Path(root) / p
            try:
                matches = sorted(p.glob("*"))
            except (OSError, ValueError):
                matches = []
            for m in matches:
                if m.is_file() and _should_index(m) and m not in seen:
                    seen.add(m)
                    result.append(m)
            continue
        if p.is_dir():
            for dirpath, dirnames, filenames in os.walk(str(p)):
                dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
                for fn in filenames:
                    fpath = Path(dirpath) / fn
                    if _should_index(fpath) and fpath not in seen:
                        seen.add(fpath)
                        result.append(fpath)
        elif p.is_file():
            if _should_index(p) and p not in seen:
                seen.add(p)
                result.append(p)
    return result


def _should_index(path: Path) -> bool:
    return path.suffix in _TEXT_EXTS or path.suffix == ""


_CHUNK_CHARS = 1500

_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have in is it of on or that the this to was were will would i you he she they we me him her them us my your his her their our its so if then than when which who what where why how all any both each few more most other some such only own same too can could should do does did done been being will shall may might must not no nor".split()
)


def _tokenize(text: str):
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z_0-9]*", text.lower())
    return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


def build_rag_index(file_paths):
    """Read files, chunk them, and return an in-memory keyword index dict."""
    entries = []
    files_list = []
    for fpath in file_paths:
        fpath_str = str(fpath)
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except (OSError, TypeError):
            continue
        if fpath_str not in files_list:
            files_list.append(fpath_str)
        lines = content.splitlines(keepends=True)
        chunk = []
        chunk_len = 0
        start_offset = 0
        offset = 0
        for line in lines:
            line_len = len(line)
            if chunk and chunk_len + line_len > _CHUNK_CHARS:
                _emit(entries, fpath_str, start_offset, "".join(chunk))
                chunk, chunk_len, start_offset = [], 0, offset
            chunk.append(line)
            chunk_len += line_len
            offset += line_len
        if chunk:
            _emit(entries, fpath_str, start_offset, "".join(chunk))
    return {"entries": entries, "files": files_list}


def _emit(entries, fpath_str, start, text):
    text_stripped = text.rstrip()
    if not text_stripped.strip():
        return
    chunk_id = hashlib.sha1(f"{fpath_str}:{start}:{text_stripped}".encode()).hexdigest()[:16]
    entries.append({"id": chunk_id, "file": fpath_str, "start": start, "text": text_stripped})


def rag_context_block(index, question, top_k=8):
    """Score index entries against question by keyword overlap, return top-k chunks."""
    entries = index.get("entries", [])
    if not entries:
        return ""
    q_tokens = set(_tokenize(question))
    if not q_tokens:
        picked = entries[:top_k]
    else:
        scored = []
        for e in entries:
            e_tokens = set(_tokenize(e["text"]))
            overlap = len(q_tokens & e_tokens)
            if overlap:
                scored.append((overlap, e))
        scored.sort(key=lambda x: -x[0])
        picked = [e for _, e in scored[:top_k]]
        if not picked:
            picked = entries[:top_k]
    if not picked:
        return ""
    parts = ["# RAG Context (retrieved chunks)"]
    for i, e in enumerate(picked, 1):
        parts.append(f"\\n## Chunk {i}  --  \\`{e['file']}\\`")
        parts.append(e["text"].strip())
    return "\\n".join(parts)
