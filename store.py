"""Estado persistente en archivos JSON dentro del propio repositorio.

Cada corrida de GitHub Actions hace commit de estos archivos, así que el historial
completo del pipeline queda versionado y auditable sin base de datos externa.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEALS_FILE = DATA / "deals.json"
STATE_FILE = DATA / "state.json"


def key(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b(inc|sas|s\.a\.s|sa de cv|sapi|ltda|llc|corp)\b", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


def _load(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _save(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load_deals() -> dict[str, dict]:
    return {d["key"]: d for d in _load(DEALS_FILE, [])}


def save_deals(deals: dict[str, dict]) -> None:
    _save(DEALS_FILE, sorted(deals.values(), key=lambda d: (-d.get("score", 0), d["key"])))


def load_state() -> dict:
    st = _load(STATE_FILE, {})
    st.setdefault("seen_articles", [])
    st.setdefault("pending", [])   # candidatas detectadas que no alcanzaron cupo
    st.setdefault("runs", [])
    return st


def save_state(st: dict) -> None:
    st["seen_articles"] = st["seen_articles"][-5000:]
    _save(STATE_FILE, st)
