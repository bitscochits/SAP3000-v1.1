# SAP3000 — Laboratorio estructural digital del Edificio de Ingeniería

Grupo 7 · Métodos Computacionales en Obras Civiles · UAndes, 2026-02.

El **Edificio de Ingeniería de la UAndes** modelado desde sus planos,
resuelto con OpenSees, verificado numéricamente y mostrado en Unity (la
app de Windows y la build Web del teléfono), con realidad aumentada en
el iPhone y en Excel.

> Para agentes de IA: las reglas, las convenciones y las trampas están en
> `CLAUDE.md`. El contrato entre Python, Unity, el servidor y la AR está en
> `CONTRATO.md`.

---

## 1. Qué es: un edificio, dos cuerpos

El edificio son **dos cuerpos** construidos en dos etapas y separados por
una junta de dilatación. Acá son **un solo edificio**, en un solo modelo
(`entrada/edificio.json`), y todo el programa trabaja sobre él: no hay un
"modo LT2" ni un "modo Ingeniería".

| | planos | tags | nodos | elementos | G (kN) |
|---|---|---|---|---|---|
| cuerpo antiguo (`ingenieria`) | 2017_67 | 1xxxxx | 331 | 572 | 64579.8816 |
| LT2 (`lt2`) | 2024_22 | 2xxxxx | 232 | 378 | 34148.9792 |
| **el edificio** (`conjunto`) | | | **563** | **950** | **98728.8608** |

- 47 secciones (44 de hormigón, cada una con el `f'c` de su cuerpo), 10
  diafragmas rígidos, 4 casos de carga propios del modelo (G, Q, EX, EY).
- La **junta** mide 0.050 m cara a cara y es **libre**: ningún elemento,
  diafragma ni brazo la cruza. Cada cuerpo, resuelto dentro del edificio,
  da lo mismo que resuelto solo, dentro del redondeo (lo comprueba
  `E2 edificio: junta libre`).
- El cuerpo de un elemento se lee en su tag: `calculo.edificio.cuerpo_de(tag)`
  (1xxxxx el antiguo, 2xxxxx el LT2).

**La regla de oro**, que no se rompe:

```
entrada/  →  Python + OpenSees CALCULA  →  salidas/ (JSON y Excel)  →  Unity, la AR y Excel MUESTRAN
```

Unity, el teléfono y Excel no calculan estructura: dibujan lo que Python
dejó escrito. Hay **dos excepciones declaradas**, las dos sumas de casos ya
resueltos por OpenSees y cada una con su guardia: los sliders
instantáneos de la superposición y la deformada de la persona
(`CONTRATO.md` §10).

La lectura de los planos DXF, los informes semanales y la historia del
curso quedaron en **SAP3000 v1.0**. `entrada/edificio.json` es lo que salió
de esos planos, con todo lo que el plano no dice declarado como supuesto en
su bloque `supuestos`.

---

## 2. Instalar

Una vez, desde la carpeta del proyecto, en PowerShell:

```powershell
.\setup.ps1
```

Crea el entorno virtual `.venv`, instala `requirements.txt` con las
versiones **fijas** que dieron los números de control (openseespy 3.8.0.0,
numpy 2.5.3, Flask 3.1.3, openpyxl 3.1.5, matplotlib 3.11.2, pillow 12.3.0)
y revisa si está Unity.

- Si PowerShell responde que la ejecución de scripts está deshabilitada:
  `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` en esa misma
  terminal, y de nuevo `.\setup.ps1`.
- Hace falta Python 3.12 del sistema (python.org, con "Add python.exe to PATH").
- **Unity 6000.5.10f1**, desde Unity Hub y en esa versión exacta: abrir el
  proyecto con otra hace que Unity migre los assets. El cálculo y casi toda
  la suite corren sin Unity.
- Para la AR: Chrome o Edge (compilan el marcador y prueban la app sin
  ventana) y el `openssl` que trae Git for Windows (el certificado https).

Todo se corre **desde la raíz** y **con el Python del proyecto**:

```powershell
.\.venv\Scripts\Activate.ps1      # en cada terminal nueva (o usar .\.venv\Scripts\python.exe)
python sap.py                     # el flujo, el estado de las salidas y los comandos
```

`python` a secas, sin activar `.venv`, es el del computador y falla con
`No module named 'openseespy'`.

---

## 3. El flujo, en una línea, y los comandos

```
entrada/edificio.json + entrada/laboratorio.json → calculo/ (Python + OpenSees) → exportar/ → salidas/ → sincronizar → Unity · AR · Excel
```

Lo mínimo para ver el edificio:

```powershell
python sap.py preparar      # calcular + exportar todo + sincronizar (unos minutos)
python sap.py unity app     # abre el visor (la primera vez compila la app)
python sap.py servidor      # en otra terminal, opcional: superposición LIBRE y reanálisis
python sap.py verificar     # la suite: 42 comprobaciones
```

`python sap.py` sin nada imprime el flujo, qué salidas faltan o quedaron
viejas respecto de `entrada/`, si las copias de Unity y de la AR están al
día, y la lista de comandos. Códigos de salida: 0 bien, 1 algo falló, 2 no
se pudo correr.

### Todos los comandos

