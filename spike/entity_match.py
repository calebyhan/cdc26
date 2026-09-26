"""Entity-resolution spike across CCDB companies, CFPB enforcement parties, and FDIC institutions.

Usage: python spike/entity_match.py   (run the ccdb/enforcement/fdic spike scripts first)

Lesson from v1 of this script: stripping generic words ("BANK", "SERVICES") and then scoring
with token_set_ratio yields confident false positives - "Experian Information Solutions" ->
"Solutions Bank" (100), "TD BANK US HOLDING" -> "U.S. Bank" (100). v2 adds a first-token guard
and uses token_sort_ratio, which penalises unmatched tokens.
"""
import json
import re
import unicodedata
from pathlib import Path

from rapidfuzz import fuzz, process

DATA = Path(__file__).parent / "data"

# FDIC NAMEHCR uses Fed-style abbreviations ("U S BCORP", "PNC FINL SERVICES GROUP INC").
ABBREV = {"FINL": "FINANCIAL", "BCORP": "BANCORP", "NATL": "NATIONAL", "SVCS": "SERVICES",
          "GRP": "GROUP", "HLDGS": "HOLDINGS", "HLDG": "HOLDING", "INTL": "INTERNATIONAL",
          "AMER": "AMERICA", "MTG": "MORTGAGE", "CORPORATION": "CORP", "COMPANY": "CO"}
# Legal-form noise: differs arbitrarily between sources for the same entity.
LEGAL = {"INC", "LLC", "LLP", "LP", "LTD", "CORP", "CO", "THE", "NA", "PLC", "PC", "FSB",
         "HOLDINGS", "HOLDING", "GROUP", "FINANCIAL", "USA", "AND"}
# Brand-level noise: "WELLS FARGO BANK" and "WELLS FARGO & COMPANY" share brand "WELLS FARGO".
GENERIC = {"BANK", "BANCORP", "BANCSHARES", "SERVICES", "SERVICING", "US"}


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().upper()
    s = re.split(r"\b(?:D/B/A|DBA|A/K/A|AKA|F/K/A|FKA)\b", s)[0]  # drop trade-name aliases
    s = s.replace("&", " AND ")
    s = re.sub(r"\bN\.\s?A\.?(?=\s|$)", " NA ", s)
    s = re.sub(r"\bU\.?\s?S\.?(?=\s)", "US", s)            # "U.S. BANCORP", "U S BCORP"
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


def split_parties(caption: str) -> list[str]:
    """Enforcement captions bundle respondents: 'A, Inc.; B, LLC; and Jane Doe'."""
    out = []
    for p in re.split(r";\s*(?:and\s+)?", caption):
        # Split on "and" only after a legal suffix so "Bank and Trust Company" stays intact.
        out += re.split(r"(?:(?<=Inc\.)|(?<=LLC)|(?<=Corp\.)|(?<=N\.A\.)|(?<=tion)),?\s+and\s+", p)
    return [p.strip(" ,") for p in out if p.strip(" ,")]


def build_index(names):
    idx = {}
    for n in names:
        idx.setdefault(normalize(n), []).append(n)
    return idx


def best(query, idx, cutoff=90):
    key = normalize(query)
    if key in idx:
        return idx[key], 100.0
    first = key.split()[0]
    cands = [k for k in idx if k.split()[0] == first]   # blocking on first brand token
    hit = process.extractOne(key, cands, scorer=fuzz.token_sort_ratio, score_cutoff=cutoff)
    return (idx[hit[0]], hit[1]) if hit else (None, 0.0)


def naive(query, idx, cutoff=88):
    hit = process.extractOne(normalize(query), list(idx), scorer=fuzz.token_set_ratio,
                             score_cutoff=cutoff)
    return idx[hit[0]] if hit else None


if __name__ == "__main__":
    ccdb = json.loads((DATA / "ccdb_companies.json").read_text())
    fdic = json.loads((DATA / "fdic_active_institutions.json").read_text())
    enf = json.loads((DATA / "enforcement_listing.json").read_text())

    ccdb_idx = build_index(ccdb)
    bank_idx = build_index(r["NAME"] for r in fdic)
    hc_idx = build_index(r["NAMEHCR"] for r in fdic if r.get("NAMEHCR"))

    top = sorted(ccdb.items(), key=lambda kv: -kv[1])
    total = sum(ccdb.values())
    for n in (50, 200, 1000):
        print(f"top-{n} CCDB companies cover {sum(v for _, v in top[:n]) / total:.1%} of complaints")

    print("\n== Top-40 CCDB companies -> FDIC  (v2 matcher | naive token_set baseline)")
    for name, n in top[:40]:
        mb, sb = best(name, bank_idx)
        mh, sh = best(name, hc_idx)
        amb = " AMBIGUOUS" if mb and len(set(mb)) < len(mb) else ""
        print(f"{n:>9} {name[:38]:38} | bank {str(mb and mb[0])[:40]:40} {sb:5.1f}{amb}"
              f" | hc {str(mh and mh[0])[:28]:28} {sh:5.1f} | naive {str(naive(name, bank_idx))[:40]}")

    print("\n== Enforcement parties (filed 2020+) -> CCDB")
    matched = parties = 0
    for a in enf:
        if a["date_filed"] < "2020-01-01":
            continue
        for party in split_parties(a["name"]):
            parties += 1
            m, s = best(party, ccdb_idx)
            matched += m is not None
            print(f"  {party[:58]:58} -> {str(m)[:70]:70} {s:5.1f}")
    print(f"\nenforcement parties (2020+) with a CCDB match: {matched}/{parties}")
