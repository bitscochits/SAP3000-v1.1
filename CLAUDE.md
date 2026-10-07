# CLAUDE.md — Lo que un agente tiene que saber antes de tocar este repo

> Contexto para Claude Code y cualquier otro agente de IA. Léelo entero
> antes de editar. El **uso** (qué hace cada comando, cada carpeta y cada
> pestaña) está en `README.md`; el **contrato** entre Python, Unity, el
> servidor y la AR, en `CONTRATO.md`; acá van las reglas, las convenciones
> y las trampas que ya costaron tiempo.
>
> **La suite es `python sap.py verificar`** (42 entradas; `--rapido` deja
> fuera las 6 lentas). Toda trampa de la sección 6 nombra la entrada que la
> vigila por su etiqueta, tal como la imprime `python sap.py verificar --lista`.
>
> SAP3000 v1.1 es la reorganización de SAP3000 v1.0: un edificio, una
> puerta de entrada (`sap.py`), los mismos números. La lectura de los planos
> DXF, los informes del curso y `AGENTS.md` (el registro de uso de IA que
> pide el curso) quedaron en v1.0. Grupo 7 · Métodos Computacionales en
> Obras Civiles, UAndes, 2026-02.

---

## 1. Qué es esto

Un laboratorio estructural digital del Edificio de Ingeniería de la
UAndes: **un edificio** con dos cuerpos — el antiguo (planos 2017_67, tags
1xxxxx) y el LT2 (planos 2024_22, tags 2xxxxx) — separados por una junta de
dilatación **libre** de 0.050 m, en **un solo modelo**
(`entrada/edificio.json`). Se resuelve con OpenSees, se verifica
numéricamente y se muestra en Unity, en la AR del teléfono y en Excel. No
se evalúa realismo gráfico; se evalúa corrección, verificación,
trazabilidad y **que cada integrante pueda explicar cualquier parte**.

## 2. La regla de oro, y sus dos licencias

```
entrada/ → Python/OpenSees CALCULA → salidas/ (el JSON es la fuente de verdad) → Unity, la AR y Excel MUESTRAN
```

Nunca cálculo estructural en C# ni en JavaScript. Si hay que calcular
algo, va en `calculo/` y viaja por JSON. Unity dibuja, y como mucho edita
el modelo, que vuelve a Python (`POST /analizar`) para recalcular. Excel no
tiene fórmulas.

**Dos licencias declaradas**, las dos para **sumar casos que OpenSees ya
resolvió**, y cada una con su guardia (`CONTRATO.md` §10):

1. **Los sliders instantáneos (INSTANT)**: `VisorResultados.Instantanea`
   escala y suma los cuatro casos base del laboratorio. Desplazamientos,
   fuerzas de extremo y diagramas son lineales; la D/C, que no lo es, se
   rehace con la regla de `calculo.demanda.demanda()` y el Mn se interpola
   en la curva que calculó Python.
2. **La persona**: `VisorPersona` suma casos unitarios por nodo receptor
   con los pesos de Hermite (exactos para `-beamPoint` en Euler-Bernoulli) y
   evalúa la forma adimensional φ(ξ, α) con la flexibilidad L³/EI que
   exporta Python.

**No son licencia para más**: ni la D/C de la persona, ni la flecha de la
carga repartida dentro del vano, ni sumar reacciones, ni interpolar entre
posiciones de la carga móvil.

## 3. El flujo de un solo edificio, y las reglas de dependencia

```
entrada/edificio.json + entrada/laboratorio.json
   → calculo/   (Python + OpenSees: lo único que calcula)
   → exportar/  → salidas/   (un archivo por consumidor)
   → sincronizar → Unity (StreamingAssets) · AR (ar/web/datos) · Excel
```

- **Un edificio.** Nada de modos `lt2`/`ingenieria`, argumentos de
  edificio, listas de edificios ni bucles "por cada cuerpo" en el cálculo o
  la exportación. Lo que necesita separar cuerpos usa
  `calculo.edificio.cuerpo_de(tag)` o `calculo.edificio.por_cuerpo(modelo)`.
  El nombre del edificio es `conjunto` (`calculo.edificio.NOMBRE`), y es el
  `info.edificio` de los JSON que lo llevan.
