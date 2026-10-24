"""Salidas para el equipo: datos del dashboard, CSV para el CRM y digest semanal.

Dos niveles de resultado:
- Deal nuevo al pipeline: pasa los filtros de tesis y no se descarta. Es lo comparable
  con los 60 deals/mes que hoy entran al pipeline de Latin Leap (KPI del reto).
- Prioridad: además, su FIT con la tesis supera el umbral calibrado con el portafolio.
"""
from __future__ import annotations

import csv
import json
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import config
import store

ACTION_LABEL = {"contactar_ya": "Contactar ya", "seguimiento": "Seguimiento",
                "descartar": "Descartar"}


def dashboard_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "RodrigoMaza/latin-leap-scout")
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}/"


def fit_threshold() -> int:
    """Umbral de FIT: el que sugiere la última calibración, o el valor inicial."""
    path = store.ROOT / "data" / "calibration.json"
    try:
        return int(json.loads(path.read_text(encoding="utf-8"))["umbral_fit"])
    except Exception:
        return config.FIT_THRESHOLD_DEFAULT


def fit_floor() -> int:
    """Piso de deal calificado: el fit mínimo del portafolio en la última calibración."""
    path = store.ROOT / "data" / "calibration.json"
    try:
        c = json.loads(path.read_text(encoding="utf-8"))
        if "piso_fit" in c:
            return int(c["piso_fit"])
        return min(int(r["fit"]) for r in c["resultados"] if r.get("grupo") == "portafolio")
    except Exception:
        return config.FIT_FLOOR_DEFAULT


def fit(d: dict) -> int:
    if "fit" in d:
        return d["fit"]
    return d.get("score", 0) - (d.get("puntajes") or {}).get("etapa_timing", 0)


def in_pipeline(d: dict) -> bool:
    # El país se revisa en código además de en el modelo: la geografía es un filtro duro.
    return (d.get("accion") != "descartar" and all((d.get("filtros") or {}).values())
            and d.get("pais") in config.SPANISH_LATAM)


def is_qualified(d: dict) -> bool:
    """KPI principal: en tesis, nuevo para el fondo y al menos tan afín como su inversión
    menos afín. Excluye el portafolio actual y las evaluadas a mano en eventos."""
    return (in_pipeline(d) and not d.get("en_portafolio") and not d.get("manual")
            and fit(d) >= fit_floor())


def is_priority(d: dict) -> bool:
    return in_pipeline(d) and not d.get("en_portafolio") and fit(d) >= fit_threshold()


def kpis(deals: list[dict], runs: list[dict]) -> dict:
    today = datetime.now(timezone.utc).date()
    since = (today - timedelta(days=30)).isoformat()
    # El KPI mide lo que la herramienta encontró sola: las evaluadas a mano (eventos) no cuentan
    recent = [d for d in deals if d.get("first_seen", "") >= since and not d.get("manual")]
    p30 = [d for d in recent if in_pipeline(d)]
    q30 = [d for d in p30 if is_qualified(d)]
    weeks: Counter = Counter()
    for d in deals:
        if is_qualified(d) and d.get("first_seen"):
            y, w, _ = date.fromisoformat(d["first_seen"]).isocalendar()
            weeks[f"{y}-S{w:02d}"] += 1
    return {
        "evaluadas_total": len(deals),
        "evaluadas_evento": sum(1 for d in deals if d.get("manual")),
        "evaluadas_30d": len(recent),
        "pipeline_30d": len(p30),                 # en tesis (definición amplia)
        "calificados_30d": len(q30),              # KPI principal
        "bajo_piso_30d": len(p30) - len(q30),
        "prioridad_30d": sum(1 for d in q30 if is_priority(d)),
        "descartadas_30d": len(recent) - len(p30),
        "baseline_mensual": config.BASELINE_DEALS_PER_MONTH,
        "incremento_pct": round(100 * len(q30) / config.BASELINE_DEALS_PER_MONTH, 1),
        "incremento_amplio_pct": round(100 * len(p30) / config.BASELINE_DEALS_PER_MONTH, 1),
        "meta_pct": 10,
        "por_pais": Counter(d.get("pais", "?") for d in q30).most_common(),
        "por_sector": Counter(d.get("sector", "?") for d in q30).most_common(),
        "por_semana": sorted(weeks.items()),
        "costo_total_usd": round(sum(r.get("cost_usd", 0) for r in runs), 2),
        "corridas": len(runs),
    }


