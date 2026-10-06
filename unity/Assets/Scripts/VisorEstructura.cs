/*
================================================================
  VisorEstructura.cs
================================================================
  DIBUJA el modelo estructural en 3D. Nada mas.

  No habla con el servidor ni define clases de datos: usa las de
  ModeloEstructural.cs. Quien calcula es AnalizadorEstructural.cs,
  que le pasa los desplazamientos ya resueltos.

  Esta separacion es la misma regla del CLAUDE.md: OpenSees calcula,
  Unity muestra.

  ----------------------------------------------------------------
  COMO USARLO
  1. El JSON sale del pipeline y lo copia el lanzador:
       python edificios/<ed>/exportar_unity.py     -> data/unity/<ed>.json
       python comun/lanzar_unity.py sincronizar <ed>
     que lo deja en Assets/StreamingAssets/ con el nombre que dice la
     ESCENA en 'nombreArchivo' (modelo_unity_edificio.json).
  2. Crea un GameObject vacio, llamalo "Visor".
  3. Arrastra este script encima.
  4. Play. Deberias ver el marco en 3D.

  Para ver la deformada de otros casos (Q, EX, EY) necesitas el
  servidor corriendo (python semana05/servidor_s5.py) y el script
  AnalizadorEstructural.

  ----------------------------------------------------------------
  CARGA ASINCRONA (Semana 5)
  El JSON se lee con LectorStreaming (UnityWebRequest), porque en
  Android y en Web StreamingAssets no es una carpeta y File.Exists da
  false aunque el archivo este. Eso hace que el modelo llegue UNO O
  MAS frames despues de Start: quien lo necesita no espera "un frame",
  espera a Listo o escucha EventosVisor.ModeloCargado.

  FILTRO DE PISO
  Redibujar respeta AjustesVista.cotaVisible (la regla de la cota
  menor, AjustesVista.ElementoEnCotaVisible). Lo de otros pisos no
  entra a ObjetosDeElementos: se dibuja, si fantasmaFueraDelPiso, como
  una linea gris sin collider, para que el piso se lea dentro del
  edificio sin que un click lo atraviese ni el mapa D/C lo pinte.
  ----------------------------------------------------------------
*/

using System.Collections;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;

public class VisorEstructura : MonoBehaviour
{
    [Header("Archivo")]
    [Tooltip("Lo pisa la escena (modelo_unity_edificio.json), y el lanzador "
           + "copia el modelo con el nombre que lee de la escena.")]
    public string nombreArchivo = "modelo_unity_edificio.json";

    [Header("Apariencia")]
    public float radioNodo = 0.15f;
    [Tooltip("Nodos intermedios de las vigas. Se dibujan mas chicos "
           + "para que no compitan con los nudos reales del marco.")]
    public float radioNodoAuxiliar = 0.05f;
    public float grosorBarra = 0.05f;
    public Color colorColumna = new Color(0.36f, 0.62f, 1f);    // azul
    public Color colorViga = new Color(0.88f, 0.48f, 0.37f);    // naranjo
    public Color colorMuro = new Color(0.65f, 0.65f, 0.70f);    // gris
    public Color colorBrazo = new Color(0.85f, 0.30f, 0.75f);   // magenta
    [Tooltip("El acero: pilares y diagonales de los balcones.")]
    public Color colorMetal = new Color(0.90f, 0.30f, 0.35f);   // rojo
    public Color colorApoyo = new Color(0.18f, 0.60f, 0.37f);   // verde
    public Color colorNodoAuxiliar = new Color(0.55f, 0.58f, 0.62f); // gris
    public Color colorDeformada = Color.yellow;

    [Header("Apoyos")]
    [Tooltip("NO SE USA: los cubos de apoyo los dibuja la capa 'Apoyos' de "
           + "VisorQA. Queda porque la escena lo serializa.")]
    public bool apoyosComoCubos = true;
    [Tooltip("NO SE USA (ver apoyosComoCubos).")]
    public float ladoCuboApoyo = 0.45f;

    [Header("Filtro de piso")]
    [Tooltip("Con un piso elegido (AjustesVista.cotaVisible), el resto del "
           + "edificio se dibuja como lineas grises sin collider: se ve "
           + "DONDE esta el piso sin que tape ni se pueda seleccionar.")]
    public bool fantasmaFueraDelPiso = true;
    public Color colorFantasma = new Color(0.62f, 0.64f, 0.68f);
    [Tooltip("Vista realista con deformada: color de las lineas de la posicion "
           + "sin deformar (las barras conservan el hormigon).")]
    public Color colorPosicionOriginal = new Color(0.16f, 0.20f, 0.27f);

    [Header("Deformada")]
    public bool mostrarDeformada = false;
    [Tooltip("Amplifica el desplazamiento. Los mm reales no se verian.")]
    public float factorEscala = 300f;

    [Header("Perfiles")]
    [Tooltip("Dibuja cada barra con su seccion REAL (b x h) en vez de un "
           + "cilindro generico. Asi se ve que una viga es 30x80 y otra "
           + "30x60, que es lo que se revisa a ojo contra el plano.")]
    public bool verPerfiles = false;

    [Header("Capas visibles")]
    public bool verNodos = true;
    [Tooltip("Los nodos intermedios de las vigas. Apagalos para ver "
           + "solo los nudos del marco.")]
    public bool verNodosAuxiliares = true;
    public bool verColumnas = true;
    public bool verVigas = true;
    public bool verMuros = true;
    [Tooltip("Brazos rigidos: el pedazo de muro entre el extremo real de "
           + "una viga y el baricentro donde vive la columna ancha, y las "
           + "esquinas donde dos muros son una sola pieza de hormigon.")]
    public bool verBrazos = true;

    // --- Estado ---
    /// El modelo cargado. AnalizadorEstructural lo lee para mandarlo
    /// al servidor: es el MISMO objeto, no una copia.
    public ModeloEstructural Modelo { get; private set; }

    // Desplazamientos actualmente dibujados, indexados por id de nodo.
    private Dictionary<int, DespNodo> deformadaActual = new Dictionary<int, DespNodo>();

    private List<GameObject> objetosCreados = new List<GameObject>();

    // Objetos de la escena indexados por el id de OpenSees. Es lo que
    // permite seleccionar y resaltar desde EditorEstructura.
    private Dictionary<int, GameObject> objetoDeNodo = new Dictionary<int, GameObject>();
    private Dictionary<int, GameObject> objetoDeElemento = new Dictionary<int, GameObject>();

    public GameObject ObjetoDeNodo(int id)
    {
        GameObject g;
        return objetoDeNodo.TryGetValue(id, out g) ? g : null;
    }

    public GameObject ObjetoDeElemento(int id)
    {
        GameObject g;
        return objetoDeElemento.TryGetValue(id, out g) ? g : null;
    }

    // --- API de la Semana 5 (semana05/CONTRATO.md) ---

    /// true despues de la primera carga y el primer dibujo. Para quien
    /// llega tarde a EventosVisor.ModeloCargado: WaitUntil(() => visor.Listo).
    public bool Listo { get; private set; }

    /// Todos los GameObject de barra dibujados, por elementTag. Los
    /// renderers que pinta AmbienteVisor y el mapa D/C. Solo lectura, y
    /// no llamar a Redibujar() mientras se recorre: lo vacia.
    public IReadOnlyDictionary<int, GameObject> ObjetosDeElementos { get { return objetoDeElemento; } }

