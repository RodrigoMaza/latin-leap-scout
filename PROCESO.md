# Proceso: cómo se construyó Latin Leap Scout

Bitácora de las 48 horas del reto. Explica qué se decidió, por qué, qué falló y cómo se
corrigió. El *qué* cambió en cada paso está en el [historial de commits](https://github.com/RodrigoMaza/latin-leap-scout/commits/main);
este documento cuenta el *por qué*.

**Construido por:** Rodrigo Maza, con Claude (Anthropic) como herramienta de desarrollo.
**Horario:** hora de Ciudad de México. Las horas son aproximadas.

---

## Resumen en una línea por decisión

| Decisión | Alternativa descartada | Por qué |
|---|---|---|
| Sourcing **outbound** (salir a buscar startups) | Optimizar el inbound (formulario de aplicación) | El inbound solo crece si hoy se pierde demanda, y eso no se demuestra en 48 h. El outbound agrega startups que el fondo no ve y se mide desde la primera corrida. |
| **Calidad antes que volumen** | Entregar todo lo que se encuentre | Equipo de ~3 personas y ~15 inversiones por fondo: mandar 200 startups no sirve. |
| Tesis **inferida del portafolio real** | Un prompt genérico de "startup LATAM" | Las inversiones reales del fondo (Morado, Cubo, Rintin, PuntoPost…) revelan patrones que su web no dice. |
| **Equipo = 30 de 100 puntos** | Pesos iguales | El fondo dice públicamente que "la idea es el 1% y el equipo el 99%". |
| **Fit separado del timing** | Un solo puntaje | Una startup buena que acaba de levantar sigue siendo dealflow relevante; solo cambia cuándo contactarla. |
| Umbrales **calibrados con el portafolio** | Un número arbitrario | Nada cuenta si encaja peor que algo en lo que el fondo ya invirtió. |
| **Solo fuentes públicas** | Scraping de LinkedIn o Crunchbase | Sus términos lo prohíben. Es una decisión defendible. |
| **GitHub Actions + Claude API** | Servidor propio, herramientas no-code | Gratis, sin servidores, y la llave queda cifrada. Cada corrida deja registro auditable. |

---

## Viernes 23 de octubre

### 09:05 · Llega el reto: definir el problema antes de construir
- Meta: +10% sobre 60 deals/mes, es decir **6 deals adicionales al mes**. Es una meta chica; lo
  que de verdad se evalúa es la **relevancia** de lo que entra.
- Lo único no negociable es que funcione **sola**, con horario y sin operación manual.
- Decisión: **outbound**. Se planteó un "Scout" que recolecta, filtra, investiga, califica y
  entrega cada semana.

### 09:10 – 09:45 · Investigar a Latin Leap
- Fuentes públicas: Bloomberg Línea, Funds Society, Contxto, descubre.vc, f4.fund.
- **Hallazgos:** fondo de ~US$20M (US$25M según algunas fuentes); cheques de US$250–500K; pre-seed y
  seed; ~15 inversiones por fondo. Fundador: Stefan Krautwald (Dafiti, Farmalisto, Fluz,
  Cdiscount). Tienen la ambición de liderar inversiones en IA.
- **Revisión del portafolio en LinkedIn** (Rodrigo): Luable/MejorCDT, Keybe, Refurbi, Rintin,
  Morado, Cubo, Mutuus, PuntoPost, Alfred, TripWip, Agua Bendita, Bacu, Restb.ai.
- **Patrones identificados:**
  1. Fintech para pymes y segmentos desatendidos (Morado, Cubo, Luable).
  2. Infraestructura para el comercio pequeño y la logística (Rintin, PuntoPost).
  3. "El modelo probado, versión LATAM", por el ADN Rocket Internet del fundador (PuntoPost =
     el InPost de LATAM; Dafiti = el Zalando de LATAM).
  4. La geografía real es **toda LATAM hispanohablante** (Cubo en El Salvador, TripWip en
     Uruguay), no solo los 5 países que mencionan los directorios.
- Se excluyeron de la calibración Bacu (restaurante) y Agua Bendita (marca de ropa) por
  atípicos, y Restb.ai por ser de su otro mandato (llevar empresas extranjeras a LATAM).

### 09:45 – 10:07 · Infraestructura
- Cuenta de GitHub, cuenta en la Claude Console con US$5 de crédito prepagado y la
  **recarga automática desactivada**.
- API key con vencimiento al 31 de diciembre, guardada como *secret* cifrado en GitHub.

### 10:05 – 10:15 · Primera versión del código
- Recolectores (Google News con 22 búsquedas en español e inglés, directorio de Y Combinator),
  extracción, investigación web y calificación con Claude, deduplicación y dashboard.
- **Guardarraíl de costo:** el pipeline se detiene antes de pasar un tope por corrida.
- **Prueba simulada** (`offline_test.py`): corre todo el flujo sin internet ni API key.

### 10:30 – 11:30 · Subir a GitHub (y dos tropiezos)
- **GitHub no acepta archivos vacíos** al subir desde la web: se les puso contenido.
- **Los archivos perdieron sus carpetas al subirlos.** En lugar de repetir la subida, se
  reorganizó el proyecto para funcionar con todos los archivos en la raíz. Los workflows
  se crearon a mano dentro de `.github/workflows`.
- Se activó GitHub Pages para publicar el dashboard.

### 11:30 · Primera corrida: **falla**
- Error: al leer 40 titulares de golpe, la respuesta de Claude se cortó por longitud y el
  JSON quedó incompleto.
- **Corrección:** lotes más chicos. Si una respuesta llega cortada, el lote se parte en dos y
  se reintenta; si aun así falla, se omite y la corrida continúa.
- **Lección:** un sistema automatizado tiene que tolerar fallas parciales sin detenerse.

### 11:47 · Primera corrida exitosa
- 342 artículos → 191 menciones → 33 candidatas en tesis → 9 investigadas antes del tope de gasto.
- **Validación inesperada:** encontró por su cuenta a **Dapta**, empresa del portafolio de Latin Leap.
- **Problema:** ninguna startup llegó al umbral inicial (65/100), ni siquiera Dapta. El umbral
  era más exigente que el propio fondo.
- **Costo:** el estimado fue de US$1.16 y el gasto real en la consola, de US$0.52. El estimado es
  conservador a propósito; con ese dato se ajustó el tope.

### 11:51 · Rediseño del puntaje: fit vs. timing
- Causa del problema: las noticias de rondas traen startups que *acaban* de levantar, y la
  rúbrica les quitaba puntos por timing.
- **Decisión:** separar el **fit** con la tesis (0–80: equipo, sector, modelo, tracción) del
  **timing** (0–20), que solo define si la acción es "contactar ya" o "seguimiento".

### 12:07 · Calibración contra el portafolio
- Se corrió el calificador sobre **12 inversiones reales** (evaluadas como eran en su ronda
  semilla) y **3 controles fuera de tesis** (Loft, Glovo, Notion).
- Resultado: fit promedio de **52** en el portafolio contra **20** en los controles; los 3 controles
  quedaron descartados.
- **Umbral de prioridad = 49/80**, el nivel que superan 3 de cada 4 inversiones reales.
- Mutuus quedó en 38, por debajo del umbral: el fondo también decide por factores que no están
  en fuentes públicas. El calificador es un primer filtro, no una decisión.

### 12:32 · Segunda corrida y un error de filtro
- 25 startups investigadas. Prioridad: Cifrato (66), Platam (57), Rebill (57), Dapta (56) y Kiggu (49).
- **Error detectado:** se coló **Platomico, de España**. El modelo no aplicó bien el filtro de
  geografía.
- **Corrección:** el país se verifica ahora también **en el código**, no solo en el criterio de la IA.
  Lección: los filtros duros no se le dejan solo a un modelo.

### 12:50 – 13:03 · Limpieza y seguridad
- Se eliminaron los archivos duplicados que habían quedado de las subidas (`llm (1).py` y los
  workflows sueltos en la raíz).
- **Licencia "todos los derechos reservados"**: el código se publica solo para el proceso de
  selección.

### 13:37 · Página del umbral (`calibracion.html`)
- Muestra cómo se fija el umbral, la distribución del portafolio, de los controles y de los deals
  nuevos, y un control para moverlo en vivo y ver su efecto.

### 13:58 · Evaluador de empresas de eventos
- Idea de Rodrigo: evaluar una startup conocida en un mixer o evento pegando solo su sitio web.
- Workflow manual (`evaluar.yml`): lee el sitio, investiga, califica y la ubica frente al umbral.
  **Solo el dueño del repositorio puede correrlo**; la API key nunca toca la página.
- Las empresas de eventos **no cuentan en el KPI**, que mide solo lo que la herramienta encuentra sola.
- **Prueba con Marein.io:** quedó fuera de tesis porque figura como empresa de EE.UU. Lección:
  muchas startups LATAM se constituyen en EE.UU. Si se sabe que operan en LATAM, hay que decirlo
  en la nota del evento.

---

## Sábado 24 de octubre

### 10:12 · El KPI estaba inflado: se cambió
- El dashboard mostraba **+45%**, con 27 deals "en tesis" contra 60/mes.
- **Rodrigo cuestionó el número.** Incluía empresas que ningún VC llamaría deal (fundadores sin
  experiencia, deep tech intensiva en capital, fit menor a 30), una empresa que ya es del
  portafolio (Dapta) y un mes de noticias acumulado en la primera corrida.
- **Nueva definición de deal calificado:** en tesis, nuevo para el fondo y con **fit ≥ 38/80**,
  el fit de la inversión menos afín del portafolio. Nada cuenta si encaja peor que algo en lo que
  el fondo ya invirtió.
- **Resultado: +23.3%** (14 deals calificados, 4 de prioridad). Es la mitad del número anterior,
  pero ninguno se cae al revisarlo. La definición amplia (+45%) se sigue mostrando como
  referencia transparente.

---

## Quién hizo qué

| Rodrigo | Claude |
|---|---|
| Definir el problema y el alcance; elegir outbound | Proponer la arquitectura y escribir el código |
| Investigar al equipo y el portafolio en LinkedIn | Investigación de fuentes públicas sobre el fondo |
| Decisiones de criterio: tesis, fit vs. timing, KPI | Traducir esas decisiones a rúbrica y reglas |
| Cuestionar el +45% y exigir una métrica defendible | Recalcular y proponer la definición con piso |
| Proponer la página del umbral y el evaluador de eventos | Construirlos y probarlos |
| Configurar cuentas, subir, desplegar y correr cada workflow | Diagnosticar errores desde los registros y corregirlos |
| Revisar resultados y costos reales en la consola | Validar cada versión con pruebas simuladas y capturas |

---

## Limitaciones conocidas
- **No sabemos si el fondo ya conocía esas startups.** Es la principal limitación del KPI.
- **Dependencia de una fuente:** cerca de la mitad de las detecciones vienen de El Ecosistema Startup.
- **El score de equipo premia el pedigrí visible.** Si no encuentra información de los fundadores,
  limita el puntaje, lo que puede castigar a perfiles con poca presencia en medios.
- **Timing tardío:** la mayoría de las detecciones son anuncios de rondas ya cerradas. Sirven
  más como seguimiento para la siguiente ronda que como deals para hoy.

## Siguientes pasos
1. Botón "ya lo conocíamos" en el dashboard, para limpiar el KPI con retroalimentación del equipo.
2. Fuentes pre-ronda (cohortes de aceleradoras, demo days, lanzamientos) para llegar antes que
   otros fondos.
3. Separar el score de equipo en subcriterios y marcar "por verificar" en lugar de castigar la
   falta de información.
4. Conexión directa con el CRM del fondo.
