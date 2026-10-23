"""Las tres llamadas a Claude que hacen el trabajo de un analista.

1. extract()  — lee titulares en lote y extrae startups concretas (Haiku, barato).
2. research() — investiga cada candidata con búsqueda web: fundadores, rondas,
                tracción (Haiku + web search).
3. score()    — califica contra la tesis de Latin Leap con una rúbrica explícita
                (Sonnet). El puntaje total lo suma el código, no el modelo, para
                que sea reproducible y auditable.

Todas las llamadas pasan por Budget, que corta el pipeline antes de exceder
MAX_USD_PER_RUN.
"""
from __future__ import annotations

import json
import os
import time

import anthropic

import config


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, limit_usd: float):
        self.limit = limit_usd
        self.spent = 0.0
        self.searches = 0
        self.calls = 0

    def add(self, model: str, usage) -> None:
        pin, pout = config.PRICE.get(model, (3.0, 15.0))
        tokens_in = (getattr(usage, "input_tokens", 0) or 0) + \
            (getattr(usage, "cache_creation_input_tokens", 0) or 0) + \
            (getattr(usage, "cache_read_input_tokens", 0) or 0)
        tokens_out = getattr(usage, "output_tokens", 0) or 0
        self.spent += tokens_in / 1e6 * pin + tokens_out / 1e6 * pout
        stu = getattr(usage, "server_tool_use", None)
        n = (getattr(stu, "web_search_requests", 0) or 0) if stu else 0
        self.searches += n
        self.spent += n * config.PRICE_PER_WEB_SEARCH
        self.calls += 1

    def check(self, reserve: float = 0.0) -> None:
        if self.spent + reserve > self.limit:
            raise BudgetExceeded(f"Gasto estimado US${self.spent:.2f} alcanzó el límite")


_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("Falta ANTHROPIC_API_KEY (GitHub → Settings → Secrets → Actions)")
        _client = anthropic.Anthropic(max_retries=4)
    return _client


def _text(resp) -> str:
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


class BadOutput(Exception):
    """La respuesta llegó cortada o no es JSON válido."""


def _json_call(model: str, system: str, user: str, schema: dict, budget: Budget,
               max_tokens: int = 16000) -> dict:
    budget.check()
    resp = client().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": schema}},
    )
    budget.add(model, resp.usage)
    if resp.stop_reason == "max_tokens":
        raise BadOutput("respuesta cortada por límite de longitud")
    try:
        return json.loads(_text(resp))
    except json.JSONDecodeError as exc:
        raise BadOutput(f"JSON inválido: {exc}") from exc


# ---------------------------------------------------------------------------
# 1. Extracción
# ---------------------------------------------------------------------------
COUNTRY_ENUM = config.SPANISH_LATAM + ["Brasil", "Estados Unidos", "España", "Otro", "Desconocido"]

EXTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["startups"],
    "properties": {
        "startups": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["nombre", "pais", "descripcion", "etapa", "evento",
                             "monto_usd", "articulos"],
                "properties": {
                    "nombre": {"type": "string", "description": "Nombre de la startup tal como aparece"},
                    "pais": {"type": "string", "enum": COUNTRY_ENUM,
                             "description": "País de operación principal"},
                    "descripcion": {"type": "string", "description": "Qué hace, en una frase en español"},
                    "etapa": {"type": "string",
                              "enum": ["pre-seed", "seed", "series-a-o-mas", "desconocida"]},
                    "evento": {"type": "string",
                               "enum": ["levanto_ronda", "levantando", "lanzamiento",
                                        "aceleradora", "otro"]},
                    "monto_usd": {"anyOf": [{"type": "number"}, {"type": "null"}],
                                  "description": "Monto de la ronda en USD si se menciona"},
                    "articulos": {"type": "array", "items": {"type": "integer"},
                                  "description": "Índices [n] de los artículos que la mencionan"},
                },
            },
        }
    },
}

EXTRACT_SYSTEM = """Eres analista de venture capital en América Latina. Recibes titulares de noticias.
Extrae SOLO startups concretas y nombradas (no fondos de inversión, no corporativos grandes,
no aceleradoras ni gobiernos). Si un titular no menciona una startup específica, ignóralo.
Si una ronda es Serie A, B o posterior, o supera ~US$10M, marca etapa "series-a-o-mas".
Usa los nombres de país en español del catálogo. Sé conservador: no inventes datos."""