    /// Todos los GameObject de nodo dibujados, por nodeTag. Mismas reglas.
    public IReadOnlyDictionary<int, GameObject> ObjetosDeNodos { get { return objetoDeNodo; } }

    /// Donde esta dibujado un nodo AHORA, con la deformada si esta puesta
    /// (coordenadas Unity). Para que lo que se dibuja encima (armadura,
    /// flecha de la carga movil) siga a la estructura.
    public Vector3 PosicionActual(Nodo n) { return PosicionDe(n); }

    private Dictionary<Color, Material> materiales = new Dictionary<Color, Material>();
    private bool necesitaRedibujar = false;

    // La cota con que se hizo el ultimo Redibujar (NaN = todos los pisos).
    // VistaCambio avisa tambien por 'suelo' y 'losas', que no cambian la
    // geometria: solo se redibuja si la cota o la vista es otra.
    private float cotaDibujada = float.NaN;

    // La vista con que se hizo el ultimo Redibujar. La realista dibuja las
    // secciones reales (DibujaPerfiles), asi que cambiar de vista SI cambia
    // la geometria y pide redibujar.
    private bool realistaDibujado = false;

    // Mallas propias de la deformada: el muro cizallado y la barra curvada,
    // una por elemento. Se destruyen en cada Redibujar (si no, quedan huerfanas).
    private readonly List<Mesh> mallasPropias = new List<Mesh>();

    /// true si las barras se dibujan con su seccion b x h: en la vista
    /// realista siempre (un edificio de tubos de 5 cm parecia un andamio);
    /// en la tecnica, si se pide con verPerfiles (como hasta la Semana 4).
    public bool DibujaPerfiles { get { return verPerfiles || AjustesVista.realista; } }

    // Barras con perfil que se dibujan DELGADAS mientras tienen un diagrama
    // encima: el diagrama nace en el eje y, dentro de una caja de 0.60 x
    // 0.80, solo asomaban los picos. Lo pide VisorSemana04.Diagramas.
    private readonly HashSet<int> barrasDelgadas = new HashSet<int>();
    private readonly Dictionary<int, Vector3> escalaDePerfil = new Dictionary<int, Vector3>();

    /// Las barras (por elementTag) que se dibujan delgadas, como en la vista
    /// tecnica; null o vacio = todas con su seccion. Solo cambia la escala
    /// de las cajas ya dibujadas (no redibuja ni avisa eventos) y se
    /// recuerda para el proximo Redibujar.
    public void FijarBarrasDelgadas(IEnumerable<int> ids)
    {
        barrasDelgadas.Clear();
        if (ids != null) foreach (int id in ids) barrasDelgadas.Add(id);
        foreach (KeyValuePair<int, Vector3> kv in escalaDePerfil)
        {
            GameObject go;
            if (!objetoDeElemento.TryGetValue(kv.Key, out go) || go == null) continue;
            go.transform.localScale = EscalaPerfil(kv.Key, kv.Value); Curvar(kv.Key);
        }
    }

    Vector3 EscalaPerfil(int id, Vector3 real)
    {
        return barrasDelgadas.Contains(id) ? new Vector3(grosorBarra, grosorBarra, real.z) : real;
    }

    // ============================================================
    void OnEnable()
    {
        EventosVisor.VistaCambio += AlCambiarVista;
    }

    void OnDisable()
    {
        EventosVisor.VistaCambio -= AlCambiarVista;
    }

    /// Corrutina: el JSON llega por UnityWebRequest, uno o mas frames
    /// despues. Listo y ModeloCargado van DESPUES del primer Redibujar,
    /// para que quien los escuche ya encuentre los GameObject.
    IEnumerator Start()
    {
        bool cargado = false;
        yield return CargarJSONAsincrono(ok => cargado = ok);
        if (!cargado) yield break;

        UsarDeformadaPrecalculada();
        Redibujar();
        Listo = true;
        EventosVisor.AvisarModeloCargado();
    }

    // ============================================================
    // CARGAR EL JSON
    // ============================================================

    /// Lee StreamingAssets/nombreArchivo con LectorStreaming y deja el
    /// resultado en Modelo. Funciona en Windows, Android y Web.
    IEnumerator CargarJSONAsincrono(System.Action<bool> fin)
    {
        string texto = null, error = null;
        yield return LectorStreaming.Leer(nombreArchivo, t => texto = t, e => error = e);

        if (texto == null)
        {
            Debug.LogError("No encontre el modelo: " + error);
            Debug.LogError(ComoGenerarlo());
            fin(false);
            yield break;
        }
        fin(Interpretar(texto));
    }

    /// Version SINCRONA, solo donde StreamingAssets es una carpeta
    /// (Windows y el editor). Queda por compatibilidad: el arranque usa
    /// la asincrona, que tambien sirve en Android y Web.
    public bool CargarJSON()
    {
        string ruta = Path.Combine(Application.streamingAssetsPath, nombreArchivo);

        if (ruta.Contains("://") || !File.Exists(ruta))
        {
            Debug.LogError("No encontre el archivo: " + ruta);
            Debug.LogError(ComoGenerarlo());
            return false;
        }
        return Interpretar(File.ReadAllText(ruta));
    }

    /// Una sola interpretacion del texto para las dos lecturas. El log
    /// "Modelo cargado: N nodos, M elementos" se busca en el logcat del
    /// movil (semana05/CONTRATO.md): no cambiarle la forma.
    bool Interpretar(string texto)
    {
        ModeloEstructural leido;
        try
        {
            leido = JsonUtility.FromJson<ModeloEstructural>(texto);
        }
        catch (System.Exception ex)
        {
            Debug.LogError("El JSON no se pudo interpretar: " + ex.Message);
            return false;
        }

        if (leido == null || leido.nodos == null || leido.nodos.Count == 0)
        {
            Debug.LogError("El JSON no trae nodos. Revisa que sea el formato "
                           + "que escribe edificios/<ed>/exportar_unity.py");
            return false;
        }

        Modelo = leido;
        Modelo.InvalidarIndice();
        Debug.Log($"Modelo cargado: {Modelo.nodos.Count} nodos, "
                  + $"{(Modelo.elementos != null ? Modelo.elementos.Count : 0)} elementos, "
                  + $"{(Modelo.casos_de_carga != null ? Modelo.casos_de_carga.Count : 0)} casos.");
        return true;
    }

    string ComoGenerarlo()
    {
        return "Generalo con 'python edificios/<ed>/exportar_unity.py' y copialo "
               + "con 'python comun/lanzar_unity.py sincronizar <ed>' a "
               + "Assets/StreamingAssets/" + nombreArchivo
               + " (el nombre lo manda la escena).";
    }

    // ============================================================
    // DEFORMADA
    // ============================================================

    /// Usa los ux/uy/uz que vienen en el JSON (caso G precalculado).
    /// Permite ver una deformada sin tener el servidor corriendo.
    public void UsarDeformadaPrecalculada()
    {
        deformadaActual.Clear();
        foreach (Nodo n in Modelo.nodos)
        {
            deformadaActual[n.id] = new DespNodo {
                id = n.id, ux = n.ux, uy = n.uy, uz = n.uz, rx = n.rx, ry = n.ry, rz = n.rz
            };
        }
    }

