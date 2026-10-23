"""Light mode: obfuscate only the values of selected Terraform attributes.

Works on plain text line by line, so it handles ``.tf`` files, ``terraform plan``
output and unified diffs (``+``/``-``/``~`` prefixes, ``"old" -> "new"`` changes).
Only quoted values of attributes whose key is, or ends in ``_<suffix>`` (default
suffixes: ``id``, ``name``, plus plurals), are replaced::

    vpc_id = "vpc-0abc"        ->  vpc_id = "obf_id_1"
    + server_name = "web-dev"  ->  + server_name = "obf_name_1"

Restore is a plain placeholder lookup, so it works on any text file type.
"""

from __future__ import annotations

import re
from typing import Iterable

from obfus.mapping import Mapping

DEFAULT_KEYS = ("id", "name")

_QUOTED = re.compile(r'"([^"\n]*)"')
_VALUE = r'(?:"[^"\n]*"|\[[^\]\n]*\])'
_PLACEHOLDER = re.compile(r"(?<!\w)obf_[a-z0-9]+_\d+(?!\w)")


def parse_keys(spec: str | None) -> tuple[str, ...]:
    if not spec:
        return DEFAULT_KEYS
    keys = tuple(k.strip().lower() for k in spec.split(",") if k.strip())
    if not keys:
        raise ValueError("--keys must list at least one attribute suffix")
    for key in keys:
        if not re.fullmatch(r"[a-z0-9]{1,16}", key):
            raise ValueError(f"invalid key suffix {key!r}: use short lowercase alphanumerics")
    return keys


def obfuscate(text: str, keys: Iterable[str] = DEFAULT_KEYS) -> tuple[str, Mapping]:
    keys = tuple(keys)
    alternation = "|".join(re.escape(k) + "s?" for k in keys)
    attr = re.compile(
        rf"(?P<key>\b(?:[\w-]*_)?(?P<suffix>{alternation}))(?P<eq>\s*=\s*)"
        rf"(?P<value>{_VALUE}(?:\s*->\s*{_VALUE})?)",
        re.IGNORECASE,
    )

    m = Mapping()
    counters: dict[str, int] = {}
    # Placeholders already present in the input must never be reused.
    taken = set(_PLACEHOLDER.findall(text))

    def placeholder_for(value: str, suffix: str) -> str:
        if value in m.forward:
            return m.forward[value]
        category = suffix.lower()
        if category.endswith("s") and category[:-1] in keys:
            category = category[:-1]
        index = counters.get(category, 0)
        while True:
            index += 1
            candidate = f"obf_{category}_{index}"
            if candidate not in taken:
                break
        counters[category] = index
        m.forward[value] = candidate
        m.reverse[candidate] = value
        return candidate

    def replace_quoted(match: re.Match[str], suffix: str) -> str:
        value = match.group(1)
        # Skip empties and interpolations: they are expressions, not literal values.
        if not value or "${" in value or "%{" in value:
            return match.group(0)
        return f'"{placeholder_for(value, suffix)}"'

    def replace_attr(match: re.Match[str]) -> str:
        suffix = match.group("suffix")
        value = _QUOTED.sub(lambda q: replace_quoted(q, suffix), match.group("value"))
        return f"{match.group('key')}{match.group('eq')}{value}"

    return attr.sub(replace_attr, text), m


def restore(text: str, m: Mapping) -> str:
    return _PLACEHOLDER.sub(lambda hit: m.reverse.get(hit.group(0), hit.group(0)), text)
