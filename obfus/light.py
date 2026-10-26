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
import ipaddress
from typing import Iterable

from obfus.mapping import Mapping

DEFAULT_KEYS = ("id", "name")

_QUOTED = re.compile(r'"([^"\n]*)"')
_VALUE = r'(?:"[^"\n]*"|\[[^\]\n]*\])'
_PLACEHOLDER = re.compile(r"(?<!\w)obf_[a-z0-9]+_\d+(?!\w)")
_IPV4 = r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,3})?(?![\w.])"
_IPV6 = r"(?<![0-9a-f:])[0-9a-f:]{2,39}(?:/\d{1,3})?(?![0-9a-f:])"
_IP_LITERAL = re.compile(rf"(?:{_IPV4}|{_IPV6})", re.IGNORECASE)


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


def obfuscate(
    text: str,
    keys: Iterable[str] = DEFAULT_KEYS,
    mapping: Mapping | None = None,
    counters: dict[str, int] | None = None,
) -> tuple[str, Mapping]:
    keys = tuple(keys)
    alternation = "|".join(re.escape(k) + "s?" for k in keys)
    name_key = r'"[^"\n]*name[^"\n]*"|[\w-]*name[\w-]*'
    suffix_key = rf"(?:[\w-]*_)?(?:{alternation})"
    attr = re.compile(
        rf"(?P<key>{name_key}|{suffix_key})(?P<eq>\s*[=:]\s*)"
        rf"(?P<value>{_VALUE}(?:\s*->\s*{_VALUE})?)",
        re.IGNORECASE,
    )

    m = Mapping() if mapping is None else mapping
    if counters is None:
        counters = {}
    # Placeholders already present in the input or mapping must never be reused.
    taken = set(_PLACEHOLDER.findall(text)) | set(m.reverse.keys())

    def placeholder_for(value: str, category: str) -> str:
        if value in m.forward:
            return m.forward[value]
        index = counters.get(category, 0)
        while True:
            index += 1
            candidate = f"obf_{category}_{index}"
            if candidate not in taken:
                break
        counters[category] = index
        taken.add(candidate)
        m.forward[value] = candidate
        m.reverse[candidate] = value
        return candidate

    def replace_quoted(match: re.Match[str], category: str) -> str:
        value = match.group(1)
        # Skip empties and interpolations: they are expressions, not literal values.
        if not value or "${" in value or "%{" in value:
            return match.group(0)
        return f'"{placeholder_for(value, category)}"'

    def replace_attr(match: re.Match[str]) -> str:
        key = match.group("key").strip('"').lower()
        if "name" in key:
            category = "name"
        else:
            category = next(
                (
                    key_suffix
                    for key_suffix in keys
                    if key == key_suffix or key.endswith(f"_{key_suffix}")
                    or key == f"{key_suffix}s" or key.endswith(f"_{key_suffix}s")
                ),
                key,
            )
            if category.endswith("s") and category[:-1] in keys:
                category = category[:-1]
        value = _QUOTED.sub(lambda q: replace_quoted(q, category), match.group("value"))
        return f"{match.group('key')}{match.group('eq')}{value}"

    result = attr.sub(replace_attr, text)

    def replace_ip(match: re.Match[str]) -> str:
        value = match.group(0)
        try:
            if "/" in value:
                ipaddress.ip_network(value, strict=False)
                category = "subnet"
            elif ":" in value:
                ipaddress.ip_address(value)
                category = "ip"
            else:
                address = ipaddress.ip_address(value)
                category = "subnet" if _is_ipv4_netmask(address) else "ip"
        except ValueError:
            return value
        return placeholder_for(value, category)

    return _IP_LITERAL.sub(replace_ip, result), m


def _is_ipv4_netmask(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if not isinstance(address, ipaddress.IPv4Address):
        return False
    try:
        ipaddress.IPv4Network(f"0.0.0.0/{address}")
        return True
    except ValueError:
        return False


def restore(text: str, m: Mapping) -> str:
    return _PLACEHOLDER.sub(lambda hit: m.reverse.get(hit.group(0), hit.group(0)), text)
