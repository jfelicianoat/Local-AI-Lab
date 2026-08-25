from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from local_ai_lab.domain.common import sha256_text

PARSER_VERSION = "markdown-parser.v1"
CHUNKER_VERSION = "heading-chunker.v1"
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
WIKILINK = re.compile(r"(!?)\[\[([^\]|#]+)(?:#([^\]|]+))?(?:\|[^\]]+)?\]\]")
TAG = re.compile(r"(?<![\w/])#([\w/-]+)", re.UNICODE)


@dataclass(frozen=True, slots=True)
class ParsedChunk:
    locator: str
    section: str
    content: str
    ordinal: int


@dataclass(frozen=True, slots=True)
class ParsedLink:
    raw_target: str
    heading: str | None
    is_embed: bool
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ParsedNote:
    frontmatter: dict[str, str]
    chunks: tuple[ParsedChunk, ...]
    links: tuple[ParsedLink, ...]
    tags: tuple[str, ...]


def parse_markdown(text: str) -> ParsedNote:
    frontmatter, body = _frontmatter(text)
    chunks = _chunks(body)
    links = tuple(
        ParsedLink(
            raw_target=match.group(2).strip(),
            heading=match.group(3).strip() if match.group(3) else None,
            is_embed=bool(match.group(1)),
            start=match.start(),
            end=match.end(),
        )
        for match in WIKILINK.finditer(body)
    )
    tags = tuple(sorted({match.group(1) for match in TAG.finditer(body)}, key=str.casefold))
    return ParsedNote(frontmatter, chunks, links, tags)


def chunk_identity(note_revision_id: str, chunk: ParsedChunk) -> str:
    return sha256_text(
        note_revision_id + PARSER_VERSION + CHUNKER_VERSION + chunk.locator
    )


def _frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, text
    closing = next((index for index in range(1, len(lines)) if lines[index].strip() == "---"), None)
    if closing is None:
        return {}, text
    values: dict[str, str] = {}
    for line in lines[1:closing]:
        key, separator, value = line.partition(":")
        if separator and key.strip():
            values[key.strip()] = value.strip()
    return values, "".join(lines[closing + 1 :])


def _chunks(body: str) -> tuple[ParsedChunk, ...]:
    lines = body.splitlines(keepends=True)
    sections: list[tuple[str, list[str]]] = [("Introducción", [])]
    for line in lines:
        match = HEADING.match(line.rstrip("\r\n"))
        if match:
            sections.append((match.group(2).strip(), [line]))
        else:
            sections[-1][1].append(line)
    result = []
    for ordinal, (section, content_lines) in enumerate(sections):
        content = "".join(content_lines).strip()
        if not content:
            continue
        locator = f"{ordinal}:{_slug(section)}"
        result.append(ParsedChunk(locator, section, content, len(result)))
    return tuple(result)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^\w]+", "-", value.casefold(), flags=re.UNICODE).strip("-")
    return normalized or "section"
