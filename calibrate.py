"""Calibración: ¿el calificador piensa como Latin Leap?

Corre exactamente el mismo flujo (investigación web + calificación) sobre:
  - el portafolio real de Latin Leap (debería salir con puntaje alto), y
  - controles negativos fuera de tesis (deberían salir bajo o descartados).

El modo calibración evalúa a cada empresa "como era en su ronda semilla", para
que su etapa actual no contamine la medición de fit con la tesis.

Uso:  python calibrate.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import config, llm
from store import ROOT

# (nombre, pista para desambiguar la búsqueda, esperado)
PORTFOLIO = [
    ("MejorCDT (Luable)", "Fintech de Colombia, comparador de CDTs e inversión; Y Combinator S21", "alto"),
    ("Keybe", "Startup de Colombia, comercio conversacional / CRM con IA", "alto"),
    ("Refurbi", "Startup de LATAM de electrónica reacondicionada", "alto"),
    ("Morado", "Bogotá, socio financiero de negocios liderados por mujeres", "alto"),
    ("Cubo", "Fintech de San Salvador: aceptación de pagos con tarjeta para mipymes", "alto"),
    ("Rintin", "Ciudad de México, B2B que conecta tienditas con proveedores", "alto"),
    ("PuntoPost", "LATAM, entregas e-commerce a puntos de recolección (OOH), tipo InPost", "alto"),
    ("Magneto", "Startup de Colombia, plataforma de empleo / HR-tech", "alto"),
    ("Dapta", "Startup de LATAM, agentes de IA / automatización", "alto"),
    ("Mutuus", "Startup de México", "alto"),
    ("TripWip", "Startup de Uruguay", "alto"),
    ("Talently", "Startup de LATAM de talento tecnológico", "alto"),
]
CONTROLS = [
    ("Loft", "Proptech de Brasil", "bajo"),
    ("Glovo", "Delivery de España", "bajo"),
    ("Notion", "Software de productividad de Estados Unidos", "bajo"),
]


def main() -> int:
    budget = llm.Budget(config.MAX_USD_PER_RUN * 1.5)
    rows = []
    for name, hint, expected in PORTFOLIO + CONTROLS:
        try:
            notes, urls = llm.research(name, hint, budget)
            profile = (f"STARTUP: {name}\nPISTA: {hint}\n\n"
                       f"INVESTIGACIÓN WEB:\n{notes or '(sin resultados)'}")
            r = llm.score(profile, budget, calibration=True)
        except llm.BudgetExceeded as exc:
            print(f"■ {exc}")
            break
        except Exception as exc:
            print(f"! {name}: {exc}")
            continue
        rows.append({
            "nombre": name, "grupo": "portafolio" if expected == "alto" else "control",
            "esperado": expected, "score": r["score"], "fit": r["fit"], "accion": r["accion"],
            "pais": r["pais"], "sector": r["sector"], "puntajes": r["puntajes"],
            "tesis_match": r["tesis_match"], "confianza": r["confianza"],
            "fuentes": urls,
        })
        print(f"fit {r['fit']:2d}/80  {name:22s} esperado={expected}  acción={r['accion']}")

    port = [r for r in rows if r["grupo"] == "portafolio"]
    ctrl = [r for r in rows if r["grupo"] == "control"]
    # Umbral = percentil 25 del FIT del portafolio: 3 de cada 4 inversiones reales
    # del fondo lo superan. Si la calibración no tiene datos, se usa el valor inicial.
    fits = sorted(r["fit"] for r in port)
    umbral = fits[len(fits) // 4] if len(fits) >= 4 else config.FIT_THRESHOLD_DEFAULT
    hit_port = sum(1 for r in port if r["fit"] >= umbral)
    hit_ctrl = sum(1 for r in ctrl if r["fit"] < umbral)
    avg = lambda xs, k: round(sum(r[k] for r in xs) / max(len(xs), 1), 1)
    out = {
        "generado": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "umbral_fit": umbral,
        "fit_promedio_portafolio": avg(port, "fit"),
        "fit_promedio_controles": avg(ctrl, "fit"),
        "portafolio_aprobado": f"{hit_port}/{len(port)}",
        "controles_rechazados": f"{hit_ctrl}/{len(ctrl)}",
        "costo_usd": round(budget.spent, 2),
        "resultados": rows,
    }
    for path in (ROOT / "data" / "calibration.json", ROOT / "calibration.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nUmbral de fit sugerido: {umbral}/80 · portafolio sobre umbral: {out['portafolio_aprobado']} · "
          f"controles bajo umbral: {out['controles_rechazados']} · costo US${out['costo_usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
