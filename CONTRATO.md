# CONTRATO.md — Python ⇄ JSON ⇄ Unity, el servidor y la AR

Qué viaja de OpenSees a la pantalla, con qué nombre exacto, de dónde sale
cada número y quién lo usa. Si una clave cambia en un lado y no en el
otro, **Unity no avisa**: por eso este documento y las guardias del final
(§12). Las reglas generales están en `CLAUDE.md`; el uso, en `README.md`.

```
entrada/ → calculo/ (OpenSees) → exportar/ → salidas/*.json, *.xlsx
                                                │  python sap.py sincronizar
                         ┌──────────────────────┴───────────────────────┐
                         ▼                                              ▼
   unity/Assets/StreamingAssets/ (y la de cada build)        ar/web/datos/ar.json
             │  LectorStreaming + JsonUtility                           │  ar.js (teléfono)
             ▼                                                          ▼
   visores C#: dibujan, no calculan  ◄── HTTP ──►  exportar.servidor (puerto 5000)
```

---

## 1. Lo que lee Unity: cinco JSON y un Excel

| archivo (StreamingAssets) | qué trae | clase raíz C# | lo lee | cuándo | lo escribe |
|---|---|---|---|---|---|
| `modelo.json` | el modelo que dibuja el visor (§7.1) | `ModeloEstructural` | `VisorEstructura` | al arrancar | `exportar.modelo` |
| `resultados.json` | los 15 casos del laboratorio, los elementos y las curvas P-M, **más** los bloques `superposicion` y `cargas_y_armadura` (§6) | `Resultados` | `VisorResultados`; `VisorCargasYArmadura` toma su bloque del visor ya cargado | al arrancar | `exportar.resultados` |
| `carga_movil.json` | las 30 posiciones de la carga móvil (§5) | `AnexoCargaMovil` | `VisorCargaMovil` | al arrancar | `exportar.carga_movil` |
| `persona.json` | los casos unitarios de la persona (§7.3) | `InfluenciasPersona` | `VisorPersona` | al usar la pestaña | `exportar.persona` |
| `relieve.json` | el relieve del sitio (§7.4) | `RelieveJson` | `AmbienteVisor` (parte `Relieve`) | al cargar el modelo | `exportar.relieve` |
| `resultados.xlsx` | el libro del edificio (§4) | — | el botón "Abrir Excel de resultados" (lo abre el sistema) | al apretarlo | `exportar.excel` |

Además, fuera de StreamingAssets: `Resources/Personaje/atst.json`
(`PersonajeJson`, el AT-ST; lo arma `python sap.py atst`) y
`Resources/Ambiente/**` (materiales, texturas y cielo de la vista
realista; los arma el editor con `RecursosRealistas`).

**Los nombres** viven en `calculo.rutas.NOMBRES_EN_UNITY` y en la constante
`ARCHIVO` de cada lector (`VisorEstructura.ARCHIVO`,
`VisorResultados.ARCHIVO`, `VisorCargaMovil.ARCHIVO`,
`VisorPersona.ARCHIVO`, `AmbienteVisor.ARCHIVO`). Son constantes y no
campos de la escena, porque la escena pisaba el valor del código sin
avisar. `U3 unity: nombres y copias al dia` compara las dos listas y el
md5 de cada copia contra `salidas/`.

**`python sap.py sincronizar`** es lo único que escribe en las
StreamingAssets (la del proyecto y la de cada build que exista: la app
compilada lee **su** copia) y en `ar/web/datos/`. Copia solo lo que tiene
otro md5, de una vez (un temporal y `os.replace`: un visor que lee justo en
ese momento ve el viejo o el nuevo, nunca uno a medias). Un JSON que dice
ser de otro edificio (`info.edificio` distinto de `conjunto`) no se copia;
un origen que falta no borra nada; los nombres viejos se borran con su
`.meta`. `--seco` dice qué haría; `--destino CARPETA` copia ahí y nada más.
En Android los archivos van dentro del `.apk`: hay que recompilar.

**Cada lector comprueba que el archivo sea de este modelo**, y si no, no
dibuja nada y lo dice en su aviso: `VisorResultados` compara `n1`, `n2` y
`seccion` de cada elemento con el modelo; `VisorCargasYArmadura`, el
edificio y los nodos; el bloque `superposicion`, su `info.edificio` y sus
`info.parametros` contra los de `resultados.json`; `persona.json` y
`relieve.json`, la **huella** del modelo (`info.n_nodos`,
`info.n_elementos`), porque `modelo.json` no trae `info.edificio`.

### 1.1 Las reglas de `JsonUtility`

`JsonUtility` es el lector de JSON de Unity y **falla en silencio**: si una
clave del JSON no calza con un campo de la clase C#, deja el campo en su
valor por defecto (0, `null`, `false`) y sigue. Un `My` mal escrito no da
error: da un diagrama plano. Además:

- no lee **arreglos anidados** (`float[][]`): cada lista va dentro de una clase;
- no lee **diccionarios**: se usan listas con un `id`;
- solo lee **campos públicos**, no propiedades;
- `ToJson` escribe **todos** los campos declarados, vengan o no en el JSON
  original. En el modelo que Unity manda a `/analizar`, un 0 o un vacío
  puede ser "no vino": `area_tributaria` y `w_gravedad` en 0,
  `info.edificio` en `""`, `info.cota_terreno` en `-9999`, `info.terrenos`
  en `[]`, y `secciones[].E` y `.G` en 0 = "usa el material del modelo"
  (`calculo.opensees.normalizar_secciones` los trata así). Y lo que el C#
  no declara (por ejemplo la `enfierradura` de cada elemento) no vuelve.

Por eso las clases de contrato tienen exactamente los campos del JSON,
**sin métodos**: `verificacion.unity` las lee como texto y las compara con
los JSON en las dos direcciones (`U1`), y Unity en batch los lee de verdad
(`U4`). Las clases C# nuevas no pueden llamarse como una de `UnityEngine`.

---

## 2. API C# entre visores

Todo vive en el namespace global y en `Assembly-CSharp`. Los C# se
compilan sin abrir Unity con `python sap.py unity compilar` (con `--solo
<archivos .cs>` mira solo los tuyos: sale con 1 si hay errores CS en ellos,
lista los ajenos como AVISO, y con 2 si no pudo verificar). Compila con los
`.csproj` del editor: no ve lo que solo falla al construir la app (código
dentro de `#if UNITY_WEBGL`, `#if UNITY_ANDROID` o `#if !UNITY_EDITOR`).

### 2.1 Lo que comparten

#### `EventosVisor` (estático)

| evento | firma | lo avisa | lo escuchan |
|---|---|---|---|
| `ModeloCargado` | `Action` | `VisorEstructura`, una vez, tras el primer `Redibujar` y con `Listo = true` | `CamaraOrbital` (encuadra), `AmbienteVisor`, `PanelVisor` |
| `Redibujado` | `Action` | `VisorEstructura.Redibujar()` al terminar; `AvisarRedibujado()` avisa **después** `MaterialesCambiados` | `AmbienteVisor` (registra el material técnico y aplica la vista), `PanelVisor`, `VisorCargasYArmadura`, `VisorCargaMovil`, `VisorPersona` |
| `ModeloEditado` | `Action<string motivo>` | `EditorEstructura`, p. ej. `"borrar elemento 200069"` | `VisorResultados` (resultados desactualizados), `PanelVisor` (aviso en la cabecera), `ClienteReanalisis`, `VisorCargaMovil` y `VisorPersona` (se apagan con aviso) |
| `PedirCentrar` | `Action<Vector3 centro, float tamano>` | `PanelVisor` (Ir a, Centrar), la lista de críticos del mapa, `VisorCargaMovil` | `CamaraOrbital`. `centro` en coordenadas **Unity**; `tamano` en m; `tamano <= 0` no cambia el zoom |
| `SeleccionCambio` | `Action<string tipo, int id>` | `PanelVisor`, **única fuente de selección** | `EditorEstructura`, `AmbienteVisor`. `tipo` = `TIPO_ELEMENTO` (`"elemento"`), `TIPO_NODO` (`"nodo"`) o `TIPO_NINGUNO` (`""`, id `-1`) |
| `VistaCambio` | `Action` | quien cambie `AjustesVista` (la pestaña Vista) | `VisorEstructura` (filtro de piso), `AmbienteVisor`, `VisorResultados`, `PanelVisor` |
| `MaterialesCambiados` | `Action` | `AvisarRedibujado()` (automático) y `AmbienteVisor` al terminar de aplicar una vista | el mapa D/C (`VisorResultados.Mapa`). Protocolo en §8 |

Quien se suscribe en `OnEnable`/`Start` se desuscribe en
`OnDisable`/`OnDestroy`. Cada suscriptor se llama en su propio `try/catch`:
uno que falla no corta a los demás. **Nadie llama a
`VisorEstructura.Redibujar()` dentro de un suscriptor de `Redibujado` o
`MaterialesCambiados`**: lazo infinito.

#### `AjustesVista` (estático, en `EventosVisor.cs`)