def publish(deals_map: dict, state: dict, stats: dict, out_root: Path | None = None,
            write_digest: bool = True) -> None:
    out_root = out_root or store.ROOT
    deals = list(deals_map.values())
    for d in deals:
        d["fit"] = fit(d)
        if d.get("pais") not in config.SPANISH_LATAM and d.get("accion") != "descartar":
            # Filtro duro de geografía, aplicado también a deals evaluados antes de la regla
            d["accion"] = "descartar"
            d.setdefault("filtros", {})["geografia"] = False
    deals.sort(key=lambda d: (-d["fit"], -d.get("score", 0), d.get("nombre", "")))
    k = kpis(deals, state["runs"])
    out_root.mkdir(parents=True, exist_ok=True)  # GitHub Pages sirve la raíz del repositorio
    payload = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "umbral_fit": fit_threshold(),
        "piso_fit": fit_floor(),
        "kpis": k,
        "ultima_corrida": stats,
        "corridas": state["runs"][-30:],
        "deals": deals,
    }
    (out_root / "data.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _csv(deals, out_root / "deals.csv")
    if not write_digest:  # una evaluación a mano no reescribe el digest semanal
        return
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
    cols = ["nombre", "calificado", "prioridad", "fit", "score", "accion", "pais", "ciudad", "sector", "etapa",
            "estado_ronda", "descripcion", "modelo_comparable", "fundadores", "ultima_ronda",
            "traccion", "tesis_match", "riesgos", "website", "origen", "first_seen",
            "en_portafolio", "fuente"]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:  # BOM: abre bien en Excel
        w = csv.writer(f)
        w.writerow(cols)
        for d in deals:
            row = dict(d)
            row["prioridad"] = "sí" if is_priority(d) else ""
            row["calificado"] = "sí" if is_qualified(d) else ""
            row["fundadores"] = "; ".join(f"{x['nombre']} ({x['antecedentes']})"
                                          for x in d.get("fundadores", []))
            row["fuente"] = (d.get("menciones") or [{}])[0].get("url", "")
            row["accion"] = ACTION_LABEL.get(d.get("accion"), d.get("accion"))
            w.writerow([row.get(c, "") for c in cols])


def _detail(d: dict) -> list[str]:
    founders = ", ".join(f"{f['nombre']} ({f['antecedentes']})"
                         for f in d.get("fundadores", [])) or "sin información"
    src = (d.get("menciones") or [{}])[0]
    L = [
        f"### {d['nombre']} — fit {d['fit']}/80 · {ACTION_LABEL.get(d['accion'], d['accion'])}",
        f"{d['descripcion']}",
        "",
        f"- **Por qué encaja:** {d['tesis_match']}",
        f"- **Fundadores:** {founders}",
        f"- **Ronda:** {d['ultima_ronda']} · **Tracción:** {d['traccion']}",
    ]
    if d.get("modelo_comparable"):
        L.append(f"- **Comparable:** {d['modelo_comparable']}")
    L.append(f"- **Riesgo:** {d['riesgos']}")
    if src.get("url"):
        L.append(f"- **Fuente:** [{src.get('title', 'artículo')}]({src['url']})")
    L.append("")
    return L


def _digest(deals: list[dict], k: dict, stats: dict) -> str:
    new_keys = set(stats.get("new_keys", []))
    new = [d for d in deals if d["key"] in new_keys]
    top = [d for d in new if is_priority(d)]
    pipe = [d for d in new if is_qualified(d) and not is_priority(d)]
    low = [d for d in new if in_pipeline(d) and not is_qualified(d) and not is_priority(d)]
    out = [d for d in new if not in_pipeline(d)]
    thr, floor = fit_threshold(), fit_floor()
    L = [
        f"# Dealflow Latin Leap — {stats['date']}",
        "",
        f"Esta corrida: **{len(top) + len(pipe)} deals calificados nuevos** (fit ≥ {floor}/80), "
        f"**{len(top)} de prioridad** (fit ≥ {thr}/80). "
        f"Se investigaron {stats.get('evaluated', 0)} startups de {stats.get('articles', 0)} artículos.",
        "",
        f"Últimos 30 días: **{k['calificados_30d']} deals calificados** = "
        f"**+{k['incremento_pct']}%** sobre el baseline de {k['baseline_mensual']}/mes "
        f"(meta: +{k['meta_pct']}%). Calificado = en tesis, nuevo para el fondo y al menos tan afín "
        f"como su inversión menos afín.",
        "",
        f"Dashboard completo: {dashboard_url()}",
        "",
    ]
    if top:
        L += ["## Prioridad", ""]
        for d in top:
            L += _detail(d)
    if pipe:
        L += ["## Calificados", "",
              "| Fit | Startup | País | Sector | Acción |", "|---:|---|---|---|---|"]
        for d in pipe:
            name = f"[{d['nombre']}]({d['website']})" if d.get("website") else d["nombre"]
            L.append(f"| {d['fit']} | {name} | {d['pais']} | {d['sector']} | "
                     f"{ACTION_LABEL.get(d['accion'], d['accion'])} |")
        L.append("")
    if low:
        L += ["## En tesis, bajo el piso", ""]
        for d in low:
            L.append(f"- {d['nombre']} ({d['pais']}, fit {d['fit']}): {d['riesgos']}")
        L.append("")
    if out:
        L += ["## Descartadas", ""]
        for d in out:
            L.append(f"- {d['nombre']} ({d['pais']}): {d['riesgos']}")
        L.append("")
    L += [f"_Costo estimado de esta corrida: US${stats.get('cost_usd', 0):.2f}_"]
    return "\n".join(L) + "\n"
