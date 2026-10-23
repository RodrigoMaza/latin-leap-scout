"""Evalúa a mano una empresa que el equipo conoció fuera del pipeline automático
(un mixer, un evento, un referido) y la ubica frente al umbral de fit.

Corre exactamente la misma investigación y la misma rúbrica que el Scout semanal,
pero además lee el sitio web de la empresa. El resultado se guarda en el pipeline
marcado como "evento" (no cuenta para el KPI del Scout, que mide solo lo que la
herramienta encontró sola) y aparece en calibracion.html.

Uso:  python evaluate.py --url https://empresa.com --nota "Mixer de Endeavor, CDMX"
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone

import config
import llm
import report
import store


def normalize_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Falta el sitio web de la empresa.")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    parts = urllib.parse.urlparse(raw)
    if not parts.netloc or "." not in parts.netloc or " " in raw:
        raise ValueError(f"No parece un sitio web válido: {raw}")
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path.rstrip('/')}"


def evaluate(url: str, nota: str, budget: llm.Budget) -> dict:
    domain = urllib.parse.urlparse(url).netloc.removeprefix("www.")
    context = f"Empresa con sitio web {url}."
    if nota:
        context += f" El equipo la conoció en: {nota}."
    print(f"1) Investigando {url} …")
    notes, urls = llm.research(f"la empresa de {domain}", context, budget, website=url, searches=4)
    print("2) Calificando contra la tesis …")
    profile = (f"STARTUP: la empresa del sitio {url}\nORIGEN: evento / referido ({nota or 'sin nota'})\n"
               f"CONTEXTO: {context}\n\nINVESTIGACIÓN WEB:\n{notes or '(sin resultados de investigación)'}")
    d = llm.score(profile, budget)
    if not d.get("website"):
        d["website"] = url
    today = datetime.now(timezone.utc).date().isoformat()
    d.update({
        "key": store.key(d["nombre"]) or store.key(domain),
        "origen": "evento", "nota_evento": nota, "manual": True,
        "menciones": [{"title": f"Evaluada a mano · {nota or 'evento / referido'}",
                       "url": url, "source": "Evento", "date": today}],
        "fuentes_investigacion": urls, "first_seen": today, "last_seen": today,
        "evaluada": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "en_portafolio": store.key(d["nombre"]) in {store.key(p) for p in config.PORTFOLIO},
    })
    return d


def summary(d: dict) -> str:
    thr = report.fit_threshold()
    verdict = ("**Por encima del umbral**: entraría como prioridad." if report.is_priority(d) else
               "**Fuera de tesis** por filtro duro." if not report.in_pipeline(d) else
               "**Por debajo del umbral**: entraría al pipeline, no como prioridad.")
    pts = d["puntajes"]
    return "\n".join([
        f"# {d['nombre']} — fit {d['fit']}/80 (umbral {thr})",
        "", verdict, "",
        f"{d['descripcion']}", "",
        f"| Equipo | Sector | Modelo | Tracción | Timing |", "|---:|---:|---:|---:|---:|",
        f"| {pts['equipo']}/30 | {pts['sector']}/20 | {pts['modelo']}/10 | {pts['traccion']}/20 | {pts['etapa_timing']}/20 |",
        "", f"- **Por qué encaja:** {d['tesis_match']}", f"- **Riesgo:** {d['riesgos']}",
        f"- **País / etapa:** {d['pais']} · {d['etapa']}",
        "", f"Ver en el dashboard: {report.dashboard_url()}calibracion.html?empresa={d['key']}", "",
    ])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("EMPRESA_URL", ""))
    ap.add_argument("--nota", default=os.environ.get("EMPRESA_NOTA", ""))
    a = ap.parse_args()
    try:
        url = normalize_url(a.url)
    except ValueError as exc:
        print(f"✗ {exc}")
        return 1
    nota = (a.nota or "").strip()[:200]
    deals, state = store.load_deals(), store.load_state()
    budget = llm.Budget(0.60)  # una sola empresa: tope bajo
    try:
        d = evaluate(url, nota, budget)
    except llm.BudgetExceeded as exc:
        print(f"✗ {exc}")
        return 1
    prev = deals.get(d["key"])
    if prev and not prev.get("manual"):
        # Ya la había encontrado el Scout: se actualiza la evaluación pero conserva su origen
        d.update(origen=prev["origen"], first_seen=prev["first_seen"],
                 menciones=prev.get("menciones", []) + d["menciones"])
    deals[d["key"]] = d
    store.save_deals(deals)
    last = state["runs"][-1] if state["runs"] else {"date": d["first_seen"]}
    report.publish(deals, state, last, write_digest=False)
    text = summary(deals[d["key"]]) + f"\n_Costo estimado: US${budget.spent:.2f}_\n"
    print("\n" + text)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