    /// Borra la deformada dibujada. Se llama al editar el modelo: los
    /// desplazamientos anteriores ya no corresponden a esta geometria.
    public void LimpiarDeformada()
    {
        deformadaActual.Clear();
        mostrarDeformada = false;
    }

    /// Recibe los desplazamientos resueltos por el servidor.
    /// Lo llama AnalizadorEstructural cuando llega una respuesta.
    public void AplicarDeformada(List<DespNodo> desplazamientos)
    {
        if (desplazamientos == null) return;
        deformadaActual.Clear();
        foreach (DespNodo d in desplazamientos) deformadaActual[d.id] = d;
        Redibujar();
    }

    /// Posicion de un nodo, deformada o no segun el toggle.
    Vector3 PosicionDe(Nodo n)
    {
        if (!mostrarDeformada) return Ejes.PosicionDe(n);

        DespNodo d;
        if (!deformadaActual.TryGetValue(n.id, out d)) return Ejes.PosicionDe(n);
        return Ejes.PosicionDeformada(n, d.ux, d.uy, d.uz, factorEscala);
    }

    // ============================================================
    // DIBUJO
    // ============================================================
    /// true si hay desplazamientos cargados para poder dibujar la
    /// deformada. Queda en false despues de editar el modelo.
    public bool HayDeformada { get { return deformadaActual.Count > 0; } }

    public void Redibujar()
    {
        if (Modelo == null) return;

        // Pedir la deformada sin tener desplazamientos NO puede quedar
        // en silencio: PosicionDe devolveria la posicion original de
        // todos los nodos y el edificio se veria intacto, como si no se
        // deformara. Pasa siempre que se edita el modelo, porque
        // MarcarModificado() borra la deformada a proposito: la que
        // habia ya no corresponde a la geometria nueva.
        if (mostrarDeformada && deformadaActual.Count == 0)
        {
            mostrarDeformada = false;
            Debug.LogWarning(
                "No hay deformada que dibujar, asi que el toggle se apago "
                + "solo (si no, el edificio se veria sin deformar y "
                + "parecria que no se mueve).\n"
                + "Se borro al editar el modelo: los desplazamientos "
                + "anteriores ya no corresponden a esta geometria.\n"
                + "Aprieta ENTER para recalcular en el servidor, o vuelve "
                + "a cargar el JSON para recuperar el caso G "
                + "precalculado.");
        }

        foreach (var go in objetosCreados) if (go != null) Destroy(go);
        objetosCreados.Clear();
        objetoDeNodo.Clear();
        objetoDeElemento.Clear();
        foreach (Mesh malla in mallasPropias) if (malla != null) Destroy(malla);
        mallasPropias.Clear();
        escalaDePerfil.Clear();

        // Se lee UNA vez: si alguien cambia la cota a mitad del dibujo,
        // el piso queda entero y VistaCambio pide el siguiente.
        cotaDibujada = AjustesVista.cotaVisible;
        realistaDibujado = AjustesVista.realista;
        bool perfiles = verPerfiles || realistaDibujado;
        Transform fantasmas = null;
        // Con la deformada en la vista realista las barras conservan el
        // hormigon (no se pintan de amarillo sobre el pasto): la posicion
        // ORIGINAL se marca con lineas finas oscuras, sin collider.
        Transform original = null;
        bool marcarOriginal = mostrarDeformada && realistaDibujado;

        // --- Nodos ---
        if (verNodos)
        {
            foreach (Nodo n in Modelo.nodos)
            {
                if (n.auxiliar && !verNodosAuxiliares) continue;
                if (!AjustesVista.EnCotaVisible(n.z)) continue;

                GameObject esfera = GameObject.CreatePrimitive(PrimitiveType.Sphere);
                esfera.name = (n.auxiliar ? "NodoAux_" : "Nodo_") + n.id;
                esfera.transform.position = PosicionDe(n);

                // Los auxiliares van mas chicos y en gris: estan para
                // que se vea la curva de la viga, no para leerlos.
                bool apoyado = n.fijo || TieneAlgunaRestriccion(n);
                float r = n.auxiliar ? radioNodoAuxiliar : radioNodo;
                // En la realista un nudo sin apoyo queda dentro de la columna
                // de 0.70 m: una esfera de 30 cm en cada nudo se veia como las
                // juntas de un andamio. Se achica (sigue existiendo para el click
                // y para quien busque ObjetosDeNodos); los apoyos quedan igual.
                if (realistaDibujado && !apoyado && !n.auxiliar) r = radioNodoAuxiliar;
                esfera.transform.localScale = Vector3.one * r * 2f;

                Pintar(esfera, n.auxiliar ? colorNodoAuxiliar
                             : (apoyado ? colorApoyo : colorColumna));

                esfera.AddComponent<DatoNodo>().idNodo = n.id;
                objetoDeNodo[n.id] = esfera;
                objetosCreados.Add(esfera);
            }
        }

        // --- Elementos ---
        if (Modelo.elementos == null) { EventosVisor.AvisarRedibujado(); return; }
        foreach (Elemento e in Modelo.elementos)
        {
            if (!CapaVisible(e.tipo)) continue;

            Nodo a = Modelo.NodoPorId(e.n1);
            Nodo b = Modelo.NodoPorId(e.n2);
            if (a == null || b == null)
            {
                Debug.LogError($"Elemento {e.id} referencia un nodo inexistente "
                               + $"(n1={e.n1}, n2={e.n2}). Se omite.");
                continue;
            }

            if (!AjustesVista.ElementoEnCotaVisible(a.z, b.z))
            {
                if (fantasmaFueraDelPiso)
                {
                    if (fantasmas == null)
                    {
                        fantasmas = new GameObject("FueraDelPiso").transform;
                        objetosCreados.Add(fantasmas.gameObject);
                    }
                    CrearFantasma(PosicionDe(a), PosicionDe(b), e, fantasmas);
                }
                continue;
            }

            GameObject barra;
            Seccion secMuro = e.EsMuro ? Modelo.SeccionPorNombre(e.seccion) : null;
            bool muroConTamano = e.EsMuro && (e.largo > 0.01f
                                              || (secMuro != null && secMuro.TieneMuro));
            if (muroConTamano)
            {
                barra = CrearPlacaMuro(PosicionDe(a), PosicionDe(b), e);
            }
            else if (e.EsBrazo)
            {
                // Un brazo rigido NO se dibuja con su seccion: su b x h
                // es un artificio numerico (4 x 4 m, la seccion de viga
                // mayor escalada para que sea rigida de verdad). Con
                // perfiles activados salia un cajon de 4 m atravesado.
                // Lo que hay ahi fisicamente es muro, y el muro ya se
                // dibuja aparte; el brazo va como linea fina.
                barra = CrearCilindro(PosicionDe(a), PosicionDe(b),
                                      grosorBarra * 0.6f);
            }
            else if (perfiles)
            {
                Seccion sec = Modelo.SeccionPorNombre(e.seccion);
                if (sec != null && sec.TienePerfil)
                {
                    barra = CrearPerfil(PosicionDe(a), PosicionDe(b), e, sec);
                    escalaDePerfil[e.id] = barra.transform.localScale;
                    barra.transform.localScale = EscalaPerfil(e.id, barra.transform.localScale);
                }
                else
                {
                    barra = CrearCilindro(PosicionDe(a), PosicionDe(b), grosorBarra);
                }
            }
            else
            {
                barra = CrearCilindro(PosicionDe(a), PosicionDe(b), grosorBarra);
            }
            barra.name = "Elem_" + e.id + "_" + e.tipo;
            Pintar(barra, mostrarDeformada ? colorDeformada : ColorDe(e.tipo));
            barra.AddComponent<DatoElemento>().idElemento = e.id;
            objetoDeElemento[e.id] = barra;
            objetosCreados.Add(barra);

            if (marcarOriginal && !e.EsBrazo)
            {
                if (original == null)
                {
                    original = new GameObject("PosicionOriginal").transform;
                    objetosCreados.Add(original.gameObject);
                }
                CrearLineaOriginal(Ejes.PosicionDe(a), Ejes.PosicionDe(b), e, original);
            }
        }

        // Los renderers de antes ya no existen: quien pinta encima
        // (ambiente, mapa D/C) vuelve a pintar. Avisa Redibujado y
        // despues MaterialesCambiados, en ese orden.
        CurvarBarras(); EventosVisor.AvisarRedibujado();
    }

