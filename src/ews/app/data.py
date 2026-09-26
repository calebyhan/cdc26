"""Read only the published dashboard bundle, never complaint-level data."""

import json
import os
from pathlib import Path

import duckdb
import streamlit as st

ROOT = Path(__file__).resolve().parents[3]
BUNDLE = Path(os.environ.get("EWS_DASHBOARD_DIR", ROOT / "data/dashboard"))
TABLES = {
    "leaderboard",
    "company_trend",
    "issue_mix",
    "states",
    "events",
    "entities",
    "relationships",
    "aliases",
    "bank_history",
    "drivers",
    "event_aggregate",
    "event_pairs",
    "event_series",
    "event_company",
    "hits",
    "metrics",
    "leads",
    "errors",
    "flags",
}


def version():
    return (BUNDLE / "manifest.json").stat().st_mtime_ns


@st.cache_data(show_spinner=False, max_entries=128)
def read_table(name, revision, entity_id=None):
    if name not in TABLES:
        raise ValueError("Unknown dashboard mart")
    with duckdb.connect(config={"threads": 2}) as con:
        relation = con.read_parquet(str(BUNDLE / f"{name}.parquet"))
        if entity_id is None:
            return relation.df()
        relation.create_view("mart")
        return con.execute("SELECT * FROM mart WHERE entity_id=?", [entity_id]).df()


def read(name, entity_id=None):
    return read_table(name, version(), entity_id)


def manifest():
    return json.loads((BUNDLE / "manifest.json").read_text())
