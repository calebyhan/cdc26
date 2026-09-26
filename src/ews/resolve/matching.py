"""Normalization and blocked fuzzy candidates; candidates require human review."""

import re
import unicodedata
from pathlib import Path

from rapidfuzz import fuzz, process

from ews.resolve.parties import split_parties  # noqa: F401

DATA = Path("data/raw")

# FDIC NAMEHCR uses Fed-style abbreviations ("U S BCORP", "PNC FINL SERVICES GROUP INC").
ABBREV = {
    "FINL": "FINANCIAL",
    "BCORP": "BANCORP",
    "NATL": "NATIONAL",
    "SVCS": "SERVICES",
    "GRP": "GROUP",
    "HLDGS": "HOLDINGS",
    "HLDG": "HOLDING",
    "INTL": "INTERNATIONAL",
    "AMER": "AMERICA",
    "MTG": "MORTGAGE",
    "CORPORATION": "CORP",
    "COMPANY": "CO",
}
# Legal-form noise: differs arbitrarily between sources for the same entity.
LEGAL = {
    "INC",
    "LLC",
    "LLP",
    "LP",
    "LTD",
    "CORP",
    "CO",
    "THE",
    "NA",
    "PLC",
    "PC",
    "FSB",
    "HOLDINGS",
    "HOLDING",
    "GROUP",
    "FINANCIAL",
    "USA",
    "AND",
}
# Brand-level noise: "WELLS FARGO BANK" and "WELLS FARGO & COMPANY" share brand "WELLS FARGO".
GENERIC = {"BANK", "BANCORP", "BANCSHARES", "SERVICES", "SERVICING", "US"}


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    s = re.split(r"\b(?:D/B/A|DBA|A/K/A|AKA|F/K/A|FKA)\b", s)[
        0
    ]  # drop trade-name aliases
    s = s.replace("&", " AND ")
    s = re.sub(r"\bN\.\s?A\.?(?=\s|$)", " NA ", s)
    s = re.sub(r"\bU\.?\s?S\.?(?=\s)", "US", s)  # "U.S. BANCORP", "U S BCORP"
    s = re.sub(r"\bNATIONAL ASSOCIATION\b", " NA ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    toks = [ABBREV.get(t, t) for t in s.split()]
    if len(toks) > 1 and toks[0] == "THE":
        toks = toks[1:]
    # Strip noise only from the tail: "BANK OF AMERICA" must not collapse to "OF AMERICA"
    # (which is also what "Financial Corporation of America" reduces to).
    while len(toks) > 1 and toks[-1] in LEGAL | GENERIC:
        toks.pop()
    return " ".join(toks)


def build_index(names):
    idx = {}
    for n in names:
        idx.setdefault(normalize(n), []).append(n)
    return idx


def best(query, idx, cutoff=90):
    key = normalize(query)
    if key in idx:
        return idx[key], 100.0
    if not key:
        return None, 0.0
    first = key.split()[0]
    cands = [
        k for k in idx if k and k.split()[0] == first
    ]  # blocking on first brand token
    hit = process.extractOne(
        key, cands, scorer=fuzz.token_sort_ratio, score_cutoff=cutoff
    )
    return (idx[hit[0]], hit[1]) if hit else (None, 0.0)


def naive(query, idx, cutoff=88):
    hit = process.extractOne(
        normalize(query), list(idx), scorer=fuzz.token_set_ratio, score_cutoff=cutoff
    )
    return idx[hit[0]] if hit else None