| miembro | qué es |
|---|---|
| `bool realista` | vista realista (texturas) o técnica (colores por tipo) |
| `bool suelo` | dibujar el suelo en `info.cota_terreno` y las terrazas de `info.terrenos` (§7.2) |
| `bool relieve`, `string relieveEstado` | el relieve del sitio y lo que el panel dice de él |
| `bool losas` | las losas de dibujo (los polígonos de las áreas tributarias) |
| `float cotaVisible` | filtro de piso: `NaN` = todos; si no, la cota z OpenSees del piso (`TOLERANCIA_COTA` = 0.01) |
| `EnCotaVisible(z)`, `ElementoEnCotaVisible(zA, zB)` | un punto pasa el filtro; una barra pasa si la **menor** de sus dos cotas es la visible (la losa y lo que nace de ella). Una sola regla para el visor, los diagramas, el mapa D/C, las capas y la armadura |

Quien cambia un campo llama a `EventosVisor.AvisarVistaCambio()`.

#### `LectorStreaming` (estático)

`IEnumerator Leer(nombre, ok, error)` lee `StreamingAssets/<nombre>` con
`UnityWebRequest` y llama exactamente uno de los dos, una vez. Funciona en
Windows, Android (`jar:file://`) y Web (una URL); `File.ReadAllText` diría
"no existe" en los dos últimos. `UrlDe(nombre)` arma la URL (un nombre que
ya es URL o ruta absoluta se usa tal cual). `RutaExcelResultados()` da la
ruta del Excel de StreamingAssets, o `null` donde no es una carpeta
(teléfono); `AbrirArchivo(ruta, out error)` lo abre con el programa del
sistema.

#### `PanelUI` (estático) e `IPanelIncrustable`

`PanelUI.Preparar()` es la **primera línea de cada `OnGUI`** que use los
estilos (escalados por DPI, sin `GUI.matrix`: los `Rect` siguen en píxeles
reales). Trae los estilos (`Texto`, `Tenue`, `Titulo`, `Seccion`, `Boton`,
`BotonActivo`, `Caja`, `Aviso`, `Pasa`, `NoPasa`, `Mono`), los controles
(`Plegable(clave, titulo, abierto)`, `Opcion`, `Fila`, `Insignia`) y **una
sola** definición del color de demanda-capacidad,
`ColorDemandaCapacidad(conFamilia, u, pasa)`: gris sin familia, morado
`u >= 9999`, rojo si no pasa, amarillo `u >= 0.7`, verde el resto (lee `u` y
`pasa` del JSON, no revisa nada). Las claves de `Plegable` no se renombran:
las usan las capturas.

```csharp
public interface IPanelIncrustable
{
    string TituloPestana { get; }
    bool PanelPropio { get; set; }
    void DibujarPanel();
}
```

#### `VisorResultados`: casos externos y conteos

| miembro | qué es |
|---|---|
| `void RegistrarCasoExterno(CasoLab caso)` | agrega o reemplaza por nombre un caso completo que llegó de afuera (E1..E3 del bloque `superposicion`, LIBRE de `/combinar`, INSTANT): lo indexa igual que los del archivo y sube `versionCasos`. **Solo reemplaza** un caso existente si es de tipo `"superposicion"` |
| `int versionCasos` | lo leen las firmas de caché (P-M, diagramas, mapa) |
| `static void ContarDemandas(CasoLab, out noPasan, out fueraDeCurva, out total)` | la cabecera "NO PASA n/m" y la leyenda del mapa: el mismo número |
| `bool LecturaTerminada` | `VisorCargasYArmadura` la espera antes de tomar su bloque |
| `void DibujarPMEnLinea()` | la P-M dentro de la pestaña Elemento |

#### `ModeloEstructural` (las clases de `modelo.json`)

`ElementoPorId(int)` y `TributariasDe(int)` usan índices que se rehacen si
cambia la cantidad de elementos; **después de toda edición** de nodos,
elementos o secciones se llama `InvalidarIndice()`. `EquilibrioCaso` trae
las claves de `calculo.opensees.equilibrio` (§3); "vino" se pregunta por el
largo del arreglo:
`c.equilibrio != null && c.equilibrio.aplicada_kN != null && c.equilibrio.aplicada_kN.Length == 3`.
`Ejes.AUnity` es el único cambio de ejes (`Unity(x, z, y)`).

### 2.2 API por visor

**`VisorEstructura`** — la estructura. `Modelo` (el modelo cargado; el mismo
objeto que se manda al servidor), `Listo` (para quien llega tarde a
`ModeloCargado`: `WaitUntil(() => visor != null && visor.Listo)`),
`ObjetosDeElementos`, `ObjetosDeNodos`, `ObjetoDeElemento(id)`,
`ObjetoDeNodo(id)` (`null` si la capa está apagada, el id no existe o es de
otro piso), `PosicionActual(Nodo)` (dónde está dibujado ahora, con la
deformada), la deformada (§2.3), `ShaderCompatible()` (el shader que no sale
magenta en URP; para todo material nuevo), las capas `verNodos`,
`verNodosAuxiliares`, `verColumnas`, `verVigas`, `verMuros`, `verBrazos`,
`verPerfiles` (después de cambiarlas, `Redibujar()`), `DibujaPerfiles` y
`fantasmaFueraDelPiso` (con un piso filtrado, lo demás se dibuja gris, sin
collider y fuera de `ObjetosDeElementos`).

**`CamaraOrbital`** — `centro`, `distancia`, `EncuadrarTodo()`,
`VistaPlanta()`, `VistaElevX()` (mira el plano X-Z de OpenSees),
`VistaElevY()`, `VistaIso()`, `FijarAngulos`, `bloqueada`, `HuboArrastre`.
Escucha `PedirCentrar`; un dedo orbita, dos hacen pinza y paneo.

**`PanelVisor`** — el panel con pestañas y el inspector:
`SeleccionarElemento(id)`, `SeleccionarNodo(id)`, `LimpiarSeleccion()`,
`ElegirPestana(titulo)`, `ElegirPiso(nivel)` (-1 = todos), `RectPanel()` (la
ventana P-M se abre a su derecha), `MouseSobreUI()`, `colorSeleccion`,
`FuenteCabecera` y `TextoCabecera`, `FijarEscalaAMano(escala)`, y la API
`Capturas_*` que usan las capturas (no hay reflexión: si algo cambia, no
compila).

**`VisorResultados`** — `Anexo` (los resultados leídos), `casoActivo`,
`CasoActivo()`, `ElegirCaso(nombre)` (diferirlo si se llama desde `OnGUI`),
el evento `CambioCasoActivo`, `Seleccionar(id)`, `ElementoPorId(id)`,
`EsfuerzosDe(id)` (del caso activo), `DemandaDe(id, caso)`,
`AplicarDeformadaDelCaso()`, `QuitarDeformada()`, `EnfocarElemento(id)`,
`Aviso`, `AnexoCalzaConElModelo`, `AnexoDesactualizado` (queda en `true`
tras `ModeloEditado` hasta recargar) y `MotivoDesactualizado`. El mapa:
`MostrarMapaDC(bool)`, `MapaDCActivo`, `MapaDCPintadas`,
`CasoConMasNoPasa()`. La superposición: `urlServidor` (la base del servidor,
guardada en PlayerPrefs con la clave `s5_url_servidor`, que no se renombra),
`OrigenDe(caso)` (de dónde salió cada caso, para el panel). INSTANT:
`CASO_INSTANT`, `Ins_Combinar(lambdas)`, `Ins_Version`, `Ins_MsUltima`.

**`VisorCargasYArmadura`** — no lee archivo propio: espera
`VisorResultados.LecturaTerminada` y toma el bloque `cargas_y_armadura`.
`mostrarCargas`, `mostrarArmadura`, `casoCarga`, `enfierrarTodas`. Las
barras se ubican con `PosicionActual`: siguen **cualquier** deformada que
esté puesta, y en cada `Redibujado` se mueven, no se recrean.

**`EditorEstructura`** (pestaña "Modificar") — `NodoSeleccionado`,
`ElementoSeleccionado`, `ArrastrandoNodo`, `BorrarElementoPorId(id)`. Toma la
selección de `SeleccionCambio` y avisa `ModeloEditado`. Al borrar una barra
limpia sus cargas repartidas; al borrar un nodo, sus cargas, las barras que
llegaban a él y sus referencias en diafragmas y brazos. Las cargas nodales
de los extremos de una barra borrada se quedan, a propósito (el peso propio
de las verticales viaja como carga nodal), y lo avisa.

**`ClienteReanalisis`** — habla con `/analizar`: `urlServidor`
(`URL_POR_DEFECTO`: `/analizar` en `localhost`, puerto 5000), `Analizar(fin)` (llama
`fin` una sola vez), `Ocupado`, `MostrarCaso(nombre)`, `CasosDisponibles()`,
`ResultadoDe(nombre)`, `CasoMostrado`, `DesplazamientoDe(id)`, `FuerzaDe(id)`,
`Estado`, `UltimoError`, `ExcelReanalisis`, `ExcelError`, `Desactualizado`, y
para la tabla de equilibrio `TieneEquilibrio`, `TablaEquilibrio`,
`NotaEquilibrio`, `DescribirEquilibrio`: muestra lo que manda el servidor,
**nunca** suma reacciones.

