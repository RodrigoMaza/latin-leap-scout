"""Configuración central del Scout: tesis de Latin Leap, fuentes y límites de costo.

Todo lo que el equipo de inversión querría ajustar vive aquí, no en el código.
"""

# --------------------------------------------------------------------------
# Modelos (Claude API)
# --------------------------------------------------------------------------
MODEL_EXTRACT = "claude-haiku-5-5"    # alto volumen: leer titulares y extraer startups
MODEL_RESEARCH = "claude-haiku-5-5"   # investigar cada candidata con búsqueda web
MODEL_SCORE = "claude-sonnet-5-5"     # juicio de inversión: calificar contra la tesis

# Precios de referencia (USD por millón de tokens) para el guardarraíl de costo.
# Se usan cifras conservadoras: es mejor sobreestimar que quedarse sin crédito.
PRICE = {
    "claude-haiku-5-5": (1.0, 5.0),
    "claude-sonnet-5-5": (2.0, 10.0),
}
PRICE_PER_WEB_SEARCH = 0.01

# --------------------------------------------------------------------------
# Límites por corrida
# --------------------------------------------------------------------------
# Calibrado con la corrida 1: el estimado fue US$1.16 y el gasto real en la consola, US$0.52.
# El estimado sobrevalora ~2x, así que 2.50 estimados ≈ US$1.10 reales por corrida.
MAX_USD_PER_RUN = 2.50          # el pipeline se detiene antes de pasar este gasto (estimado)
MAX_CANDIDATES_PER_RUN = 25     # startups nuevas que se investigan y califican por corrida
SEARCHES_PER_CANDIDATE = 3      # búsquedas web por startup al investigarla
LOOKBACK_DAYS = 7               # ventana de noticias en corridas normales
LOOKBACK_DAYS_FIRST_RUN = 30    # primera corrida: llena el pipeline con el último mes
YC_RECENT_BATCH_YEARS = 2       # YC: solo batches de los últimos N años

# --------------------------------------------------------------------------
# Umbrales de calificación (puntaje 0-100)
# --------------------------------------------------------------------------
# El score total (0-100) = FIT con la tesis (equipo+sector+modelo+tracción, 0-80)
#                          + TIMING (etapa y momento de ronda, 0-20).
# - "Deal nuevo al pipeline": pasa los filtros de tesis y no se descarta (KPI vs. baseline).
# - "Prioridad": además, su FIT supera el umbral. El umbral se calibra con el portafolio
#   real (calibrate.py escribe data/calibration.json); este es solo el valor inicial.
FIT_THRESHOLD_DEFAULT = 50
BASELINE_DEALS_PER_MONTH = 60   # baseline dado por Latin Leap en el reto

# --------------------------------------------------------------------------
# Geografía: América Latina hispanohablante
# --------------------------------------------------------------------------
SPANISH_LATAM = [
    "México", "Colombia", "Argentina", "Chile", "Perú", "Uruguay", "Ecuador",
    "Bolivia", "Paraguay", "Venezuela", "Guatemala", "Costa Rica", "Panamá",
    "El Salvador", "Honduras", "Nicaragua", "República Dominicana", "Puerto Rico",
]
# Nombres en inglés tal como aparecen en el directorio de YC
YC_SPANISH_LATAM = {
    "Mexico", "Colombia", "Argentina", "Chile", "Peru", "Uruguay", "Ecuador",
    "Bolivia", "Paraguay", "Venezuela", "Guatemala", "Costa Rica", "Panama",
    "El Salvador", "Honduras", "Nicaragua", "Dominican Republic", "Puerto Rico",
}

# --------------------------------------------------------------------------
# Fuentes: Google News RSS (consultas públicas, sin scraping de sitios cerrados)
# Cada consulta se combina con "when:Nd" para limitar a noticias recientes.
# --------------------------------------------------------------------------
NEWS_QUERIES_ES = [
    '"pre-semilla" startup',
    '"presemilla" startup',
    '"ronda semilla" startup',
    'startup "levanta" ronda inversión',
    'startup "cierra ronda"',
    'startup "recauda" millones dólares ronda',
    '"startup mexicana" ronda',
    '"startup colombiana" ronda',
    '"startup chilena" ronda',
    '"startup peruana" ronda',
    '"startup argentina" ronda',
    '"startup uruguaya" OR "startup ecuatoriana" OR "startup guatemalteca" ronda',
    'fintech latinoamérica ronda semilla',
    'aceleradora startups seleccionadas latinoamérica',
    'site:contxto.com ronda',
    'site:latamlist.com',
    'site:bloomberglinea.com startup ronda',
]
NEWS_QUERIES_EN = [
    '"pre-seed" startup Mexico OR Colombia OR Chile OR Peru OR Argentina',
    '"seed round" startup "Latin America"',
    'Mexican startup raises',
    'Colombian startup raises',
    'Chilean startup raises',
]
# (hl, gl, ceid) de Google News: español LatAm y edición en inglés
NEWS_EDITION_ES = ("es-419", "MX", "MX:es-419")
NEWS_EDITION_EN = ("en-US", "US", "US:en")

