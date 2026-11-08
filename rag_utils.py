"""Shared RAG utilities for cecli custom commands.

Provides:
- collect_target_files(paths, root): expand directories/globs into concrete files
- build_rag_index(file_paths): build a lightweight keyword index (in-memory)
- rag_context_block(index, question, top_k): retrieve relevant chunks
- Module-level session store so RAG state survives coder switches (like the
  /rag-question child-coder created by SwitchCoderSignal).

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

    The returned tokens have their surrounding quote characters stripped.
    """
    out = []
    cur = []
    in_q = ""
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

    Accepts a flat list of path strings / Path objects. Strings that contain
    embedded quoted-spaces (from cecli command-arg parsing) are re-split via
    split_args_with_spaces so "C:\\...\\my folder\\notes.md" is treated as one path.
    """
    result = []
    seen = set()
    root = Path(root)
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


# ---------------------------------------------------------------------------
# Module-level session store.
#
# RAG state is now module-scoped rather than attached to the live Coder
# instance, so it survives the SwitchCoderSignal done by /rag-question.
# ---------------------------------------------------------------------------
_SESSION_RAG = {
    "files": set(),       # set of str paths currently in the RAG set
    "entries": [],        # list of chunk dicts {id, file, start, text}
    "files_list": [],     # de-duplicated str file list (parallel to entries' files)
}


def get_session_rag():
    """Return the module-scoped RAG store dict (single shared instance)."""
    return _SESSION_RAG


def session_rag_add(files, new_index_data):
    """Merge a freshly-built index into the session store.

    - files: iterable of Path/str files that were just collected
    - new_index_data: dict returned by build_rag_index({'entries':..., 'files':...})
    Returns (added_file_count, added_chunk_count).
    """
    added_files = 0
    for f in files:
        fstr = str(f)
        if fstr not in _SESSION_RAG["files"]:
            _SESSION_RAG["files"].add(fstr)
            added_files += 1
    seen_ids = {e["id"] for e in _SESSION_RAG["entries"]}
    added_chunks = 0
    for entry in new_index_data["entries"]:
        if entry["id"] not in seen_ids:
            _SESSION_RAG["entries"].append(entry)
            seen_ids.add(entry["id"])
            added_chunks += 1
    for fpath in new_index_data["files"]:
        if fpath not in _SESSION_RAG["files_list"]:
            _SESSION_RAG["files_list"].append(fpath)
    return added_files, added_chunks


def session_rag_drop_all():
    """Remove every RAG object from the session store."""
    removed = len(_SESSION_RAG["files"])
    _SESSION_RAG["files"].clear()
    _SESSION_RAG["entries"] = []
    _SESSION_RAG["files_list"] = []
    return removed


def session_rag_drop_matching(patterns, root):
    """Drop session RAG entries matching the given pattern strings.

    - patterns: list of raw tokens (filenames, globs, or full paths)
    - root: project root used to resolve relative patterns
    Returns (dropped_count, dropped_paths).
    """
    dropped = []
    for word in patterns:
        expanded = os.path.expanduser(word)
        is_glob = any(c in expanded for c in "*?[")
        for fpath in list(_SESSION_RAG["files"]):
            if is_glob:
                if fnmatch.fnmatch(fpath, expanded) or fnmatch.fnmatch(os.path.basename(fpath), expanded):
                    _SESSION_RAG["files"].discard(fpath)
                    dropped.append(fpath)
            else:
                p = Path(expanded)
                if not p.is_absolute():
                    p = Path(root) / p
                if str(p) == fpath or expanded in fpath:
                    _SESSION_RAG["files"].discard(fpath)
                    dropped.append(fpath)
    # Rebuild index entries from the surviving file list so it stays consistent.
    if dropped:
        _SESSION_RAG["entries"] = []
        _SESSION_RAG["files_list"] = []
        remaining = [Path(f) for f in _SESSION_RAG["files"]]
        if remaining:
            new_data = build_rag_index(remaining)
            _SESSION_RAG["entries"] = new_data["entries"]
            _SESSION_RAG["files_list"] = new_data["files"]
    return len(dropped), dropped


def session_rag_list():
    """Return (file_count, chunk_count, files)."""
    return len(_SESSION_RAG["files"]), len(_SESSION_RAG["entries"]), sorted(_SESSION_RAG["files"])


def session_rag_index():
    """Return the index dict shaped like build_rag_index output (for rag_context_block)."""
    return {"entries": _SESSION_RAG["entries"], "files": _SESSION_RAG["files_list"]}


# ---------------------------------------------------------------------------
# Tokenizer + chunking + retrieval.
# ---------------------------------------------------------------------------
_CHUNK_CHARS = 1500

_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have in is it of on or that the this to was were will would i you he she they we me him her them us my your his her their our its so if then than when which who what where why how all any both each few more most other some such only own same too can could should do does did done been being will shall may might must not no nor".split()
)

_CJK_STOPWORDS = frozenset("\u7684 \u4e86 \u5728 \u662f \u6211 \u6709 \u548c \u5c31 \u4e5f \u90fd \u800c \u53ca \u4ee5 \u4e8e \u8fd9 \u90a3 \u4f60 \u4ed6 \u5979 \u5b83 \u5417 \u5462 \u5427 \u554a \u54e6 \u55ef \u4e0e \u5e76 \u6216 \u5bf9 \u4ece \u5411 \u88ab \u628a \u7ed9 \u8ba9 \u4e3a \u6240 \u4e4b \u5176 \u6b64 \u5f7c".split())


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
            content = Path(fpath).read_text(encoding="utf-8", errors="replace")
        except (OSError, TypeError, FileNotFoundError):
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