**`AmbienteVisor`**, **`VisorCargaMovil`** y **`VisorPersona`** se crean
solos (`RuntimeInitializeOnLoadMethod(AfterSceneLoad)`) si la escena tiene un
`VisorEstructura`. `AmbienteVisor` no expone API: todo por eventos y
`AjustesVista`; su suelo, sus terrazas y el relieve no tienen collider (la
selección es un raycast que se queda con el primero). `VisorCargaMovil`
("Carga movil": `Activar()`, `Apagar()`, `ElegirPosicion(i)`, `Activo`,
`Indice`, `CantidadPosiciones`, `Anexo`, `Aviso`) y `VisorPersona`
("Persona") son `IPanelIncrustable`.

**`ConstruirApp`** (editor) — `Construir()`, `ConstruirWeb()` (compresión
desactivada, `build/web`), `ConstruirAndroid()` (sale con 1 si falta el
módulo). Toda build pasa por `Compilar()`, que permite HTTP a la red local.
El menú **Laboratorio** del editor tiene además *Configurar escena*,
*Recursos de la vista realista* y *Verificar lectura de los JSON*.

### 2.3 Dibujar una deformada: una fuente a la vez

El formato es **`List<DespNodo>`**: `{id, ux, uy, uz, rx, ry, rz}` por nodo,
traslaciones en **m** y giros en **rad**, en ejes **OpenSees**. Es el mismo
de `CasoLab.desplazamientos`, `CasoResultado.desplazamientos` y
`PosicionMovil.desplazamientos`.

```csharp
visor.mostrarDeformada = true;           // sin esto no se ve
visor.factorEscala = escala;             // solo gráfico
visor.AplicarDeformada(desplazamientos); // ya llama a Redibujar()
```

- Se espera la lista **completa**; un nodo que no está se dibuja en su
  posición original. `AplicarDeformada` reemplaza la anterior entera.
- **La última que se aplica manda, y nadie re-aplica la suya sin que el
  usuario la pida.** Para quitarla, `visor.LimpiarDeformada();
  visor.Redibujar();`, **solo si la puso tu script** y sigue siendo la tuya;
  si otra fuente puso otra, se suelta sin borrar nada.
- Las fuentes: `PanelVisor` (Sin deformar, Caso activo; en *Avanzado*, la G
  precalculada de `modelo.json` con `UsarDeformadaPrecalculada()` y los
  sismos del bloque de cargas), `VisorResultados.AplicarDeformadaDelCaso`,
  `ClienteReanalisis.MostrarCaso`, `VisorCargaMovil` y `VisorPersona` (al
  caminar; se pide al **moverse**, no al redibujar).
- La escala la recomienda Python (`info.escala_deformada`, §6.1): el panel la
  usa la primera vez y no pisa lo que mueva el usuario.
- **Flecha dentro del vano**: `visor.FlechaEnVano = (id, xi) => ...` suma un
  desplazamiento (m, ejes OpenSees) a la curva de **una** barra. Lo pone quien
  sabe la carga dentro del vano (`VisorPersona`, con la forma que exporta
  Python), vale cero cuando la deformada dibujada ya no es la suya y se suelta
  al quitarla.
- Los **giros** no son decorativos: con ellos el visor curva cada barra (§9).
  Una fuente que los mande en cero dibuja palos rectos, sin avisar.

### 2.4 El objeto y el renderer de un elemento

```csharp
GameObject go = visor.ObjetoDeElemento(id);      // null si no se dibuja
Renderer r = go != null ? go.GetComponent<Renderer>() : null;
foreach (var kv in visor.ObjetosDeElementos) { /* kv.Key = id, kv.Value = GameObject */ }
```

Los objetos se destruyen y se crean de nuevo en cada `Redibujar()`: no
guardar referencias entre redibujos (escuchar `Redibujado` o
`MaterialesCambiados`). Cambiar su `sharedMaterial`: solo según §8.

### 2.5 Lo que no se toca

| qué | por qué |
|---|---|
| los nombres `Elem_<id>_<tipo>`, `Nodo_<id>`, `NodoAux_<id>` y los componentes `DatoElemento` / `DatoNodo` | `objeto_unity` de `resultados.json` se compara en vivo con el objeto seleccionado, y la suite lee del C# la línea que nombra la barra |
| el texto del inspector (`VisorResultados.DescribirElemento`) y los rótulos que leen las capturas ("Caso activo", "NO PASA n/m", "Max. componente", "Reanalisis del servidor", "Carga movil") | van a `registro.txt` y se cruzan con Python |
| las claves de `PanelUI.Plegable`, la clave `s5_url_servidor` de PlayerPrefs, los prefijos privados `Sup_`, `Ins_`, `Pnl_`, `Hook_` | las usan las capturas y las preferencias guardadas |
| las clases de contrato (un archivo de JSON = sus clases, sin métodos) | `verificacion.unity` las lee como texto |
| las fórmulas transcritas (`VisorEstructura.CurvaDe`; en `VisorPersona` los pesos N1..N4, la forma local, las sumas y los momentos) | `U2` lee esas líneas y las compara con `calculo.elastica` |
| `ConstruirApp.Construir` | el lanzador la llama por nombre |
| el log `Modelo cargado: N nodos, M elementos` de `VisorEstructura` | se busca en el log del teléfono |

### 2.6 Convenciones

- Clases `[Serializable]` del contrato con nombres que no choquen: las de la
  carga móvil llevan sufijo `Movil`. Se reusan `DespNodo`, `ReacNodo`,
  `EquilibrioCaso` y `CasoLab`; no se redefinen.
- `FindObjectsByType<T>()` **sin** `FindObjectsSortMode` (obsoleto en Unity 6.5).
- Materiales nuevos cacheados por color con `ShaderCompatible()`; nada de
  `renderer.material` (crea una copia por objeto).
- IMGUI: lo que cambia la escena o la cantidad de controles se difiere a
  `Update`; el panel se dibuja de una foto tomada en `EventType.Layout`.
- Nada de cálculo estructural en C# (CLAUDE.md §2), salvo las dos sumas de §10.

---

## 3. Servidor

**Un solo servidor, puerto 5000**: `python sap.py servidor [--lan] [--puerto
5000] [--sin-precalentar] [flags]` (`exportar.servidor`). Por defecto escucha
en 127.0.0.1; `--lan` en toda la red local (teléfono, build Web). Los flags
del laboratorio cambian la base de `/combinar`; tienen que ser los de
`resultados.json`, o el visor avisa que los parámetros no calzan.

| ruta | pedido | respuesta |
|---|---|---|
| `GET /ping` | — | `{"estado": "vivo", "motor": "OpenSees"}` |
| `POST /analizar` | el modelo (`JsonUtility.ToJson(ModeloEstructural)`) | sus casos resueltos, con equilibrio, y el Excel del reanálisis |
| `POST /combinar` | `{"edificio": "conjunto", "G": 1.2, "Q": 1.0, "EX": -1.4, "EY": 0.0}` | el caso LIBRE completo y su equilibrio |
| `GET /estados` | — | E1..E3 (sin su caso) y los rangos de los sliders |

**Dos fuentes de casos, cada una en su ruta**: `/analizar` resuelve los
casos que trae el modelo que manda Unity (los **del modelo**, editados o
no); `/combinar` combina los casos **del laboratorio**, los mismos de
`resultados.json`. Solo G coincide.

### `POST /analizar`

Construye el modelo una vez (`calculo.opensees.construir_y_resolver`) y
resuelve sus casos bajo `opensees.LOCK` (OpenSees es un singleton: dos
pedidos a la vez se borrarían el modelo uno al otro).

- **Multi-caso** (el modelo trae `casos_de_carga`, que es lo que manda
  Unity): `{ok, error, avisos[str], casos[{nombre, ok, max_desplazamiento,
  desplazamientos[{id, ux, uy, uz, rx, ry, rz}], reacciones[{id, fx, fy, fz,
  mx, my, mz}], fuerzas_elementos[{id, f[12]}], equilibrio}], excel,
  excel_error}`.
- **Plana** (las cargas en la raíz, un caso): `desplazamientos`,
  `reacciones`, `fuerzas_elementos` y `max_desplazamiento` en la raíz, sin
  `equilibrio`.
- `equilibrio` = `calculo.opensees.equilibrio` del caso: `aplicada_kN[3]`,
  `reaccion_kN[3]` (solo las filas que **cuentan**, por GDL), `error_kN[3]`,
  `cargas_sin_convertir`, `nodos_en_diafragma`, `confiable`. Si no se pudo
  calcular, `null` y un aviso: un chequeo que falla no tumba un análisis
  resuelto.
- `excel`: la ruta **absoluta** de `salidas/reanalisis.xlsx`
  (`exportar.excel.escribir_libro_reanalisis`); `excel_error`: por qué no
  hay. Un Excel que no se pudo escribir (o que está abierto) **nunca** rompe
  `/analizar`.
- Unidades: m y rad; kN y kN·m. `max_desplazamiento` es la **mayor
  componente** (el "Desp. max" de `resultados.json` es la **norma**). `f` es
  `localForce`: fuerzas **sobre** la barra en i y j.
- C#: `RespuestaServidor` (`casos`, `excel`, `excel_error`), `CasoResultado`,
  `EquilibrioCaso`, `FuerzaElemento`.

### `POST /combinar`

