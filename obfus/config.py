"""Loading and validation of ``.obfusconfig.json`` and patterns configuration files."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from obfus.patterns import load_patterns_file

CONFIG_FILENAME = ".obfusconfig.json"
DEFAULT_PATTERNS_FILENAMES = ("tokens.json", ".obfustokens.json", "patterns.json", ".obfuspatterns.json")


@dataclass
class EncryptionConfig:
    enabled: bool = False
    password_env: str = "OBFUS_PASSWORD"


@dataclass
class Config:
    encryption: EncryptionConfig = field(default_factory=EncryptionConfig)
    target_dir: str | None = None
    input_dir: str | None = None
    tokens: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    tokens_file: str | None = None
    patterns_file: str | None = None
    config_path: str | None = None

    def all_patterns(self) -> list[str]:
        """Return combined unique list of all configured tokens and patterns."""
        seen: set[str] = set()
        result: list[str] = []
        for p in (*self.tokens, *self.patterns):
            if p and p not in seen:
                seen.add(p)
                result.append(p)
        return result


def default() -> Config:
    return Config()


def load(path: str | Path) -> Config:
    path_obj = Path(path)
    try:
        data = path_obj.read_bytes()
    except OSError as exc:
        raise ValueError(f"read config: {exc}") from exc

    raw = None
    try:
        raw = json.loads(data)
    except ValueError as exc:
        # Fallback for JSON with unescaped backslashes in regexes (e.g. \d)
        try:
            text = data.decode("utf-8", errors="replace")
            fixed_text = re.sub(r'\\([^"\\/bfnrtu])', lambda m: "\\\\" + m.group(1), text)
            raw = json.loads(fixed_text)
        except ValueError:
            raise ValueError(f"parse config: {exc}") from exc

    cfg = default()
    cfg.config_path = str(path_obj.resolve())
    if raw is not None:
        if isinstance(raw, list):
            for item in raw:
                if not isinstance(item, str):
                    raise ValueError("parse config: array elements must be strings")
                cfg.patterns.append(item)
        elif isinstance(raw, dict):
            enc = raw.get("encryption")
            if enc is not None:
                if not isinstance(enc, dict):
                    raise ValueError("parse config: 'encryption' must be an object")
                if enc.get("enabled") is not None:
                    if not isinstance(enc["enabled"], bool):
                        raise ValueError("parse config: 'encryption.enabled' must be a boolean")
                    cfg.encryption.enabled = enc["enabled"]
                if enc.get("passwordEnv") is not None:
                    if not isinstance(enc["passwordEnv"], str):
                        raise ValueError("parse config: 'encryption.passwordEnv' must be a string")
                    cfg.encryption.password_env = enc["passwordEnv"]

            for key in ("targetDir", "target_dir", "outputDir", "output_dir"):
                if key in raw:
                    val = raw[key]
                    if val is not None and not isinstance(val, str):
                        raise ValueError(f"parse config: {key!r} must be a string")
                    cfg.target_dir = val
                    break

            for key in ("inputDir", "input_dir", "sourceDir", "source_dir"):
                if key in raw:
                    val = raw[key]
                    if val is not None and not isinstance(val, str):
                        raise ValueError(f"parse config: {key!r} must be a string")
                    cfg.input_dir = val
                    break

            for key in ("tokens", "knownTokens", "known_tokens"):
                if key in raw:
                    val = raw[key]
                    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                        raise ValueError(f"parse config: {key!r} must be a list of strings")
                    cfg.tokens.extend(val)
                    break

            for key in ("patterns", "knownPatterns", "known_patterns"):
                if key in raw:
                    val = raw[key]
                    if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                        raise ValueError(f"parse config: {key!r} must be a list of strings")
                    cfg.patterns.extend(val)
                    break

            for key in ("tokensFile", "tokens_file"):
                if key in raw:
                    val = raw[key]
                    if val is not None and not isinstance(val, str):
                        raise ValueError(f"parse config: {key!r} must be a string")
                    cfg.tokens_file = val
                    break

            for key in ("patternsFile", "patterns_file"):
                if key in raw:
                    val = raw[key]
                    if val is not None and not isinstance(val, str):
                        raise ValueError(f"parse config: {key!r} must be a string")
                    cfg.patterns_file = val
                    break

            base_dir = path_obj.parent
            if cfg.tokens_file:
                tokens_path = base_dir / cfg.tokens_file
                loaded_tokens = load_patterns_file(tokens_path)
                cfg.tokens.extend(loaded_tokens)

            if cfg.patterns_file:
                patterns_path = base_dir / cfg.patterns_file
                loaded_patterns = load_patterns_file(patterns_path)
                cfg.patterns.extend(loaded_patterns)
        else:
            raise ValueError("parse config: top-level value must be an object or array")

    _validate(cfg)
    return cfg


def load_optional(path: str | Path) -> Config:
    path_obj = Path(path)
    if path_obj.exists():
        return load(path_obj)
    # Check default pattern/token files in the same directory if config file is not found
    for filename in DEFAULT_PATTERNS_FILENAMES:
        cand = path_obj.parent / filename
        if cand.is_file():
            try:
                patterns = load_patterns_file(cand)
                cfg = default()
                cfg.patterns.extend(patterns)
                cfg.config_path = str(cand.resolve())
                return cfg
            except Exception:
                pass
    return default()


def resolve_config_path(working_dir: str | Path) -> Path:
    return Path(working_dir) / CONFIG_FILENAME


def _validate(cfg: Config) -> None:
    if not cfg.encryption.password_env:
        raise ValueError("encryption.passwordEnv must not be empty")
    if not isinstance(cfg.tokens, list) or not all(isinstance(t, str) for t in cfg.tokens):
        raise ValueError("tokens must be a list of strings")
    if not isinstance(cfg.patterns, list) or not all(isinstance(p, str) for p in cfg.patterns):
        raise ValueError("patterns must be a list of strings")
