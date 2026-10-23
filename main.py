"""Pipeline completo: recolectar → extraer → deduplicar → investigar → calificar → publicar.

Uso:
    python main.py            # corrida normal (la que dispara GitHub Actions)
    python main.py --dry-run  # sin llamadas a la API, con datos de ejemplo
"""
from __future__ import annotations

import argparse
import sys
import unicodedata
from datetime import datetime, timezone

import config, llm, report, sources, store


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


LATAM_NORM = {_norm(c) for c in config.SPANISH_LATAM}
PORTFOLIO_KEYS = {store.key(p) for p in config.PORTFOLIO}


def build_candidates(extracted: list[dict], articles: list, yc: list, deals: dict) -> tuple[list[dict], int]:
    """Une startups de noticias y de YC, filtra fuera de tesis y separa las ya conocidas."""
    by_key: dict[str, dict] = {}
    remention = 0
    for s in extracted:
        k = store.key(s["nombre"])
        if not k or _norm(s["pais"]) not in LATAM_NORM or s["etapa"] == "series-a-o-mas":
            continue
        refs = [articles[i] for i in s.get("articulos", []) if 0 <= i < len(articles)]
        art = [{"title": a.title, "url": a.url, "source": a.source, "date": a.published}
               for a in refs]
        if k in deals:  # ya la teníamos: suma la mención como señal de momentum
            deals[k].setdefault("menciones", []).extend(art)
            deals[k]["last_seen"] = _today()
            remention += 1
            continue
        c = by_key.setdefault(k, {
            "key": k, "nombre": s["nombre"], "origen": "noticias", "pais": s["pais"],
            "contexto": s["descripcion"], "evento": s["evento"], "etapa_detectada": s["etapa"],
            "monto_usd": s.get("monto_usd"), "menciones": [],
        })
        c["menciones"].extend(art)
    for y in yc:
        k = store.key(y.name)
        if not k or k in deals or k in by_key:
            continue
        by_key[k] = {
            "key": k, "nombre": y.name, "origen": f"Y Combinator {y.batch}",
            "pais": y.location, "contexto": f"{y.one_liner}. {y.description} "
            f"Ubicación: {y.location}. Equipo: {y.team_size}. Web: {y.website}",
            "evento": "aceleradora", "etapa_detectada": "pre-seed", "monto_usd": None,
            "menciones": [{"title": f"{y.name} — perfil en Y Combinator ({y.batch})",
                           "url": y.yc_url, "source": "Y Combinator", "date": ""}],
        }
    # Prioridad: quien está levantando o acaba de levantar va primero
    order = {"levantando": 0, "levanto_ronda": 1, "aceleradora": 2, "lanzamiento": 3, "otro": 4}
    cands = sorted(by_key.values(), key=lambda c: (order.get(c["evento"], 9), -len(c["menciones"])))
    return cands, remention


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def evaluate(c: dict, budget: llm.Budget) -> dict:
    ctx = f"{c['contexto']} (país: {c['pais']}; evento: {c['evento']}; " \
          f"monto: {c.get('monto_usd') or 'n/d'})"
    notes, urls = llm.research(c["nombre"], ctx, budget)
    titles = "\n".join(f"- {m['title']} ({m['source']}, {m['date']})" for m in c["menciones"][:5])
    profile = (f"STARTUP: {c['nombre']}\nORIGEN: {c['origen']}\nCONTEXTO DE LA FUENTE: {ctx}\n"
               f"TITULARES:\n{titles or '- (sin titulares)'}\n\n"
               f"INVESTIGACIÓN WEB:\n{notes or '(sin resultados de investigación)'}")
    result = llm.score(profile, budget)
    result.update({
        "key": c["key"], "origen": c["origen"], "menciones": c["menciones"],
        "fuentes_investigacion": urls, "first_seen": _today(), "last_seen": _today(),
        "en_portafolio": c["key"] in PORTFOLIO_KEYS,
    })
    return result


def run(dry_run: bool = False) -> int:
    deals = store.load_deals()
    state = store.load_state()
    first_run = not deals
    days = config.LOOKBACK_DAYS_FIRST_RUN if first_run else config.LOOKBACK_DAYS
    stats = {"date": _today(), "articles": 0, "extracted": 0, "candidates": 0,
             "evaluated": 0, "qualified": 0, "remention": 0, "cost_usd": 0.0}

    if dry_run:
        from demo import demo_deals
        for d in demo_deals():
            deals[d["key"]] = d
        stats.update(evaluated=len(deals), new_keys=list(deals))
    else:
        budget = llm.Budget(config.MAX_USD_PER_RUN)
        print(f"1) Recolectando noticias de los últimos {days} días…")
        seen = set(state["seen_articles"])
        articles = [a for a in sources.fetch_news(days) if a.id not in seen]
        stats["articles"] = len(articles)
        print(f"   {len(articles)} artículos nuevos")

        print("2) Directorio de Y Combinator…")
        yc = sources.fetch_yc(datetime.now().year - config.YC_RECENT_BATCH_YEARS)

        print("3) Extrayendo startups de los titulares…")
        extracted = llm.extract(articles, budget) if articles else []
        stats["extracted"] = len(extracted)
        print(f"   {len(extracted)} menciones de startups")

        cands, stats["remention"] = build_candidates(extracted, articles, yc, deals)
        # Las que quedaron pendientes de corridas anteriores tienen prioridad
        pend = [p for p in state["pending"] if p["key"] not in deals]
        pend_keys = {p["key"] for p in pend}
        queue = pend + [c for c in cands if c["key"] not in pend_keys]
        stats["candidates"] = len(queue)
        print(f"4) {len(queue)} candidatas nuevas en tesis (geo + etapa). "
              f"Investigando hasta {config.MAX_CANDIDATES_PER_RUN}…")

        done = 0
        new_keys: list[str] = []
        for c in queue[:config.MAX_CANDIDATES_PER_RUN]:
            try:
                d = evaluate(c, budget)
            except llm.BudgetExceeded as exc:
                print(f"   ■ {exc}. Lo restante queda en cola para la próxima corrida.")
                break
            except Exception as exc:
                print(f"   ! error evaluando {c['nombre']}: {exc}")
                continue
            deals[d["key"]] = d
            new_keys.append(d["key"])
            done += 1
            print(f"   {d['score']:3d}  {d['nombre']} ({d['pais']}) → {d['accion']}")
        evaluated_keys = set(deals)
        state["pending"] = [c for c in queue if c["key"] not in evaluated_keys][:100]
        state["seen_articles"] += [a.id for a in articles]
        stats.update(evaluated=done, cost_usd=round(budget.spent, 3),
                     searches=budget.searches, new_keys=new_keys)

    stats["qualified"] = sum(1 for k in stats.get("new_keys", []) for d in [deals[k]]
                             if d.get("score", 0) >= config.QUALIFIED_THRESHOLD
                             and d.get("accion") != "descartar")
    state["runs"].append(stats)
    if dry_run:  # la vista previa nunca toca los datos reales
        report.publish(deals, state, stats, out_root=store.ROOT / "_preview")
    else:
        store.save_deals(deals)
        store.save_state(state)
        report.publish(deals, state, stats)
    print(f"\nListo. Evaluadas: {stats['evaluated']} · calificadas hoy: {stats['qualified']} · "
          f"costo estimado: US${stats['cost_usd']:.2f}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(run(ap.parse_args().dry_run))
