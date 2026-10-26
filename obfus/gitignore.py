"""Gitignore parsing and path filtering using gitwildmatch semantics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence
import pathspec


class GitIgnoreFilter:
    """Filters paths according to .gitignore rules across a directory tree."""

    def __init__(self, root_dir: Path | str) -> None:
        self.root_dir = Path(root_dir).resolve()
        # List of (directory_path, GitIgnoreSpec) sorted by depth
        self._specs: list[tuple[Path, pathspec.GitIgnoreSpec]] = []
        self._load_all_gitignores()

    def _load_all_gitignores(self) -> None:
        if not self.root_dir.is_dir():
            return

        # Check root and all subdirectories for .gitignore files
        for root, dirs, files in os.walk(self.root_dir):
            if ".git" in dirs:
                dirs.remove(".git")
            if ".gitignore" in files:
                git_path = Path(root, ".gitignore")
                try:
                    content = git_path.read_text(encoding="utf-8", errors="surrogateescape")
                    lines = content.splitlines()
                    spec = pathspec.GitIgnoreSpec.from_lines(lines)
                    self._specs.append((Path(root).resolve(), spec))
                except OSError:
                    continue

        # Sort by path length so parent specs come before deeper child specs
        self._specs.sort(key=lambda item: len(item[0].parts))

    @property
    def has_gitignore(self) -> bool:
        """True if at least one .gitignore was found in the folder."""
        return len(self._specs) > 0

    def is_ignored(self, path: Path | str, is_dir: bool = False) -> bool:
        """Return True if path should be ignored according to gitignore rules."""
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = (self.root_dir / resolved).resolve()
        else:
            resolved = resolved.resolve()

        if ".git" in resolved.parts:
            return True

        if not self._specs:
            return False

        try:
            # Must be within root_dir
            resolved.relative_to(self.root_dir)
        except ValueError:
            return False

        ignored = False
        for spec_dir, spec in self._specs:
            try:
                rel = resolved.relative_to(spec_dir)
            except ValueError:
                # Path is not under this .gitignore's scope
                continue

            rel_posix = rel.as_posix()
            if is_dir:
                res = spec.check_file(f"{rel_posix}/")
                if res.include is None:
                    res = spec.check_file(rel_posix)
            else:
                res = spec.check_file(rel_posix)

            if res.include is not None:
                ignored = res.include

        return ignored