    /// Una barra de otro piso: linea gris, SIN collider (un click pasa al
    /// piso visible), sin DatoElemento y fuera de ObjetosDeElementos (ni
    /// AmbienteVisor ni el mapa D/C la pintan), sin sombra. El nombre no
    /// empieza con "Elem_": no es el objeto_unity de nadie.
    void CrearFantasma(Vector3 desde, Vector3 hasta, Elemento e, Transform padre)
    {
        GameObject linea = CrearCilindro(desde, hasta, grosorBarra * 0.6f);
        Collider col = linea.GetComponent<Collider>();
        if (col != null) DestroyImmediate(col);   // en este mismo frame ya no se puede clickear
        linea.name = "Fantasma_" + e.id;
        linea.transform.SetParent(padre, true);
        Pintar(linea, colorFantasma);
        Renderer r = linea.GetComponent<Renderer>();
        r.shadowCastingMode = ShadowCastingMode.Off;
        r.receiveShadows = false;
    }

    /// La posicion SIN deformar de una barra, con la deformada puesta en la
    /// vista realista: linea fina oscura, sin collider, sin sombra y fuera
    /// de ObjetosDeElementos (nadie la pinta ni la selecciona). Mismo
    /// trato que CrearFantasma, otro color y otro nombre.
    void CrearLineaOriginal(Vector3 desde, Vector3 hasta, Elemento e, Transform padre)
    {
        GameObject linea = CrearCilindro(desde, hasta, grosorBarra);
        Collider col = linea.GetComponent<Collider>();
        if (col != null) DestroyImmediate(col);
        linea.name = "Original_" + e.id;
        linea.transform.SetParent(padre, true);
        Pintar(linea, colorPosicionOriginal);
        Renderer r = linea.GetComponent<Renderer>();
        r.shadowCastingMode = ShadowCastingMode.Off;
        r.receiveShadows = false;
    }

    /// Llega de EventosVisor.VistaCambio. No redibuja aca: el aviso sale
    /// casi siempre de un OnGUI (el panel), y Redibujar destruye y crea
    /// cientos de objetos y avisa otros eventos. Se deja para Update.
    void AlCambiarVista()
    {
        if (Modelo == null) return;
        if (!MismaCota(AjustesVista.cotaVisible, cotaDibujada)) necesitaRedibujar = true;
        // Realista <-> tecnica cambia las secciones (DibujaPerfiles) y el
        // tamano de los nudos: es geometria, se redibuja.
        if (AjustesVista.realista != realistaDibujado) necesitaRedibujar = true;
    }

    static bool MismaCota(float a, float b)
    {
        bool nanA = float.IsNaN(a), nanB = float.IsNaN(b);
        if (nanA || nanB) return nanA && nanB;
        return Mathf.Abs(a - b) < 1e-5f;
    }

    bool TieneAlgunaRestriccion(Nodo n)
    {
        if (n.restricciones == null) return false;
        foreach (int r in n.restricciones) if (r != 0) return true;
        return false;
    }

    bool CapaVisible(string tipo)
    {
        if (tipo == "columna") return verColumnas;
        if (tipo == "muro") return verMuros;
        // "brazo" (LT2) y "brazo_rigido" (Ingenieria) son lo mismo.
        if (tipo == "brazo" || tipo == "brazo_rigido") return verBrazos;
        if (tipo == "pilar_metal") return verColumnas;
        if (tipo == "viga_metal" || tipo == "diagonal") return verVigas;
        return verVigas;   // viga_x, viga_y y cualquier otra
    }

    Color ColorDe(string tipo)
    {
        if (tipo == "columna") return colorColumna;
        if (tipo == "muro") return colorMuro;
        // "brazo" (LT2) y "brazo_rigido" (Ingenieria) son lo mismo.
        if (tipo == "brazo" || tipo == "brazo_rigido") return colorBrazo;
        // El acero se distingue del hormigon a simple vista.
        if (tipo == "pilar_metal" || tipo == "viga_metal"
            || tipo == "diagonal") return colorMetal;
        return colorViga;
    }

    // ============================================================
    // PERFILES
    // ============================================================
    /// <summary>
    /// Dibuja la barra con su seccion REAL (b x h), orientada segun sus
    /// EJES LOCALES.
    ///
    /// La orientacion no se adivina: se usan los versores localX/localY/
    /// localZ que vienen calculados desde Python con la misma convencion
    /// de geomTransf que uso OpenSees. Por eso el perfil que se ve es
    /// literalmente el que se calculo: si alguien cambiara vecxz en el
    /// modelo, el dibujo giraria con el.
    ///
    /// Convencion: b va a lo largo del eje local y, h a lo largo del
    /// local z. Para una viga con vecxz=(0,0,1) el local z es el
    /// vertical, asi que h es el CANTO -- que es lo que uno espera ver.
    /// </summary>
    GameObject CrearPerfil(Vector3 desde, Vector3 hasta, Elemento e, Seccion sec)
    {
        GameObject caja = GameObject.CreatePrimitive(PrimitiveType.Cube);
        caja.transform.position = (desde + hasta) / 2f;

        float largo = (hasta - desde).magnitude;

        Vector3 ejeX = (hasta - desde).normalized;          // ya en Unity
        Vector3 ejeZ = VectorUnity(e.localZ, Vector3.up);   // canto

        // Si por lo que sea localZ resultara paralelo al eje de la
        // barra, LookRotation devolveria basura: se usa un respaldo.
        if (Mathf.Abs(Vector3.Dot(ejeX, ejeZ)) > 0.999f)
            ejeZ = Mathf.Abs(ejeX.y) > 0.9f ? Vector3.forward : Vector3.up;

        // forward = eje de la barra, up = canto.
        // Queda: cubo Z = largo, cubo Y = h, cubo X = b.
        caja.transform.rotation = Quaternion.LookRotation(ejeX, ejeZ);
        caja.transform.localScale = new Vector3(sec.b, sec.h, largo);
        return caja;
    }

    /// Pasa un vector en ejes OpenSees (como viene del JSON) a Unity.
    /// Los VECTORES tienen que cruzar el mismo swap Z-Y que las
    /// posiciones; si no, apuntan mal aunque el modelo se vea bien.
    static Vector3 VectorUnity(float[] v, Vector3 porDefecto)
    {
        if (v == null || v.Length < 3) return porDefecto;
        Vector3 r = Ejes.AUnity(v[0], v[1], v[2]);
        return r.sqrMagnitude > 1e-8f ? r.normalized : porDefecto;
    }

