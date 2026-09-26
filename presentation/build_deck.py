"""Build presentation/deck.html: the template with the exported deck data inlined.

Run this after editing text in deck.template.html. It needs only the standard
library. Re-run scripts/export_deck_data.py first only if the data should change.

    .venv/bin/python presentation/build_deck.py
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
PLACEHOLDER = "__DATA__"


def main() -> None:
    template = (HERE / "deck.template.html").read_text(encoding="utf-8")
    data = (HERE / "deck-data.json").read_text(encoding="utf-8")
    if PLACEHOLDER not in template:
        raise SystemExit(
            f"deck.template.html lost its {PLACEHOLDER} placeholder; put it back in the data <script> tag"
        )
    if "</script" in data:
        raise SystemExit(
            "deck-data.json contains '</script', which would end the inlined data block early"
        )
    out = HERE / "deck.html"
    out.write_text(template.replace(PLACEHOLDER, data), encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size // 1024} KiB)")


if __name__ == "__main__":
    main()