# --------------------------------------------------------------------------
# Portafolio conocido de Latin Leap: se marca si una startup ya es del fondo
# y se usa para calibrar el calificador.
# --------------------------------------------------------------------------
PORTFOLIO = [
    "Luable", "MejorCDT", "Keybe", "Refurbi", "Rintin", "Morado", "Cubo",
    "Mutuus", "PuntoPost", "Alfred", "Magneto", "Dapta", "TripWip",
    "Habi", "Talently", "Vozy", "Restb.ai", "Agua Bendita", "Bacu",
]

# --------------------------------------------------------------------------
# Tesis (se inyecta en el prompt del calificador)
# --------------------------------------------------------------------------
THESIS = """
LATIN LEAP — TESIS DE INVERSIÓN (inferida de fuentes públicas y del portafolio)

Fondo: VC studio de ~US$20M con base en Medellín y presencia en CDMX. Equipo pequeño
(socio fundador Stefan Krautwald, ex-operador de e-commerce: cofundó Dafiti LATAM,
Farmalisto y Fluz; fue director de Cdiscount Latam). Invierte en pre-seed y seed,
cheques iniciales de ~US$250K-500K, con capacidad de follow-on. Planea ~15 inversiones
por fondo, así que cada deal debe ser de alta convicción.

FILTROS DUROS
- Geografía: la empresa opera principalmente en América Latina hispanohablante
  (incluye México, Colombia, Perú, Chile, Argentina, Uruguay, Centroamérica, Caribe
  hispano). Brasil-only, EE.UU.-only o España-only quedan fuera.
- Etapa: pre-seed o seed. Series A o posterior queda fuera.
- Base tecnológica: tecnología como catalizador del negocio.

LO QUE MÁS PESA (en orden)
1. EQUIPO. El fondo dice que "la idea es el 1% y el equipo el 99%". Valoran fundadores
   con experiencia operativa relevante, exits previos, paso por scale-ups de la región
   (Rappi, Mercado Libre, Kavak, Nubank, Clip, Konfío, Platzi, etc.), complementariedad
   técnica/comercial y equipo completo.
2. SECTOR. Patrones del portafolio real:
   - Fintech para pymes y segmentos desatendidos (Morado: negocios liderados por mujeres;
     Cubo: aceptación de pagos para mipymes en El Salvador; Luable/MejorCDT: inversión).
   - Infraestructura para el comercio pequeño y logística (Rintin: tienditas conectadas
     a proveedores en CDMX; PuntoPost: entrega e-commerce a puntos de recolección).
   - E-commerce / consumo con fuerte canal digital (Refurbi, Agua Bendita).
   - IA aplicada / SaaS B2B (Keybe, Dapta), PropTech (Habi), HR-tech (Magneto, Talently).
   - Ambición declarada de liderar inversiones en inteligencia artificial.
3. MODELO PROBADO, VERSIÓN LATAM. ADN Rocket Internet del fundador: les atraen modelos
   que ya funcionaron en otro mercado ejecutados en la región (PuntoPost = "el InPost
   de LATAM"; Dafiti = "el Zalando de LATAM").
4. TRACCIÓN. Para seed esperan ventas y tracción reales; para pre-seed, señales tempranas
   (pilotos, clientes pagando, crecimiento).
5. TIMING. Lo ideal es una startup que está levantando o levantará pronto su pre-seed/seed.
""".strip()

SECTORS = [
    "Fintech", "Insurtech", "E-commerce / Retail", "Logística / Movilidad",
    "B2B Commerce / Supply", "PropTech", "HealthTech", "EdTech", "HR-tech",
    "IA / SaaS B2B", "AgTech", "ClimateTech", "Consumo / Marketplace", "Otro",
]
