from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass(frozen=True)
class ParsedReport:
    section1_raw: str
    section2_raw: str
    table: Optional[List[List[str]]]  # includes header as row[0]


_SECTION_1_RE = re.compile(
    r"##\s*Section\s*1\s*(.*?)(?=##\s*Section\s*2\b)",
    re.IGNORECASE | re.DOTALL,
)
_SECTION_2_RE = re.compile(r"##\s*Section\s*2\s*(.*)$", re.IGNORECASE | re.DOTALL)


def parse_assistant_answer(answer: str) -> ParsedReport:
    """Extract Section 1/2 and (if present) parse a single markdown table from Section 1."""
    s1_match = _SECTION_1_RE.search(answer)
    s2_match = _SECTION_2_RE.search(answer)

    section1 = (s1_match.group(1).strip() if s1_match else "").strip()
    section2 = (s2_match.group(1).strip() if s2_match else "").strip()

    table = _parse_markdown_table(section1)
    return ParsedReport(section1_raw=section1, section2_raw=section2, table=table)


def _parse_markdown_table(text: str) -> Optional[List[List[str]]]:
    """Parse a GitHub-flavored markdown table.

    Returns table as list of rows, each row is list of cell strings.
    First row is header.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    # Find first likely header line
    header_idx = None
    for i, ln in enumerate(lines):
        if ln.startswith("|") and "|" in ln[1:]:
            header_idx = i
            break
    if header_idx is None:
        return None

    if header_idx + 1 >= len(lines):
        return None

    sep = lines[header_idx + 1]
    if not _is_separator_line(sep):
        return None

    header = _split_row(lines[header_idx])
    rows: List[List[str]] = []
    for ln in lines[header_idx + 2 :]:
        if not ln.startswith("|"):
            break
        if _is_separator_line(ln):
            continue
        row = _split_row(ln)
        # normalize column count
        if len(row) < len(header):
            row = row + [""] * (len(header) - len(row))
        elif len(row) > len(header):
            row = row[: len(header)]
        rows.append(row)

    if not header or not rows:
        return None
    return [header] + rows


def _split_row(line: str) -> List[str]:
    # Remove leading/trailing pipes, then split
    core = line.strip().strip("|")
    parts = [p.strip() for p in core.split("|")]
    return parts


def _is_separator_line(line: str) -> bool:
    # e.g. | --- | ---: | :--- |
    if not line.startswith("|"):
        return False
    core = line.strip().strip("|")
    cells = [c.strip() for c in core.split("|")]
    if not cells:
        return False
    for c in cells:
        if not c:
            return False
        # allow alignment colons
        c2 = c.replace(":", "")
        if set(c2) != {"-"}:
            return False
        if len(c2) < 3:
            return False
    return True
