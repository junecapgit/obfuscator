"""Command-line entry point: obfuscate, restore and AI-safe modes."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Sequence, TextIO

from obfus import config as config_mod
from obfus import light, mapping as mapping_mod, patterns as patterns_mod, service, storage, transform
from obfus.fileio import read_text, write_text
from obfus.tokenizer import for_file, reconstruct

USAGE = """usage:
  obfus <input-file-or-dir> [-o <safe-path>] [--map <map.json>] [--patterns <pat-or-file>] [--config <file>] [-v|--verbose]
  obfus restore <safe-file-or-dir> [-o <output-path>] [--map <map.json>] [--config <file>] [-v|--verbose]
  obfus ai <input-file-or-dir> [-o <ai-safe-path>] [--patterns <pat-or-file>] [--config <file>] [-v|--verbose]
  obfus light <input-file-or-dir> [-o <safe-path>] [--map <map.json>] [--keys id,name] [--patterns <pat-or-file>] [--config <file>] [-v|--verbose]
  obfus light restore <safe-file-or-dir> [-o <output-path>] [--map <map.json>] [--config <file>] [-v|--verbose]
"""


def main(argv: Sequence[str] | None = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv), sys.stdout, sys.stderr)


def run(args: list[str], stdout: TextIO, stderr: TextIO) -> int:
    verbose = False
    filtered_args: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("-v", "--verbose"):
            verbose = True
            i += 1
            continue
        filtered_args.append(arg)
        if (
            arg
            in (
                "-o",
                "--output",
                "--target-dir",
                "--target",
                "--map",
                "--patterns",
                "--tokens",
                "--patterns-file",
                "--tokens-file",
                "--config",
                "--keys",
            )
            and i + 1 < len(args)
        ):
            i += 1
            filtered_args.append(args[i])
        i += 1

    if not filtered_args:
        stderr.write(USAGE)
        return 1
    if _is_help(filtered_args[0]) or filtered_args[0] == "help":
        stdout.write(USAGE)
        return 0
    if filtered_args[0] in ("restore", "ai", "light") and len(filtered_args) > 1 and _is_help(filtered_args[1]):
        stdout.write(USAGE)
        return 0

    # Check for explicit --config flag in arguments
    config_override: str | None = None
    i = 0
    while i < len(filtered_args):
        if filtered_args[i] == "--config":
            if i + 1 >= len(filtered_args):
                stderr.write("config load failed: missing value for --config\n")
                return 1
            config_override = filtered_args[i + 1]
            break
        elif filtered_args[i].startswith("--config="):
            config_override = filtered_args[i][len("--config=") :]
            break
        i += 1

    try:
        if config_override:
            cfg = config_mod.load(config_override)
        else:
            cfg = config_mod.load_optional(config_mod.resolve_config_path(Path.cwd()))
            if cfg.config_path is None:
                # Check if any argument is a directory containing .obfusconfig.json
                for a in filtered_args:
                    if not a.startswith("-") and a not in ("restore", "ai", "light", "help"):
                        candidate_dir = Path(os.path.expanduser(a))
                        if candidate_dir.is_dir():
                            cand_cfg = candidate_dir / config_mod.CONFIG_FILENAME
                            if cand_cfg.is_file():
                                try:
                                    cfg = config_mod.load(cand_cfg)
                                    break
                                except Exception:
                                    pass
    except (OSError, ValueError) as exc:
        stderr.write(f"config load failed: {exc}\n")
        return 1

    if verbose:
        _display_loaded_config(cfg, stdout)

    if filtered_args[0] == "restore":
        action, handler = "restore", lambda: _run_restore(filtered_args[1:], cfg, verbose, stdout)
    elif filtered_args[0] == "ai":
        action, handler = "ai mode", lambda: _run_ai(filtered_args[1:], cfg, verbose, stdout)
    elif filtered_args[0] == "light":
        action, handler = "light mode", lambda: _run_light(filtered_args[1:], cfg, verbose, stdout)
    else:
        action, handler = "obfuscate", lambda: _run_obfuscate(filtered_args, cfg, verbose, stdout)

    try:
        handler()
    except (OSError, ValueError) as exc:
        stderr.write(f"{action} failed: {exc}\n")
        return 1
    return 0


def _make_status_reporter() -> tuple[list[str], list[str], Callable[[Path, str], None]]:
    converted: list[str] = []
    copied: list[str] = []

    def on_file(rel_path: Path, action: str) -> None:
        path_str = rel_path.as_posix()
        if action == "converted":
            converted.append(path_str)
        else:
            copied.append(path_str)

    return converted, copied, on_file


def _print_folder_status(
    action_name: str,
    input_path: str,
    output_path: str,
    converted: list[str],
    copied: list[str],
    stdout: TextIO,
) -> None:
    stdout.write(f"Status: {action_name} folder {input_path!r} -> {output_path!r}\n")
    stdout.write("Files converted:\n")
    if converted:
        for f in sorted(converted):
            stdout.write(f"  - {f}\n")
    else:
        stdout.write("  (none)\n")
    if copied:
        stdout.write("Files copied (unsupported):\n")
        for f in sorted(copied):
            stdout.write(f"  - {f}\n")
        stdout.write(f"Total: {len(converted)} file(s) converted, {len(copied)} file(s) copied\n")
    else:
        stdout.write(f"Total files converted: {len(converted)}\n")


def _display_loaded_config(cfg: config_mod.Config, stdout: TextIO) -> None:
    if cfg.config_path:
        filename = Path(cfg.config_path).name
        try:
            content = Path(cfg.config_path).read_text(encoding="utf-8").strip()
            stdout.write(f"Loaded {filename} from {cfg.config_path}:\n{content}\n")
        except Exception:
            stdout.write(f"Loaded {filename} from {cfg.config_path}\n")
    else:
        stdout.write("No .obfusconfig.json loaded\n")


def _run_obfuscate(
    args: list[str],
    cfg: config_mod.Config,
    verbose: bool = False,
    stdout: TextIO | None = None,
) -> None:
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
        converted, copied, on_file = _make_status_reporter()
        service.obfuscate_folder(
            input_path,
            output_dir=out_dir,
            map_path=map_path,
            mode="full",
            cfg=cfg,
            on_file=on_file if verbose else None,
        )
        if verbose and stdout is not None:
            _print_folder_status("converting", input_path, out_dir, converted, copied, stdout)
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

    if verbose and stdout is not None:
        stdout.write(f"Status: converting {input_path!r} -> {output_path!r}\n")
        stdout.write(f"File converted: {input_path}\n")


def _run_restore(
    args: list[str],
    cfg: config_mod.Config,
    verbose: bool = False,
    stdout: TextIO | None = None,
) -> None:
    input_path, output_path, map_path = _parse_cli_args(args, cfg)
    if not input_path and cfg.input_dir:
        input_path = os.path.expanduser(cfg.input_dir)
    if not output_path and cfg.target_dir:
        output_path = os.path.expanduser(cfg.target_dir)

    if not os.path.exists(input_path):
        raise ValueError(f"input path does not exist: {input_path}")

    if os.path.isdir(input_path):
        out_dir = output_path or "restored"
        converted, copied, on_file = _make_status_reporter()
        service.restore_folder(
            input_path,
            output_dir=out_dir,
            map_path=map_path or None,
            mode="full",
            cfg=cfg,
            on_file=on_file if verbose else None,
        )
        if verbose and stdout is not None:
            _print_folder_status("restoring", input_path, out_dir, converted, copied, stdout)
        return

    _require(output_path, map_path)
    source = _read_input(input_path)
    if cfg.encryption.enabled:
        m = storage.load_mapping_encrypted(map_path, _password(cfg))
    else:
        m = storage.load_mapping(map_path)

    tokenize = for_file(input_path)
    write_text(output_path, transform.restore_source(source, tokenize, m))

    if verbose and stdout is not None:
        stdout.write(f"Status: restoring {input_path!r} -> {output_path!r}\n")
        stdout.write(f"File converted: {input_path}\n")


def _run_ai(
    args: list[str],
    cfg: config_mod.Config,
    verbose: bool = False,
    stdout: TextIO | None = None,
) -> None:
    input_path, output_path, _ = _parse_cli_args(args, cfg)
    if not input_path and cfg.input_dir:
        input_path = os.path.expanduser(cfg.input_dir)
    if not output_path and cfg.target_dir:
        output_path = os.path.expanduser(cfg.target_dir)

    if not os.path.exists(input_path):
        raise ValueError(f"input path does not exist: {input_path}")

    if os.path.isdir(input_path):
        out_dir = output_path or "output"
        converted, copied, on_file = _make_status_reporter()
        service.ai_safe_folder(input_path, output_dir=out_dir, cfg=cfg, on_file=on_file if verbose else None)
        if verbose and stdout is not None:
            _print_folder_status("redacting", input_path, out_dir, converted, copied, stdout)
        return

    _require(output_path)
    source = _read_input(input_path)
    effective_patterns = cfg.all_patterns()
    if effective_patterns:
        source = patterns_mod.ai_safe_text(source, effective_patterns)
    tokens = for_file(input_path)(source)
    write_text(output_path, reconstruct(transform.ai_safe_tokens(tokens)))

    if verbose and stdout is not None:
        stdout.write(f"Status: redacting {input_path!r} -> {output_path!r}\n")
        stdout.write(f"File converted: {input_path}\n")


def _run_light(
    args: list[str],
    cfg: config_mod.Config,
    verbose: bool = False,
    stdout: TextIO | None = None,
) -> None:
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
        converted, copied, on_file = _make_status_reporter()
        if restoring:
            out_dir = output_path or "restored"
            service.restore_folder(
                input_path,
                output_dir=out_dir,
                map_path=map_path or None,
                mode="light",
                cfg=cfg,
                on_file=on_file if verbose else None,
            )
            if verbose and stdout is not None:
                _print_folder_status("restoring", input_path, out_dir, converted, copied, stdout)
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
                on_file=on_file if verbose else None,
            )
            if verbose and stdout is not None:
                _print_folder_status("converting", input_path, out_dir, converted, copied, stdout)
        return

    _require(output_path, map_path)
    text = _read_input(input_path)

    if restoring:
        if cfg.encryption.enabled:
            m = storage.load_mapping_encrypted(map_path, _password(cfg))
        else:
            m = storage.load_mapping(map_path)
        write_text(output_path, light.restore(text, m))
        if verbose and stdout is not None:
            stdout.write(f"Status: restoring {input_path!r} -> {output_path!r}\n")
            stdout.write(f"File converted: {input_path}\n")
        return

    safe, m = light.obfuscate(text, light.parse_keys(keys_spec), patterns=cfg.all_patterns())
    write_text(output_path, safe)
    if cfg.encryption.enabled:
        storage.save_mapping_encrypted(map_path, m, _password(cfg))
    else:
        storage.save_mapping(map_path, m)
    if verbose and stdout is not None:
        stdout.write(f"Status: converting {input_path!r} -> {output_path!r}\n")
        stdout.write(f"File converted: {input_path}\n")


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
        elif arg in ("-v", "--verbose"):
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
