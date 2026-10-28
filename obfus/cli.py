"""Command-line entry point: obfuscate, restore and AI-safe modes."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence, TextIO

from obfus import config as config_mod
from obfus import light, mapping as mapping_mod, patterns as patterns_mod, service, storage, transform
from obfus.fileio import read_text, write_text
from obfus.tokenizer import for_file, reconstruct

USAGE = """usage:
  obfus <input-file-or-dir> [-o <safe-path>] [--map <map.json>] [--patterns <pat-or-file>]
  obfus restore <safe-file-or-dir> [-o <output-path>] [--map <map.json>]
  obfus ai <input-file-or-dir> [-o <ai-safe-path>] [--patterns <pat-or-file>]
  obfus light <input-file-or-dir> [-o <safe-path>] [--map <map.json>] [--keys id,name] [--patterns <pat-or-file>]
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

    # Check for explicit --config flag in arguments
    config_override: str | None = None
    i = 0
    while i < len(args):
        if args[i] == "--config":
            if i + 1 >= len(args):
                stderr.write("config load failed: missing value for --config\n")
                return 1
            config_override = args[i + 1]
            break
        elif args[i].startswith("--config="):
            config_override = args[i][len("--config=") :]
            break
        i += 1

    try:
        if config_override:
            cfg = config_mod.load(config_override)
        else:
            cfg = config_mod.load_optional(config_mod.resolve_config_path(Path.cwd()))
    except (OSError, ValueError) as exc:
        stderr.write(f"config load failed: {exc}\n")
        return 1

    if args[0] == "restore":
        action, handler = "restore", lambda: _run_restore(args[1:], cfg)
    elif args[0] == "ai":
        action, handler = "ai mode", lambda: _run_ai(args[1:], cfg)
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
    input_path, output_path, map_path = _parse_cli_args(args, cfg)
    if not input_path and cfg.input_dir:
        input_path = os.path.expanduser(cfg.input_dir)
    if not output_path and cfg.target_dir:
        output_path = os.path.expanduser(cfg.target_dir)

    if not os.path.exists(input_path):
        raise ValueError(f"input path does not exist: {input_path}")

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
    effective_patterns = cfg.all_patterns()
    m = mapping_mod.Mapping()
    counters: dict[str, int] = {}

    if effective_patterns:
        source, m = patterns_mod.obfuscate_text(source, effective_patterns, mapping=m, counters=counters)

    tokenize = for_file(input_path)
    tokens = tokenize(source)

    m = mapping_mod.generate(tokens, current=m)
    write_text(output_path, reconstruct(transform.obfuscate_tokens(tokens, m)))

    if cfg.encryption.enabled:
        storage.save_mapping_encrypted(map_path, m, _password(cfg))
    else:
        storage.save_mapping(map_path, m)


def _run_restore(args: list[str], cfg: config_mod.Config) -> None:
    input_path, output_path, map_path = _parse_cli_args(args, cfg)
    if not input_path and cfg.input_dir:
        input_path = os.path.expanduser(cfg.input_dir)
    if not output_path and cfg.target_dir:
        output_path = os.path.expanduser(cfg.target_dir)

    if not os.path.exists(input_path):
        raise ValueError(f"input path does not exist: {input_path}")

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


def _run_ai(args: list[str], cfg: config_mod.Config) -> None:
    input_path, output_path, _ = _parse_cli_args(args, cfg)
    if not input_path and cfg.input_dir:
        input_path = os.path.expanduser(cfg.input_dir)
    if not output_path and cfg.target_dir:
        output_path = os.path.expanduser(cfg.target_dir)

    if not os.path.exists(input_path):
        raise ValueError(f"input path does not exist: {input_path}")

    if os.path.isdir(input_path):
        out_dir = output_path or "output"
        service.ai_safe_folder(input_path, output_dir=out_dir, cfg=cfg)
        return

    _require(output_path)
    source = _read_input(input_path)
    effective_patterns = cfg.all_patterns()
    if effective_patterns:
        source = patterns_mod.ai_safe_text(source, effective_patterns)
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

    input_path, output_path, map_path = _parse_cli_args(rest, cfg)
    if not input_path and cfg.input_dir:
        input_path = os.path.expanduser(cfg.input_dir)
    if not output_path and cfg.target_dir:
        output_path = os.path.expanduser(cfg.target_dir)

    if not os.path.exists(input_path):
        raise ValueError(f"input path does not exist: {input_path}")

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

    safe, m = light.obfuscate(text, light.parse_keys(keys_spec), patterns=cfg.all_patterns())
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


def _parse_cli_args(args: Sequence[str], cfg: config_mod.Config | None = None) -> tuple[str, str, str]:
    input_path = output_path = map_path = ""
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-o", "--output", "--target-dir", "--target"):
            i += 1
            if i >= len(args):
                flag = "-o" if arg == "-o" else arg
                raise ValueError(f"missing value for {flag}")
            output_path = args[i]
        elif arg.startswith(("-o=", "--output=", "--target-dir=", "--target=")):
            output_path = arg.split("=", 1)[1]
        elif arg == "--map":
            i += 1
            if i >= len(args):
                raise ValueError("missing value for --map")
            map_path = args[i]
        elif arg.startswith("--map="):
            map_path = arg[len("--map=") :]
        elif arg in ("--patterns", "--tokens"):
            i += 1
            if i >= len(args):
                raise ValueError(f"missing value for {arg}")
            val = args[i]
            _add_pattern_arg(val, cfg)
        elif arg.startswith(("--patterns=", "--tokens=")):
            val = arg.split("=", 1)[1]
            _add_pattern_arg(val, cfg)
        elif arg in ("--patterns-file", "--tokens-file"):
            i += 1
            if i >= len(args):
                raise ValueError(f"missing value for {arg}")
            val = args[i]
            if cfg is not None:
                cfg.patterns.extend(patterns_mod.load_patterns_file(val))
        elif arg.startswith(("--patterns-file=", "--tokens-file=")):
            val = arg.split("=", 1)[1]
            if cfg is not None:
                cfg.patterns.extend(patterns_mod.load_patterns_file(val))
        elif arg == "--config":
            i += 1
            if i >= len(args):
                raise ValueError("missing value for --config")
            # Already handled earlier
        elif arg.startswith("--config="):
            pass
        elif arg.startswith("-"):
            raise ValueError(f"unknown flag {arg!r}")
        else:
            if input_path:
                raise ValueError("expected exactly one input file")
            input_path = arg
        i += 1

    if not input_path:
        raise ValueError("expected exactly one input file")
    return (
        os.path.expanduser(input_path),
        os.path.expanduser(output_path) if output_path else "",
        os.path.expanduser(map_path) if map_path else "",
    )


def _add_pattern_arg(val: str, cfg: config_mod.Config | None) -> None:
    if cfg is None:
        return
    if Path(val).is_file():
        cfg.patterns.extend(patterns_mod.load_patterns_file(val))
    else:
        cfg.patterns.append(val)


def _is_help(arg: str) -> bool:
    return arg in ("--help", "-h")


if __name__ == "__main__":
    sys.exit(main())