La base (los cuatro casos del laboratorio resueltos y las curvas P-M,
`calculo.superposicion.base`, unos 15 a 30 s) se arma **una vez** y queda en
memoria; al arrancar se arma en segundo plano (`--sin-precalentar` lo
evita). Desde ahí cada pedido es `calculo.superposicion.caso_combinado`:
suma lineal en Python, sin volver a OpenSees, con la demanda-capacidad
rehecha entera porque no es lineal.

| clave | tipo C# | regla |
|---|---|---|
| `ok`, `error` | bool, string | `error` vacío si `ok` |
| `edificio` | string | el del pedido; el servidor resuelve **un** edificio (`conjunto`): otro nombre es un 400 |
| `parametros` | string[] | las líneas de `calculo.laboratorio.describir(p)` de la base; iguales a `resultados.json → info.parametros` si son los mismos parámetros |
| `caso` | `CasoLab` | **completo**, con la forma de §6: `nombre = "LIBRE"`, `tipo = "superposicion"`, `descripcion`, `factores = [G, Q, EX, EY]`, `max_desplazamiento_mm`, `desplazamientos` (todos los nodos), `esfuerzos` (todas las barras, con estaciones), `demandas` (las barras con fierro) |
| `equilibrio` | `EquilibrioCaso` | `calculo.superposicion.equilibrio_combinado`: la carga combinada contra las reacciones combinadas, por GDL. El panel la muestra tal cual |

Cualquier λ finito vale (los rangos son de los sliders); uno tan grande que
la combinación desborda responde 400. Unity: `RegistrarCasoExterno(resp.caso)`
y `ElegirCaso("LIBRE")`, con un timeout de al menos 30 s (el primer pedido
puede armar la base). C#: `PeticionCombinar`, `RespuestaCombinar`.

### `GET /estados`

```json
{"ok": true, "error": "",
 "estados": [{"nombre": "E1", "descripcion": "1.0G + 1.0Q",
              "lambdas": {"G": 1.0, "Q": 1.0, "EX": 0.0, "EY": 0.0}}],
 "rangos": {"G": {"min": 0.0, "max": 1.6, "paso": 0.05}, "Q": {"min": 0.0, "max": 1.6, "paso": 0.05},
            "EX": {"min": -1.4, "max": 1.4, "paso": 0.05}, "EY": {"min": -1.4, "max": 1.4, "paso": 0.05}}}
```

E1 = 1.0G + 1.0Q, E2 = 1.2G + 1.6Q, E3 = 1.2G + 1.0Q − 1.4EX, y los rangos,
salen de `entrada/laboratorio.json` (bloque `superposicion`). Los objetos de
`estados` son `EstadoSuperposicion` sin `caso` ni `equilibrio`. C#:
`RespuestaEstados`, `Rangos`, `Rango`, `Lambdas`. Sin servidor, el visor
reintenta cada 10 s; E1..E3 siguen andando desde `resultados.json`.

### Errores y CORS

- **Toda respuesta es JSON, también los errores**: `{"ok": false, "error":
  "..."}`. Unity lee el cuerpo también en un `ProtocolError`; con una página
  HTML mostraría "JSON ilegible" en vez del motivo.
- **400** si el pedido es inválido (se arregla cambiando el pedido: JSON
  roto, falta una clave, una sección inexistente, un `vecxz` paralelo al eje,
  un modelo de más de 32 MB); **500** si falló algo nuestro. En `/analizar`
  el error trae además `avisos: []`, `excel: null` y `excel_error`. Los 404 y
  405 que arma Flask solo (una ruta mal escrita, un `GET /combinar`) también
  salen en JSON.
- `/combinar` y `/estados` atrapan `BaseException` (salvo Ctrl+C): el
  laboratorio corta con `SystemExit`, y un `SystemExit` dentro de un hilo de
  Flask terminaría la petición sin respuesta.
- `OPENSEES_DEBUG=1` agrega el traceback a la respuesta (apagado: trae
  rutas absolutas del disco). Siempre queda completo en la consola.
- **CORS**: `Access-Control-Allow-Origin: *` (y `Allow-Methods`,
  `Allow-Headers: Content-Type`) en toda respuesta, para la build Web, que
  corre en otro origen. `OPENSEES_CORS=0` lo apaga.

---

## 4. El Excel

`exportar.excel` escribe libros que una persona puede abrir sin saber nada
del proyecto. **En Excel no se calcula nada**: ninguna celda tiene fórmula
(un texto que empieza con `=` se escribe como texto).

| función | qué escribe |
|---|---|
| `escribir_libro_anexo(ruta=None, argv=None)` | el libro del edificio: los 15 casos del laboratorio con los mismos números de `resultados.json`. `ruta=None` = `salidas/resultados.xlsx`; `argv` = flags del laboratorio |
| `escribir_libro_desde_anexo(anexo, ctx, ruta=None, argv=None)` | lo mismo desde unos resultados ya construidos (lo usa `sap.py exportar todo` para armar la base una vez) |
| `escribir_libro_reanalisis(modelo, respuesta, ruta=None)` | el de un `/analizar`: `modelo` es el JSON que mandó Unity, `respuesta` la del servidor (multi-caso o plana; si falta `equilibrio`, lo calcula con la misma regla) |

Las tres devuelven la **ruta absoluta** del `.xlsx`, crean la carpeta si
falta, escriben de forma atómica, dan un `PermissionError` claro si el
archivo está abierto en Excel, y son **deterministas** (mismos datos, mismos
bytes). La parte genérica (`escribir(ruta, hojas)`, `leer`, `estructura`) no
sabe de edificios.

Hojas del libro del edificio: LEEME, Resumen, Nodos, Desplazamientos,
Elementos, Esfuerzos (i/j), Reacciones, Demanda-capacidad, Curvas P-M y
Supuestos. Desplazamientos en mm; el libro dice si un máximo es norma o
mayor componente. **Reacciones**: columnas "Cuenta en Fx/Fy" y "Cuenta en
Fz" con la regla de `calculo.opensees.equilibrio`; nunca un total de la
columna entera (dobla el corte basal). Un 0 que en el modelo de Unity
significa "no vino" (§1.1) no se escribe como dato.

---

## 5. `carga_movil.json`

Una carga puntual de 100 kN (`P_kN`, positiva hacia abajo) que recorre las
vigas 200203 a 200208 en 30 posiciones, cada una resuelta en OpenSees con
`eleLoad -beamPoint`. Unity elige un **índice**: salta entre posiciones y
**no interpola** (promediar dos vecinas aplana el quiebre del momento bajo
la carga). Clases en `VisorCargaMovil.cs`, con sufijo `Movil`.

| clave | tipo C# | qué es |
|---|---|---|
| `info` | `InfoMovil` | `edificio` (`"conjunto"`), `descripcion`, `unidades`, `generado_por`, `comando`, `convencion`, `n_posiciones`, `escala_deformada` (una para todo el recorrido, ×1600: con una por posición la animación "respiraría"), `_escala_por_que`, `max_desplazamiento_recorrido_mm`, `uz_bajo_carga_min_mm`, `indice_uz_bajo_carga_min`, `apoyos_z`, `cota_redondeo_kN`, `verificaciones` (`List<VerificacionMovil>`: `nombre`, `detalle`, `criterio`, `cumple`) |
| `P_kN`, `_P_kN_por_que` | float, string | la carga |
| `recorrido` | `RecorridoMovil` | `elementos`, `nodos`, `largos_m`, `largo_m`, `z`, `eje`, `coord`, `divisiones`, `descripcion`, `_por_que` |
| `posiciones` | `List<PosicionMovil>` | en orden a lo largo del recorrido |

Cada `PosicionMovil`: `indice`, `elemento` (la viga cargada), `xL` (abscisa
relativa desde `n1`), `a_m`, `L_m`, `s_m` (desde el inicio del recorrido),
`x`, `y`, `z` (el punto, OpenSees), `Px_local_kN`, `Py_local_kN`,
`Pz_local_kN`, `max_desplazamiento_mm` (norma), `nodo_max_desplazamiento`,
`uz_min_mm`, `nodo_uz_min`, `u_carga_m`, `uz_bajo_carga_mm`,
`M_bajo_carga_kNm`, `elastica` (`List<PuntoElasticaMovil>`: la elástica de la
viga cargada, que Python exporta y Unity solo escala), `desplazamientos`
(**todos** los nodos: van tal cual a `AplicarDeformada`), `reacciones`
(Unity no las suma), `equilibrio` (con la carga puntual **incluida** en
`aplicada_kN`), `reparto` (`RepartoMovil`: cuánto llega a cada extremo de la
viga, con el empotramiento y la explicación) y `conservacion`
(`ConservacionMovil`: ΣRz contra P con su cota, también en horizontal, y el
cierre).

---

## 6. `resultados.json`

Lo escribe `exportar.resultados` (y no escribe nada si una barra no cierra,
§6.2). Clases en `VisorResultados.cs` (y sus partes).

| clave | tipo C# | qué es |
|---|---|---|
| `info` | `InfoResultados` | de qué edificio es y cómo se generó |
| `casos` | `List<CasoLab>` | G, Q, EX, EY y las 11 combinaciones de `laboratorio.json`, **en ese orden** (15) |
| `elementos` | `List<ElementoOpenSees>` | **todos** los elementos del modelo (937) |
| `familias` | `List<FamiliaPM>` | una curva P-M por familia de sección con fierro (54) |
| `superposicion` | `Superposicion` | E1..E3 precalculados, tal cual (§6.4) |
| `cargas_y_armadura` | `CargasYArmadura` | flechas de carga, deformadas sísmicas y la jaula de una columna, tal cual (§6.5) |