- **Dependencias en un solo sentido**: `calculo ← exportar ← sap.py`.
  `calculo/` **nunca** importa `exportar/`. `verificacion/` lee todo y **no
  escribe en `salidas/`**. `herramientas/` y `ar/` usan `calculo.rutas`.
- **Cómo se corre**: los módulos se importan como paquetes desde la raíz
  (`from calculo import opensees`; no hay `__init__.py`). Ninguno hace
  `sys.path.insert` salvo `sap.py`. Se corren con `python sap.py <comando>`
  o con `python -m paquete.modulo` desde la raíz. Cada `main(argv)` recibe
  los argumentos sin el nombre del comando y devuelve el código de salida.
- **Lo que se edita a mano está en `entrada/`; lo que se genera, en
  `salidas/`** (no se edita, no va a git). Unity y la AR leen **copias**
  (`python sap.py sincronizar`). Dos excepciones declaradas: los assets de
  Unity que regeneran `herramientas/` (`atst.json`, `sol.json`,
  `detalle.json`: necesitan su `.meta`) y `build/`, que escribe Unity.
  Lo que la app y el navegador escriben **para** la suite va a
  `verificacion/registros/`.
- **Dos fuentes de casos, con nombre** (sección 6): los del **modelo**
  (`casos_de_carga` de `edificio.json`; los resuelve `/analizar`) y los del
  **laboratorio** (`laboratorio.json`). No se unifican.
- **Ningún nombre lleva "semana"** (archivos, carpetas, funciones, clases,
  subcomandos). Las **claves** de los JSON que lee el C# no se renombran:
  son el contrato.

## 4. Convenciones que no se rompen