def _extract_range(articles: list, start: int, end: int, budget: Budget) -> list[dict]:
    """Extrae de articles[start:end]; si la respuesta falla, parte el lote en dos."""
    lines = [f"[{i}] {articles[i].title} — {articles[i].source} ({articles[i].published})"
             for i in range(start, end)]
    try:
        data = _json_call(config.MODEL_EXTRACT, EXTRACT_SYSTEM,
                          "Titulares:\n" + "\n".join(lines), EXTRACT_SCHEMA, budget)
        out = data.get("startups", [])
        for s in out:  # descarta índices fuera del lote
            s["articulos"] = [i for i in s.get("articulos", []) if start <= i < end]
        return out
    except BadOutput as exc:
        if end - start <= 5:
            print(f"   ! lote {start}-{end} omitido: {exc}")
            return []
        mid = (start + end) // 2
        return (_extract_range(articles, start, mid, budget)
                + _extract_range(articles, mid, end, budget))


def extract(articles: list, budget: Budget, batch_size: int = 25) -> list[dict]:
    found: list[dict] = []
    for i in range(0, len(articles), batch_size):
        found.extend(_extract_range(articles, i, min(i + batch_size, len(articles)), budget))
    return found


# ---------------------------------------------------------------------------
# 2. Investigación con búsqueda web
# ---------------------------------------------------------------------------
RESEARCH_SYSTEM = """Eres analista de venture capital. Investiga una startup latinoamericana con
búsqueda web y entrega notas concisas y verificables en español. Cubre:
- Sitio web y qué hace exactamente (cliente, modelo de negocio, cómo cobra).
- Fundadores: nombres, rol, experiencia previa (empresas, exits, estudios).
- Rondas e inversionistas conocidos, con montos y fechas.
- Tracción: clientes, ingresos, crecimiento, países donde opera.
- ¿Es la versión latinoamericana de un modelo probado en otro mercado? ¿Cuál?
Si algo no aparece en fuentes, escribe "no encontrado". No inventes. Máximo 250 palabras."""


def research(name: str, context: str, budget: Budget) -> tuple[str, list[str]]:
    """Devuelve (notas, urls_fuente). Si la búsqueda falla, regresa notas vacías."""
    budget.check(reserve=0.05)
    model = config.MODEL_RESEARCH
    messages = [{"role": "user", "content": f"Startup: {name}\nContexto: {context}"}]
    tools = [{"type": "web_search_20250305", "name": "web_search",
              "max_uses": config.SEARCHES_PER_CANDIDATE}]
    urls: list[str] = []
    notes = ""
    try:
        for _ in range(4):  # maneja pause_turn de turnos largos de búsqueda
            resp = client().messages.create(model=model, max_tokens=3000,
                                            system=RESEARCH_SYSTEM, messages=messages,
                                            tools=tools)
            budget.add(model, resp.usage)
            for b in resp.content:
                if getattr(b, "type", "") == "web_search_tool_result" and isinstance(b.content, list):
                    urls += [r.url for r in b.content if getattr(r, "url", None)]
            if resp.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": resp.content})
                continue
            notes = _text(resp).strip()
            break
    except BudgetExceeded:
        raise
    except Exception as exc:
        print(f"    ! investigación falló para {name}: {exc}")
    dedup = list(dict.fromkeys(urls))[:6]
    return notes, dedup


# ---------------------------------------------------------------------------
# 3. Calificación contra la tesis
# ---------------------------------------------------------------------------
RUBRIC = {
    "equipo": 30, "sector": 20, "modelo": 10, "traccion": 20, "etapa_timing": 20,
}