| comando | qué hace |
|---|---|
| `python sap.py calcular [--caso G]` | resuelve en OpenSees los 4 casos **del modelo** (G, Q, EX, EY de `edificio.json`) → `salidas/casos_del_modelo.json`. Imprime la carga aplicada, la mayor componente y el equilibrio de cada caso |
| `python sap.py exportar <modelo\|resultados\|carga_movil\|persona\|relieve\|excel\|ar\|todo> [flags]` | arma lo que leen Unity, la AR y Excel → `salidas/`. `todo` arma la base del laboratorio **una vez** para los resultados, el Excel y la AR |
| `python sap.py sincronizar [--seco] [--destino CARPETA]` | copia `salidas/` a las StreamingAssets de Unity (el proyecto y cada build que exista) y `ar.json` a `ar/web/datos/`. Solo lo que cambió (md5), de forma atómica |
| `python sap.py preparar [--seco] [--sin-persona] [flags]` | `calcular` + `exportar todo` + `sincronizar`. La carga móvil y la persona son opcionales: si fallan, avisan y el resto sigue |
| `python sap.py servidor [--lan] [--puerto 5000] [--sin-precalentar] [flags]` | el servidor para Unity: `/ping`, `/analizar`, `/combinar`, `/estados` (`CONTRATO.md` §3). `--lan` lo abre a la red local (teléfono, build Web) |
| `python sap.py unity <app\|editor\|build\|web\|android\|compilar>` | `app` compila (una vez) y abre la app de Windows; `editor` abre el proyecto; `build`, `web` y `android` compilan (Unity cerrado); `compilar` compila los C# sin abrir Unity. Opciones: `--forzar`, `--seco`, `--pantalla-completa`, `--preparar` (corre `preparar` antes) |
| `python sap.py capturar <visor\|diagramas\|persona\|relieve> [--carpeta C] [--sin-servidor] [--seco]` | la app compilada saca sus fotos y su `registro.txt` en `verificacion/registros/capturas/<modo>/`, y después se compara con Python |
| `python sap.py ar <servir\|marcador\|precision>` | la app de realidad aumentada: servirla al teléfono, armar el marcador, el presupuesto de error del registro (§9) |
| `python sap.py revisar <tema>` | las herramientas para explicar y defender (tabla de abajo) |
| `python sap.py verificar [--rapido] [--solo palabra ...] [--lista]` | la suite (§10) |
| `python sap.py recursos [--verificar]` | vista realista: el giro del cielo, los mapas de detalle, las licencias (§7) |
| `python sap.py atst [--verificar]` | el AT-ST de la pestaña Persona: `unity/FuentesPersonaje` → `Resources/Personaje/atst.json` |

**Los parámetros del laboratorio** (`[flags]`) son los que dicta el profesor:
`--q`, `--uso`, `--cs`, `--fq`, `--patron`, `--k`, `--fracciones`, `--comb`,
`--combinacion`. Cambian lo que se calcula **en esa corrida** y nunca
escriben `entrada/laboratorio.json`. Un flag mal escrito corta antes de
correr nada.

```powershell
python sap.py revisar parametros --cs 0.15 --patron nch433   # cómo quedan, sin calcular nada
python sap.py exportar excel --cs 0.20                         # el Excel con otro Cs
python sap.py servidor --cs 0.20                               # /combinar sobre otra base
```

`--uso` elige la fila de NCh1537 Of.2009 Tabla 4 (`--uso oficinas` pone
q = 2.5 kN/m²); un `--q` cualquiera queda marcado como dictado.

### `python sap.py revisar <tema>`

| tema | qué muestra |
|---|---|
| `parametros [flags]` | las líneas de `describir()` (la huella que viaja en cada salida) y las 11 combinaciones |
| `laboratorio [flags]` | las Partes A, B y C: q·A, corte basal y superposición |
| `sismo [EX\|EY] [--detalle]` | el sismo de los casos del modelo: corte, sentido, torsión de piso, centro de rigidez |
| `superposicion [--lambdas G Q EX EY \| --explicita]` | un caso combinado cualquiera, o las 11 combinaciones contra OpenSees resolviendo la carga combinada |
| `capacidad <elem> [--pm --mphi --dibujo --sensibilidad]` | la sección de fibras de una columna o muro: M-φ y curva P-M |
| `demanda <elem>\|--todas\|--lista [--comb G Q EX EY] [--grafico --mphi]` | el punto (P, M) sobre su curva, para uno o para todos |
| `rc [elem]` | fibras contra el cálculo a mano (Whitney, β₁, balanceado) |
| `nucleos` | los grupos de patas de núcleo y su axial |
| `losa-colaborante` | la regla de la viga T escrita y **no** conectada (solo informa) |
| `viga-partida [nodo]` | refinar una viga no cambia la flecha: el nodo compartido no es una rótula |
| `m1 [--float32] [--url] [--desde]` | borrar la columna 200069 y reanalizar, sin Unity |
| `m2 [--cs 0.20]` | cambiar Cs sin escribir nada |
| `m3`, `m4` | cambiar la sección de la viga 200337; soltar los giros del apoyo 200002 |
| `trazabilidad <elem> [--caso]` | la cadena OpenSees → modelo → GameObject → resultados → capacidad |
| `qa [--salida ARCHIVO]` | la tabla de QA de 10 filas para la defensa |

Los ids por defecto (200069, 200186, 200337, 200002...) salen de
`entrada/laboratorio.json`, bloque `modificaciones`.

---

## 4. Mapa de carpetas

```
SAP3000 v1.1/
  sap.py  setup.ps1  requirements.txt  README.md  CLAUDE.md  CONTRATO.md
  entrada/       lo ÚNICO que se edita a mano
  calculo/       Python + OpenSees: lo único que calcula
  exportar/      arma un archivo por consumidor, y el servidor
  salidas/       GENERADO (no se edita, no va a git)
  unity/         el visor
  ar/            la app de realidad aumentada
  verificacion/  la suite y los números de control
  herramientas/  abrir y compilar Unity, recursos de la vista realista, el AT-ST
  build/         GENERADO por Unity (las apps compiladas)
```

### `entrada/`

| archivo | qué es |
|---|---|
| `edificio.json` | el edificio: la **estructura** (material, secciones, nodos, elementos, diafragmas, brazos, los 4 casos del modelo), la **vista** (áreas tributarias, cota del terreno y terrazas: solo dibujo) y los **supuestos** (calce entre los planos, junta, lo que cada plano no dice, problemas conocidos del dato) |
| `laboratorio.json` | lo que define el laboratorio: `parametros` (q, sismo, las 11 combinaciones), `superposicion` (E1..E3, rangos de los sliders, elementos de control), `modificaciones` (M1..M4), `carga_movil` y `ar` (dónde se pega la imagen) |
| `sitio/` | el relieve: `sitio.json` (supuestos), el DEM Copernicus GLO-30 y los dos `.kmz` de Google Earth |

