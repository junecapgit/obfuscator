"""Known token strings and regex pattern obfuscation and restoration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable, Sequence

from obfus.mapping import Mapping

_PLACEHOLDER = re.compile(r"(?<!\w)obf_[a-z0-9]+_\d+(?!\w)")
_BRACKET_ALTERNATION = re.compile(r"\[([a-zA-Z0-9_\-]+(?:\|[a-zA-Z0-9_\-]+)+)\]")


def normalize_pattern(pat: str) -> str:
    """Normalize regex pattern syntax, e.g. converting [dev|qa|prod] to (?:dev|qa|prod)."""
    return _BRACKET_ALTERNATION.sub(r"(?:\1)", pat)


def compile_pattern(pat: str, is_literal: bool = False) -> re.Pattern[str]:
    """Compile a pattern or literal string into a regex with word boundaries when appropriate."""
    if not pat:
        return re.compile(r"$^")  # Matches nothing

    if is_literal:
        regex = re.escape(pat)
        left = r"(?<!\w)" if pat[0].isalnum() else ""
        right = r"(?!\w)" if pat[-1].isalnum() else ""
        return re.compile(f"{left}{regex}{right}")

    normalized = normalize_pattern(pat)
    try:
        compiled = re.compile(normalized)
    except re.error:
        # Fallback to literal matching if not a valid regex
        return compile_pattern(pat, is_literal=True)

    # If the user didn't specify start/end anchors or boundary assertions, add boundary checks
    # so e.g. ABC12345 doesn't match inside ABC12345678.
    left = r"(?<!\w)" if normalized[0].isalnum() and not normalized.startswith(("^", r"\b", "(?")) else ""
    right = (
        r"(?!\w)"
        if (normalized[-1].isalnum() or normalized.endswith(("}", r"\d", r"\w")))
        and not normalized.endswith(("$", r"\b"))
        else ""
    )

    if left or right:
        try:
            return re.compile(f"{left}{normalized}{right}")
        except re.error:
            return compiled
    return compiled


def load_patterns_file(path: str | Path) -> list[str]:
    """Load known tokens and patterns from a JSON file (list or object) or text file."""
    path_obj = Path(path)
    try:
        data = path_obj.read_bytes()
    except OSError as exc:
        raise ValueError(f"read patterns file: {exc}") from exc

    raw = None
    # 1. Try standard JSON
    try:
        raw = json.loads(data)
    except ValueError:
        # 2. Try JSON with raw unescaped regex backslashes (e.g. \d)
        try:
            text = data.decode("utf-8", errors="replace")
            fixed_text = re.sub(r'\\([^"\\/bfnrtu])', lambda m: "\\\\" + m.group(1), text)
            raw = json.loads(fixed_text)
        except ValueError:
            pass

    if raw is not None:
        if isinstance(raw, list):
            if not all(isinstance(item, str) for item in raw):
                raise ValueError("parse patterns file: all array elements must be strings")
            return [item for item in raw if item]
        if isinstance(raw, dict):
            patterns: list[str] = []
            for key in ("tokens", "patterns", "knownTokens", "knownPatterns", "known_tokens", "known_patterns"):
                if key in raw and isinstance(raw[key], list):
                    for item in raw[key]:
                        if isinstance(item, str) and item:
                            patterns.append(item)
            return patterns
        raise ValueError("parse patterns file: top-level value must be an array or object")

    # 3. Fallback: line-delimited plain text file
    lines = data.decode("utf-8", errors="replace").splitlines()
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            result.append(stripped)
    return result


def obfuscate_text(
    text: str,
    patterns: Iterable[str],
    mapping: Mapping | None = None,
    counters: dict[str, int] | None = None,
    category: str = "token",
) -> tuple[str, Mapping]:
    """Obfuscate all occurrences of patterns in text using the given or new Mapping."""
    patterns_list = [p for p in patterns if p]
    if not patterns_list or not text:
        return text, (Mapping() if mapping is None else mapping)

    m = Mapping() if mapping is None else mapping
    if counters is None:
        counters = {}

    taken = set(_PLACEHOLDER.findall(text)) | set(m.reverse.keys()) | set(m.forward.keys())

    def placeholder_for(val: str, cat: str) -> str:
        if val in m.forward:
            return m.forward[val]
        idx = counters.get(cat, 0)
        while True:
            idx += 1
            candidate = f"obf_{cat}_{idx}"
            if candidate not in taken:
                break
        counters[cat] = idx
        taken.add(candidate)
        m.forward[val] = candidate
        m.reverse[candidate] = val
        return candidate

    compiled_patterns = [compile_pattern(p) for p in patterns_list]

    raw_matches: list[tuple[int, int, str]] = []
    for cp in compiled_patterns:
        for match in cp.finditer(text):
            matched_str = match.group(0)
            if not matched_str:
                continue
            if _PLACEHOLDER.fullmatch(matched_str) or matched_str in m.reverse:
                continue
            raw_matches.append((match.start(), match.end(), matched_str))

    if not raw_matches:
        return text, m

    # Sort matches: earlier start first, then longer match first
    raw_matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    # Select non-overlapping matches
    selected_matches: list[tuple[int, int, str]] = []
    last_end = 0
    for start, end, matched_str in raw_matches:
        if start >= last_end:
            selected_matches.append((start, end, matched_str))
            last_end = end

    result_pieces: list[str] = []
    cur_idx = 0
    for start, end, matched_str in selected_matches:
        result_pieces.append(text[cur_idx:start])
        placeholder = placeholder_for(matched_str, category)
        result_pieces.append(placeholder)
        cur_idx = end
    result_pieces.append(text[cur_idx:])

    return "".join(result_pieces), m


def restore_text(text: str, m: Mapping) -> str:
    """Restore placeholders in text back to original values using mapping.reverse."""
    if not text or not m or not m.reverse:
        return text
    return _PLACEHOLDER.sub(lambda hit: m.reverse.get(hit.group(0), hit.group(0)), text)


def ai_safe_text(text: str, patterns: Iterable[str], counters: dict[str, int] | None = None) -> str:
    """Irreversibly redact occurrences of patterns in text with REDACTED_TOKEN_N."""
    patterns_list = [p for p in patterns if p]
    if not patterns_list or not text:
        return text

    if counters is None:
        counters = {}

    compiled_patterns = [compile_pattern(p) for p in patterns_list]
    raw_matches: list[tuple[int, int, str]] = []
    for cp in compiled_patterns:
        for match in cp.finditer(text):
            matched_str = match.group(0)
            if matched_str:
                raw_matches.append((match.start(), match.end(), matched_str))

    if not raw_matches:
        return text

    raw_matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected_matches: list[tuple[int, int, str]] = []
    last_end = 0
    for start, end, matched_str in raw_matches:
        if start >= last_end:
            selected_matches.append((start, end, matched_str))
            last_end = end

    token_map: dict[str, str] = {}
    result_pieces: list[str] = []
    cur_idx = 0
    for start, end, matched_str in selected_matches:
        result_pieces.append(text[cur_idx:start])
        if matched_str not in token_map:
            idx = counters.get("redacted_token", 0) + 1
            counters["redacted_token"] = idx
            token_map[matched_str] = f"REDACTED_TOKEN_{idx}"
        result_pieces.append(token_map[matched_str])
        cur_idx = end
    result_pieces.append(text[cur_idx:])

    return "".join(result_pieces)