| Convención | Regla | Dónde vive |
|---|---|---|
| **Ejes** | OpenSees: Z vertical. Unity: Y vertical. `Unity(x, z, y)`. La AR no pasa por Unity: va de OpenSees al marcador | `Ejes.AUnity` (`ModeloEstructural.cs`); `exportar.ar` y `ar.js` |
| **Unidades** | m, kN, kPa. `Ec = 4700·√f'c·1000` | todo el repo; `E` sellado por sección en `edificio.json` |
| **Tags** | Cuerpo antiguo 1xxxxx, LT2 2xxxxx (`PASO_DE_TAG = 100000`). El tag es el mismo en el modelo, OpenSees, `resultados.json`, el GameObject (`Elem_<tag>_<tipo>`) y la AR | `calculo.edificio.cuerpo_de`, `por_cuerpo` |
| **Inercias** | En el contrato `Iz` es la de **gravedad** (`b·h³/12`), `Iy` la lateral. En los muros del cuerpo antiguo (`b` = espesor, `h` = largo) la grande, `b·h³/12`, está en `Iy`. El servidor las **cruza** solo en elementos no verticales (`vecxz=(0,0,1)` deja el local *z* vertical: la gravedad flecta en `My`, que resiste `Iy`) | `calculo.opensees.construir_modelo`; `calculo.esfuerzos.rigidez_como_el_servidor` lo replica |
| **`vecxz`** | Se elige por **geometría**, nunca por la etiqueta `tipo`. Vertical → `(1,0,0)`; si no → `(0,0,1)`. Un muro trae el suyo: el LT2 su normal (inercia grande en `Iz`), el antiguo su largo (grande en `Iy`); el momento del plano se elige por inercias | `calculo.edificio.es_vertical`, `vecxz_por_defecto`, `ejes_locales`; `calculo.opensees.construir_modelo` |
| **Fuerzas internas** | `eleResponse(tag,'localForce')`, **nunca** `eleForce` (que es global). Vector `[N,Vy,Vz,T,My,Mz]` por extremo, fuerzas **sobre** la barra | `calculo.opensees.extraer_resultados`, `calculo.esfuerzos.esfuerzos_internos`, `calculo.demanda` |
| **Reacciones** | `nodeReaction` en un nodo de diafragma incluye la fuerza de la restricción, que es interna. Se separa **por grado de libertad**: en horizontal solo cuentan nodos fuera de todo diafragma; en vertical, cualquier restringido salvo el maestro. Sumar todo **dobla el corte basal** | `calculo.opensees.equilibrio`, `cuenta_en`, `filas_que_cuentan`; `calculo.superposicion.equilibrio_combinado` |
| **Diafragma rígido** | `constraints('Transformation')`. Los GDL fuera del plano del maestro se fijan. El piso se traslada **y gira**: `ux_i = ux_m − rz·(y_i−y_m)` | `calculo.opensees.construir_modelo`, `resolver_caso`, `diafragmas` |
| **Muro** | Una barra en su eje baricéntrico (columna ancha) + brazos rígidos como barras ×100 hasta las caras. **No** `rigidLink` (pelea con el diafragma). `brazo` (LT2) y `brazo_rigido` (antiguo) son lo mismo | los elementos de `edificio.json`; `calculo.demanda.BRAZOS` |
| **Hormigón por sección** | `E`, `G` y `fpc_MPa` en cada sección pisan al material del modelo: el solver usa `E`/`G`, la capacidad `fpc_MPa`. Es lo que deja un cuerpo G35 junto a uno G28 en un modelo con **un** `material` | `calculo.opensees.normalizar_secciones`, `construir_modelo`; `calculo.capacidad._fpc_kPa` |
| **Rutas** | Solo `calculo.rutas` sabe dónde está cada cosa; encuentra la raíz subiendo hasta la marca (`setup.ps1` y `sap.py` juntos). **Nunca** contar `dirname`. Los nombres que lee Unity viven en `rutas.NOMBRES_EN_UNITY` y en las constantes `ARCHIVO` del C# | `calculo.rutas` |
| **Resultados** | El servidor **redondea**: desplazamientos a 8 decimales, fuerzas a 4. Nada se puede comparar por debajo de eso; la cota de una suma es `5e-5·(Σ\|λ\|+1)` más la coma flotante | `calculo.opensees.extraer_resultados`; `calculo.superposicion.piso_de_redondeo`; `calculo.esfuerzos.COTA_REDONDEO` |
| **Esfuerzos internos** | Desde `f_i` y la carga repartida `w` local: `N(x) = −(N_i + wx·x)`, `My(x) = −(My_i + x·Vz_i + wz·x²/2)`, `Mz(x) = −(Mz_i − x·Vy_i − wy·x²/2)`; en `x = L` tienen que dar `f_j`. 9 estaciones equiespaciadas si la barra está cargada, 2 si no. Se dibujan del lado traccionado | `calculo.esfuerzos.esfuerzos_internos`, `estaciones`, `cota_de_cierre` |

## 5. Supuestos declarados (no están en el código)

Todo lo que el plano no dice vive **en el dato**, con su justificación al
lado, para que se vea como supuesto y se pueda reemplazar sin tocar
código:

- **`entrada/edificio.json`, bloque `supuestos`**: el calce entre los dos
  juegos de planos (`dx`, `dy`, `dz`, cómo se midió cada uno) y la **junta**
  (0.050 m, de ahí sale el `dx`); por cuerpo, los materiales, las cargas,
  los niveles, el terreno y sus terrazas, los dinteles del LT2, el
  **diámetro longitudinal de los pilares** (el número de barras se deduce
  del estribo; solo el diámetro es supuesto: Ø25 en el LT2, Ø22 en el
  antiguo), las **secciones del cuerpo antiguo** (cada una con su `origen`
  si se leyó del plano o `_supuesto: true` si no) y el fierro de sus muros;
  y `problemas_conocidos`, los huecos del dato que se corrigen en otra
  versión.