    // ============================================================
    // MUROS
    // ============================================================
    /// <summary>
    /// Dibuja un muro con su tamano REAL en planta (largo x espesor),
    /// no como una barra delgada.
    ///
    /// POR QUE
    /// El muro se idealiza como "columna ancha": UNA barra vertical en
    /// su eje baricentrico. Eso es correcto para el calculo, pero si se
    /// dibuja tal cual se ve una columna flaca en medio del vano y es
    /// imposible juzgar si el muro esta donde dice el plano, ni hacia
    /// donde apunta su eje fuerte.
    ///
    /// La orientacion sale de 'vecxz', que en un muro apunta en la
    /// direccion del muro en planta -- el MISMO vector con el que
    /// OpenSees oriento su inercia fuerte. Asi lo que se ve y lo que se
    /// calculo no pueden desincronizarse.
    /// </summary>
    GameObject CrearPlacaMuro(Vector3 desde, Vector3 hasta, Elemento e)
    {
        GameObject caja = GameObject.CreatePrimitive(PrimitiveType.Cube);
        caja.transform.position = (desde + hasta) / 2f;

        float alto = (hasta - desde).magnitude;

        // vecxz viene en ejes OpenSees (x, y de planta): hay que pasarlo
        // por el mismo swap que las posiciones.
        // La direccion del muro en planta viene DADA desde Python en
        // 'dir_largo'. Antes se deducia de vecxz, y estaba mal: en un
        // muro vecxz es la NORMAL al muro (es lo que pone la inercia
        // fuerte donde corresponde), no su direccion. El resultado era
        // que TODOS los muros se dibujaban girados 90 grados: los del
        // nucleo de ascensores atravesados y el de fachada metido
        // dentro del edificio.
        //
        // Si el JSON no trae dir_largo (modelos viejos), se cae al
        // comportamiento anterior para no dejar de dibujar nada.
        Vector3 alLargo = Vector3.right;
        if (e.dir_largo != null && e.dir_largo.Length >= 2)
        {
            Vector3 d = Ejes.AUnity(e.dir_largo[0], e.dir_largo[1], 0f);
            if (d.sqrMagnitude > 1e-8f) alLargo = d.normalized;
        }
        else if (e.vecxz != null && e.vecxz.Length >= 2)
        {
            Vector3 d = Ejes.AUnity(e.vecxz[0], e.vecxz[1], 0f);
            // El comportamiento viejo suponia vecxz A LO LARGO del muro.
            if (d.sqrMagnitude > 1e-8f) alLargo = d.normalized;
        }

        // El cubo queda: X = largo del muro, Y = alto de piso,
        // Z = espesor. Se rota para que su X corra a lo largo del muro.
        caja.transform.rotation = Quaternion.LookRotation(
            Vector3.Cross(Vector3.up, alLargo).normalized, Vector3.up);
        // El tamano en planta puede venir en el ELEMENTO (LT2) o en la
        // SECCION (edificio de Ingenieria). Se prefiere el del elemento:
        // dos muros pueden compartir seccion y medir distinto.
        float largoMuro = e.largo, espesorMuro = e.espesor;
        if (largoMuro < 0.01f || espesorMuro < 0.01f)
        {
            Seccion sec = Modelo.SeccionPorNombre(e.seccion);
            if (sec != null && sec.TieneMuro)
            {
                largoMuro = sec.largo;
                espesorMuro = sec.espesor;
            }
        }

        caja.transform.localScale = new Vector3(
            Mathf.Max(largoMuro, 0.05f), alto, Mathf.Max(espesorMuro, 0.05f));

        if (mostrarDeformada) InclinarPlaca(caja, desde, hasta);
        return caja;
    }

    /// Con la deformada, la placa vertical en el punto medio dejaba el pie y
    /// la cabeza lejos de sus nodos: cada tramo de muro se corria
    /// (u_cabeza - u_pie)/2 respecto del de abajo y el muro se veia partido
    /// en escalera. Aca la caja se CIZALLA: la cara inferior queda centrada
    /// en 'desde' y la superior en 'hasta', asi dos tramos seguidos comparten
    /// arista. Es solo dibujo con las posiciones que ya dio PosicionActual;
    /// no se interpola nada. La malla sigue siendo un "Cube" de 24 vertices
    /// con la escala real (AmbienteVisor la texturiza por su lossyScale).
    void InclinarPlaca(GameObject caja, Vector3 desde, Vector3 hasta)
    {
        Transform t = caja.transform;
        Vector3 local = Quaternion.Inverse(t.rotation) * (hasta - desde);
        Vector3 escala = t.localScale;
        // Menos de 1 mm de corrimiento en planta: la caja de siempre.
        if (Mathf.Abs(local.x) < 1e-3f && Mathf.Abs(local.z) < 1e-3f) return;

        escala.y = Mathf.Max(Mathf.Abs(local.y), 0.01f);
        t.localScale = escala;
        float signo = local.y >= 0f ? 1f : -1f;
        // Un vertice a altura v.y (-0.5 o 0.5) se corre v.y * delta / escala.
        float kx = signo * local.x / escala.x, kz = signo * local.z / escala.z;

        Vector3[] normales = { Vector3.right, Vector3.left, Vector3.up, Vector3.down, Vector3.forward, Vector3.back };
        var vertices = new List<Vector3>(24);
        var uvs = new List<Vector2>(24);
        var triangulos = new List<int>(36);
        foreach (Vector3 n in normales)
        {
            Vector3 u = Mathf.Abs(n.y) > 0.5f ? Vector3.right : Vector3.up;
            Vector3 v = Vector3.Cross(n, u);
            Vector3 c = n * 0.5f;
            Vector3[] p = { c - u * 0.5f - v * 0.5f, c - u * 0.5f + v * 0.5f,
                            c + u * 0.5f + v * 0.5f, c + u * 0.5f - v * 0.5f };
            int i0 = vertices.Count;
            Vector2[] uv = { new Vector2(0f, 0f), new Vector2(0f, 1f), new Vector2(1f, 1f), new Vector2(1f, 0f) };
            for (int k = 0; k < 4; k++)
            {
                Vector3 q = p[k];
                vertices.Add(new Vector3(q.x + q.y * kx, q.y, q.z + q.y * kz));
                uvs.Add(uv[k]);
            }
            // La cara mira hacia n antes de cizallar: se elige el orden de los
            // triangulos con el producto cruz, sin suponer la mano de u y v.
            bool derecho = Vector3.Dot(Vector3.Cross(p[1] - p[0], p[2] - p[0]), n) > 0f;
            if (derecho) triangulos.AddRange(new[] { i0, i0 + 1, i0 + 2, i0, i0 + 2, i0 + 3 });
            else triangulos.AddRange(new[] { i0, i0 + 2, i0 + 1, i0, i0 + 3, i0 + 2 });
        }
        Mesh malla = new Mesh { name = "Cube cizallado" };
        malla.SetVertices(vertices);
        malla.SetUVs(0, uvs);
        malla.SetTriangles(triangulos, 0);
        malla.RecalculateNormals();
        // Tangentes: sin ellas un material con mapa normal (la vista realista)
        // sombrea negras las caras que no son horizontales.
        malla.RecalculateTangents();
        malla.RecalculateBounds();
        caja.GetComponent<MeshFilter>().sharedMesh = malla;
        mallasPropias.Add(malla);
    }