Los dos bloques van **tal cual**, con sus claves de siempre: el C# solo
cambió **de dónde** saca el objeto (el `VisorResultados` ya cargado), no
cómo lo lee. Hay datos repetidos a propósito (las deformadas EX/EY del
bloque de cargas son los casos EX/EY; E2 es el caso `1.2G+1.6Q`), y una
guardia exige que sean iguales.

### 6.1 `InfoResultados`

| campo | qué es |
|---|---|
| `edificio` | `"conjunto"` |
| `descripcion`, `unidades` | m, kN, kPa; momentos kN·m; desplazamientos m y rad |
| `parametros` | las líneas de `calculo.laboratorio.describir(p)`: q, Cs, patrón, combinación (la huella de los parámetros) |
| `convencion` | la convención de esfuerzos y de dibujo, en texto |
| `generado_por` | el módulo que lo escribió |
| `caso_por_defecto` | el caso con que abre el visor: `S3` |
| `columna_demo` | la columna con fierro de mayor axial bajo G: **200005** |
| `muro_demo` | el muro con fierro más largo: **100537** |
| `n_estaciones_cargada` | 9 |
| `cota_redondeo_kN` | `5e-5`: el redondeo del servidor, medio de la cuarta decimal |
| `escala_deformada`, `_escala_deformada_por_que` | la exageración recomendada, ×160: el mayor desplazamiento de **todos** los casos llevado al 5 % de la diagonal de la caja del modelo (`calculo.esfuerzos.escala_deformada`), redondeado a 2 cifras. Una sola, para que no salte al cambiar de caso |

### 6.2 `CasoLab`, `EsfuerzosBarra` y la convención de esfuerzos

`CasoLab`: `nombre` (`G`, `Q`, `EX`, `EY`, `S3`, `1.4G`, `1.2G+1.6Q`,
`1.2G+1.0Q±1.4EX`, `1.2G+1.0Q±1.4EY`, `0.9G±1.4EX`, `0.9G±1.4EY`), `tipo`
(`caso`, `combinacion`, o `superposicion` para E1..E3, LIBRE e INSTANT),
`descripcion`, `factores` (`[λG, λQ, λEX, λEY]`), `max_desplazamiento_mm` (la
**norma** mayor), `desplazamientos` (`List<DespNodo>`, todos los nodos),
`esfuerzos` (`List<EsfuerzosBarra>`, uno por elemento) y `demandas`
(`List<Demanda>`, solo los elementos con fierro).

`EsfuerzosBarra`: `id`; `f` (12): `eleResponse(tag, 'localForce')`, `[N Vy Vz
T My Mz]` en *i* y en *j*, fuerzas **sobre** la barra en ejes locales (en una
combinación, `Σ λ·f`); `w` (3): la carga repartida `(wx, wy, wz)` en ejes
locales, kN/m, la que recibe `beamUniform`, combinada con los mismos λ; `x`:
las estaciones desde *i*, de 0 a L, **9** equiespaciadas si la barra tiene
carga repartida en ese caso y **2** si no; `N`, `Vy`, `Vz`, `T`, `My`, `Mz`:
los esfuerzos **internos** en cada estación, del equilibrio del tramo
`[0, x]` (`calculo.esfuerzos.esfuerzos_internos`):

```
N(x)  = −(N_i  + wx·x)                 tracción positiva
Vy(x) = −(Vy_i + wy·x)
Vz(x) = −(Vz_i + wz·x)
T(x)  = −T_i
My(x) = −(My_i + x·Vz_i + wz·x²/2)
Mz(x) = −(Mz_i − x·Vy_i − wy·x²/2)
```

En `x = L` tienen que dar exactamente `f_j`, el extremo *j* que calculó
OpenSees. El exportador lo comprueba en todas las barras y todos los casos
antes de escribir, contra una cota que sale del redondeo del servidor y de
la coma flotante (`calculo.esfuerzos.cota_de_cierre`); si una barra no
cierra, **no escribe el archivo**. Una viga simplemente apoyada con carga
hacia abajo tiene `My` **negativo** en el tramo. El servidor aplica la carga
con `beamUniform`, que recibe `wy, wz, wx` **en ese orden**.

### 6.3 `Demanda`, `ElementoOpenSees` y `FamiliaPM`

`Demanda` (el punto sobre la curva): `id`, `familia`; `P` (kN, **compresión
positiva**); `M` (kN·m: en una columna √(My² + Mz²); en un muro, el momento
**de su plano**, `|My|` o `|Mz|` según `elementos[].momento_en_el_plano`);
`M_fuera_plano` (muro: el otro; columna: 0); `extremo` (`i (inferior)` o
`j (superior)`: gana el de mayor M); `Mn` (la capacidad nominal a ese P,
interpolada en la curva); `u` (`M / Mn`; **9999** si `Mn = 0`, que es un P
fuera del rango de la curva); `pasa` (`u ≤ 1`); y de qué **núcleo** es la
pata, si lo es: `nucleo_patas` (0 = no es pata), `nucleo_P`, `nucleo_Asfy`,
`nucleo_estado` (`comprimido`, `traccion_dentro` o `traccion_fuera`). Los
campos de núcleo **no** cambian `pasa`: dicen de dónde viene el axial. Las
funciones son `calculo.demanda.demanda(f, tipo, plano)` (sin default para
muros: sin `plano` lanza un error) y `calculo.demanda.capacidad_en(P, curva)`.
El momento del plano lo dicen las inercias (`momento_en_el_plano(Iy, Iz)`:
`My` si `Iy > Iz`), porque los dos cuerpos eligieron distinto el `vecxz` de
sus muros (el LT2 la normal, el antiguo el largo).

`ElementoOpenSees` (los datos fijos de cada barra): `id`, `n1`, `n2`,
`tipo`, `seccion`, `momento_en_el_plano` (`My`, `Mz` o `""`), `L`,
`objeto_unity` (`Elem_<id>_<tipo>`, el nombre que le pone
`VisorEstructura.Redibujar`), `tag_opensees` (la línea
`element elasticBeamColumn` con A, E, G, J, Iy, Iz **en el orden en que el
servidor se los pasa**, y su `vecxz`), `material`, `fpc_MPa`, `E_kPa`,
`G_kPa` (los que usa el servidor para **esta** barra), `poisson`, `gamma`, `A`,
`Iy`, `Iz`, `J`, `b`, `h`, `vecxz`, `restr_n1`, `restr_n2` (`[ux uy uz rx ry
rz]` que el servidor fija, incluidos los del maestro de diafragma),
`diafragma_n1`, `diafragma_n2` (el maestro, -1 si ninguno),
`es_brazo_rigido`, `condiciones`, `cargada` (repartida en G o Q), `familia`
(-1 sin fierro) y `resultados` (de dónde salen sus esfuerzos). Los arma
`calculo.esfuerzos` replicando al servidor (`rigidez_como_el_servidor`,
`restricciones_como_el_servidor`).

`FamiliaPM` (una curva): `indice`, `clave` (la firma legible: sección, b,
h, barras, As, estribo, malla), `tipo`, `seccion`, `b`, `h`, `As_cm2`,
`cuantia_pct`, `refuerzo`, `fuente`, `P`, `Mn`, `Mmax` (puntos de
`calculo.capacidad.interaccion`: axial, momento nominal con el hormigón a
0.003 y momento máximo del M-φ), `de` (de dónde sale cada punto) y
`elementos`. Una familia agrupa las barras con **la misma firma**
(`calculo.demanda.firma_de_seccion`): misma sección y mismo fierro, misma
curva, calculada una vez.

**Qué hace Unity con todo esto**: escalarlo para dibujarlo, buscar el mayor
para ponerle etiqueta, y armar mallas y texto. Los esfuerzos y la
trazabilidad van al panel; `desplazamientos` a la deformada del caso
activo; `demandas` al punto de la ventana P-M y al mapa; `familias` a la
curva; `objeto_unity` se compara en vivo con el objeto seleccionado; `n1`,
`n2`, `seccion` se comparan con el modelo al cargar.

**La convención de dibujo.** Los momentos se dibujan **del lado
traccionado**: `My > 0` tracciona la fibra +z local (la curva va en
`+My·z_local`); `Mz < 0` tracciona la fibra +y local (va en `−Mz·y_local`).
`Vz`, `N` y `T` se dibujan en `z_local`, `Vy` en `y_local`, y el color dice
el signo; `wy` y `wz`, en su eje local, hacia donde empuja la carga. Los ejes
locales son `Elemento.localY` y `localZ` de `modelo.json`, que salen de la
misma regla que usa el servidor (`calculo.edificio.ejes_locales`).

### 6.4 El bloque `superposicion`

```json
"superposicion": {
  "info": {"edificio": "conjunto", "descripcion": "...", "generado_por": "...",
           "parametros": ["...las mismas líneas que info.parametros..."]},
  "estados": [{"nombre": "E1", "descripcion": "1.0G + 1.0Q",
               "lambdas": {"G": 1.0, "Q": 1.0, "EX": 0.0, "EY": 0.0},
               "caso": { CasoLab }, "equilibrio": { EquilibrioCaso }}]}
```

