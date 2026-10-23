"""Prueba de punta a punta SIN internet ni API key.

Simula Google News, el directorio de YC y la API de Claude, y verifica que el
pipeline completo (recolectar → extraer → filtrar → investigar → calificar →
publicar) funciona y respeta los filtros de tesis.

Uso:  python -m tests.offline_test
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import anthropic
try:
    import httpx2 as httpx
except ImportError:  # versiones anteriores del SDK usan httpx
    import httpx

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Pagofácil, startup mexicana de pagos para tienditas, levanta US$1.5M en ronda pre-semilla - Contxto</title>
<link>https://example.com/a1</link><pubDate>{d}</pubDate><source url="https://contxto.com">Contxto</source>
<description>La fintech mexicana...</description></item>
<item><title>Ruta9, startup colombiana de logística, cierra ronda semilla de US$3M - LatamList</title>
<link>https://example.com/a2</link><pubDate>{d}</pubDate><source url="https://latamlist.com">LatamList</source></item>
<item><title>BrasilPay, fintech brasileña, levanta Serie B de US$40M - Valor</title>
<link>https://example.com/a3</link><pubDate>{d}</pubDate><source url="https://valor.com">Valor</source></item>
</channel></rss>"""

YC = [{"name": "Altur", "website": "https://altur.ai", "all_locations": "Mexico City, CDMX, Mexico",
       "one_liner": "Voice AI agents for debt collection", "long_description": "…",
       "batch": "Summer 2025", "team_size": 9, "url": "https://ycombinator.com/companies/altur",
       "tags": ["AI"], "regions": ["Mexico", "Latin America"], "status": "Active"},
      {"name": "OldCo", "regions": ["Mexico"], "status": "Active", "batch": "Winter 2015"}]

EXTRACTED = {"startups": [
    {"nombre": "Pagofácil", "pais": "México", "descripcion": "Pagos para tienditas",
     "etapa": "pre-seed", "evento": "levanto_ronda", "monto_usd": 1500000, "articulos": [0]},
    {"nombre": "Ruta9", "pais": "Colombia", "descripcion": "Logística de última milla",
     "etapa": "seed", "evento": "levanto_ronda", "monto_usd": 3000000, "articulos": [1]},
    {"nombre": "BrasilPay", "pais": "Brasil", "descripcion": "Pagos",
     "etapa": "series-a-o-mas", "evento": "levanto_ronda", "monto_usd": 40000000, "articulos": [2]},
]}


def score_json(name: str) -> dict:
    return {
        "nombre": name, "website": f"https://{name.lower()}.com", "pais": "México",
        "ciudad": "CDMX", "sector": "Fintech", "descripcion": "desc", "modelo_comparable": "",
        "fundadores": [{"nombre": "Ana", "antecedentes": "ex-Clip"}], "etapa": "pre-seed",
        "estado_ronda": "cerro_recientemente", "ultima_ronda": "US$1.5M", "traccion": "200 tiendas",
        "filtros": {"geografia": True, "etapa": True, "tecnologia": True},
        "puntajes": {"equipo": 99, "sector": 18, "modelo": 7, "traccion": 12, "etapa_timing": 12},
        "tesis_match": "encaja", "riesgos": "competencia", "accion": "contactar_ya",
        "mensaje_contacto": "Hola", "confianza": "media",
    }


def fake_api(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    usage = {"input_tokens": 1000, "output_tokens": 200}
    if "tools" in body:  # investigación
        assert body["tools"][0]["type"] == "web_search_20250305"
        content = [{"type": "text", "text": "Notas de investigación."}]
        usage["server_tool_use"] = {"web_search_requests": 2}
    else:
        schema = body["output_config"]["format"]["schema"]
        if "startups" in schema["properties"]:
            payload = EXTRACTED
        else:
            name = body["messages"][0]["content"].split("\n")[0].replace("STARTUP: ", "")
            payload = score_json(name)
        content = [{"type": "text", "text": json.dumps(payload)}]
    return httpx.Response(200, json={
        "id": "msg_x", "type": "message", "role": "assistant", "model": body["model"],
        "content": content, "stop_reason": "end_turn", "stop_sequence": None, "usage": usage})


def fake_get(url, **kw):
    r = mock.Mock()
    r.raise_for_status = lambda: None
    if "news.google.com" in url:
        from email.utils import format_datetime
        from datetime import datetime, timezone
        r.content = RSS.format(d=format_datetime(datetime.now(timezone.utc))).encode()
    else:
        r.json = lambda: YC
    return r


def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    os.environ["ANTHROPIC_API_KEY"] = "test"
    from scout import config, llm, main as pipeline, store
    store.ROOT = tmp
    store.DATA = tmp / "data"
    store.DEALS_FILE = store.DATA / "deals.json"
    store.STATE_FILE = store.DATA / "state.json"
    llm._client = anthropic.Anthropic(api_key="test",
                                      http_client=httpx.Client(transport=httpx.MockTransport(fake_api)))
    config.NEWS_QUERIES_ES = config.NEWS_QUERIES_ES[:1]
    config.NEWS_QUERIES_EN = []
    with mock.patch("scout.sources.requests.get", fake_get), \
            mock.patch("scout.sources.time.sleep", lambda s: None):
        pipeline.run()
        deals = json.loads((tmp / "data" / "deals.json").read_text())
        names = {d["nombre"] for d in deals}
        assert names == {"Pagofácil", "Ruta9", "Altur"}, names           # Brasil y Serie B filtrados
        assert all(d["puntajes"]["equipo"] <= 30 for d in deals)          # rúbrica acotada
        assert all(d["score"] == sum(d["puntajes"].values()) for d in deals)
        # Segunda corrida: no re-evalúa lo ya visto (dedupe)
        pipeline.run()
        st = json.loads((tmp / "data" / "state.json").read_text())
        assert st["runs"][-1]["evaluated"] == 0, st["runs"][-1]
        data = json.loads((tmp / "docs" / "data.json").read_text())
        assert data["kpis"]["calificadas_30d"] == 3
        print("OK — pipeline completo:", sorted(names))
        print("   costo simulado por corrida: US$", st["runs"][0]["cost_usd"])
        print((tmp / "reports" / "latest.md").read_text()[:300])
    shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
