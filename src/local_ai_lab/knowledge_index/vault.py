from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterator


class VaultSecurityError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class VaultEntry:
    relative_path: str
    size: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class VaultExclusionPolicy:
    excluded_directories: tuple[str, ...] = (".obsidian", ".git", ".trash", ".stfolder")
    excluded_patterns: tuple[str, ...] = ("*.tmp", "*.temp", "*.swp", "~$*")
    included_extensions: tuple[str, ...] = (".md",)

    def includes(self, relative_path: str, *, is_directory: bool) -> bool:
        pure = PurePosixPath(relative_path)
        if any(part.casefold() in {value.casefold() for value in self.excluded_directories} for part in pure.parts):
            return False
        if any(pure.match(pattern) for pattern in self.excluded_patterns):
            return False
        if is_directory:
            return True
        return pure.suffix.casefold() in {value.casefold() for value in self.included_extensions}

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "excluded_directories": list(self.excluded_directories),
            "excluded_patterns": list(self.excluded_patterns),
            "included_extensions": list(self.included_extensions),
        }


class ReadOnlyVaultAdapter:
    """A capability-limited port: enumeration and binary reads are the only operations."""

    def __init__(
        self,
        *,
        allowed_root: Path,
        vault_root: Path,
        exclusions: VaultExclusionPolicy | None = None,
    ) -> None:
        self.allowed_root = allowed_root.resolve(strict=True)
        self.vault_root = vault_root.resolve(strict=True)
        if not self.allowed_root.is_dir() or not self.vault_root.is_dir():
            raise ValueError("vault roots must be directories")
        if self.vault_root.parent != self.allowed_root:
            raise VaultSecurityError("selected vault must be a direct child of the allowed root")
        self.exclusions = exclusions or VaultExclusionPolicy()
        self._reject_reparse(self.allowed_root)
        self._reject_reparse(self.vault_root)

    @property
    def identity_has_write_access(self) -> bool:
        """Detection only; it never attempts a canary write against the real vault."""

        return os.access(self.vault_root, os.W_OK)

    def entries(self) -> list[VaultEntry]:
        discovered: list[VaultEntry] = []
        self._walk(self.vault_root, discovered)
        return sorted(discovered, key=lambda item: item.relative_path.casefold())

    def open_binary(self, relative_path: str) -> BinaryIO:
        path = self._validated_file(relative_path)
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        return os.fdopen(descriptor, "rb", closefd=True)

    def read_bytes(self, relative_path: str) -> bytes:
        with self.open_binary(relative_path) as source:
            return source.read()

    def stat(self, relative_path: str) -> VaultEntry:
        path = self._validated_file(relative_path)
        info = path.stat()
        return VaultEntry(self._relative(path), info.st_size, info.st_mtime_ns)

    def _walk(self, directory: Path, discovered: list[VaultEntry]) -> None:
        self._reject_reparse(directory)
        with os.scandir(directory) as iterator:
            items = sorted(iterator, key=lambda item: item.name.casefold())
        for item in items:
            path = Path(item.path)
            relative = self._relative(path)
            if item.is_symlink():
                raise VaultSecurityError(f"reparse/symlink entry rejected: {relative}")
            is_directory = item.is_dir(follow_symlinks=False)
            if not self.exclusions.includes(relative, is_directory=is_directory):
                continue
            self._reject_reparse(path)
            if is_directory:
                self._walk(path, discovered)
            elif item.is_file(follow_symlinks=False):
                info = item.stat(follow_symlinks=False)
                discovered.append(VaultEntry(relative, info.st_size, info.st_mtime_ns))

    def _validated_file(self, relative_path: str) -> Path:
        pure = PurePosixPath(relative_path.replace("\\", "/"))
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise VaultSecurityError("vault path must be relative and cannot traverse parents")
        path = (self.vault_root / Path(*pure.parts)).resolve(strict=True)
        try:
            common = os.path.commonpath((self.vault_root, path))
        except ValueError as error:
            raise VaultSecurityError("vault path is on another volume") from error
        if Path(common) != self.vault_root or not path.is_file():
            raise VaultSecurityError("vault path escapes the selected root or is not a file")
        if not self.exclusions.includes(self._relative(path), is_directory=False):
            raise VaultSecurityError("vault path is excluded by policy")
        current = path
        while current != self.vault_root:
            self._reject_reparse(current)
            current = current.parent
        return path

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.vault_root).as_posix()

    @staticmethod
    def _reject_reparse(path: Path) -> None:
        info = path.lstat()
        attributes = getattr(info, "st_file_attributes", 0)
        reparse_flag = getattr(os.stat_result, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        if path.is_symlink() or attributes & reparse_flag:
            raise VaultSecurityError(f"reparse point rejected: {path.name}")


def discover_vaults(allowed_root: Path) -> list[str]:
    """List direct child directories without opening vault contents."""

    root = allowed_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("allowed vault root must be a directory")
    ReadOnlyVaultAdapter._reject_reparse(root)
    names: list[str] = []
    with os.scandir(root) as iterator:
        for item in iterator:
            if item.is_symlink() or not item.is_dir(follow_symlinks=False):
                continue
            path = Path(item.path)
            ReadOnlyVaultAdapter._reject_reparse(path)
            names.append(item.name)
    return sorted(names, key=str.casefold)
