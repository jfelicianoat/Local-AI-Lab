from __future__ import annotations

import os
from pathlib import Path

import pytest

from local_ai_lab.knowledge_index.markdown import parse_markdown
from local_ai_lab.knowledge_index.vault import ReadOnlyVaultAdapter, VaultSecurityError


def make_vault(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "Vaults"
    vault = root / "Research"
    vault.mkdir(parents=True)
    (vault / "Project.md").write_text("# Project\nDecision [[Evidence#Source]] #active", encoding="utf-8")
    (vault / ".obsidian").mkdir()
    (vault / ".obsidian" / "workspace.json").write_text("{}", encoding="utf-8")
    (vault / "ignored.tmp").write_text("temporary", encoding="utf-8")
    return root, vault


def test_adapter_exposes_only_included_files_and_binary_reads(tmp_path: Path) -> None:
    root, vault = make_vault(tmp_path)
    adapter = ReadOnlyVaultAdapter(allowed_root=root, vault_root=vault)

    assert adapter.entries() == [adapter.stat("Project.md")]
    assert adapter.read_bytes("Project.md").startswith(b"# Project")
    assert not hasattr(adapter, "write")
    assert not hasattr(adapter, "delete")
    assert not hasattr(adapter, "rename")


@pytest.mark.parametrize("path", ["../outside.md", "/absolute.md", ".obsidian/workspace.json", "ignored.tmp"])
def test_adapter_rejects_traversal_and_exclusions(tmp_path: Path, path: str) -> None:
    root, vault = make_vault(tmp_path)
    adapter = ReadOnlyVaultAdapter(allowed_root=root, vault_root=vault)
    with pytest.raises((VaultSecurityError, FileNotFoundError)):
        adapter.read_bytes(path)


def test_selected_vault_must_be_a_direct_child(tmp_path: Path) -> None:
    root, vault = make_vault(tmp_path)
    nested = vault / "Nested"
    nested.mkdir()
    with pytest.raises(VaultSecurityError):
        ReadOnlyVaultAdapter(allowed_root=root, vault_root=nested)


def test_symlink_is_rejected_when_platform_allows_it(tmp_path: Path) -> None:
    root, vault = make_vault(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    link = vault / "link.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("test identity cannot create symlinks")

    with pytest.raises(VaultSecurityError):
        ReadOnlyVaultAdapter(allowed_root=root, vault_root=vault).entries()


def test_markdown_parser_preserves_sections_links_embeds_tags_and_frontmatter() -> None:
    parsed = parse_markdown(
        "---\ntitle: Project\nowner: Ana\n---\nIntro #active\n# Decision\nSee [[Evidence#Source|proof]] and ![[Diagram]]."
    )

    assert parsed.frontmatter == {"title": "Project", "owner": "Ana"}
    assert [chunk.section for chunk in parsed.chunks] == ["Introducción", "Decision"]
    assert parsed.links[0].raw_target == "Evidence"
    assert parsed.links[0].heading == "Source"
    assert parsed.links[1].is_embed is True
    assert parsed.tags == ("active",)