- **`entrada/laboratorio.json`**: lo que define el profesor — q de
  NCh1537 (3.0 kN/m², salas de clases), el sismo (Cs = 0.10, fracción 0.5
  de Q en el peso sísmico, patrón en altura), las **11 combinaciones** y la
  por defecto (S3) — y los estados E1..E3, los rangos de los sliders, las
  modificaciones M1..M4, la carga móvil y la AR (qué columna, qué cara, a
  qué altura). Cada valor con su `_por_que`. Los parámetros se
  sobreescriben por línea de comandos (`--q`, `--uso`, `--cs`, `--fq`,
  `--patron`, `--k`, `--fracciones`, `--comb`, `--combinacion`) y **nunca**
  se escriben de vuelta.
- **`entrada/sitio/sitio.json`**: los supuestos del relieve (rumbo, posición,
  calce vertical).

Lo leído y lo supuesto se distinguen en el dato (`origen`, `_supuesto`,
`provisorio`), no en la memoria de nadie. Una dimensión escrita como
constante en el código **no** se parece a un supuesto y nadie la revisa
(sección 6).

## 6. Trampas que ya costaron tiempo (y la entrada de la suite que las vigila)

Todas fallan **en silencio**: el modelo corre, da números, y el error solo
se ve mirando otra cosa. La guardia va con el código y la etiqueta exactos
de `verificacion/suite.py`; se corre sola con
`python sap.py verificar --solo <código>`.

