"""High-level service interface for obfuscating and restoring files and folders."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable, Sequence

from obfus import config as config_mod
from obfus import light
from obfus import mapping as mapping_mod
from obfus import storage
from obfus import transform
from obfus.fileio import read_text, write_text
from obfus.gitignore import GitIgnoreFilter
from obfus.tokenizer import for_file, is_supported_file, reconstruct
from obfus.tokenizer.token import Token


def _resolve_password(cfg: config_mod.Config | None, explicit_password: str | None = None) -> str:
    if explicit_password:
        return explicit_password
    if cfg is None or not cfg.encryption.enabled:
        return ""
    env_name = cfg.encryption.password_env
    password = os.environ.get(env_name, "")
    if not password:
        raise ValueError(f"encryption enabled but password env {env_name!r} is empty")
    return password


def obfuscate_folder(
    input_dir: str | Path,
    output_dir: str | Path | None = None,
    map_path: str | Path | None = None,
    mode: str = "full",
    keys: str | Iterable[str] | None = None,
    cfg: config_mod.Config | None = None,
    password: str | None = None,
    copy_unsupported: bool = True,
) -> tuple[Path, mapping_mod.Mapping]:
    """Obfuscate an entire directory, respecting .gitignore and maintaining structure.

    Args:
        input_dir: Directory containing files to obfuscate.
        output_dir: Destination directory. Defaults to ``./output`` in the current working directory.
        map_path: Path to write the mapping file. Defaults to ``map.json`` (or ``map.enc``) inside output_dir.
        mode: Obfuscation mode - "full" (tokenizer-based) or "light" (attribute/diff/IP-based).
        keys: Attribute suffixes for light mode (e.g. "id,name").
        cfg: Optional obfus configuration.
        password: Password for encrypted mapping (falls back to config env var).
        copy_unsupported: If True, unsupported or binary files are copied as-is into duplicate structure.

    Returns:
        tuple of (resolved output_dir, generated Mapping).
    """
    in_dir = Path(input_dir).resolve()
    if not in_dir.is_dir():
        raise ValueError(f"input directory does not exist or is not a directory: {input_dir}")

    if output_dir is None:
        out_dir = (Path.cwd() / "output").resolve()
    else:
        out_dir = Path(output_dir).resolve()

    out_dir.mkdir(parents=True, exist_ok=True)

    git_filter = GitIgnoreFilter(in_dir)

    files_to_process: list[Path] = []
    for root, dirs, files in os.walk(in_dir):
        dirs_to_remove: list[str] = []
        for d in dirs:
            d_path = Path(root, d).resolve()
            if d == ".git" or d_path == out_dir:
                dirs_to_remove.append(d)
            elif git_filter.is_ignored(d_path, is_dir=True):
                dirs_to_remove.append(d)
        for d in dirs_to_remove:
            dirs.remove(d)

        for f in sorted(files):
            f_path = Path(root, f).resolve()
            if f == ".git":
                continue
            if git_filter.is_ignored(f_path, is_dir=False):
                continue
            files_to_process.append(f_path)

    normalized_mode = mode.lower().strip()

    if normalized_mode == "full":
        tokens_by_file: dict[Path, list[Token]] = {}
        for f_path in files_to_process:
            if is_supported_file(str(f_path)):
                source = read_text(str(f_path))
                tokens = for_file(str(f_path))(source)
                tokens_by_file[f_path] = tokens

        all_tokens = [tok for toks in tokens_by_file.values() for tok in toks]
        m = mapping_mod.generate(all_tokens)

        for f_path in files_to_process:
            rel_path = f_path.relative_to(in_dir)
            dest_path = out_dir / rel_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            if f_path in tokens_by_file:
                safe_tokens = transform.obfuscate_tokens(tokens_by_file[f_path], m)
                write_text(str(dest_path), reconstruct(safe_tokens))
            elif copy_unsupported:
                shutil.copy2(f_path, dest_path)

    elif normalized_mode == "light":
        parsed_keys = light.parse_keys(keys) if isinstance(keys, str) else (tuple(keys) if keys else light.DEFAULT_KEYS)
        m = mapping_mod.Mapping()
        counters: dict[str, int] = {}

        for f_path in files_to_process:
            rel_path = f_path.relative_to(in_dir)
            dest_path = out_dir / rel_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                source = read_text(str(f_path))
                safe, m = light.obfuscate(source, keys=parsed_keys, mapping=m, counters=counters)
                write_text(str(dest_path), safe)
            except (UnicodeDecodeError, ValueError):
                if copy_unsupported:
                    shutil.copy2(f_path, dest_path)
    else:
        raise ValueError(f"unknown mode {mode!r}: expected 'full' or 'light'")

    if map_path is None:
        enc_enabled = cfg.encryption.enabled if cfg else False
        ext = ".enc" if enc_enabled else ".json"
        actual_map_path = out_dir / f"map{ext}"
    else:
        actual_map_path = Path(map_path)

    actual_map_path.parent.mkdir(parents=True, exist_ok=True)
    if cfg and cfg.encryption.enabled:
        storage.save_mapping_encrypted(str(actual_map_path), m, _resolve_password(cfg, password))
    else:
        storage.save_mapping(str(actual_map_path), m)

    return out_dir, m


def restore_folder(
    input_dir: str | Path,
    output_dir: str | Path | None = None,
    map_path: str | Path | None = None,
    mode: str = "full",
    cfg: config_mod.Config | None = None,
    password: str | None = None,
    copy_unsupported: bool = True,
) -> Path:
    """Restore an obfuscated directory back to its original content using a mapping."""
    in_dir = Path(input_dir).resolve()
    if not in_dir.is_dir():
        raise ValueError(f"input directory does not exist or is not a directory: {input_dir}")

    resolved_map_path: Path | None = None
    if map_path is not None:
        resolved_map_path = Path(map_path).resolve()
    else:
        candidate_enc = in_dir / "map.enc"
        candidate_json = in_dir / "map.json"
        if candidate_enc.is_file():
            resolved_map_path = candidate_enc
        elif candidate_json.is_file():
            resolved_map_path = candidate_json
        else:
            raise ValueError("missing required map file for restore")

    if cfg and cfg.encryption.enabled:
        m = storage.load_mapping_encrypted(str(resolved_map_path), _resolve_password(cfg, password))
    else:
        m = storage.load_mapping(str(resolved_map_path))

    if output_dir is None:
        out_dir = (Path.cwd() / "restored").resolve()
    else:
        out_dir = Path(output_dir).resolve()

    out_dir.mkdir(parents=True, exist_ok=True)
    normalized_mode = mode.lower().strip()

    for root, dirs, files in os.walk(in_dir):
        dirs_to_remove: list[str] = []
        for d in dirs:
            d_path = Path(root, d).resolve()
            if d == ".git" or d_path == out_dir:
                dirs_to_remove.append(d)
        for d in dirs_to_remove:
            dirs.remove(d)

        for f in sorted(files):
            f_path = Path(root, f).resolve()
            if f == ".git" or (resolved_map_path and f_path == resolved_map_path):
                continue

            rel_path = f_path.relative_to(in_dir)
            dest_path = out_dir / rel_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            if normalized_mode == "full":
                if is_supported_file(str(f_path)):
                    source = read_text(str(f_path))
                    tok_fn = for_file(str(f_path))
                    restored = transform.restore_source(source, tok_fn, m)
                    write_text(str(dest_path), restored)
                elif copy_unsupported:
                    shutil.copy2(f_path, dest_path)
            elif normalized_mode == "light":
                try:
                    source = read_text(str(f_path))
                    restored = light.restore(source, m)
                    write_text(str(dest_path), restored)
                except (UnicodeDecodeError, ValueError):
                    if copy_unsupported:
                        shutil.copy2(f_path, dest_path)
            else:
                raise ValueError(f"unknown mode {mode!r}: expected 'full' or 'light'")

    return out_dir


def ai_safe_folder(
    input_dir: str | Path,
    output_dir: str | Path | None = None,
    copy_unsupported: bool = True,
) -> Path:
    """Create an AI-safe redacted copy of an entire directory."""
    in_dir = Path(input_dir).resolve()
    if not in_dir.is_dir():
        raise ValueError(f"input directory does not exist or is not a directory: {input_dir}")

    if output_dir is None:
        out_dir = (Path.cwd() / "output").resolve()
    else:
        out_dir = Path(output_dir).resolve()

    out_dir.mkdir(parents=True, exist_ok=True)
    git_filter = GitIgnoreFilter(in_dir)

    for root, dirs, files in os.walk(in_dir):
        dirs_to_remove: list[str] = []
        for d in dirs:
            d_path = Path(root, d).resolve()
            if d == ".git" or d_path == out_dir:
                dirs_to_remove.append(d)
            elif git_filter.is_ignored(d_path, is_dir=True):
                dirs_to_remove.append(d)
        for d in dirs_to_remove:
            dirs.remove(d)

        for f in sorted(files):
            f_path = Path(root, f).resolve()
            if f == ".git":
                continue
            if git_filter.is_ignored(f_path, is_dir=False):
                continue

            rel_path = f_path.relative_to(in_dir)
            dest_path = out_dir / rel_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            if is_supported_file(str(f_path)):
                source = read_text(str(f_path))
                tok_fn = for_file(str(f_path))
                tokens = tok_fn(source)
                safe = reconstruct(transform.ai_safe_tokens(tokens))
                write_text(str(dest_path), safe)
            elif copy_unsupported:
                shutil.copy2(f_path, dest_path)

    return out_dir


class ObfuscatorService:
    """Configurable service instance for obfuscation operations."""

    def __init__(self, cfg: config_mod.Config | None = None, password: str | None = None) -> None:
        self.cfg = cfg
        self.password = password

    def obfuscate_folder(
        self,
        input_dir: str | Path,
        output_dir: str | Path | None = None,
        map_path: str | Path | None = None,
        mode: str = "full",
        keys: str | Iterable[str] | None = None,
        copy_unsupported: bool = True,
    ) -> tuple[Path, mapping_mod.Mapping]:
        return obfuscate_folder(
            input_dir,
            output_dir=output_dir,
            map_path=map_path,
            mode=mode,
            keys=keys,
            cfg=self.cfg,
            password=self.password,
            copy_unsupported=copy_unsupported,
        )

    def restore_folder(
        self,
        input_dir: str | Path,
        output_dir: str | Path | None = None,
        map_path: str | Path | None = None,
        mode: str = "full",
        copy_unsupported: bool = True,
    ) -> Path:
        return restore_folder(
            input_dir,
            output_dir=output_dir,
            map_path=map_path,
            mode=mode,
            cfg=self.cfg,
            password=self.password,
            copy_unsupported=copy_unsupported,
        )

    def ai_safe_folder(
        self,
        input_dir: str | Path,
        output_dir: str | Path | None = None,
        copy_unsupported: bool = True,
    ) -> Path:
        return ai_safe_folder(input_dir, output_dir=output_dir, copy_unsupported=copy_unsupported)