### `calculo/` (nunca importa `exportar/`)

| módulo | qué hace |
|---|---|
| `rutas` | el único que sabe dónde está cada cosa; encuentra la raíz subiendo hasta `setup.ps1` + `sap.py` |
| `edificio` | lee `edificio.json`; tags por cuerpo (`cuerpo_de`, `por_cuerpo`), niveles, ejes locales (`ejes_locales`, `vecxz_por_defecto`), `validar()` |
| `opensees` | el motor: `construir_modelo`, `aplicar_cargas`, `resolver_caso`, `extraer_resultados` (`localForce`, redondeo), `equilibrio()` por grado de libertad, `Resolutor` |
| `laboratorio` | los parámetros y los casos del laboratorio: Q por área tributaria, EX y EY con el patrón en altura, combinaciones |
| `capacidad` | la sección de fibras: M-φ, curva P-M nominal (ε_c = 0.003), confinamiento de Mander |
| `demanda` | el (P, M) de cada columna o muro sobre su curva; familias P-M; los grupos de núcleo |
| `esfuerzos` | los esfuerzos internos a lo largo de cada barra, reconstruidos y cerrados contra `f_j` de OpenSees |
| `superposicion` | `R = Σ λ·R` y su prueba contra una corrida explícita; la base de `/combinar` |
| `sismo` | un caso lateral: corte basal, sentido, torsión (cociente NCh433), centro de rigidez |
| `elastica` | la elástica de una barra con las funciones de forma (la que transcribe el C#) |
| `losa_colaborante` | la regla de la viga T (ACI), escrita y sin conectar |

### `exportar/`

| módulo | escribe | lo lee |
|---|---|---|
| `modelo` | `salidas/modelo.json`, `salidas/casos_del_modelo.json` | el visor (`VisorEstructura`) |
| `resultados` | `salidas/resultados.json` (los 15 casos del laboratorio, E1..E3, cargas y armadura) | `VisorResultados`, `VisorCargasYArmadura` |
| `carga_movil` | `salidas/carga_movil.json` | `VisorCargaMovil` |
| `persona` | `salidas/persona.json` (lento: unos 2 min) | `VisorPersona` |
| `relieve` | `salidas/relieve.json` | `AmbienteVisor` |
| `excel` | `salidas/resultados.xlsx` (y el del reanálisis) | el botón "Abrir Excel de resultados" |
| `ar` | `salidas/ar.json` | la app AR (`ar/web/datos/ar.json`) |
| `sincronizar` | las copias de StreamingAssets y de `ar/web/datos` | — |
| `servidor` | `salidas/reanalisis.xlsx` en cada `/analizar` | Unity, en vivo |

### `salidas/`

Todo lo genera `python sap.py preparar` (o cada `exportar`): `modelo.json`,
`resultados.json`, `carga_movil.json`, `persona.json`, `relieve.json` y
`resultados.xlsx` (lo que lee Unity), `ar.json` (lo que lee el teléfono),
`casos_del_modelo.json` (los 4 casos del modelo resueltos),
`reanalisis.xlsx` (el último `/analizar`) y `figuras/`. No se edita a mano
ni va a git: si algo está mal, se corrige en `entrada/` o en el código y se
vuelve a generar.

### `herramientas/`

| módulo | comando | qué hace |
|---|---|---|
| `lanzador` | `python sap.py unity <modo>`, `python sap.py capturar <modo>` | abrir, compilar y capturar el visor sin tocar el editor; compilar los C# sin Unity |
| `recursos_realistas` | `python sap.py recursos` | el giro del cielo, el HDR con suelo y los mapas de detalle de la vista realista, y sus verificaciones |
| `atst` | `python sap.py atst` | el AT-ST de la pestaña Persona, de `unity/FuentesPersonaje` a `Resources/Personaje/atst.json` |

### `unity/`

`Assets/Scripts/` por función: `Modelo/` (el modelo, el dibujo, la cámara,
los eventos, la lectura de StreamingAssets), `Panel/` (el panel y sus
estilos), `Resultados/` (casos, diagramas, P-M, mapa D/C, superposición,
cargas y armadura), `Ambiente/` (vista realista, losas, terrazas, relieve),
`Modificar/` (editor y cliente del reanálisis), `CargaMovil/`, `Persona/`,
`Capturas/`. `Assets/Editor/` tiene el menú **Laboratorio** del editor
(configurar escena, construir las apps, recursos de la vista realista,
verificar la lectura de los JSON). `Assets/StreamingAssets/` son
**copias**: las deja `sincronizar`, no se editan.

### `ar/`

`web/` es la app que corre en el teléfono (`index.html`, `ar.js`,
`estilo.css`, MindAR y three.js en `vendor/`, `datos/ar.json`,
`targets.mind`); `marcador/` tiene la foto base y el PDF para imprimir;
`servir.py` y `marcador.py` son los programas del PC.

### `verificacion/`

`suite.py` (la lista de las 42 entradas y la tabla QA),
`numeros_de_control.json` (los números que no pueden cambiar sin una
decisión) y un módulo por tema (`edificio`, `motor`, `laboratorio`,
`capacidad`, `resultados`, `persona`, `unity`, `excel`, `capturas`, `ar`).
`registros/` guarda lo que la app y el navegador escriben **para** la
suite: las capturas con su `registro.txt`, el tracking de la AR y las
fotos del iPhone. La suite nunca escribe en `salidas/`.

---

## 5. El visor (Unity)

```powershell
python sap.py preparar                       # si cambió algo en entrada/
python sap.py unity app --pantalla-completa  # la app de Windows
python sap.py servidor                       # otra terminal: LIBRE y reanálisis
```

**Controles:** clic selecciona nodo, barra o símbolo de apoyo; arrastrar
orbita; botón derecho o medio mueve; rueda acerca; `F` encuadra todo; `C`
centra la selección; `Esc` la suelta; `H` oculta el panel. En el teléfono,
un dedo orbita y dos hacen pinza y paneo. Ninguna tecla actúa con el foco
en un campo de texto.

Lo que hay en el visor sale de cinco archivos y un Excel de
StreamingAssets (los nombres y las clases C# que los leen están en
`CONTRATO.md` §1), y de las respuestas del servidor.

### La cabecera (siempre visible)

El edificio y sus conteos, el caso activo, "Desp. max" (la **norma** del
mayor desplazamiento del caso), **NO PASA n/m** (los elementos con fierro
que no pasan en ese caso), los avisos (por ejemplo, resultados
desactualizados después de editar), la selección y el botón **Abrir Excel
de resultados**. Si lo que se ve **no** es un caso de los resultados (un
reanálisis o la carga móvil), la cabecera lo dice y cambia el rótulo a
"Max. componente" (la mayor componente, que es lo que da el servidor).
Datos: `resultados.json`, la respuesta de `/analizar`, `carga_movil.json`.
Guardia: `K1 capturas: visor` (registra de qué fuente es cada número de la
cabecera).

### Las pestañas

| pestaña | qué hace | de dónde salen sus datos | cómo se verifica |
|---|---|---|---|
| **Vista** | realista o técnica; perfiles reales b×h; losas de dibujo; suelo donde apoya el edificio (base y terrazas); relieve del sitio; cámara (encuadrar, Planta, Elev. X, Elev. Y, Iso); **filtro de piso** (cada barra es del piso de su nodo más bajo: la losa y lo que nace de ella); tamaño del texto (A− / A+) | `modelo.json` (áreas tributarias, `info.terrenos`), `relieve.json`, `Resources/Ambiente` | `U1 unity: contrato JSON <-> C#` (cada apoyo sobre su nivel de terreno), `P3 relieve del sitio`, `K3 capturas: relieve`, `H1 vista realista: recursos` |
| **Capas** | estructura (nodos, auxiliares, columnas, vigas, muros, brazos rígidos); control de calidad (apoyos por tipo, diafragmas, ejes locales x rojo / y verde / z azul, IDs, áreas tributarias); **cargas y enfierradura** (flechas de G, Q, EX, EY o la combinación, al costado del edificio; la jaula de la columna más cargada, en sitio o como lámina ampliada) | `modelo.json`; `resultados.json`, bloque `cargas_y_armadura` | `U1 unity: contrato JSON <-> C#`, `K1 capturas: visor` |
| **Caso** (la que abre) | **deformada**: sin deformar o el caso activo, con la escala que recomienda Python (×160) o a mano (x1 a x1000) y "Volver a la recomendada"; en *Avanzado*, la G precalculada de `modelo.json` y los sismos del bloque de cargas. **Casos**: los 15 del laboratorio (G, Q, EX, EY y las 11 combinaciones). **Superposición**: E1..E3 precalculados, LIBRE (los sliders, combinados por el servidor) e INSTANT (sliders sin servidor, al instante). **Diagramas** (My, Mz, Vz, Vy, N, T y la carga repartida wy, wz). **Curva P-M**. **Mapa demanda / capacidad** y los críticos del caso. Botones *Columna demo* (200005) y *Muro demo* (100537) | `resultados.json`; `GET /estados` y `POST /combinar` para LIBRE | `R1 resultados: al dia y cierre f_j`, `R2 resultados: esfuerzos y signos [1]-[8]`, `R4 resultados: superposicion E1..E3 por 4 vias`, `R5 resultados: sliders instantaneos (replica)`, `K1 capturas: visor` |
| **Elemento** | *Ir a* un id de elemento o de nodo, y el **inspector**: de una barra, su tag, nodos, sección, material, condiciones de borde, ejes locales, qué la carga (la `w` de la losa más la de peso propio = la `w` total de G), esfuerzos en i y j del caso activo, demanda-capacidad con la P-M en línea y la trazabilidad (la línea `element elasticBeamColumn ...` de OpenSees y el GameObject `Elem_<tag>_<tipo>`); de un nodo, coordenadas, cota, piso, sus seis GDL en palabras y sus desplazamientos | `modelo.json`, `resultados.json` | `U1 unity: contrato JSON <-> C#`, `R3 resultados: trazabilidad 100018`, `K1 capturas: visor` |
| **Modificar** | mover nodos (se selecciona primero y se arrastra después; con Shift, en altura), crear y borrar barras (Supr), cambiar la sección, empotrar o liberar un apoyo, *Guardar JSON*, **Recalcular en el servidor** (Enter): la deformada nueva, los 4 casos del modelo, la tabla de equilibrio y *Abrir Excel de este reanálisis*. Al editar, los resultados del laboratorio quedan marcados desactualizados | el modelo del visor → `POST /analizar` → `salidas/reanalisis.xlsx` | `M3 motor: reanalisis = modelo`, `M4 motor: M1 borrar columna 200069`, `M5 motor: M3 seccion de una viga`, `M6 motor: M4 soltar un apoyo`, `X1 excel: libro y reanalisis` |
| **Carga movil** | 100 kN que recorren las vigas 200203 a 200208 (z = 3.91 m) en 30 posiciones resueltas en OpenSees: la deformada del edificio (una escala para todo el recorrido, ×1600), la elástica de la viga cargada, el reparto a sus extremos, la conservación (ΣRz = P) y las verificaciones de Python. Salta entre posiciones, **no interpola** | `carga_movil.json` | `P1 carga movil [a]-[i]`, `U1 unity: contrato JSON <-> C#`, `K1 capturas: visor` |
| **Persona** | *Poner persona* y caminar con las flechas por cualquier losa; Q / E, PgUp / PgDn o los botones cambian de piso. Identifica el paño y la región tributaria donde está parada, resalta las vigas receptoras y dice cuánta carga le llega a cada una; muestra **al instante** la deformada que produce (×540) y sus momentos. Camina un AT-ST de 2.8 m; *Manejar desde la cabina* (V) pone la cámara en sus ojos (W/S avanzan, A/D giran, botón derecho mira). El peso va de 0.3 a 300 kN (100 kN para que se vea; una persona son 0.80 kN) | `modelo.json` (áreas tributarias), `persona.json` (se lee al usar la pestaña), `Resources/Personaje/atst.json` | `P2 persona: suma = OpenSees`, `U2 unity: transcripciones C# = elastica.py`, `K2 capturas: persona`, `H2 persona: el AT-ST` |

Con 100 kN a media viga 200141, la persona la hace bajar 0.715 mm bajo la
carga, con un momento de -123.53 kN·m: entre PL/8 (empotrada) y PL/4
(simplemente apoyada), como debe.

### Rehacer la evidencia de la app

```powershell
python sap.py unity build --forzar         # la app con lo último (Unity cerrado)
python sap.py capturar visor               # fotos y registro.txt, y la comparación con Python
python sap.py capturar persona
python sap.py capturar relieve
```

`capturar` levanta el servidor si hace falta (`--sin-servidor` lo evita),
corre la app sin intervención y compara lo que la app escribió contra
Python (las entradas K1, K2 y K3 de la suite). Un registro capturado con
otras salidas no vale: después de un `preparar` que cambie números, se
vuelve a capturar.

---

## 6. El Excel

`salidas/resultados.xlsx` tiene los mismos números que `resultados.json`
(lo que muestra el visor): LEEME, Resumen, Nodos, Desplazamientos,
Elementos, Esfuerzos, Reacciones, Demanda-capacidad, Curvas P-M y
Supuestos. Ninguna celda tiene fórmula: en Excel no se calcula nada.
Cada `/analizar` deja `salidas/reanalisis.xlsx` con el modelo editado.

En la hoja **Reacciones no se suma la columna entera**: un nodo de
diafragma reacciona también a su restricción, que es interna, y la suma
**dobla** el corte basal. Se filtran las filas con "Cuenta en Fx/Fy" o
"Cuenta en Fz" = sí (lo comprueba `X1 excel: libro y reanalisis`: la suma
filtrada es el equilibrio de OpenSees).

---

## 7. La vista realista

**Vista → Realista.** Texturas y cielo descargados, todos **CC0**
(ambientCG y Poly Haven; la lista está en
`unity/Assets/Resources/Ambiente/LICENCIAS.md` y las fuentes en
`unity/FuentesAmbiente/`): hormigón con mapa normal, pasto, tierra, acero
galvanizado y un cielo HDRI con suelo de pasto bajo el horizonte, girado
para que su sol caiga donde está la luz (las sombras y el sol coinciden),
con tonos ACES. Para que de lejos no se note la grilla de una textura
repetida, el mapa de detalle del material (URP/Lit) le multiplica un ruido
de periodo largo. Sin esos recursos, el visor vuelve a texturas
procedurales.

- Las barras se dibujan con su sección real (b × h) y las losas con los
  polígonos de sus áreas tributarias.
- **El suelo en niveles**: la base en -7.97 (45 apoyos) y la terraza
  oriente del cuerpo antiguo en -4.01 (40 apoyos), con sus taludes. Las
  regiones vienen de `edificio.json` (bloque `vista`), y la suite exige que
  cada apoyo en terreno quede sobre su nivel.
- **El relieve del sitio**: el terreno del campus alrededor del edificio,
  con un hueco donde está el edificio. La planta sale de Google Earth (el
  techo del cuerpo antiguo da el rumbo y la posición, sin escala) y las
  cotas del DEM Copernicus GLO-30, calzado en vertical con los 85 apoyos en
  terreno. Es **solo dibujo**: ningún cálculo lo lee. Trae la huella del
  modelo (563 nodos, 950 elementos) y el visor no lo dibuja si es de otro.

```powershell
python sap.py recursos               # rehace el giro del cielo, el HDR con suelo y los mapas de detalle
python sap.py recursos --verificar   # licencias, mapas normales, materiales, sol (la entrada H1)
python sap.py exportar relieve       # salidas/relieve.json (--bajar-dem vuelve a bajar la ventana del DEM)
```

En el editor, el menú **Laboratorio → Recursos de la vista realista** arma
los materiales y el cielo como assets (la build solo incluye lo que es
asset).

---

## 8. El teléfono con la build Web

La build Web de la versión anterior (SAP3000 v1.0, con este mismo
edificio) se probó en un iPhone 16 con Safari: carga el edificio, se
selecciona tocando y los sliders instantáneos mueven la deformada. La de
esta versión se compila igual y falta probarla en el teléfono.

```powershell
python sap.py unity web --seco       # qué haría
python sap.py unity web              # build/web (Unity cerrado; tarda)
cd build\web
..\..\.venv\Scripts\python.exe -m http.server 8080 --bind 0.0.0.0
```

En el teléfono, conectado al **mismo WiFi**, se abre la dirección http de la
IPv4 del PC (`ipconfig` la da) en el puerto 8080; `python sap.py unity web`
la imprime al terminar. Windows pregunta si deja pasar a Python por el
firewall: solo redes privadas. Para LIBRE y el reanálisis, en otra terminal:

```powershell
python sap.py servidor --lan
```

y en la app se escribe la base del servidor (http, la IPv4 del PC y el
puerto 5000) en **Caso → Superposición** (URL), y esa misma base seguida de
`/analizar` en **Modificar**. En el teléfono, `localhost` es el propio
teléfono. `--lan` no se usa en una red pública.

- Sin servidor funcionan el modelo, las capas, los 15 casos, los
  diagramas, la P-M, el mapa D/C, E1..E3, los sliders instantáneos, la carga
  móvil y la persona. LIBRE y el reanálisis necesitan el servidor. Los
  botones de Excel no funcionan en el teléfono (StreamingAssets no es una
  carpeta).
- `unity/Assets/link.xml` le pide a Unity conservar los colliders: la
  build Web quita del motor las clases que ninguna escena usa, y sin
  colliders no se puede seleccionar nada tocando.
- Datos nuevos: `python sap.py sincronizar` también copia a la build Web
  (es una carpeta suelta), sin recompilar. En Android
  (`python sap.py unity android`, necesita el módulo de Unity) los JSON van
  dentro del `.apk` y hay que recompilar.
- En vertical el panel ocupa media pantalla: para la demo, el teléfono
  acostado.

---

## 9. La app de realidad aumentada (iPhone, Safari)

Relaciona el modelo con un elemento físico: el teléfono reconoce una
imagen pegada en una columna real y dibuja encima esa columna y su sector,
con **el mismo elementTag de OpenSees** y **sus resultados de OpenSees**.

**Por qué es web y no Unity:** el grupo tiene iPhone y no tiene Mac, y la
AR de Unity en iOS exige compilar en Xcode. En el navegador,
[MindAR](https://github.com/hiukim/mind-ar-js) hace el image tracking y
[three.js](https://threejs.org) dibuja; las dos van copiadas en
`ar/web/vendor/` (licencias MIT), así que la demo no depende de internet.
La regla de oro es la misma: el teléfono transforma coordenadas y dibuja.

### Usarla

```powershell
python sap.py preparar      # deja salidas/ar.json y su copia ar/web/datos/ar.json
python sap.py ar servir     # https en el puerto 8443; deja la terminal abierta
```

La primera vez, Windows pregunta si Python puede recibir conexiones:
permitirlo en **redes privadas**. En el iPhone, en el mismo WiFi:

1. Abrir en **Safari** la dirección que imprime el servidor (https, la IP
   del PC y el puerto 8443).
2. Safari avisa "Esta conexión no es privada": el certificado lo firma el
   PC, no una autoridad. **Mostrar detalles → visitar este sitio web**.
3. Elegir **Maqueta** (la imagen sobre la mesa, el sector a escala 1/50) o
   **En sitio** (la imagen en la columna, a tamaño real) y permitir la
   cámara.
4. Apuntar a la imagen impresa: `ar/marcador/marcador_imprimir.pdf` al
   **100 %** (20 cm de ancho; trae una regla de 10 cm para comprobar que la
   impresora no escaló).

`python sap.py ar servir --http` la sirve por http en `localhost`, puerto
8080, para probarla en el PC.

**Lo que muestra.** La columna **200037** (`lt2:P 0.70x0.70`, eje C del LT2,
de -0.05 a 3.91 m: la del piso 2 según los títulos de las láminas; hay que
confirmarla en obra) y las barras a menos de 6 m: 21 elementos y 22 nodos.
La barra de arriba dice "imagen detectada" y la pose (distancia e
inclinación de la cámara). El panel: `elementTag 200037`, la línea
`element elasticBeamColumn 200037 200062 200103 ...` de OpenSees y, para el
caso elegido (los 15; por defecto `1.2G+1.0Q+1.4EX`), N, V, T y M en los dos
extremos, desplazamientos, la curva P-M con el punto de demanda, Mn, u y
PASA / NO PASA; sobre las barras, el diagrama, la deformada y las áreas
tributarias. Tocar una barra la selecciona.

### Las coordenadas y la matriz M

| sistema | ejes | origen | unidades |
|---|---|---|---|
| OpenSees | x, y horizontales, **z arriba** (derecho) | el de los planos, calzado para el edificio | m |
| Unity | x, **y arriba**, z (izquierdo) | el mismo | m |
| marcador | x a la derecha de la imagen, y hacia arriba, z saliendo de la imagen hacia quien la mira (derecho) | el centro de la imagen | m |
| anchor de AR | los del marcador | el centro de la imagen | anchos de imagen (1 = 0.20 m) |

OpenSees → Unity es `Unity(x, y, z) = OpenSees(x, z, y)`: intercambiar y con
z invierte la mano. La app AR no pasa por Unity: va de OpenSees al
marcador. Python (`exportar.ar`) calcula dónde queda la imagen en el
edificio: pegada en la cara +x de la columna, con su centro a 1.40 m sobre
el nodo inferior, `c = (-2.38, 55.0833, 1.35)` m (el eje de la columna más
medio ancho, 0.35 m, hacia +x, más la altura); ejes `z = (1, 0, 0)` (la
normal de la cara), `y = (0, 0, 1)` (el arriba del edificio) y
`x = y × z = (0, 1, 0)`. Para cada punto `p` del modelo:

```
q = Rᵀ (p − c)               en el marcador, en metros   (traslación y rotación)
a = (escala / ancho) · q     en el anchor, en anchos     (escala)

M = S(k) · Rᵀ · T(−c),   k = escala / ancho;   en sitio k = 1 / 0.20 = 5
    [ 0  5  0 | -275.4165 ]
    [ 0  0  5 |   -6.7500 ]
    [ 5  0  0 |   11.9000 ]
```

**Ejemplo, en sitio.** El nodo 200103 (arriba de la columna), en
`(-2.73, 55.0833, 3.91)`: `p − c = (-0.35, 0, 2.56)`;
en el marcador `q = (0, 2.56, -0.35)`, o sea 2.56 m sobre el centro de la
imagen y 35 cm detrás de ella (en el eje de la columna); en el anchor
`a = (0, 12.8, -1.75)` anchos. La columna entera, de 200062 a 200103, mide
`(12.8 − (-7.0)) × 0.20 = 3.96 m`, igual que en OpenSees.

**En maqueta** la imagen va acostada: `z = (0, 0, 1)` (el arriba del
edificio sale de la imagen), `x = (0, 1, 0)`, `y = z × x = (-1, 0, 0)`, el
origen en la base de la columna `(-2.73, 55.0833, -0.05)` y
`k = 0.02 / 0.20 = 0.1`: el nodo 200103 queda en `(0, 0, 0.396)` anchos,
7.92 cm sobre la imagen (3.96 m / 50).

La cadena completa: `p` (OpenSees) → `M` (`ar.js`) → anchor → la pose que
MindAR estima en cada cuadro → la cámara → la pantalla. En el teléfono
corren la cámara, el tracking, la pose, la matriz y el dibujo; todo lo
estructural (los 15 casos, las curvas P-M, la pose de la imagen en el
edificio, el sector, `targets.mind`) se calculó antes en el PC. La matriz
está escrita dos veces a propósito, en `ar.js` y en `exportar.ar`, y la
suite las compara (`A2 AR: registro y tracking`).

### Cambiar de columna

Se edita `entrada/laboratorio.json`, bloque `ar` (elemento, cara, altura,
ancho, radio del sector), y:

```powershell
python sap.py ar marcador     # la imagen (con su rótulo), el PDF y targets.mind
python sap.py preparar        # ar.json y su copia
```

Para probar otra sin tocar el JSON: `python sap.py exportar ar --elemento
200069 --cara -y`. La imagen y `targets.mind` van juntos: una imagen nueva
con el `targets.mind` viejo sigue "funcionando" con los puntos de la
anterior.

### Si algo sale mal

| síntoma | qué hacer |
|---|---|
| Safari no abre la página | el mismo WiFi que el PC; la dirección con **https** y el puerto **8443**; el firewall permite Python en redes privadas |
| no pide la cámara o pantalla negra | Ajustes → Safari → Cámara → Permitir; recargar |
| no detecta la imagen | más luz, sin reflejos, que la imagen ocupe al menos un tercio de la pantalla |
| el modelo sale del tamaño equivocado | la imagen impresa no mide 20 cm: imprimir al 100 % o corregir `ancho_impreso_m` |
| el modelo tiembla | acercarse; que la imagen quede plana |

### La prueba en el iPhone

La fila **AR** de la tabla QA queda en PARCIAL mientras no haya una
captura del teléfono en `verificacion/registros/iphone/` (`.jpg`, `.png`,
`.heic`, `.mp4` o `.mov`); con una, pasa sola a OK. Qué capturar:

1. **Maqueta**: una captura de pantalla con "imagen detectada" y el panel
   de `elementTag 200037` en el caso por defecto.
2. **Focal, con una cinta**: el teléfono de frente a la imagen a 30, 50 y
   80 cm, anotando lo que dice "pose:". Si la razón app / cinta da cerca de
   1.00, la focal que supone MindAR sirve para ese teléfono
   (`python sap.py ar precision` da el presupuesto de error).
3. **Regla vertical en maqueta**: el techo dibujado de la columna tiene que
   quedar a 7.92 cm de la mesa.
4. **En sitio** (opcional): primero confirmar la columna en obra.

---

## 10. Verificar

```powershell
python sap.py verificar               # las 42
python sap.py verificar --rapido      # sin las 6 lentas (36)
python sap.py verificar --solo U1 L4  # esas entradas, por su código
python sap.py verificar --solo sismo  # las que nombran esa palabra
python sap.py verificar --lista       # la lista, sin correr nada
python sap.py revisar qa              # la tabla de 10 filas para la defensa
```

Cada entrada corre en su propio proceso y también se puede correr sola
desde la raíz: `python -m verificacion.<modulo> <bloque>` (el comando sale
en `--lista`). La entrada `U4 unity: JsonUtility real` abre Unity en batch:
con Unity abierto sale con 2. Ninguna entrada escribe en `salidas/`: que
las salidas estén al día es una entrada más (`R1`, `U3`).

Los números que no pueden cambiar sin una decisión están en
`verificacion/numeros_de_control.json`. Algunos:

| | |
|---|---|
| edificio | 563 nodos, 950 elementos, G = 98728.8608 kN = 64579.8816 (antiguo) + 34148.9792 (LT2); junta 0.050 m |
| laboratorio | A tributaria 6894.5944 m², Q = 20683.7833 kN, V = 10907.0752 kN, 15 casos, escala ×160 |
| superposición | E1 9.6322 mm, E2 12.3262 mm, E3 25.1115 mm (NO PASA 9 de 207, 3 fuera de curva) |
| columna 200037 | Mn(P = 0) = 1190.2 kN·m; nariz de la P-M en P = 4186 kN, M = 1762 kN·m |
| M1 | borrar la 200069: el nodo 200186 baja de -3.64515 a -21.59875 mm bajo G |
| benchmark | marco de prueba de 4 columnas: UZ techo = -0.06348 mm (SAP2000: -0.06375) |

---

## 11. Limitaciones y diferencias a propósito

Dichas de frente: ninguna es un error escondido, y cada una se puede
mostrar con un comando.

**Dos fuentes de casos, con nombre.** Los casos **del modelo** son los G, Q,
EX y EY que trae `edificio.json`; los resuelve `calcular` y `/analizar`
(el reanálisis de la pestaña Modificar y la deformada *Avanzado → Cargas
G*). Los casos **del laboratorio** son los que arma `calculo.laboratorio`
con q de NCh1537 y el Cs de `laboratorio.json`; son los 15 casos de
`resultados.json`, E1..E3, LIBRE, INSTANT, la AR y el Excel. **Solo G
coincide** (98728.8608 kN):

| | del modelo | del laboratorio |
|---|---|---|
| Q | 20118.4025 kN | 20683.7833 kN (q = 3.0 kN/m² por área tributaria) |
| corte basal EX = EY | 10021.3500 kN (6388.2870 del antiguo + 3633.0630 del LT2) | 10907.0752 kN = 0.10 × (G + 0.5 Q) |

Los 874.23 kN de diferencia salen del peso sísmico: el laboratorio cuenta
el peso aplicado directo sobre los apoyos y usa 0.5·Q con q = 3.0; el
modelo arma el sismo de cada cuerpo con **su** peso sísmico y su propia
fórmula. Además el laboratorio calcula **un** corte para todo el edificio y
lo reparte en altura sobre los dos cuerpos, cuando con la junta libre cada
cuerpo debería llevar su propio Cs·W (los casos del modelo sí lo hacen).
Se conservan los dos a propósito: no se unifican sin una decisión.
`python sap.py revisar laboratorio` da el del laboratorio y `python sap.py
revisar sismo` el del modelo.

**Mayor componente contra norma.** "Desp. max" de los resultados es la
**norma** √(ux² + uy² + uz²) del nodo que más se mueve. El
`max_desplazamiento` del servidor, de `casos_del_modelo.json` y de la
pestaña Modificar es la **mayor componente** (rotulada "Max. componente").
No se comparan entre sí. Los de los casos del modelo: G 7.5488, Q 2.9052,
EX 16.4151 y EY 16.8064 mm.

**D/C nominal, sin φ.** `u = M / Mn` compara la demanda mayorada con la
capacidad **nominal** (hormigón a ε_c = 0.003), sin factor φ y sin chequeo
de corte (no hay Vn). La columna se revisa con el momento resultante
√(My² + Mz²) contra una curva uniaxial. Cerca de P = 0 la curva de fibras
incluye algo del endurecimiento del acero (Steel01). La inercia es la
bruta, sin fisurar: los desplazamientos quedan del lado bajo.

**Losa colaborante sin conectar.** La regla de la viga T (ancho efectivo
de ACI) está escrita en `calculo.losa_colaborante` y la informa
`python sap.py revisar losa-colaborante`, pero el modelo usa la viga
rectangular: las vigas quedan más flexibles de lo que serían.

**u = 9999 casi nunca es la capacidad: es el axial.** Quiere decir que P
cayó fuera del rango de la curva (Mn = 0). Casi siempre es una **pata de
núcleo revisada sola**: un núcleo se modela como columnas anchas unidas
por brazos rígidos, y resiste el volcamiento con un par de axiales entre
sus patas. La tracción que saca a una pata de su curva es ese par interno.
El panel dice de qué grupo es cada pata (50 patas en 15 grupos);
`python sap.py revisar nucleos`. La revisión de verdad, el núcleo como una
sección compuesta, está pendiente. Y no se arregla densificando la curva:
la rama de tracción con el acero sin endurecer **es** una recta.

**Lo que dice el plano, y lo que no.** El dato de los planos tiene huecos
declarados en `edificio.json`, `supuestos.problemas_conocidos`: el fierro
de los muros del LT2 se leyó de CANT y no de NUM; el M 0.60x2.92 y 11 muros
del LT2 no traen enfierradura (sin curva P-M no tienen D/C: el mapa los
pinta grises, que es una omisión optimista); la capacidad usa
recubrimiento 0.03 m y fy 420 porque el plano del LT2 no los da. El
diámetro de los pilares (Ø25 en el LT2, Ø22 en el antiguo) es supuesto. Un
NO PASA marca dónde falta información tanto como un veredicto. Cs = 0.10 es
un valor de trabajo, sin R, sin I y sin corte mínimo: `--cs` lo cambia.

**El peso propio viaja dentro de G.** Las cargas de G ya traen el peso de
cada barra. Si en Modificar se cambia una sección, K cambia pero su peso
no; si se borra una columna, su peso nodal queda aplicado (48.51 kN en la
200069), y el editor lo avisa.

**Qué exige reanálisis** (la regla sale de `K·u = F`):

| lo que cambia | ¿cambia K? | ¿reanálisis? | ¿curva P-M nueva? |
|---|:---:|:---:|:---:|
| los λ de un caso (los sliders), escalar un caso completo | no | **no**: es superposición | no |
| el coeficiente sísmico Cs | no | **no**: EX(Cs′) = (Cs′/Cs)·EX(Cs), es λEX = Cs′/Cs | no |
| q en el peso sísmico, o el patrón en altura | no | **sí**: cambia la forma de F piso a piso, es otro caso base | no |
| la carga de una barra o de una zona, un área tributaria | no | **sí**: no hay un caso base resuelto solo ahí | no |
| activar o desactivar un elemento, un apoyo, mover un nodo | **sí** | **sí** | no |
| la sección de una barra | **sí** | **sí** | **sí**, si tiene fierro |
| el material de todo el modelo (E y G por un mismo factor) | K → αK | los esfuerzos no cambian; u → u/α | sí, si cambia f'c |

El reanálisis de la app (`/analizar`) rehace desplazamientos, esfuerzos y
reacciones, pero **no** las curvas P-M ni los resultados del laboratorio:
después de editar, el visor los marca desactualizados (y los sliders
INSTANT y la carga móvil también lo dicen), porque son del modelo
original. Para que vuelvan a valer: cambiar `entrada/` y
`python sap.py preparar`.

**Dibujo.** La enfierradura "en todas las columnas" repite en cada columna
la jaula de **una** (la de mayor axial en G, la del bloque de armadura): el
fierro de cada una está en su curva P-M, no en ese dibujo. La deformada
curva cada barra con los giros de sus nudos, pero no dibuja la flecha que
la carga repartida produce **dentro** del vano (sumarla sería cálculo en
C#). En la AR, la deformada va recta entre nodos.

**La AR.** El panel muestra `(undefined)` en las áreas tributarias del LT2:
`ar.js` lee `trib.forma` y `ar.json` no trae esa clave (pendiente
declarado). La app no se probó todavía en un iPhone (toda la evidencia es
de Chrome con una cámara sintética), y en sitio el registro vertical tiene
5 a 10 cm de incertidumbre: el nodo está en el nivel de la losa (-0.05), no
en el piso terminado.

**El sismo.** Es pseudoestático, aplicado en el nodo maestro de cada piso,
sin torsión accidental. En EY el LT2 tiene torsión extrema (cociente de
NCh433 sobre 1.4): es la planta, con la rigidez en Y cargada a un lado, no
un error del modelo. `python sap.py revisar sismo EY --detalle`.