    // Unity no tiene "linea gruesa 3D": se usa un cilindro estirado.
    GameObject CrearCilindro(Vector3 desde, Vector3 hasta, float grosor)
    {
        GameObject cil = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        cil.transform.position = (desde + hasta) / 2f;

        Vector3 direccion = hasta - desde;
        float largo = direccion.magnitude;

        // El cilindro de Unity mide 2 de alto y apunta en Y.
        cil.transform.localScale = new Vector3(grosor, largo / 2f, grosor);
        if (largo > 1e-6f) cil.transform.up = direccion.normalized;
        return cil;
    }

    // Cachea materiales: crear uno por objeto deja cientos huerfanos
    // que Unity no libera. Con el edificio completo es una fuga real.
    void Pintar(GameObject go, Color color)
    {
        Material mat;
        if (!materiales.TryGetValue(color, out mat))
        {
            mat = new Material(ShaderDelProyecto());
            mat.color = color;
            // URP/HDRP usan _BaseColor. Material.color suele mapearlo
            // solo, pero asignarlo explicito no cuesta nada y evita
            // depender de la version de Unity.
            if (mat.HasProperty("_BaseColor")) mat.SetColor("_BaseColor", color);
            materiales[color] = mat;
        }
        go.GetComponent<Renderer>().sharedMaterial = mat;
    }

    // ============================================================
    // El shader depende del RENDER PIPELINE del proyecto.
    // "Standard" solo existe en el Built-in. En URP (que es lo que usa
    // la plantilla 3D de Unity 6) Shader.Find("Standard") devuelve
    // null, y un material sin shader se dibuja MAGENTA.
    // Si toda la estructura se ve rosada, es esto.
    // ============================================================
    static Shader shaderCache;

    /// Version publica: VisorQA necesita el mismo shader para que sus
    /// capas no salgan magenta cuando el proyecto usa URP.
    public static Shader ShaderCompatible()
    {
        return ShaderDelProyecto();
    }

    static Shader ShaderDelProyecto()
    {
        if (shaderCache != null) return shaderCache;

        // currentRenderPipeline != null significa URP o HDRP.
        if (GraphicsSettings.currentRenderPipeline != null)
        {
            shaderCache = Shader.Find("Universal Render Pipeline/Lit");
            if (shaderCache == null) shaderCache = Shader.Find("HDRP/Lit");
        }
        if (shaderCache == null) shaderCache = Shader.Find("Standard");
        if (shaderCache == null) shaderCache = Shader.Find("Unlit/Color");

        if (shaderCache == null)
            Debug.LogError("No encontre ningun shader utilizable. Todo se "
                           + "vera magenta.");
        return shaderCache;
    }

    // ============================================================
    // Permite prender/apagar toggles desde el Inspector en Play.
    // OJO: NO se puede llamar Destroy() desde OnValidate (Unity lo
    // prohibe). Solo levantamos una bandera; se redibuja en Update.
    // ============================================================
    void OnValidate()
    {
        if (Application.isPlaying && Modelo != null) necesitaRedibujar = true;
    }

    void Update()
    {
        if (necesitaRedibujar) { necesitaRedibujar = false; Redibujar(); }
    }

    // ============================================================
    // LA CURVA DE LA DEFORMADA
    // ============================================================
    // Va al final de la clase para no correr las lineas que citan los
    // informes (CLAUDE.md seccion 6). Las constantes tambien.
    //
    // POR QUE
    // Una barra dibujada como un palo recto entre sus dos nodos
    // deformados NO se dobla. Una viga cargada baja en el centro, pero
    // si sus dos extremos cuelgan de nudos que casi no bajan, el palo
    // queda igual de recto y parece que la viga no trabaja. Y una
    // columna entre dos pisos que se corren distinto solo se INCLINA,
    // cuando en la realidad entra en doble curvatura: se dobla como una
    // S y sale vertical de los dos nudos, porque el nudo es rigido.
    //
    // Lo que faltaba no era calcular nada: son los GIROS de los nudos,
    // que ya venian en cada desplazamiento (rx, ry, rz) y nadie usaba.
    // El nudo rigido obliga a la barra a arrancar con SU pendiente, y
    // de ahi sale la curva.
    //
    // NO ES CALCULO ESTRUCTURAL (CLAUDE.md seccion 2)
    // No sale ningun numero nuevo ni se reporta nada: son las MISMAS
    // funciones de forma con que el elemento de OpenSees interpola
    // entre sus dos nodos, usadas para poner vertices. La formula es la
    // de semana05/carga_movil.py:471 desplazamiento_en(), donde esta
    // verificada contra la misma viga partida en nodos y con Betti;
    // aca se omite su termino de carga puntual, que solo existe en el
    // recorrido de la carga movil.
    //
    // QUE NO SE CURVA
    //   muro   la placa ya sigue a sus nodos cizallada (InclinarPlaca)
    //   brazo  es un artificio rigido: no tiene forma que mostrar
    //   y cualquier barra sin ejes locales, sin giros, o que se aparta
    //   del palo recto menos de DESVIO_MINIMO (no se distinguiria).
    //
    // EL COLLIDER NO SE CURVA: sigue siendo la caja del primitivo entre
    // los dos nodos deformados. Un clic sobre una barra muy curvada le
    // pega al palo recto, no a la panza. Se prefirio eso a un
    // MeshCollider por barra, que en el conjunto son 800 mallas.

    /// En cuantos tramos se parte la barra para dibujar su curva. Una
    /// cubica queda lisa con 8, y cada tramo cuesta un anillo de
    /// vertices en cada una de las ~800 barras del conjunto.
    const int TRAMOS_CURVA = 8;

    /// Cuanto tiene que apartarse la curva del palo recto, en metros de
    /// mundo (ya exagerados por factorEscala), para que valga la pena
    /// darle malla propia. Debajo de esto no se ve la diferencia.
    const float DESVIO_MINIMO = 0.01f;

    /// Lados del tubo con que se curva una barra sin perfil.
    const int LADOS_TUBO = 8;

    /// Desde que giro sobre su propio eje (rad, YA exagerados) vale la
    /// pena torcer la seccion. 0.01 rad son 0.6 grados: menos no se ve.
    const float GIRO_MINIMO = 0.01f;

    /// Curva todas las barras dibujadas. Corre al final de Redibujar y
    /// ANTES de AvisarRedibujado, para que quien pinta encima
    /// (AmbienteVisor, mapa D/C) encuentre ya la malla definitiva.
    void CurvarBarras()
    {
        if (!mostrarDeformada || Modelo == null || Modelo.elementos == null) return;
        foreach (Elemento e in Modelo.elementos) Curvar(e.id);
    }

    /// Le cambia la malla a UNA barra para que siga su curva. Se puede
    /// volver a llamar sobre la misma barra: la malla se rehace con la
    /// escala que tenga puesta en ese momento, que es lo que necesita
    /// FijarBarrasDelgadas cuando adelgaza la barra de un diagrama.
    void Curvar(int id)
    {
        if (!mostrarDeformada || Modelo == null) return;
        GameObject go;
        if (!objetoDeElemento.TryGetValue(id, out go) || go == null) return;
        Elemento e = Modelo.ElementoPorId(id);
        if (e == null || e.EsMuro || e.EsBrazo) return;
        float[] giro;
        Vector3[] curva = CurvaDe(e, out giro);
        if (curva != null) CurvarMalla(go, curva, giro);
    }