C#: `Superposicion` (`info`: `InfoSuperposicion`; `estados`:
`List<EstadoSuperposicion>`), con `nombre`, `descripcion`, `lambdas`
(`Lambdas {G, Q, EX, EY}`), `caso` (completo, como en `/combinar`, con
`nombre` = el del estado, `tipo = "superposicion"`, `factores = [G, Q, EX,
EY]`) y `equilibrio`. E1..E3 en ese orden; funcionan **sin servidor**.
`VisorResultados.Superposicion` comprueba `info.edificio` e
`info.parametros` contra los resultados y registra cada caso con
`RegistrarCasoExterno`.

### 6.5 El bloque `cargas_y_armadura`

C#: `CargasYArmadura` (en `VisorCargasYArmadura.cs`):

| clave | tipo C# | qué es |
|---|---|---|
| `info` | `InfoCargas` | `descripcion`, `edificio`, `unidades`, `parametros`, `nota` |
| `caja` | `CajaEdificio` | `x_min` … `z_max`: la caja del edificio, para correr las flechas al costado |
| `sismo` | `BloqueSismo` | `patron`, `Cs`, `corte_basal_kN`, `fuerza_maxima_kN` y `niveles` (`NivelSismo`: `nodo_maestro`, `x`, `y`, `z`, `peso_kN`, `fraccion`, `F_kN`) |
| `cargas` | `List<CasoCarga>` | G, Q, EX, EY y `COMBINACION`: `caso`, `descripcion`, `maxima_kN`, `total_kN`, `flechas` (`FlechaCarga`: `x, y, z` del punto, `fx, fy, fz`, `kN`) |
| `deformadas` | `List<CasoDeformada>` | EX y EY: `caso`, `max_horizontal_mm`, `desplazamientos` |
| `armadura` | `BloqueArmadura` | la jaula de **una** columna (la de mayor axial en G): `columna_id`, `axial_G_kN`, `b`, `h`, `diametro_barra`, `diametro_estribo`, `espaciamiento_estribo`, `cuantia_pct`, `procedencia`, `barras`, `estribo_exterior`, `estribo_rombo` (`PuntoSeccion {y, z}`), `nodo_inferior`, `nodo_superior` (`PuntoXYZ`) y `columnas` (`ColumnaRef {id, n1, n2, axial_G_kN}`: dónde se repite esa jaula con "en todas las columnas") |

---

## 7. Los otros tres JSON

### 7.1 `modelo.json` (`ModeloEstructural`)

Lo escribe `exportar.modelo` desde `entrada/edificio.json` (la estructura
más la vista) con la G precalculada en los nodos.

| clave | tipo C# | qué es |
|---|---|---|
| `info` | `InfoModelo` | `descripcion`, `unidades`, `caso_precalculado` (`G`), `nota`, `cota_terreno` (la base: -7.97), `terrenos` (§7.2). `edificio` existe en el C# y el archivo no lo trae |
| `material` | `MaterialModelo` | `fpc_MPa`, `poisson`, `gamma` del modelo (cada sección puede traer el suyo) |
| `secciones` | `List<Seccion>` | `nombre` (`<cuerpo>:<sección>`), `A`, `Iy`, `Iz`, `J`, `b`, `h`, `largo`, `espesor`, `E`, `G` (kPa; los del cuerpo de la sección) |
| `nodos` | `List<Nodo>` | `id`, `x`, `y`, `z` (OpenSees), `fijo`, `auxiliar`, `restricciones[6]`, y `ux … rz`: la G precalculada |
| `elementos` | `List<Elemento>` | `id`, `n1`, `n2`, `seccion`, `tipo` (`columna`, `viga_x`, `viga_y`, `muro`, `brazo`, `brazo_rigido`, `pilar_metal`, `diagonal`), `vecxz`, `localX`, `localY`, `localZ` (sellados con la regla del servidor), y en los muros `largo`, `espesor` y `dir_largo` (la dirección del largo en planta, con la convención de **su** cuerpo: el visor no la deduce), `area_tributaria`, `w_gravedad` |
| `diafragmas` | `List<Diafragma>` | `nodo_maestro`, `nodos`, `perpendicular` (3 = horizontal) |
| `brazos_rigidos` | `List<BrazoRigido>` | la lista del contrato (el edificio no usa `rigidLink`: sus brazos son barras) |
| `casos_de_carga` | `List<CasoDeCarga>` | los 4 casos **del modelo**: `nombre`, `descripcion`, `cargas_nodales` (`nodo, fx … mz`), `cargas_distribuidas` (`elemento, wy, wz, wx`) |
| `areas_tributarias` | `List<AreaTributaria>` | 705 polígonos: `elemento`, `nivel`, `area`, `luz`, `qG`, `carga_total`, `w` (**solo la losa**), `w_peso_propio`, `w_total_G` (`w + w_peso_propio = w_total_G = −wz` de G), `z`, `vertices`, `tamanos`, `n_poligonos` |

Trae además claves que el visor no lee (por ejemplo la `enfierradura` de
cada elemento y un `resumen`): `JsonUtility` las ignora, y no viajan de
vuelta a `/analizar`.

### 7.2 El terreno en niveles (`info.terrenos`)

El terreno no es un plano: la planta de fundaciones del cuerpo antiguo
rotula dos N.R., y con un solo plano en la cota más baja sus apoyos de la
terraza quedaban 3.96 m en el aire.

```json
"cota_terreno": -7.97,
"terrenos": [
  {"nombre": "base", "z": -7.97, "vertices": []},
  {"nombre": "ingenieria: terraza oriente (N.R. -4.01)", "z": -4.01,
   "vertices": [{"x": 7.67, "y": 47.35}, "..."]}]
```

- `NivelTerreno {nombre, z, vertices}`; `vertices` es `List<VerticePlanta>`
  (x, y OpenSees): un polígono simple antihorario, sin agujeros. **Vacío = la
  base**, el plano hasta el horizonte. Hay una base y su `z` es
  `cota_terreno`; cada terraza está más arriba y trae 3 vértices o más.
- Las regiones vienen de `edificio.json` (`vista`), y en el dato salen de la
  misma definición con que el modelo crea esos apoyos. No se dibujan a ojo.
- `AmbienteVisor` dibuja la base (con su hueco si algo queda bajo la cota) y
  cada terraza (`AmbienteVisor.Terrazas`): pasto a su `z` y taludes hasta la
  base, sin collider, hija del objeto `Suelo`; lo que queda bajo la terraza se
  recorta (`HuecoDelSuelo.CalcularTerraza`).
- Solo dibujo: ningún cálculo lee `terrenos`.
- Guardia: `U1` exige que **cada apoyo no auxiliar quede sobre un nivel** (su
  z = la del nivel cuya región lo contiene, a 0.01 m) y cuenta por nivel: 45
  en -7.97 y 39 en -4.01.

### 7.3 `persona.json` (`InfluenciasPersona`)

Lo escribe `exportar.persona`: una carga unitaria resuelta en OpenSees por
cada nodo que puede recibir a la persona (`Fz` = 1 kN hacia abajo, `Mx` y
`My` = 1 kN·m): 1098 casos.

| clave | tipo C# | qué es |
|---|---|---|
| `info` | `InfoInfluencias` | `edificio`, `generado_por`, `unidades`, la huella (`n_nodos` 558, `n_elementos` 937), `n_casos`, `P_por_defecto_kN` (100), `escala_deformada` (×540), `largo_dibujo_m`, `escala_momento`, `largo_momento_m`, `segundos_opensees`, y los supuestos con su porqué (`_supuesto_receptor`, `_supuesto_punto_en_la_viga`, `_supuesto_muro`, `_supuesto_P`) |
| `grupos` | `GrupoInfluencias[]` | los nodos de cada cuerpo (2 grupos: con la junta libre, una carga en un cuerpo no mueve al otro) |
| `casos` | `CasoInfluencia[]` | `nodo`, `grupo`, `gdl` (`Fz`, `Mx`, `My`), `datos` (los desplazamientos de los nodos de su grupo, enteros de 16 bits en base64, por `escala_t` en traslaciones y `escala_r` en giros), `elementos` y `fuerzas` (el `localForce` de las barras que muestra su receptor, igual, por `escala_f` y `escala_m`) |
| `receptores` | `ReceptorPersona[]` | 544: por cada región tributaria, quién recibe la carga: `elemento`, `nodo`, `n1`, `n2`, `tipo` (`viga` o `nodo`, la losa que apoya directo en un muro), `z`, `L`, `flex` (= L³/EI, m/kN), `dx`, `dy` (la dirección en planta) y `elementos_m` (las barras cuyos momentos se muestran) |

La carga cae en la **proyección** de la persona sobre el eje de la viga
dueña de la región donde está parada; si la región es de un muro, en su
nodo de esa cota. La suma y la elástica están en §10.

### 7.4 `relieve.json` (`RelieveJson`)

Lo escribe `exportar.relieve` desde `entrada/sitio/`. Solo dibujo.

