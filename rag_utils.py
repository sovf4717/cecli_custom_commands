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
from typing import List

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


def _quote_path_token(p):
    """Quote a path string for shell-ish argument parsing (keeps spaces intact)."""
    p = str(p)
    if " " in p and '"' not in p:
        return f'"{p}"'
    return p


def split_args_with_spaces(args):
    """Split command arguments on unquoted whitespace, preserving quoted spans.

    This is a helper so command files can parse things like:
    /rag-add "C:\\Users\\me\\my folder\\notes.md"  extra.txt
    without breaking on spaces. The returned tokens keep their surrounding
    quote characters stripped.
    """
    out = []
    cur: List[str] = []
    in_q: str = ""
    for ch in args:
        if ch in ('"', "'"):
            if not in_q:
                in_q = ch
            elif in_q == ch:
                in_q = ""
        elif ch.isspace() and not in_q:
            if cur:
                out.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        out.append("".join(cur))
    return out


def collect_target_files(paths, root):
    """Expand a list of paths (files, dirs, globs) into concrete, indexable files.

    Accepts either:
    - a flat list of path strings / Path objects
    - strings where spaces are wrapped in quotes (we split them with
      split_args_with_spaces before resolving).
    """
    result = []
    seen = set()
    root = Path(root)
    # Accept plain text where quoted paths were embedded; re-split if needed.
    flat: List[str] = []
    for p in paths:
        p_str = str(p)
        if any(c in p_str for c in ('"', "'")) and any(c in p_str for c in " \t"):
            flat.extend(split_args_with_spaces(p_str))
        else:
            flat.append(p_str)

    for raw in flat:
        p = Path(os.path.expanduser(raw))
        if any(c in str(p) for c in "*?["):
            if not p.is_absolute():
                p = root / p
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

_CJK_STOPWORDS = frozenset("的 了 在 是 我 有 和 就 也 都 而 及 以 于 这 那 你 他 她 它 吗 呢 吧 啊 哦 嗯 与 并 或 对 从 向 被 把 给 让 为 所 之 其 此 彼".split())


def _tokenize(text: str):
    """Extract tokens from mixed CJK + Latin text.

    - Latin: word tokens [a-zA-Z_][a-zA-Z_0-9]* (lowercased, stopwords filtered).
    - CJK: character + bigram tokens of CJK runs (light segmentation, no
      external dependencies).
    """
    tokens = []
    latin = re.findall(r"[a-zA-Z_][a-zA-Z_0-9]*", text.lower())
    for t in latin:
        if t not in _STOPWORDS and len(t) > 1:
            tokens.append(t)
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        run = run.strip()
        if not run:
            continue
        for ch in run:
            if ch not in _CJK_STOPWORDS:
                tokens.append(ch)
        for i in range(len(run) - 1):
            bigram = run[i:i + 2]
            if bigram not in _CJK_STOPWORDS:
                tokens.append(bigram)
    return tokens


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
    """Score index entries against the question; return the top-k chunks as a
    real, newlined Markdown-ish block the model can read."""
    entries = index.get("entries", [])
    if not entries:
        return ""
    q_tokens = set(_tokenize(question))
    scored = []
    for e in entries:
        e_tokens = set(_tokenize(e["text"]))
        overlap = len(q_tokens & e_tokens)
        if overlap:
            scored.append((overlap, e))
    scored.sort(key=lambda x: -x[0])
    picked = [e for _, e in scored[:top_k]]
    # Pad with unselected head entries so the model has surrounding context
    # even when the question barely overlaps the chunks.
    if len(picked) < top_k:
        seen_ids = {e["id"] for e in picked}
        for e in entries:
            if e["id"] in seen_ids:
                continue
            picked.append(e)
            seen_ids.add(e["id"])
            if len(picked) >= top_k:
                break
    if not picked:
        return ""
    parts = ["# RAG Context (retrieved chunks)"]
    for i, e in enumerate(picked, 1):
        parts.append("")
        parts.append(f"## Chunk {i}  --  `{e['file']}`")
        parts.append(e["text"].strip())
    return "\n".join(parts)
