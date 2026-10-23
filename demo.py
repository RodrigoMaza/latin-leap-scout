"""Datos ficticios SOLO para probar el dashboard sin gastar API (--dry-run).

Nunca se guardan en data/ ni se publican: la vista previa se escribe en _preview/.
"""
from datetime import date


def demo_deals() -> list[dict]:
    today = date.today().isoformat()
    base = {
        "first_seen": today, "last_seen": today, "en_portafolio": False,
        "fuentes_investigacion": [], "confianza": "media", "ciudad": "",
        "filtros": {"geografia": True, "etapa": True, "tecnologia": True},
        "mensaje_contacto": "Hola, soy del equipo de Latin Leap. (ejemplo)",
    }
    rows = [
        ("Ejemplo Pagos", "México", "Fintech", 84, "contactar_ya", "levantando",
         {"equipo": 26, "sector": 18, "modelo": 8, "traccion": 14, "etapa_timing": 18}),
        ("Ejemplo Logística", "Colombia", "Logística / Movilidad", 72, "contactar_ya",
         "cerro_recientemente",
         {"equipo": 22, "sector": 16, "modelo": 9, "traccion": 13, "etapa_timing": 12}),
        ("Ejemplo SaaS", "Chile", "IA / SaaS B2B", 58, "seguimiento", "sin_info",
         {"equipo": 15, "sector": 15, "modelo": 3, "traccion": 9, "etapa_timing": 16}),
        ("Ejemplo Brasil", "Brasil", "Fintech", 30, "descartar", "sin_info",
         {"equipo": 18, "sector": 15, "modelo": 5, "traccion": 10, "etapa_timing": 10}),
    ]
    out = []
    for name, pais, sector, score, accion, estado, pts in rows:
        d = dict(base)
        d.update({
            "key": name.lower().replace(" ", ""), "nombre": name, "pais": pais,
            "sector": sector, "score": score, "accion": accion, "estado_ronda": estado,
            "puntajes": pts, "etapa": "seed", "website": "",
            "descripcion": "Startup ficticia para probar la interfaz.",
            "modelo_comparable": "", "ultima_ronda": "sin info", "traccion": "n/d",
            "tesis_match": "Dato de ejemplo.", "riesgos": "Dato de ejemplo.",
            "fundadores": [{"nombre": "Fundador Ejemplo", "antecedentes": "ex-Rappi"}],
            "origen": "noticias",
            "menciones": [{"title": f"{name} levanta ronda (ejemplo)", "url": "",
                           "source": "Demo", "date": today}],
        })
        d["filtros"] = {"geografia": pais != "Brasil", "etapa": True, "tecnologia": True}
        out.append(d)
    return out