| clave | tipo C# | qué es |
|---|---|---|
| `info` | `InfoRelieve` | `edificio`, `generado_por`, `fuente` (Copernicus DEM GLO-30), `atribucion`, `zona`, `_por_que`, la huella (`n_nodos`, `n_elementos`), `rumbo_x_grados` (el rumbo de +x, del techo trazado en Google Earth), `lon_centro_techo`, `lat_centro_techo`, `desfase_vertical_m` y `residuo_rms_m` (el calce vertical con los 84 apoyos en terreno) |
| `x0`, `y0`, `paso`, `nx`, `ny` | float, int | la malla, en m OpenSees (paso 4 m) |
| `z` | `float[]` | `ny` filas de `nx` cotas (z OpenSees); `sin_dato` es la cota de los nodos fuera de la zona |
| `cota_fondo` | float | la cota del terreno del modelo (`info.cota_terreno`): hasta ahí bajan los taludes |
| `huecos` | `HuecoRelieve[]` | `x1, y1, x2, y2`: la planta de cada cuerpo más un margen (2) |
| `techo_foto` | `VerticePlanta[]` | el techo trazado en Google Earth, llevado al modelo |

Con el relieve a la vista se apaga el plano del suelo (no las terrazas):
taparía la parte del relieve que queda más abajo.

---

## 8. Materiales y pestañas

### Protocolo de materiales (el mapa D/C y la vista realista)

Prioridad visual: **mapa D/C > realista > técnica**.

1. Solo dos cambian el `sharedMaterial` de los renderers de la estructura:
   `AmbienteVisor` y el mapa D/C (`VisorResultados.Mapa`). El resaltado de
   selección, la persona, los diagramas y la carga móvil no lo tocan:
   dibujan objetos propios (o usan `MaterialPropertyBlock`).
2. `VisorEstructura.Redibujar` crea los objetos con el material técnico y
   llama `AvisarRedibujado()`, que avisa **primero** `Redibujado` y
   **después** `MaterialesCambiados`.
3. `AmbienteVisor`, en `Redibujado` (y en `ModeloCargado`), **registra** el
   material técnico de cada renderer (en ese momento siempre es el técnico),
   aplica realista o técnica según `AjustesVista.realista` y termina con
   `EventosVisor.AvisarMaterialesCambiados()`. En `VistaCambio` aplica desde
   lo registrado (nunca lee el material actual, que puede ser del mapa) y
   termina igual.
4. El mapa D/C **no** escucha `Redibujado`. Al activarse y en cada
   `MaterialesCambiados`, guarda como base el `sharedMaterial` actual de cada
   renderer **salvo que sea uno de sus propios materiales**, y pinta. Al
   apagarse restaura la base de los renderers que sigan vivos. Recibir
   `MaterialesCambiados` dos veces no corrompe la base.
5. Materiales cacheados por color; nada de `renderer.material`.

En la vista realista los materiales son **assets** de `Resources/Ambiente`
(la build solo conserva las variantes de shader que algún asset usa) y toda
malla armada en código hace `RecalculateTangents()` (sin tangentes, un mapa
normal deja negras las caras no horizontales).

### Pestañas

- `PanelVisor` dibuja **Vista | Capas | Caso | Elemento** y después una
  pestaña por cada `IPanelIncrustable`, en este orden: **Modificar**
  (`EditorEstructura`), **Carga movil** (`VisorCargaMovil`), **Persona**
  (`VisorPersona`), y cualquier otro por título. Abre en **Caso**.
- Los busca con `FindObjectsByType<MonoBehaviour>()` e `is IPanelIncrustable`
  al arrancar y al cambiar de pestaña, y a cada uno le pone
  `PanelPropio = false`.
- Un panel incrustable dibuja solo con `GUILayout` (sin `BeginArea`, sin
  `ScrollView`, sin `GUI.Window`), usa `PanelUI` y difiere a `Update` lo que
  redibuja la escena. Con `PanelPropio == false` su `OnGUI` no dibuja nada.
  Sin `PanelVisor` en la escena, dibuja su propio panel.
- Si falta el panel de una pestaña esperada, `PanelVisor` lo dice con un
  texto, no con una pestaña vacía.

---

## 9. La curva de la deformada

Una barra dibujada como un palo recto entre sus nodos deformados no se
dobla. Lo que faltaba no era calcular: eran los **giros** de los nudos, que
viajan en cada desplazamiento (`rx, ry, rz`). Un nudo rígido obliga a la
barra a arrancar con **su** pendiente, y de ahí sale la curva.

- La forma son las **funciones de forma del propio elemento** (axial
  lineal, transversal cúbica de Hermite), las mismas con que OpenSees
  interpola entre sus dos nodos. La fórmula está escrita una vez en Python
  (`calculo.elastica.desplazamiento_en`) y transcrita a
  `VisorEstructura.CurvaDe`. **No es cálculo estructural**: no sale ningún
  número nuevo; solo se ponen vértices.
- El visor la usa en `CurvarBarras()`, al final de `Redibujar()` y antes de
  `AvisarRedibujado`, para que `AmbienteVisor` y el mapa D/C encuentren la
  malla definitiva. `TRAMOS_CURVA` = 8, y se salta la barra que se aparta del
  palo recto menos de `DESVIO_MINIMO` = 1 cm.
- La sección se barre **sin girar por la flexión** (las caras de los
  extremos quedan donde estaban y dos barras seguidas no se abren en el
  nudo). La **torsión** sí la gira (`SeccionGirada`): el giro sobre el eje de
  la barra varía lineal entre sus nudos, se exagera con el mismo
  `factorEscala` y bajo `GIRO_MINIMO` = 0.01 rad la barra queda como
  primitivo. El collider no se curva.
- No se curvan los muros, los brazos rígidos ni las líneas fantasma de
  otros pisos.
- **Lo que no dibuja, y no es un error**: la flecha que la carga repartida
  produce **dentro** del vano no está en ningún GDL nodal. Sumarla pediría E,
  I y la carga del caso en C#, que es cálculo. La única flecha dentro del
  vano que se dibuja es la de la persona (`FlechaEnVano`, §2.3), que viene de
  Python.
- Guardia: `U2 unity: transcripciones C# = elastica.py` lee las líneas de
  `CurvaDe`, las evalúa contra `calculo.elastica.desplazamiento_en` con tiros
  al azar y exige que coincidan (dos copias de la misma fórmula no pueden
  divergir en silencio); `U1` exige `rx/ry/rz` en todos los nodos y los tres
  ejes locales unitarios y perpendiculares.

---

## 10. Las dos sumas que se hacen en C#, a propósito

Las dos combinan casos que OpenSees ya resolvió, porque el enunciado pide
respuesta **al instante** y un viaje al servidor por cada movimiento no lo
es. Ninguna arma rigidez ni resuelve `K·u = F`. Cada una tiene su guardia.

### 10.1 INSTANT: los sliders de la superposición