| Trampa | Guardia |
|---|---|
| **Dos fuentes de casos.** El modelo trae sus propios G, Q, EX, EY (`casos_de_carga`, los que resuelven `calcular` y `/analizar`); el laboratorio arma los suyos con q de NCh1537 y el Cs de `laboratorio.json` (los de `resultados.json`, E1..E3, LIBRE, INSTANT, la AR y el Excel). **Solo G coincide**: Q 20118.4025 contra 20683.7833 kN; corte basal 10021.3500 contra 10907.0752 kN. Comparar un número de una fuente con uno de la otra da una "diferencia" que no es error. Se conservan las dos con nombre y no se unifican sin una decisión | `M3 motor: reanalisis = modelo` (`/analizar` = los casos del modelo), `L2 laboratorio: Partes A, B y C` (V = 10907.0752), `L3 laboratorio: sismo del modelo` (10021.3500), `L5 laboratorio: M2 cs 0.20` (G de `/analizar` = G del laboratorio) |
| **`JsonUtility` ignora sin avisar** un campo C# que no calza con el JSON: deformada plana, diagrama vacío, sin error. Tampoco lee arreglos anidados, diccionarios ni propiedades | `U1 unity: contrato JSON <-> C#` (las dos direcciones, tipos, anidados; FALLA si falta un `.cs` o una clase), `U4 unity: JsonUtility real` (Unity en batch lee los 5 JSON y los vuelve a escribir) |
| **Un paño de losa que nunca entró al modelo no rompe el equilibrio**: la carga que no se aplicó tampoco se reacciona | `E3 edificio: losa aplicada = dibujada` (área sellada = polígonos = carga, con el q implícito constante por piso, por cuerpo) |
| **Dos secciones con el mismo número de barras no son la misma sección** (caché de curvas P-M) | `C3 capacidad: demanda --todas` (la firma de familia, `calculo.demanda.firma_de_seccion`: sección, b, h, barras, As, estribo, malla) |
| **Un cociente de torsión sobre un piso que casi no se mueve es ruido** | `L3 laboratorio: sismo del modelo` (`calculo.sismo`) |
| **El momento del plano de un muro no es siempre `Mz`**: el LT2 da como `vecxz` la normal (inercia grande en `Iz`) y el antiguo el largo (grande en `Iy`, momento del plano `My`). Con `\|Mz\|` fijo, los muros del cuerpo antiguo se comparaban con su momento **fuera** de plano y trabajaban muy por debajo de lo real. Se elige por inercias (`calculo.demanda.momento_en_el_plano`) y `demanda()` **no tiene default** para muros | `R2 resultados: esfuerzos y signos [1]-[8]` (bloque [8]) |
| **El diagrama del medio se reconstruye por equilibrio**: `localForce` da los extremos. Un signo o un eje de carga mal puesto da un diagrama igual de razonable. Se exige llegar a `f_j` de OpenSees (cociente de cierre ≤ 1; el peor es 0.9999999995, al filo a propósito) y el lado traccionado se prueba con una sección de fibras. `exportar.resultados` **no escribe** si una barra no cierra | `R1 resultados: al dia y cierre f_j`, `R2 resultados: esfuerzos y signos [1]-[8]` (bloques [1] y [6]) |
| **Sumar la columna de reacciones** (en el Excel o en un log) dobla el corte basal, porque un nodo de diafragma reacciona también a su restricción. Unity no suma: muestra la tabla que manda el servidor (`ClienteReanalisis.TablaEquilibrio`); el Excel marca "Cuenta en Fx/Fy" y "Cuenta en Fz" | `X1 excel: libro y reanalisis` (suma filtrada = equilibrio; la columna entera dobla), `M1 motor: benchmark y servidor` (equilibrio por caso) |
| **Comparar lo que muestra Unity con Python "al decimal"** falla sin que nadie se haya equivocado: `JsonUtility` guarda float32, el modelo editado viaja en float32 al servidor y el servidor **redondea** lo que devuelve. La tolerancia de cada fila es la suma de sus causas medidas (`python sap.py revisar m1 --float32` emula lo que manda Unity) | `K1 capturas: visor`, `M3 motor: reanalisis = modelo` (M1 por HTTP en float32) |
| **El mapa D/C y la vista realista cambian los mismos `sharedMaterial`**: el que llega último pisa al otro, y al apagar el mapa se "restaura" un material realista como si fuera el técnico. Solo se ven colores equivocados. Protocolo en `CONTRATO.md` §8 | `K1 capturas: visor` (registra las barras pintadas por el mapa) |
| **IMGUI**: `OnGUI` corre una vez por evento y cada evento repite el Layout. Si un clic agrega o quita controles a mitad de evento, salta "Getting control N's position". Un `ScrollView` recorta el scroll a lo que cabe **en ese frame**. Lo que cambia la cantidad de controles se difiere a `Update`, y el panel se dibuja de una foto tomada en `EventType.Layout` | `K1 capturas: visor` (exige 0 errores en el log de la app), `K3 capturas: relieve` (ídem) |
| **La escena pisa los valores serializados del C#**: cambiar el default de un campo público no cambia nada si `SampleScene.unity` ya lo guardó. Por eso los nombres de archivo son constantes `ARCHIVO` y no campos, y `ConfigurarEscena` rehace la escena con los defaults del código. Antes de cambiar un default: `grep` del campo en `SampleScene.unity`. Para imponer el valor del código: una propiedad que no dependa del campo guardado (`VisorEstructura.DibujaPerfiles`) o un campo con otro nombre (`PanelVisor.colorSeleccion`) | `U3 unity: nombres y copias al dia` (constantes `ARCHIVO` = `rutas.NOMBRES_EN_UNITY`, y las copias de StreamingAssets = `salidas/`) |
| **Lo que dice el panel puede no ser lo que se ve.** La cabecera leía siempre el caso de los resultados aunque se viera un reanálisis o la carga móvil. Ojo con el rótulo: "Desp. max" es la **norma** y el `max_desplazamiento` del servidor la **mayor componente**. Y la `w` de un área tributaria es **solo la losa**: el `wz` de G suma el peso propio | `K1 capturas: visor` (la fuente de cada cabecera, `PanelVisor.FuenteDeLoQueSeVe`), `U1 unity: contrato JSON <-> C#` (`w + w_peso_propio = w_total_G = −wz` de G) |
| **Los datos de dibujo del muro** (`dir_largo`, `largo`, `espesor`) los emite cada cuerpo con **su** convención; si no viajan, el visor los deduce con la del otro y un muro del cuerpo antiguo sale **girado 90°**, con `b` y `h` cruzados. No se ve en ningún número: las dos lecturas dan el mismo `A`, `Iy` e `Iz` | `E1 edificio: dato` (convención de muros por cuerpo; `b = espesor`, `h = largo`), `U1 unity: contrato JSON <-> C#` (`dir_largo` presente y unitario) |
| **La exageración de la deformada** no puede ser un número fijo de la escena: el mismo factor dibuja un edificio deformado en un modelo y una carpa colapsada en otro. La calcula Python (`calculo.esfuerzos.escala_deformada`: el mayor desplazamiento de **todos** los casos al 5 % de la diagonal, `FRACCION_DIAGONAL`) y viaja en `info.escala_deformada` (×160), una sola por modelo | `U1 unity: contrato JSON <-> C#` (escala × desplazamiento = el objetivo ± medio paso del redondeo), `R1 resultados: al dia y cierre f_j` |
| **Un suelo plano sobre un terreno escalonado**: la planta de fundaciones del cuerpo antiguo rotula dos N.R. y sus apoyos de la terraza quedaban 3.96 m en el aire; el chequeo "la cota está en el apoyo más bajo" daba OK igual. El terreno viaja en niveles (`info.terrenos`): la base en -7.97 (45 apoyos) y la terraza en -4.01 (39) | `U1 unity: contrato JSON <-> C#` (cada apoyo no auxiliar sobre el nivel cuya región lo contiene, contado por nivel), `E1 edificio: dato` |
| **Una barra dibujada como un palo recto** entre sus nodos deformados no se dobla: una columna entre dos pisos que se corren distinto solo se **inclina**. Los giros `rx, ry, rz` de los nudos ya viajaban y nadie los usaba. La barra se dibuja con las funciones de forma del elemento (`VisorEstructura.CurvaDe`), transcritas de `calculo.elastica.desplazamiento_en`. No dibuja la flecha de la carga repartida dentro del vano: sumarla sería cálculo en C# | `U2 unity: transcripciones C# = elastica.py` (lee las líneas del C# y las evalúa contra Python: dos copias de la misma fórmula no pueden divergir en silencio) |
| **Media tabla de combinaciones** hace que el mapa D/C sea optimista sin que nada falle. En un modelo lineal `−E` **no** es la misma demanda que `+E` (da vuelta el axial sísmico), y `0.9G ± 1.4E` es la que manda en tracción de muros y columnas de borde. `laboratorio.json` declara las **11** de NCh3171 / ACI 318-08 9.2.1, cada una con su `_por_que`; nada en el código supone cuántas hay | `L4 laboratorio: superposicion contra corrida explicita` (las 11 contra OpenSees), `R1 resultados: al dia y cierre f_j` (los 15 casos) |
| **Un `u` enorme casi nunca es la capacidad: es el axial.** La rama de tracción de la curva P-M tiene 2 puntos y parece poco muestreo, pero con el acero sin endurecer la interacción entre tracción pura y flexión pura **es** una recta: densificarla con fibras solo agregaría el endurecimiento de Steel01, que no es capacidad nominal. Los `u = 9999` son **patas de núcleo revisadas solas**; la tracción que las saca de su curva es el par interno del núcleo. Antes de tocar el muestreo, mirar el axial y de qué grupo es la pata (`calculo.demanda.grupos_de_nucleo`) | `C4 capacidad: nucleos = grupos de resultados.json` (50 patas en 15 grupos, 735 filas) |
| **Una dimensión escrita como constante en el código no se parece a un supuesto, y nadie la revisa.** El pilar del cuerpo antiguo vivía como `0.50 x 0.50` en el código, sin origen; la lámina 2017_67-103 lo rotula `P. 70x70`. El cuerpo salía mucho más flexible, eso explicaba casi la mitad de los NO PASA, y el equilibrio cerraba igual. Las secciones viven en `edificio.json` con su `origen` o su `_supuesto`, y se leen **sin default**: si falta una, el `KeyError` dice cuál | `E1 edificio: dato` (lo supuesto declarado es lo usado) |
| **La superposición SÍ se suma en C#, y es a propósito** (INSTANT, sección 2). Dos errores que no daban ningún número malo: interpolar por la `x` de la estación (viene redondeada a 4 decimales) en vez de por **fracción de índice**, y registrar el caso como `"combinacion"`, que el hook solo reemplaza si es `"superposicion"`: el primer movimiento andaba y los siguientes quedaban congelados | `R5 resultados: sliders instantaneos (replica)` (el algoritmo en float32 sobre 10 juegos de λ), `K1 capturas: visor` (lo que la app escribió, con la versión del caso subiendo en cada movimiento) |
| **La deformada de la persona también se suma en C#, con la misma licencia, y una flecha que no está en ningún nodo no se ve.** Aplicar la deformada redibuja, y pedirla al redibujar la pedía en cada cuadro: se pide al **moverse** y se aplica a lo más cada 0.08 s. La flecha local dentro de la viga cargada entra al dibujo por `VisorEstructura.FlechaEnVano`, que vale cero si la deformada dibujada no es la de la persona | `P2 persona: suma = OpenSees`, `U2 unity: transcripciones C# = elastica.py`, `K2 capturas: persona` (lo que la app sumó = OpenSees) |
| **El relieve de Google Earth no trae cotas, y el JSON del visor no dice de qué edificio es.** Un trazo "pegado al suelo" se guarda con `z = 0`: las cotas salen del DEM Copernicus GLO-30, calzado en vertical con los 85 apoyos en terreno. `modelo.json` no trae `info.edificio`: el relieve trae la **huella** del modelo (`info.n_nodos`, `info.n_elementos`) y el visor la compara al cargar | `P3 relieve del sitio` (el techo de la foto calza con el del modelo, el terreno sube hacia +x como las terrazas, cada apoyo dentro del DEM), `K3 capturas: relieve` |
| **Una textura real en la vista realista falla en silencio de tres maneras**: un material creado con `new Material` y `_NORMALMAP` sale **plano en el exe** (la build borra las variantes que ningún asset usa); un mapa normal sobre una malla **sin tangentes** deja negras las caras no horizontales; el albedo de un hormigón real es un tercio del de las texturas procedurales. Los materiales y el cielo son **assets** en `Resources/Ambiente`, todo constructor de malla hace `RecalculateTangents()`, y un ruido de periodo corto arma **otra** grilla | `H1 vista realista: recursos` (licencias CC0, normales como `NormalMap`, `_NORMALMAP` por GUID, `_DETAIL_MULX2`, el sol del HDRI en el rumbo de la luz) |