    /// <summary>
    /// Los TRAMOS_CURVA+1 puntos del eje deformado de la barra, en
    /// mundo Unity, o null si esta barra no tiene curva que dibujar.
    ///
    /// Todo el algebra va en ejes OPENSEES (Z vertical), que es como
    /// vienen localX/localY/localZ y como esta escrita la formula en
    /// Python; el cambio a Unity se hace al final, una sola vez, con el
    /// Ejes.AUnity de siempre.
    ///
    /// Los extremos salen EXACTOS: en xi = 0 y xi = 1 las funciones de
    /// forma valen 1 y 0, asi que curva[0] y curva[n] son las mismas
    /// posiciones que da PosicionDe(). Por eso dos barras seguidas
    /// siguen tocandose en el nudo.
    /// </summary>
    Vector3[] CurvaDe(Elemento e, out float[] giro)
    {
        giro = null;
        Nodo a = Modelo.NodoPorId(e.n1), b = Modelo.NodoPorId(e.n2);
        if (a == null || b == null) return null;

        DespNodo di, dj;
        if (!deformadaActual.TryGetValue(a.id, out di)) return null;
        if (!deformadaActual.TryGetValue(b.id, out dj)) return null;

        Vector3 ex = EjeLocal(e.localX), ey = EjeLocal(e.localY), ez = EjeLocal(e.localZ);
        if (ex == Vector3.zero || ey == Vector3.zero || ez == Vector3.zero) return null;

        Vector3 pa = new Vector3(a.x, a.y, a.z), pb = new Vector3(b.x, b.y, b.z);
        float L = (pb - pa).magnitude;
        if (L < 1e-6f) return null;

        Vector3 ti = new Vector3(di.ux, di.uy, di.uz), tj = new Vector3(dj.ux, dj.uy, dj.uz);
        Vector3 ri = new Vector3(di.rx, di.ry, di.rz), rj = new Vector3(dj.rx, dj.ry, dj.rz);
        // Sin giros la cubica se degrada a la recta que ya dibuja el
        // primitivo. Pasa con un JSON viejo, sin rx/ry/rz.
        if (ri == Vector3.zero && rj == Vector3.zero) return null;

        Vector3[] curva = new Vector3[TRAMOS_CURVA + 1];
        float[] torsion = new float[TRAMOS_CURVA + 1];
        for (int k = 0; k <= TRAMOS_CURVA; k++)
        {
            float xi = k / (float)TRAMOS_CURVA;
            // LA TORSION: el giro sobre el PROPIO eje de la barra. En una
            // barra prismatica sin torque repartido varia LINEAL entre sus
            // dos nudos, asi que no lleva cubica. Se exagera con el mismo
            // factorEscala que las traslaciones, si no no se veria: medido
            // en el LT2, el mayor de los 15 casos es 1.9e-3 rad, que a x74
            // son 8.2 grados (en el conjunto, bajo G, hasta 24).
            torsion[k] = ((1f - xi) * Vector3.Dot(ex, ri)
                          + xi * Vector3.Dot(ex, rj)) * factorEscala;
            float N1 = 1f - 3f * xi * xi + 2f * xi * xi * xi;
            float N2 = xi - 2f * xi * xi + xi * xi * xi;
            float N3 = 3f * xi * xi - 2f * xi * xi * xi;
            float N4 = -xi * xi + xi * xi * xi;
            // axial lineal; en local y, cubica con dv/dx = +rz_local;
            // en local z, con dw/dx = -ry_local (girar +ry lleva el eje
            // x hacia -z). Es carga_movil.desplazamiento_en() sin el
            // termino de la carga puntual.
            float u = (1f - xi) * Vector3.Dot(ex, ti) + xi * Vector3.Dot(ex, tj);
            float v = N1 * Vector3.Dot(ey, ti) + N2 * L * Vector3.Dot(ez, ri)
                    + N3 * Vector3.Dot(ey, tj) + N4 * L * Vector3.Dot(ez, rj);
            float w = N1 * Vector3.Dot(ez, ti) - N2 * L * Vector3.Dot(ey, ri)
                    + N3 * Vector3.Dot(ez, tj) - N4 * L * Vector3.Dot(ey, rj);
            Vector3 p = Vector3.Lerp(pa, pb, xi) + (u * ex + v * ey + w * ez + EnVano(e, xi)) * factorEscala;
            curva[k] = Ejes.AUnity(p.x, p.y, p.z);
        }

        // Cuanto se aparta del palo recto que dibujaria el primitivo, y
        // cuanto se tuerce. Con cualquiera de las dos vale la malla.
        float desvio = 0f;
        for (int k = 1; k < TRAMOS_CURVA; k++)
            desvio = Mathf.Max(desvio, Vector3.Distance(
                curva[k], Vector3.Lerp(curva[0], curva[TRAMOS_CURVA], k / (float)TRAMOS_CURVA)));
        float giroMax = Mathf.Max(Mathf.Abs(torsion[0]), Mathf.Abs(torsion[TRAMOS_CURVA]));
        if (desvio < DESVIO_MINIMO && giroMax < GIRO_MINIMO) return null;
        giro = torsion;
        return curva;
    }

    /// Un eje local del JSON (ejes OpenSees) como versor. Vector3.zero
    /// si no viene: esa barra se queda recta en vez de curvarse mal.
    static Vector3 EjeLocal(float[] v)
    {
        if (v == null || v.Length < 3) return Vector3.zero;
        Vector3 r = new Vector3(v[0], v[1], v[2]);
        return r.sqrMagnitude > 1e-8f ? r.normalized : Vector3.zero;
    }

