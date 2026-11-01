"""Extract clean text from SEC filing HTML, dropping struck-through content."""

from pathlib import Path
import re

from bs4 import BeautifulSoup

STRUCK_TAGS = {"s", "strike", "del"}
LINE_THROUGH_RE = re.compile(r"line\s*-\s*through", re.IGNORECASE)
BLANK_RUN_RE = re.compile(r"\n{3,}")


def _is_struck(tag) -> bool:
    name = (tag.name or "").lower()
    if name in STRUCK_TAGS:
        return True
    style = tag.get("style", "")
    if isinstance(style, (list, tuple)):
        style = " ".join(style)
    return bool(style) and bool(LINE_THROUGH_RE.search(style))


def html_to_text_with_stats(html) -> tuple[str, int]:
    """Clean HTML to text, dropping struck-through elements.

    Removes every element whose tag is s, strike, or del, or whose style
    contains "line-through" (case-insensitive, any spacing). Extracts text
    with newlines between block elements and collapses runs of blank lines.

    Returns (text, removed_count).
    """
    soup = BeautifulSoup(html, "html.parser")

    matches = soup.find_all(_is_struck)
    removed = 0
    for el in matches:
        if getattr(el, "decomposed", False):
            continue
        el.decompose()
        removed += 1

    raw = soup.get_text(separator="\n")
    lines = [line.strip() for line in raw.splitlines()]
    text = BLANK_RUN_RE.sub("\n\n", "\n".join(lines)).strip()
    if text:
        text += "\n"
    return text, removed


def html_to_text(html) -> str:
    """Clean HTML to text, dropping struck-through elements."""
    text, _ = html_to_text_with_stats(html)
    return text


def textify(in_path, out_path) -> tuple[int, int]:
    """Parse HTML at in_path, drop struck-through elements, save text to out_path.

    Removes every element whose tag is s, strike, or del, or whose style
    contains "line-through" (case-insensitive, any spacing). Extracts text
    with newlines between block elements, collapses runs of blank lines,
    and saves UTF-8 text.

    Returns (character_count, removed_count).
    """
    in_path = Path(in_path)
    out_path = Path(out_path)

    text, removed = html_to_text_with_stats(in_path.read_bytes())

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")

    return len(text), removed


FILES = [
    ("data/raw/snbr_13th_amendment.htm", "data/extracted/snbr_13th_amendment.txt"),
    ("data/raw/snbr_10q_20250927.htm", "data/extracted/snbr_10q_20250927.txt"),
    ("data/raw/snbr_8k_20251110.htm", "data/extracted/snbr_8k_20251110.txt"),
]


if __name__ == "__main__":
    for in_p, out_p in FILES:
        chars, removed = textify(in_p, out_p)
        print(f"{in_p} -> {out_p}: {chars} characters, {removed} struck-through elements removed")