## 7. Reglas para el agente

1. **Toda** modificación al modelo, a las cargas o a lo que se exporta
   termina corriendo `python sap.py verificar` (y, si cambió algo de
   `entrada/`, antes `python sap.py preparar`). Si algo falla, se dice con
   la salida; no se relaja la tolerancia para que pase.
2. Cuando una verificación marque algo, **primero** sospechar de la
   verificación y comprobar la hipótesis (así aparecieron el peso propio en
   la carga distribuida, el +1 de la cota de redondeo y el confinamiento
   en el balanceado).
3. Una tolerancia se **mide** contra su causa (redondeo, muestreo, float32),
   no se elige a ojo.
4. Una sola definición de cada cosa: la sección de fibras que se resuelve
   es la que se dibuja; los nombres de archivo los manda
   `rutas.NOMBRES_EN_UNITY` (y el C# los repite en su constante `ARCHIVO`,
   vigilada por U3); el área tributaria vive en el elemento.
5. Lo leído del plano y lo supuesto se distinguen **en el dato**
   (`origen`, `_supuesto`, `provisorio`), no en la memoria de nadie.
6. Avisar antes de tocar `calculo/` y `unity/`: son de todos. En Unity,
   todo `.cs` se mueve **con** su `.meta` (mismo GUID); antes de cambiar el
   default de un campo público, `grep` del campo en `SampleScene.unity`.