    /// <summary>
    /// Cambia la malla del primitivo por una barra que sigue la curva.
    ///
    /// La seccion se BARRE sin girar, igual que InclinarPlaca en los
    /// muros: las caras de los extremos quedan como estaban y dos
    /// barras seguidas no se abren en el nudo. Girar la seccion con la
    /// tangente se ve mejor en una barra suelta y abre las esquinas.
    ///
    /// Los vertices van en coordenadas LOCALES del objeto, que sigue
    /// siendo el mismo primitivo con su posicion, rotacion y escala
    /// (b, h, largo). InverseTransformPoint ya divide por esa escala,
    /// asi que la curva sale del tamano justo sin corregir nada, y
    /// FijarBarrasDelgadas puede cambiar la escala y volver a llamar.
    ///
    /// El nombre de la malla conserva "Cube"/"Cylinder" porque
    /// AmbienteVisor.Repeticion() lo lee para repetir la textura.
    /// </summary>
    void CurvarMalla(GameObject go, Vector3[] curva, float[] giro)
    {
        MeshFilter mf = go.GetComponent<MeshFilter>();
        if (mf == null || mf.sharedMesh == null) return;
        bool caja = mf.sharedMesh.name.Contains("Cube");
        if (!caja && !mf.sharedMesh.name.Contains("Cylinder")) return;

        int lados = caja ? 4 : LADOS_TUBO;
        int n = curva.Length - 1;
        Vector3 escala = go.transform.localScale;
        Vector3[,] anillo = new Vector3[curva.Length, lados];
        Vector3[,] hacia = new Vector3[curva.Length, lados];   // hacia afuera, ya girado
        for (int k = 0; k <= n; k++)
        {
            Vector3 c = go.transform.InverseTransformPoint(curva[k]);
            float g = giro != null && k < giro.Length ? giro[k] : 0f;
            for (int i = 0; i < lados; i++)
            {
                Vector3 s = SeccionGirada(caja, i, g, escala);
                anillo[k, i] = c + s;
                hacia[k, i] = s;
            }
        }

        var vertices = new List<Vector3>();
        var uvs = new List<Vector2>();
        var tri = new List<int>();
        for (int k = 0; k < n; k++)
            for (int i = 0; i < lados; i++)
            {
                int j = (i + 1) % lados;
                // El cubo mapea cada cara entera (0..1), como el
                // primitivo; el tubo reparte la vuelta entre sus lados.
                float u0 = caja ? 0f : i / (float)lados;
                float u1 = caja ? 1f : (i + 1) / (float)lados;
                // Hacia afuera de ESA cara, con la seccion ya torcida.
                Vector3 fuera = (hacia[k, i] + hacia[k, j]
                                 + hacia[k + 1, i] + hacia[k + 1, j]) * 0.25f;
                Cara(vertices, uvs, tri, fuera,
                     anillo[k, i], anillo[k, j], anillo[k + 1, j], anillo[k + 1, i],
                     u0, u1, k / (float)n, (k + 1) / (float)n);
            }
        Tapa(vertices, uvs, tri, anillo, 0, lados, caja ? Vector3.back : Vector3.down);
        Tapa(vertices, uvs, tri, anillo, n, lados, caja ? Vector3.forward : Vector3.up);

        Mesh malla = new Mesh { name = (caja ? "Cube" : "Cylinder") + " curvado" };
        malla.SetVertices(vertices);
        malla.SetUVs(0, uvs);
        malla.SetTriangles(tri, 0);
        malla.RecalculateNormals();
        // Tangentes: sin ellas un material con mapa normal (la vista realista)
        // sombrea negras las caras que no son horizontales.
        malla.RecalculateTangents();
        malla.RecalculateBounds();
        mf.sharedMesh = malla;
        mallasPropias.Add(malla);
    }

    /// La seccion del primitivo alrededor de su eje, en coordenadas
    /// locales: el cubo mide 1 y corre en Z; el cilindro mide 2 de alto,
    /// radio 0.5, y corre en Y. Los cuatro vertices del cubo van en
    /// orden antihorario, asi que el punto medio de dos seguidos apunta
    /// hacia afuera de la barra.
    static Vector3 Seccion(bool caja, int i)
    {
        if (caja)
            return new Vector3(i == 0 || i == 3 ? -0.5f : 0.5f, i < 2 ? -0.5f : 0.5f, 0f);
        float ang = 2f * Mathf.PI * i / LADOS_TUBO;
        return new Vector3(0.5f * Mathf.Cos(ang), 0f, 0.5f * Mathf.Sin(ang));
    }

    /// <summary>
    /// La seccion GIRADA sobre el eje de la barra: la torsion.
    ///
    /// El giro es un giro de verdad en METROS, y las coordenadas
    /// locales estan escaladas distinto en cada eje (una viga es 0.60
    /// de ancho y 0.80 de canto). Girar directamente en locales no
    /// giraria: cizallaria la seccion y la viga saldria mas ancha de un
    /// lado. Por eso se pasa a metros con la escala, se gira ahi, y se
    /// vuelve. El cilindro tiene la misma escala en sus dos ejes
    /// transversales, asi que no necesita la correccion.
    /// </summary>
    static Vector3 SeccionGirada(bool caja, int i, float giro, Vector3 escala)
    {
        Vector3 s = Seccion(caja, i);
        if (Mathf.Abs(giro) < 1e-6f) return s;
        float c = Mathf.Cos(giro), sn = Mathf.Sin(giro);
        if (!caja)
            return new Vector3(s.x * c - s.z * sn, s.y, s.x * sn + s.z * c);
        float sx = Mathf.Abs(escala.x), sy = Mathf.Abs(escala.y);
        if (sx < 1e-6f || sy < 1e-6f) return s;
        float mx = s.x * sx, my = s.y * sy;             // a metros
        return new Vector3((mx * c - my * sn) / sx,     // girado y de vuelta
                           (mx * sn + my * c) / sy, s.z);
    }

    /// Un cuadrilatero con sus dos triangulos, mirando hacia 'fuera'.
    /// El orden se elige con el producto cruz y no se supone, como en
    /// InclinarPlaca: con la barra curvada el cuadrilatero ya no es
    /// plano ni tiene siempre la misma mano.
    static void Cara(List<Vector3> v, List<Vector2> uv, List<int> tri, Vector3 fuera,
                     Vector3 p0, Vector3 p1, Vector3 p2, Vector3 p3,
                     float u0, float u1, float v0, float v1)
    {
        int i0 = v.Count;
        v.Add(p0); v.Add(p1); v.Add(p2); v.Add(p3);
        uv.Add(new Vector2(u0, v0)); uv.Add(new Vector2(u1, v0));
        uv.Add(new Vector2(u1, v1)); uv.Add(new Vector2(u0, v1));
        if (Vector3.Dot(Vector3.Cross(p1 - p0, p2 - p0), fuera) > 0f)
            tri.AddRange(new[] { i0, i0 + 1, i0 + 2, i0, i0 + 2, i0 + 3 });
        else
            tri.AddRange(new[] { i0, i0 + 2, i0 + 1, i0, i0 + 3, i0 + 2 });
    }

    /// La tapa de un extremo: un abanico sobre el anillo k.
    static void Tapa(List<Vector3> v, List<Vector2> uv, List<int> tri,
                     Vector3[,] anillo, int k, int lados, Vector3 fuera)
    {
        int i0 = v.Count;
        for (int i = 0; i < lados; i++)
        {
            v.Add(anillo[k, i]);
            float ang = 2f * Mathf.PI * i / lados;
            uv.Add(new Vector2(0.5f + 0.5f * Mathf.Cos(ang), 0.5f + 0.5f * Mathf.Sin(ang)));
        }
        for (int i = 1; i + 1 < lados; i++)
        {
            if (Vector3.Dot(Vector3.Cross(v[i0 + i] - v[i0], v[i0 + i + 1] - v[i0]), fuera) > 0f)
                tri.AddRange(new[] { i0, i0 + i, i0 + i + 1 });
            else
                tri.AddRange(new[] { i0, i0 + i + 1, i0 + i });
        }
    }

    // ============================================================
    // FLECHA DENTRO DEL VANO QUE MANDA OTRA FUENTE
    // ============================================================
    /// Lo que se suma, dentro del vano, a la curva de los nodos (m, ejes
    /// OpenSees) de la barra 'id' en xi; null = nada. El visor no lo
    /// calcula: lo pone quien SABE la carga dentro del vano (VisorPersona,
    /// con la forma que exporta Python) y vale cero cuando la deformada
    /// que se dibuja no es la suya. Va al final de la clase para no
    /// correr las lineas que citan los informes.
    public System.Func<int, float, Vector3> FlechaEnVano;

    Vector3 EnVano(Elemento e, float xi)
    {
        return FlechaEnVano != null ? FlechaEnVano(e.id, xi) : Vector3.zero;
    }
}