`VisorResultados.Instantanea` (pestaña Caso, bloque "Superposicion
INSTANTANEA en Unity"): cuatro sliders `G`, `Q`, `EX`, `EY` que mueven la
deformada, los esfuerzos, los diagramas y el punto P-M sin servidor. Sus
botones E1..E3 ponen los λ del bloque `superposicion` (no hay otra copia de
los λ en el C#), para comparar a la vista con los precalculados.

1. **Escalar y sumar** los cuatro casos base de `resultados.json`. u, f y los
   esfuerzos a lo largo de la barra son lineales en λ porque `K` es la misma.
2. **Retabular antes de sumar**: los casos no vienen en las mismas
   estaciones (una viga cargada trae 9 en G y Q, y 2 en EX y EY). Se lleva
   cada caso a la malla más fina interpolando **linealmente por fracción de
   índice** (las mallas son equiespaciadas de 0 a L), y es exacto: sin carga
   repartida, N y V son constantes y M es una recta. Por la `x` de la
   estación no: viene redondeada a 4 decimales, y ese error por la pendiente
   del momento se nota.
3. **Rehacer la demanda**, que no es lineal: del `f` combinado salen (P, M)
   con la regla de `calculo.demanda.demanda()` (el extremo de mayor momento;
   columna √(My² + Mz²), muro el momento de su plano) y Mn se interpola en la
   curva de su familia.

El caso se registra con `RegistrarCasoExterno` como `"INSTANT"` y
**`tipo = "superposicion"`** (con `"combinacion"` el hook no lo reemplaza y
el visor queda congelado en el primer λ); `Ins_Version` sube en cada
movimiento. La aritmética es float32 y las cotas de la verificación la
incluyen. Si el modelo se edita, INSTANT queda desactualizado como el resto.

Guardia: `R5 resultados: sliders instantaneos (replica)` (el algoritmo,
repetido en Python en float32, contra `calculo.superposicion` en 10 juegos de
λ, incluidos negativos, uno solo y el nulo) y `K1 capturas: visor` (lo que la
app escribió al mover los sliders, con la versión subiendo, contra Python).

### 10.2 La persona

`VisorPersona.Deformada` y `VisorPersona.Momentos`: el modelo es lineal, así
que una carga P en la abscisa α = a/L de una viga es la suma de a lo más
**seis** casos unitarios de `persona.json` (Fz, Mx, My en sus dos nodos) con
los pesos de Hermite, que son las fuerzas nodales equivalentes que OpenSees
ensambla para `eleLoad -beamPoint`:

```
en n1:  Fz = −P N1(α)      M = P L N2(α) (z × d)
en n2:  Fz = −P N3(α)      M = P L N4(α) (z × d)       d = versor de la viga en planta
```

Dentro de la viga cargada se suma la flecha biempotrada,
`uz_local = −P (L³/EI) φ(ξ, α)`: Python exporta `flex` = L³/EI y el C# solo
evalúa la forma **adimensional** φ (E e I no entran al C#); entra al dibujo
por `FlechaEnVano`. Los **momentos**: cada caso trae el `localForce` de las
barras que muestra su receptor; Unity los suma con los mismos pesos y la
viga cargada agrega su empotramiento perfecto; M(x) es lineal entre
extremos con el quiebre de P. La deformada se pide al **moverse** y se
aplica a lo más cada 0.08 s (aplicarla redibuja todo el edificio).

**No es licencia para más**: la D/C de la persona no se calcula en C#.

Guardia: `P2 persona: suma = OpenSees` (la suma = OpenSees resolviendo la
carga directo, en todos los GDL; los enteros de 16 bits y el float32 dentro
de su cota; cada región tiene receptor; fuera de su grupo vale 0),
`U2 unity: transcripciones C# = elastica.py` (los pesos, la forma local, las
sumas y los momentos del C# se leen y se comparan con `calculo.elastica`),
`K2 capturas: persona` (lo que la app sumó = OpenSees: 100 kN a media viga
200141 dan -0.715 mm y -123.53 kN·m bajo la carga).

---

## 11. `ar.json` y la matriz de la AR

`exportar.ar` lo escribe en `salidas/ar.json` desde el modelo y
`resultados.json` (los mismos números que muestra el visor), y
`sincronizar` lo copia a `ar/web/datos/ar.json`, que lee el teléfono. Todo
en coordenadas y unidades de OpenSees. Dónde se pega la imagen y cómo se
muestra está en `entrada/laboratorio.json`, bloque `ar`.

| clave | qué es |
|---|---|
| `info` | `edificio`, `generado_por`, `resultados_de`, `unidades`, `regla_de_oro`, `ejes_opensees`, `mapeo_unity`, `mapeo_anchor`, `escala_deformada` (160), `caso_por_defecto` (`1.2G+1.0Q+1.4EX`), `modo_por_defecto` (`maqueta`) |
| `modos` | `sitio` (escala 1) y `maqueta` (escala 0.02 = 1/50), con su descripción |
| `marcador` | la **pose** de la imagen en el edificio: `elemento` (200037), `cara` (`+x`), `centro` `[-2.38, 55.0833, 1.35]`, `ejes` (`x`, `y`, `z`), `ancho_m` (0.20), `altura_centro_m` (1.40), `medio_ancho_columna_m` (0.35), y `maqueta` (su propio `centro` y `ejes`: la imagen acostada sobre la mesa) |
| `objetivo` | el elementTag de la columna: 200037 |
| `nodos` | 22: `id` (el **mismo** tag del modelo), `x`, `y`, `z`, `restricciones` |
| `elementos` | 21: `id` (el mismo elementTag), `tipo`, `seccion`, `n1`, `n2`, `b`, `h`, `L`, `localY`, `localZ`, `familia`, `momento_en_el_plano`, `tag_opensees`, `area_tributaria_m2` |
| `familias` | las curvas P-M del sector con fierro, **por su `indice`** (`"29": {clave, P, Mn, refuerzo}`), no por su posición en la lista: si los resultados se reordenaran, la app dibujaría la curva de otra sección sin que nada fallara |
| `tributarias` | los polígonos de las áreas tributarias del sector (`elemento`, `nivel`, `area`, `luz`, `qG`, `carga_total`, `w`, `w_peso_propio`, `w_total_G`, `z`, `vertices`, ...). No trae `forma`, y `ar.js` la lee: de ahí el `(undefined)` del panel (pendiente declarado) |
| `casos` | los 15 del laboratorio: `nombre`, `tipo`, `descripcion`, `factores`, y por id `desplazamientos` (`[ux, uy, uz, rx, ry, rz]`), `esfuerzos` (`x`, `f`, `w`, `N` … `Mz`) y `demandas` (`P`, `M`, `Mn`, `u`, `pasa`, `extremo`) |

**La matriz.** El marcador tiene `x` a la derecha de la imagen, `y` hacia
arriba y `z` saliendo de la columna hacia quien la mira (sistema derecho);
el anchor de MindAR usa los mismos ejes, en **anchos de imagen**. Para cada
punto `p` del modelo:

```
anchor = (escala / ancho_m) · Rᵀ (p − centro),     R = [ejes.x  ejes.y  ejes.z]
M = S(k) · Rᵀ · T(−centro),   k = escala / ancho_m
```

En sitio (`k = 5`) el nodo 200103 `(-2.73, 55.0833, 3.91)` queda en
`(0, 12.8, -1.75)` anchos: 2.56 m sobre el centro de la imagen y 0.35 m
detrás, en el eje de la columna. En maqueta (`k = 0.1`, origen en la base de
la columna) queda en `(0, 0, 0.396)`: 7.92 cm sobre la imagen. La
transformación está escrita **dos veces a propósito**: en `ar/web/ar.js`
(`matrizModeloAAnchor`, en el teléfono) y en `exportar.ar` (`a_anchor`).

En el teléfono no se resuelve nada: se transforma y se dibuja. La deformada
va recta entre nodos.

Guardias: `A1 AR: tags, resultados y pose` (los 21 elementos y 22 nodos con
el mismo tag, nodos, tipo y sección que el modelo; los 23024 números de la
app idénticos bit a bit a los resultados; la pose del marcador, ortonormal y
derecha, en la cara de la columna), `A2 AR: registro y tracking` (la matriz
de `ar.js`, corrida en un navegador sin ventana, = la de Python; la app
detecta la imagen en un video sintético desde poses conocidas) y
`A3 AR: precision del registro`.

---

## 12. Python que lee C#, y lo que vigila este contrato

Algunas guardias **leen el C# como texto**, para que una regla escrita en
dos lados no diverja en silencio. Buscan los `.cs` por nombre con
`calculo.rutas.cs(nombre)`: si un archivo cambia de carpeta la guardia lo
sigue, y si no aparece es una FALLA, no un salto.

| qué lee | quién | para qué |
|---|---|---|
| las clases de contrato de los cinco JSON, `atst.json`, `/combinar`, `/estados` y la respuesta de `/analizar` | `verificacion.unity` (contratos) | cada clave con su campo, en las dos direcciones, con tipos y anidados |
| `VisorEstructura.CurvaDe`; en `VisorPersona` N1..N4, la forma local, las sumas, `UzEn`, `MyEn`, `MzEn` | `verificacion.unity` (transcripciones) | evaluarlas contra `calculo.elastica` |
| las constantes `ARCHIVO` | `verificacion.unity` (nombres y copias) | = `rutas.NOMBRES_EN_UNITY` |
| la línea de `VisorEstructura` que nombra la barra (`"Elem_" + e.id + "_" + e.tipo`) | `verificacion.suite` (tabla QA, fila IDs) | `objeto_unity` de los resultados es el nombre del GameObject |
| `AmbienteVisor.SOL_REALISTA` | `herramientas.recursos_realistas` | girar el cielo para que su sol caiga donde está la luz |
| `ar/web/ar.js` (en un navegador) | `verificacion.ar` (registro y tracking) | la matriz del teléfono = la de Python |

| entrada de la suite | qué comprueba del contrato |
|---|---|
| `U1 unity: contrato JSON <-> C#` | claves, tipos, anidados y largos de los 5 JSON y las respuestas; ejes locales sellados; muros (`dir_largo` unitario, `b = espesor`, `h = largo`); terreno por niveles; `w + w_peso_propio = w_total_G`; la escala de la deformada; clases sin choque con `UnityEngine` |
| `U2 unity: transcripciones C# = elastica.py` | las fórmulas copiadas al C# (§9, §10.2) |
| `U3 unity: nombres y copias al dia` | nombres y md5 de StreamingAssets (proyecto y builds) y de `ar/web/datos/ar.json` contra `salidas/` |
| `U4 unity: JsonUtility real` | Unity en batch lee los 5 JSON con sus clases y los vuelve a escribir; Python compara campo a campo con la cota de float32 (sale con 2 si Unity está abierto) |
| `R1 resultados: al dia y cierre f_j` | `resultados.json` = lo que se arma ahora (tolerancia 0) y el cierre de cada barra |
| `R3 resultados: trazabilidad 100018` | la llamada a `ops.element` = `tag_opensees` = lo que lee Unity |
| `M1 motor: benchmark y servidor` | `/analizar` (multi-caso, plana, equilibrio), el Excel, `excel_error`, los 400, el tope de 32 MB y CORS |
| `X1 excel: libro y reanalisis` | celdas = resultados; suma filtrada de Reacciones = equilibrio; dos generaciones con los mismos bytes |
| `K1 capturas: visor`, `K2 capturas: persona`, `K3 capturas: relieve` | lo que la app compilada escribió en su `registro.txt` contra Python, y 0 errores en su log |
| `A1`, `A2`, `A3` | la AR (§11) |