7. Mensajes de commit que digan **por qué** y qué se comprobó, con los
   números.
8. Se cita por **nombre de función o de módulo**, nunca `archivo:línea`:
   agregar una línea en medio de un archivo corre todas las citas de abajo
   sin ningún error.

**Lo que no se "limpia"** (parece desprolijo y es así a propósito; tocarlo
mueve números): los redondeos a 8, 4 y 6 decimales; `COTA_REDONDEO = 5e-5`;
`FACTOR_COMA_FLOTANTE`; `u = 9999`; el orden de los casos y de las
combinaciones; las 9 estaciones equiespaciadas; el formato de
`calculo.laboratorio.describir()` (es la huella que viaja en cada salida);
la firma de familia P-M; `demanda()` sin default en muros; el cierre al filo
(0.9999999995); la numeración de `calculo.edificio.subdividir`; los
`except BaseException` del servidor (el laboratorio corta con
`SystemExit`); `silenciar=False` al armar la base de `/combinar`.

## 8. Cómo saber si está todo bien

```powershell
python sap.py verificar            # la suite entera (42)
python sap.py verificar --rapido   # sin las 6 lentas (36)
python sap.py revisar qa           # la tabla de QA de 10 filas
```

Los números de control viven en **`verificacion/numeros_de_control.json`**
(los decimales escritos como texto: se exigen a medio último dígito). Si un
cambio los mueve, no se corrige el número para que pase: se decide si el
cambio es correcto y, si lo es, se cambia el número **ahí**, con el commit
que lo explica. Los principales:

| | valor | lo mide |
|---|---|---|
| edificio | 563 nodos, 950 elementos, 47 secciones (44 de hormigón), 10 diafragmas, 4 casos del modelo | E1, E2 |
| por cuerpo | antiguo 331 nodos / 572 elementos; LT2 232 / 378 | E1 |
| G | 98728.8608 kN = 64579.8816 (antiguo) + 34148.9792 (LT2) | E1, M1 |
| junta | 0.050 m | E2 |
| casos del modelo | Q 20118.4025 kN; EX = EY 10021.3500 kN (6388.2870 + 3633.0630); mayor componente G 7.5488, Q 2.9052, EX 16.4151, EY 16.8064 mm | M2, L3 |
| terreno | base -7.97 con 45 apoyos; terraza -4.01 con 39 | U1, E1 |
| tributarias | 551 elementos con losa, 6894.59 m² | E3 |
| derivas (NCh433) | LT2 EX 1/1011, EY 1/1659 (cota 3.91); antiguo EX 1/2188, EY 1/895 (cota 7.87) | E4 |
| laboratorio | A = 6894.5944 m², Q = 20683.7833 kN, V = 10907.0752 kN; 15 casos; escala ×160; columna demo 200005, muro demo 100537; 207 elementos con fierro; NO PASA 7 en S3 y 14 en 0.9G-1.4EX; peor cierre 0.9999999995 | L2, R1 |
| superposición | E1 9.6322 mm (0 NO PASA), E2 12.3262 mm (0), E3 25.1115 mm (9 NO PASA, 3 fuera de curva), de 207 | R4 |
| columna 200037 | Mn(P = 0) 1190.2 kN·m; nariz de la P-M en P = 4186 kN, M = 1762 kN·m | C1 |
| demanda G + Q | 54 familias, 207 elementos con fierro; la más exigida 100080, u = 0.560 | C3 |
| núcleos | 50 patas, 15 grupos, 735 filas de pata | C4 |
| benchmark | UZ techo = -0.06348 mm | M1 |
| carga móvil | 30 posiciones, escala ×1600, máximo 0.9635 mm | P1 |
| persona | 1113 casos, escala ×540; 100 kN a media viga 200141: uz -0.715 mm, M -123.53 kN·m bajo la carga | P2, K2 |
| M1 | borrar la columna 200069: el nodo 200186 pasa de -3.64515 a -21.59875 mm bajo G | M4 |
| AR | 21 elementos, 22 nodos, 23024 números idénticos a los resultados | A1 |
