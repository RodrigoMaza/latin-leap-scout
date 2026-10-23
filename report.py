"""Salidas para el equipo: datos del dashboard, CSV para el CRM y digest semanal."""
from __future__ import annotations

import csv
import json
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config
from . import store

ACTION_LABEL = {"contactar_ya": "Contactar ya", "seguimiento": "Seguimiento",
                "descartar": "Descartar"}


def dashboard_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "RodrigoMaza/latin-leap-scout")
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


def _qualified(d: dict) -> bool:
    return d.get("score", 0) >= config.QUALIFIED_THRESHOLD and d.get("accion") != "descartar"


def kpis(deals: list[dict], runs: list[dict]) -> dict:
    today = datetime.now(timezone.utc).date()
    since = (today - timedelta(days=30)).isoformat()
    recent = [d for d in deals if d.get("first_seen", "") >= since]
    q30 = [d for d in recent if _qualified(d)]
    weeks: Counter = Counter()
    for d in deals:
        if _qualified(d) and d.get("first_seen"):
            y, w, _ = date.fromisoformat(d["first_seen"]).isocalendar()
            weeks[f"{y}-S{w:02d}"] += 1
    return {
        "evaluadas_total": len(deals),
        "evaluadas_30d": len(recent),
        "calificadas_30d": len(q30),
        "alto_fit_30d": sum(1 for d in q30 if d["score"] >= config.HIGH_FIT_THRESHOLD),
        "baseline_mensual": config.BASELINE_DEALS_PER_MONTH,
        "incremento_pct": round(100 * len(q30) / config.BASELINE_DEALS_PER_MONTH, 1),
        "meta_pct": 10,
        "por_pais": Counter(d.get("pais", "?") for d in q30).most_common(),
        "por_sector": Counter(d.get("sector", "?") for d in q30).most_common(),
        "por_semana": sorted(weeks.items()),
        "costo_total_usd": round(sum(r.get("cost_usd", 0) for r in runs), 2),
        "corridas": len(runs),
    }


def publish(deals_map: dict, state: dict, stats: dict, out_root: Path | None = None) -> None:
    out_root = out_root or store.ROOT
    deals = sorted(deals_map.values(), key=lambda d: (-d.get("score", 0), d.get("nombre", "")))
    k = kpis(deals, state["runs"])
    docs = out_root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    payload = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "umbral_calificada": config.QUALIFIED_THRESHOLD,
        "umbral_alto_fit": config.HIGH_FIT_THRESHOLD,
        "kpis": k,
        "ultima_corrida": stats,
        "corridas": state["runs"][-30:],
        "deals": deals,
    }
    (docs / "data.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _csv(deals, docs / "deals.csv")
    digest = _digest(deals, k, stats)
    rep = out_root / "reports"
    rep.mkdir(parents=True, exist_ok=True)
    (rep / f"digest-{stats['date']}.md").write_text(digest, encoding="utf-8")
    (rep / "latest.md").write_text(digest, encoding="utf-8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(digest)


def _csv(deals: list[dict], path: Path) -> None:
    cols = ["nombre", "score", "accion", "pais", "ciudad", "sector", "etapa", "estado_ronda",
            "descripcion", "modelo_comparable", "fundadores", "ultima_ronda", "traccion",
            "tesis_match", "riesgos", "website", "origen", "first_seen", "en_portafolio",
            "fuente"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM: abre bien en Excel
        w = csv.writer(f)
        w.writerow(cols)
        for d in deals:
            row = dict(d)
            row["fundadores"] = "; ".join(f"{x['nombre']} ({x['antecedentes']})"
                                          for x in d.get("fundadores", []))
            row["fuente"] = (d.get("menciones") or [{}])[0].get("url", "")
            row["accion"] = ACTION_LABEL.get(d.get("accion"), d.get("accion"))
            w.writerow([row.get(c, "") for c in cols])


def _digest(deals: list[dict], k: dict, stats: dict) -> str:
    new_keys = set(stats.get("new_keys", []))
    new = [d for d in deals if d["key"] in new_keys]
    top = [d for d in new if _qualified(d)]
    rest = [d for d in new if not _qualified(d)]
    L = [
        f"# Dealflow Latin Leap — {stats['date']}",
        "",
        f"**{len(top)} startups calificadas nuevas** en esta corrida "
        f"(de {stats.get('evaluated', 0)} investigadas, {stats.get('articles', 0)} artículos leídos).",
        "",
        f"Últimos 30 días: **{k['calificadas_30d']} deals calificados** = "
        f"**+{k['incremento_pct']}%** sobre el baseline de {k['baseline_mensual']}/mes "
        f"(meta: +{k['meta_pct']}%).",
        "",
        f"Dashboard completo: {dashboard_url()}",
        "",
    ]
    if top:
        L += ["## Prioridad", "",
              "| Score | Startup | País | Sector | Acción |", "|---:|---|---|---|---|"]
        for d in top:
            name = f"[{d['nombre']}]({d['website']})" if d.get("website") else d["nombre"]
            L.append(f"| {d['score']} | {name} | {d['pais']} | {d['sector']} | "
                     f"{ACTION_LABEL.get(d['accion'], d['accion'])} |")
        L.append("")
        for d in top:
            founders = ", ".join(f"{f['nombre']} ({f['antecedentes']})"
                                 for f in d.get("fundadores", [])) or "sin información"
            src = (d.get("menciones") or [{}])[0]
            L += [
                f"### {d['nombre']} — {d['score']}/100",
                f"{d['descripcion']}",
                "",
                f"- **Por qué encaja:** {d['tesis_match']}",
                f"- **Fundadores:** {founders}",
                f"- **Ronda:** {d['ultima_ronda']} · **Tracción:** {d['traccion']}",
            ]
            if d.get("modelo_comparable"):
                L.append(f"- **Comparable:** {d['modelo_comparable']}")
            L += [f"- **Riesgo:** {d['riesgos']}"]
            if src.get("url"):
                L.append(f"- **Fuente:** [{src.get('title', 'artículo')}]({src['url']})")
            L.append("")
    if rest:
        L += ["## Revisadas y no priorizadas", ""]
        for d in rest:
            L.append(f"- {d['nombre']} ({d['pais']}, {d['score']}): {d['riesgos']}")
        L.append("")
    L += [f"_Costo estimado de esta corrida: US${stats.get('cost_usd', 0):.2f}_"]
    return "\n".join(L) + "\n"
