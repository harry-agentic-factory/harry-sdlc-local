"""Front matter reading and `category` insertion, on raw bytes.

- A UTF-8 BOM (EF BB BF) is detected and skipped; it always stays at byte 0.
- The file end of line is the one of its first line (CRLF, else LF; no newline at all: LF).
- The block starts when the first line is exactly `---` and ends at the next `---` line.
- `category` is a top-level `category:` line; value stripped of spaces and quotes.
- An opening line without closing line, a duplicated `category` key or a block that is not valid
  UTF-8 make the front matter unreadable.
- Insertion never decodes nor re-encodes the body: the output is a concatenation of byte slices.
"""
from __future__ import annotations

from dataclasses import dataclass

BOM = b"\xef\xbb\xbf"
UNREADABLE = "frontmatter_unreadable"


@dataclass(frozen=True)
class Frontmatter:
    bom: bool                   # file starts with a UTF-8 BOM
    eol: bytes                  # b"\r\n" or b"\n"
    has_block: bool             # a complete `---` ... `---` block is present
    keys: tuple[str, ...]       # top-level keys, in file order
    category: str | None        # raw `category` value (None when absent)
    body_start: int             # offset of the first byte after the block (or after the BOM)
    close_start: int            # offset of the closing `---` line (-1 without block)
    error: str | None = None    # "frontmatter_unreadable" or None


def _lines(data: bytes, start: int):
    """Yield (line_start, content_without_eol, next_start) from `start`."""
    pos = start
    n = len(data)
    while pos < n:
        nl = data.find(b"\n", pos)
        end = n if nl < 0 else nl + 1
        content = data[pos:end].rstrip(b"\n")
        if content.endswith(b"\r"):
            content = content[:-1]
        yield pos, content, end
        pos = end


def _strip_value(v: str) -> str:
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        v = v[1:-1].strip()
    return v


def parse_frontmatter(data: bytes) -> Frontmatter:
    bom = data.startswith(BOM)
    off = len(BOM) if bom else 0
    nl = data.find(b"\n", off)
    eol = b"\r\n" if nl > off and data[nl - 1:nl] == b"\r" else b"\n"
    plain = Frontmatter(bom, eol, False, (), None, off, -1)
    lines = _lines(data, off)
    first = next(lines, None)
    if first is None or first[1] != b"---":
        return plain
    close = None
    for start, content, nxt in lines:
        if content == b"---":
            close = (start, nxt)
            break
    if close is None:
        return Frontmatter(bom, eol, False, (), None, off, -1, UNREADABLE)
    block = data[first[2]:close[0]]
    try:
        text = block.decode("utf-8")
    except UnicodeDecodeError:
        return Frontmatter(bom, eol, False, (), None, off, -1, UNREADABLE)
    keys: list[str] = []
    categories: list[str] = []
    for raw in text.splitlines():
        if not raw or raw[0] in " \t#-":
            continue
        key, sep, value = raw.partition(":")
        key = key.strip()
        if not sep or not key:
            continue
        keys.append(key)
        if key == "category":
            categories.append(_strip_value(value))
    if len(categories) > 1:
        return Frontmatter(bom, eol, True, tuple(keys), None, close[1], close[0], UNREADABLE)
    category = categories[0] if categories else None
    return Frontmatter(bom, eol, True, tuple(keys), category, close[1], close[0])


def insert_category(data: bytes, fm: Frontmatter, category: str) -> bytes:
    """Return `data` with `category: <category>` added (new block, or last line of the block)."""
    if fm.error or fm.category is not None:
        raise ValueError("front matter is unreadable or already has a category")
    line = b"category: " + category.encode("utf-8") + fm.eol
    if fm.has_block:
        return data[:fm.close_start] + line + data[fm.close_start:]
    off = len(BOM) if fm.bom else 0
    return data[:off] + b"---" + fm.eol + line + b"---" + fm.eol + data[off:]
