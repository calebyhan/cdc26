"""Conservative caption splitting; reviewed party rows are the production authority."""

import re

SUFFIX = re.compile(
    r"(?:Inc\.?|LLC\.?|L\.L\.C\.?|LLP\.?|LP\.?|L\.P\.?|Corp\.?|Corporation|Co\.?|Company|N\.?A\.?|National Association|F\.?S\.?B\.?|Ltd\.?|P\.?C\.?|PLC\.?|L\.P\.A\.?)$",
    re.I,
)
SUFFIX_ONLY = re.compile(
    r"^(?:Inc\.?|LLC\.?|L\.L\.C\.?|LLP\.?|LP\.?|L\.P\.?|Corp\.?|Corporation|Co\.?|N\.?A\.?|F\.?S\.?B\.?|Ltd\.?|P\.?C\.?|PLC\.?|L\.P\.A\.?|Jr\.?|Sr\.?|III|II)$",
    re.I,
)
ALIAS = re.compile(
    r"^(?:also\s+)?(?:d/?b/?a|f/?k/?a|a/?k/?a|n/?k/?a|formerly|doing business|aka\.?|fka\b)",
    re.I,
)


def split_top_level(text, pattern):
    """Split delimiters outside parentheses, preserving trade-name lists inside."""
    depth, start, pieces = 0, 0, []
    delimiters = {m.start(): m for m in re.finditer(pattern, text, flags=re.I)}
    for position, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and position in delimiters:
            match = delimiters[position]
            pieces.append(text[start:position])
            start = match.end()
    pieces.append(text[start:])
    return pieces


def split_parties(caption):
    """Handle top-level ; and , and; retain suffix commas and inline aliases.

    Bare comma lists, ambiguous 'and', and source-truncated captions need reviewed
    overrides. Never split parentheses or the brand 'Bank and Trust'.
    """
    pieces = split_top_level(caption, r";\s*(?:and\s+)?")
    result = []
    for piece in pieces:
        # Comma-and is an explicit separator unless it belongs to an inline alias.
        chunks = split_top_level(piece, r",\s*and\s+")
        for chunk in chunks:
            # Split other comma lists only after an unambiguous legal suffix.
            fragments = split_top_level(chunk, r",\s*")
            grouped = []
            for fragment in fragments:
                fragment = fragment.strip()
                if not fragment:
                    continue
                if grouped and (
                    SUFFIX_ONLY.fullmatch(fragment) or ALIAS.match(fragment)
                ):
                    grouped[-1] += ", " + fragment
                elif grouped and not SUFFIX.search(grouped[-1]):
                    grouped[-1] += ", " + fragment
                else:
                    grouped.append(fragment)
            for group in grouped:
                # Unsuffixed personal/brand lists remain intact for manual review.
                parts = split_top_level(
                    group,
                    r"(?<=[.])\s+and\s+|(?<=LLC)\s+and\s+|(?<=Corporation)\s+and\s+|(?<=Company)\s+and\s+|(?<=Association)\s+and\s+",
                )
                result.extend(p.strip(" ,") for p in parts if p.strip(" ,"))
    return result


def suggest_type(party):
    """A review suggestion only; no heuristic label is consumed by staging."""
    if re.search(
        r"\bet al\b|\b(?:other subsidiaries|related entities|affiliates|subsidiaries|associated companies|debt relief companies)\b",
        party,
        re.I,
    ):
        return "non_entity"
    if SUFFIX.search(party) or re.search(
        r"\b(?:Bank|Mortgage|Credit Union|Financial|Services|Capital|Lending|Law|Title|Trust|Group|Funding|Loan|Corp|Company|LLC|Inc|LLP|LP|PLC)\b",
        party,
        re.I,
    ):
        return "company"
    return "review"