SCORE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["nombre", "website", "pais", "ciudad", "sector", "descripcion",
                 "modelo_comparable", "fundadores", "etapa", "estado_ronda",
                 "ultima_ronda", "traccion", "filtros", "puntajes", "tesis_match",
                 "riesgos", "accion", "mensaje_contacto", "confianza"],
    "properties": {
        "nombre": {"type": "string"},
        "website": {"type": "string", "description": "URL o cadena vacía"},
        "pais": {"type": "string", "enum": COUNTRY_ENUM},
        "ciudad": {"type": "string"},
        "sector": {"type": "string", "enum": config.SECTORS},
        "descripcion": {"type": "string", "description": "Qué hace, máx. 25 palabras"},
        "modelo_comparable": {"type": "string",
                              "description": "'El X de LATAM' si aplica, si no cadena vacía"},
        "fundadores": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["nombre", "antecedentes"],
            "properties": {"nombre": {"type": "string"},
                           "antecedentes": {"type": "string", "description": "máx. 20 palabras"}}}},
        "etapa": {"type": "string", "enum": ["idea", "pre-seed", "seed", "series-a-o-mas", "desconocida"]},
        "estado_ronda": {"type": "string",
                         "enum": ["levantando", "cerro_recientemente", "sin_info"]},
        "ultima_ronda": {"type": "string", "description": "Monto, fecha e inversionistas, o 'sin info'"},
        "traccion": {"type": "string", "description": "Señales concretas, máx. 25 palabras"},
        "filtros": {"type": "object", "additionalProperties": False,
                    "required": ["geografia", "etapa", "tecnologia"],
                    "properties": {"geografia": {"type": "boolean"},
                                   "etapa": {"type": "boolean"},
                                   "tecnologia": {"type": "boolean"}}},
        "puntajes": {"type": "object", "additionalProperties": False,
                     "required": list(RUBRIC),
                     "properties": {k: {"type": "integer", "description": f"0 a {v}"}
                                    for k, v in RUBRIC.items()}},
        "tesis_match": {"type": "string", "description": "Por qué encaja con Latin Leap, 1-2 frases"},
        "riesgos": {"type": "string", "description": "Principal riesgo o duda, 1 frase"},
        "accion": {"type": "string", "enum": ["contactar_ya", "seguimiento", "descartar"]},
        "mensaje_contacto": {"type": "string",
                             "description": "Borrador breve de primer contacto al founder, en español, 3-4 frases"},
        "confianza": {"type": "string", "enum": ["alta", "media", "baja"]},
    },
}

SCORE_SYSTEM = f"""Eres el Associate de Latin Leap que hace el primer filtro del dealflow.
Calificas startups contra esta tesis:

{config.THESIS}

RÚBRICA (entero por criterio):
- equipo (0-30): experiencia operativa relevante, exits, scale-ups de la región, equipo
  completo y complementario. Sin información de fundadores: máx. 10.
- sector (0-20): cercanía a los patrones del portafolio y a la ambición en IA.
- modelo (0-10): modelo probado en otro mercado ejecutado en LATAM ("el X de LATAM").
- traccion (0-20): ingresos, clientes, crecimiento. Sin evidencia: máx. 6.
- etapa_timing (0-20): 20 si levanta pre-seed/seed ahora; ~12 si cerró pre-seed hace
  poco (candidata a seed); ~8 si cerró seed hace poco (seguimiento/follow-on); 0 si
  es Serie A o posterior.

FILTROS DUROS: marca false si no opera principalmente en LATAM hispanohablante
(geografia), si es Serie A o posterior (etapa), o si no es de base tecnológica
(tecnologia). Si algún filtro es false, la acción es "descartar".

Sé exigente y honesto: un equipo pequeño solo quiere ver lo que vale su tiempo.
Basa todo en la evidencia proporcionada; si falta, baja la confianza."""


def score(profile: str, budget: Budget, calibration: bool = False) -> dict:
    user = profile
    if calibration:
        user += ("\n\nMODO CALIBRACIÓN: evalúa a la empresa como era en su ronda semilla. "
                 "Ignora su etapa actual: pon etapa_timing=20 y filtros.etapa=true.")
    data = _json_call(config.MODEL_SCORE, SCORE_SYSTEM, user, SCORE_SCHEMA, budget)
    # Normaliza: el código, no el modelo, decide el total
    pts = {k: max(0, min(v, int(data["puntajes"].get(k, 0)))) for k, v in RUBRIC.items()}
    data["puntajes"] = pts
    data["score"] = sum(pts.values())
    data["fit"] = data["score"] - pts["etapa_timing"]
    if not all(data["filtros"].values()):
        data["accion"] = "descartar"
        data["score"] = min(data["score"], 30)
        data["fit"] = min(data["fit"], 20)
    return data
