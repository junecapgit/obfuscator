"""Command-line entry point: obfuscate, restore and AI-safe modes."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence, TextIO

from obfus import config as config_mod
from obfus import mapping as mapping_mod
from obfus import light, service, storage, transform
from obfus.fileio import read_text, write_text
from obfus.tokenizer import for_file, reconstruct

USAGE = """usage:
  obfus <input-file-or-dir> [-o <safe-path>] [--map <map.json>]
  obfus restore <safe-file-or-dir> [-o <output-path>] [--map <map.json>]
  obfus ai <input-file-or-dir> [-o <ai-safe-path>]
  obfus light <input-file-or-dir> [-o <safe-path>] [--map <map.json>] [--keys id,name]
  obfus light restore <safe-file-or-dir> [-o <output-path>] [--map <map.json>]
"""


def main(argv: Sequence[str] | None = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv), sys.stdout, sys.stderr)


def run(args: list[str], stdout: TextIO, stderr: TextIO) -> int:
    if not args:
        stderr.write(USAGE)
        return 1
    if _is_help(args[0]) or args[0] == "help":
        stdout.write(USAGE)
        return 0
    if args[0] in ("restore", "ai", "light") and len(args) > 1 and _is_help(args[1]):
        stdout.write(USAGE)
        return 0

    try:
        cfg = config_mod.load_optional(config_mod.resolve_config_path(Path.cwd()))
    except (OSError, ValueError) as exc:
        stderr.write(f"config load failed: {exc}\n")
        return 1

    if args[0] == "restore":
        action, handler = "restore", lambda: _run_restore(args[1:], cfg)
    elif args[0] == "ai":
        action, handler = "ai mode", lambda: _run_ai(args[1:])
    elif args[0] == "light":
        action, handler = "light mode", lambda: _run_light(args[1:], cfg)
    else:
        action, handler = "obfuscate", lambda: _run_obfuscate(args, cfg)

    try:
        handler()
    except (OSError, ValueError) as exc:
        stderr.write(f"{action} failed: {exc}\n")
        return 1
    return 0


def _run_obfuscate(args: list[str], cfg: config_mod.Config) -> None:
    input_path, output_path, map_path = _parse_cli_args(args)
    if os.path.isdir(input_path):
        out_dir = output_path or "output"
        if not map_path:
            ext = ".enc" if cfg.encryption.enabled else ".json"
            map_path = str(Path(out_dir) / f"map{ext}")
        service.obfuscate_folder(
            input_path,
            output_dir=out_dir,
            map_path=map_path,
            mode="full",
            cfg=cfg,
        )
        return

    _require(output_path, map_path)
    source = _read_input(input_path)
    tokenize = for_file(input_path)
    tokens = tokenize(source)

    m = mapping_mod.generate(tokens)
    write_text(output_path, reconstruct(transform.obfuscate_tokens(tokens, m)))

    if cfg.encryption.enabled:
        storage.save_mapping_encrypted(map_path, m, _password(cfg))
    else:
        storage.save_mapping(map_path, m)


def _run_restore(args: list[str], cfg: config_mod.Config) -> None:
    input_path, output_path, map_path = _parse_cli_args(args)
    if os.path.isdir(input_path):
        out_dir = output_path or "restored"
        service.restore_folder(
            input_path,
            output_dir=out_dir,
            map_path=map_path or None,
            mode="full",
            cfg=cfg,
        )
        return

    _require(output_path, map_path)
    source = _read_input(input_path)
    if cfg.encryption.enabled:
        m = storage.load_mapping_encrypted(map_path, _password(cfg))
    else:
        m = storage.load_mapping(map_path)

    tokenize = for_file(input_path)
    write_text(output_path, transform.restore_source(source, tokenize, m))


def _run_ai(args: list[str]) -> None:
    input_path, output_path, _ = _parse_cli_args(args)
    if os.path.isdir(input_path):
        out_dir = output_path or "output"
        service.ai_safe_folder(input_path, output_dir=out_dir)
        return

    _require(output_path)
    source = _read_input(input_path)
    tokens = for_file(input_path)(source)
    write_text(output_path, reconstruct(transform.ai_safe_tokens(tokens)))


def _run_light(args: list[str], cfg: config_mod.Config) -> None:
    restoring = bool(args) and args[0] == "restore"
    if restoring:
        args = args[1:]

    keys_spec: str | None = None
    rest: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--keys":
            i += 1
            if i >= len(args):
                raise ValueError("missing value for --keys")
            keys_spec = args[i]
        elif args[i].startswith("--keys="):
            keys_spec = args[i][len("--keys=") :]
        else:
            rest.append(args[i])
        i += 1

    input_path, output_path, map_path = _parse_cli_args(rest)
    if os.path.isdir(input_path):
        if restoring:
            out_dir = output_path or "restored"
            service.restore_folder(
                input_path,
                output_dir=out_dir,
                map_path=map_path or None,
                mode="light",
                cfg=cfg,
            )
        else:
            out_dir = output_path or "output"
            if not map_path:
                ext = ".enc" if cfg.encryption.enabled else ".json"
                map_path = str(Path(out_dir) / f"map{ext}")
            service.obfuscate_folder(
                input_path,
                output_dir=out_dir,
                map_path=map_path,
                mode="light",
                keys=keys_spec,
                cfg=cfg,
            )
        return

    _require(output_path, map_path)
    text = _read_input(input_path)

    if restoring:
        if cfg.encryption.enabled:
            m = storage.load_mapping_encrypted(map_path, _password(cfg))
        else:
            m = storage.load_mapping(map_path)
        write_text(output_path, light.restore(text, m))
        return

    safe, m = light.obfuscate(text, light.parse_keys(keys_spec))
    write_text(output_path, safe)
    if cfg.encryption.enabled:
        storage.save_mapping_encrypted(map_path, m, _password(cfg))
    else:
        storage.save_mapping(map_path, m)


def _require(output_path: str, map_path: str | None = None) -> None:
    if not output_path:
        raise ValueError("missing required -o output file")
    if map_path is not None and not map_path:
        raise ValueError("missing required --map file")


def _read_input(path: str) -> str:
    try:
        return read_text(path)
    except OSError as exc:
        raise ValueError(f"read input: {exc}") from exc


def _password(cfg: config_mod.Config) -> str:
    return service._resolve_password(cfg)


def _parse_cli_args(args: Sequence[str]) -> tuple[str, str, str]:
    input_path = output_path = map_path = ""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-o":
            i += 1
            if i >= len(args):
                raise ValueError("missing value for -o")
            output_path = args[i]
        elif arg == "--map":
            i += 1
            if i >= len(args):
                raise ValueError("missing value for --map")
            map_path = args[i]
        elif arg.startswith("--map="):
            map_path = arg[len("--map=") :]
        elif arg.startswith("-"):
            raise ValueError(f"unknown flag {arg!r}")
        else:
            if input_path:
                raise ValueError("expected exactly one input file")
            input_path = arg
        i += 1

    if not input_path:
        raise ValueError("expected exactly one input file")
    return input_path, output_path, map_path


def _is_help(arg: str) -> bool:
    return arg in ("--help", "-h")


if __name__ == "__main__":
    sys.exit(main())
