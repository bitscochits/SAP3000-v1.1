/*
================================================================
  VisorResultados.cs
================================================================
  Unity como POSTPROCESADOR de los resultados de OpenSees. Lee
  StreamingAssets/resultados.json (lo escribe exportar/resultados.py y
  lo copia "python sap.py sincronizar") y dibuja lo que ahi viene
  calculado:

    - los esfuerzos internos de cada barra en el CASO ACTIVO, como
      diagrama (My, Mz, Vz, Vy, N o T) sobre la geometria sin deformar;
    - la deformada del caso activo, sea un caso base o una combinacion;
    - la curva P-M de la seccion seleccionada con su punto de demanda;
    - el bloque de datos y de trazabilidad que PanelVisor agrega a su
      panel al seleccionar un elemento.

  resultados.json trae ademas, tal cual, dos bloques que leen otros
  desde este visor ya cargado (sin volver a leer el archivo):
    superposicion      E1..E3 precalculados (VisorResultados.Superposicion.cs)
    cargas_y_armadura  flechas de carga, deformadas sismicas y la jaula
                       de la columna (VisorCargasYArmadura, que espera a
                       LecturaTerminada)

  ----------------------------------------------------------------
  REGLA QUE NO SE ROMPE: aca no se calcula estructura
  ----------------------------------------------------------------
  Los esfuerzos a lo largo de la barra, las combinaciones, la curva
  P-M y la demanda vienen hechos de Python. Este script solo escala
  valores para que se vean, busca el mayor para ponerle etiqueta, y
  arma mallas y texto. Si aca se calculara algo habria dos
  implementaciones de la misma mecanica -- la de Python, verificada,
  y esta -- y tarde o temprano la pantalla mostraria algo distinto de
  lo que se comprobo.

  ----------------------------------------------------------------
  DE QUE LADO SE DIBUJA
  ----------------------------------------------------------------
  Del lado TRACCIONADO, que es la convencion de hormigon armado. Con
  los esfuerzos internos del contrato (cara positiva):

      My > 0 tracciona la fibra +z local  -> la curva va en +My * z_local
      Mz < 0 tracciona la fibra +y local  -> la curva va en -Mz * y_local

  Corte y axial no tienen lado traccionado: Vz, N y T van en z_local,
  Vy en y_local, y el color dice el signo. Los ejes locales son los
  del modelo base (Elemento.localY / localZ), que salen de la misma
  regla que usa el servidor. Ver CONTRATO.md.

  ----------------------------------------------------------------
  COMO SE USA
  ----------------------------------------------------------------
  Si la escena no lo trae, PanelVisor lo agrega solo al arrancar, y sus
  controles van dentro del panel de PanelVisor, pestana "Caso".
  Click en una barra -> el panel suma material, seccion,
  restricciones, esfuerzos del caso activo y trazabilidad; si la
  barra tiene fierro, se abre la ventana con su curva P-M.

  ----------------------------------------------------------------
  LA CARGA Y LOS CASOS EXTERNOS
  ----------------------------------------------------------------
  - El archivo se lee con LectorStreaming (UnityWebRequest) y no con
    File.ReadAllText: en Android y en Web StreamingAssets no es una
    carpeta y File.Exists diria "falta" aunque el archivo este.
  - Se espera a que VisorEstructura diga Listo: su Start tambien es
    asincrono, y un frame no alcanza.
  - Casos EXTERNOS (RegistrarCasoExterno): E1..E3 del bloque
    superposicion y la combinacion LIBRE de POST /combinar. Llegan
    completos de Python con la forma de CasoLab y se indexan igual que
    los del archivo; aca no se completa ni se combina nada. Ver
    VisorResultados.Superposicion.cs.
  - Al llegar EventosVisor.ModeloEditado el anexo queda DESACTUALIZADO:
    sus numeros son del modelo original. Los diagramas se apagan, la
    deformada del caso deja de aplicarse y el aviso lo dice.
================================================================
*/

using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;


// ================================================================
// CONTRATO: las clases que JsonUtility llena desde resultados.json
// ----------------------------------------------------------------
// JsonUtility NO avisa cuando un nombre no calza: deja el campo en su
// valor por defecto y sigue. Cada nombre de aca es la clave exacta del
// JSON; lo comprueban en las dos direcciones verificacion/unity.py
// (contratos y jsonutility). Un campo por linea y sin metodos.
// ================================================================

[System.Serializable]
public class InfoResultados
{
    public string edificio;
    public string descripcion;
    public string unidades;
    public string[] parametros;
    public string[] convencion;
    public string generado_por;
    public string caso_por_defecto;
    public int columna_demo;
    public int muro_demo;
    public int n_estaciones_cargada;
    public float cota_redondeo_kN;
    public float escala_deformada;              // exageracion grafica sugerida
    public string _escala_deformada_por_que;    // su criterio, declarado en Python
}

/// Esfuerzos de UNA barra en un caso. f son los 12 de localForce,
/// fuerzas SOBRE la barra en ejes locales; x son las estaciones desde
/// el nodo i, y N..Mz los esfuerzos internos en cada estacion, ya
/// calculados en Python.
[System.Serializable]
public class EsfuerzosBarra
{
    public int id;
    public float[] f;
    public float[] w;      // (wx, wy, wz) en ejes locales, kN/m
    public float[] x;
    public float[] N;
    public float[] Vy;
    public float[] Vz;
    public float[] T;
    public float[] My;
    public float[] Mz;
}

[System.Serializable]
public class Demanda
{
    public int id;
    public int familia;
    public float P;
    public float M;
    public float M_fuera_plano;
    public string extremo;
    public float Mn;
    public float u;
    public bool pasa;

    // De que NUCLEO es esta pata, si lo es (lo calcula Python: los grupos
    // de nucleo de calculo/demanda.py).
    // NO cambia 'pasa': dice de DONDE viene el axial, porque la traccion
    // que saca a una pata de su curva casi siempre es el par interno de
    // su grupo. nucleo_patas = 0 -> este muro no es pata de un nucleo.
    // nucleo_estado: "comprimido", "traccion_dentro" o "traccion_fuera".
    public int nucleo_patas;
    public float nucleo_P, nucleo_Asfy;
    public string nucleo_estado;
}

[System.Serializable]
public class CasoLab
{
    public string nombre;
    public string tipo;
    public string descripcion;
    public float[] factores;
    public float max_desplazamiento_mm;
    public List<DespNodo> desplazamientos;
    public List<EsfuerzosBarra> esfuerzos;
    public List<Demanda> demandas;
}

[System.Serializable]
public class ElementoOpenSees
{
    public int id;
    public int n1;
    public int n2;
    public string tipo;
    public string seccion;
    public string momento_en_el_plano;   // muro: "My" o "Mz"; si no, ""
    public float L;
    public string objeto_unity;
    public string tag_opensees;
    public string material;
    public float fpc_MPa;
    public float E_kPa;
    public float G_kPa;
    public float poisson;
    public float gamma;
    public float A;
    public float Iy;
    public float Iz;
    public float J;
    public float b;
    public float h;
    public float[] vecxz;
    public int[] restr_n1;
    public int[] restr_n2;
    public int diafragma_n1;
    public int diafragma_n2;
    public bool es_brazo_rigido;
    public string condiciones;
    public bool cargada;
    public int familia;
    public string resultados;
}

[System.Serializable]
public class FamiliaPM
{
    public int indice;
    public string clave;
    public string tipo;
    public string seccion;
    public float b;
    public float h;
    public float As_cm2;
    public float cuantia_pct;
    public string refuerzo;
    public string fuente;
    public float[] P;
    public float[] Mn;
    public float[] Mmax;
    public string[] de;
    public int[] elementos;
}

[System.Serializable]
public class Resultados
{
    public InfoResultados info;
    public List<CasoLab> casos;
    public List<ElementoOpenSees> elementos;
    public List<FamiliaPM> familias;
    // Dos bloques que van TAL CUAL, con sus claves de siempre: E1..E3
    // precalculados (VisorResultados.Superposicion.cs) y las flechas de
    // carga, deformadas y jaula (VisorCargasYArmadura.cs).
    public Superposicion superposicion;
    public CargasYArmadura cargas_y_armadura;
}


// ================================================================
// EL VISOR
// ================================================================
public partial class VisorResultados : MonoBehaviour
{
    /// El nombre en StreamingAssets. Es constante y no un campo de la
    /// escena: la escena pisaba el valor del codigo sin avisar. Tiene que
    /// ser el de calculo/rutas.NOMBRES_EN_UNITY (lo comprueba
    /// verificacion/unity.py nombres_y_copias).
    public const string ARCHIVO = "resultados.json";

    [Header("Caso activo")]
    [Tooltip("Vacio = el caso por defecto del anexo. Manda sobre los " +
             "diagramas, los esfuerzos del panel, el punto de demanda " +
             "P-M y la deformada 'Caso activo'.")]
    public string casoActivo = "";

    [Header("Diagramas")]
    public bool mostrarDiagramas = true;

    [Tooltip("My, Mz, Vz, Vy, N, T, o la carga repartida wy / wz (kN/m).")]
    public string magnitud = "My";

    [Tooltip("true: solo la barra seleccionada. false: todas las que el " +
             "visor dibuja y pasan el filtro de piso de PanelVisor.")]
    public bool soloSeleccionado = true;

    [Tooltip("El mayor |valor| de la magnitud entre las barras dibujadas " +
             "se dibuja con este largo, en metros. Es solo grafico: no " +
             "cambia ningun numero.")]
    public float largoDiagramaMaximo = 2f;

    [Range(0.1f, 5f)] public float multiplicadorEscala = 1f;

    public Color colorPositivo = new Color(0.25f, 0.55f, 1f);
    public Color colorNegativo = new Color(1f, 0.40f, 0.25f);
    public Color colorContorno = new Color(0.08f, 0.08f, 0.10f);
    public Color colorEtiqueta = new Color(0.05f, 0.05f, 0.05f);

    [Header("Curva P-M")]
    public bool mostrarPM = true;

    // --- lo que se lee ---
    public Resultados Anexo { get; private set; }
    public int Seleccionado { get; private set; } = -1;

    /// Texto para el panel cuando algo impide usar el anexo.
    public string Aviso { get; private set; } = "";
    public bool AnexoCalzaConElModelo { get; private set; }

    /// true desde que llego EventosVisor.ModeloEditado: el modelo del visor
    /// ya no es el que se resolvio para el anexo (ni para E1..E3 ni para
    /// LIBRE, que el servidor combina sobre el edificio EXPORTADO). No se
    /// vuelve a false sin recargar: mover un nodo deja los mismos n1, n2 y
    /// seccion, y ComprobarModelo diria "calza" con numeros de otra
    /// geometria.
    public bool AnexoDesactualizado { get; private set; }

    /// El ultimo motivo que aviso el editor ("borrar elemento 69").
    public string MotivoDesactualizado { get; private set; } = "";

    /// Lo escucha PanelVisor: si esta mostrando la deformada del caso
    /// activo la tiene que cambiar, y el texto del panel tambien.
    public event System.Action CambioCasoActivo;

    // wy y wz no son esfuerzos: son la carga repartida que recibe OpenSees.
    // Van en la misma fila porque se dibujan con el mismo mecanismo.
    public static readonly string[] MAGNITUDES =
        { "My", "Mz", "Vz", "Vy", "N", "T", "wy", "wz" };

    /// El 'tipo' de los casos que no vienen en la lista de casos de
    /// resultados.json: E1..E3 de su bloque superposicion y LIBRE de POST
    /// /combinar (CONTRATO.md). El panel no los dibuja entre los demas.
    public const string TIPO_SUPERPOSICION = "superposicion";

    // --- indices: se arman al cargar y al registrar un caso externo ---
    private readonly Dictionary<int, ElementoOpenSees> elementoPorId =
        new Dictionary<int, ElementoOpenSees>();
    private readonly Dictionary<string, CasoLab> casoPorNombre =
        new Dictionary<string, CasoLab>();
    private readonly Dictionary<string, Dictionary<int, EsfuerzosBarra>> esfuerzos =
        new Dictionary<string, Dictionary<int, EsfuerzosBarra>>();
    private readonly Dictionary<string, Dictionary<int, Demanda>> demandas =
        new Dictionary<string, Dictionary<int, Demanda>>();

    // --- referencias ---
    private VisorEstructura visor;
    private PanelVisor qa;
    private CamaraOrbital camara;

    // --- estado ---
    private readonly List<GameObject> creados = new List<GameObject>();
    private readonly Dictionary<Color, Material> materiales =
        new Dictionary<Color, Material>();
    private bool deformadaPuesta = false;
    private bool necesitaRedibujar = false;
    private bool refrescarPendiente = false;
    private bool redibujarVisorPendiente = false;
    private bool avisarCambioCasoPendiente = false;

    /// versionCasos con que se aplico por ultima vez el caso activo. Con
    /// el mismo nombre (LIBRE) los numeros pueden ser otros: ElegirCaso
    /// solo se salta el trabajo si el nombre Y la version son los mismos.
    private int versionCasoAplicada = -1;

    // ============================================================
    void OnEnable()
    {
        EventosVisor.ModeloEditado += AlEditarModelo;
        EventosVisor.VistaCambio += AlCambiarVista;
    }

    void OnDisable()
    {
        EventosVisor.ModeloEditado -= AlEditarModelo;
        EventosVisor.VistaCambio -= AlCambiarVista;
        Sup_AlDeshabilitar();
    }

    void Start()
    {
        visor = FindAnyObjectByType<VisorEstructura>();
        qa = FindAnyObjectByType<PanelVisor>();
        camara = FindAnyObjectByType<CamaraOrbital>();
        StartCoroutine(CargarYPreparar());
    }

    IEnumerator CargarYPreparar()
    {
        Aviso = "leyendo " + ARCHIVO + " ...";
        string texto = null, error = null;
        yield return LectorStreaming.Leer(ARCHIVO, t => texto = t, e => error = e);
        bool cargado = Cargar(texto, error);
        // Haya o no haya archivo: quien toma un bloque de aca
        // (VisorCargasYArmadura) deja de esperar.
        LecturaTerminada = true;
        if (!cargado) yield break;
        yield return PrepararCuandoElVisorEsteListo();
        // E1..E3 se registran DESPUES de elegir el caso por defecto: son
        // extras, no cambian con que arranca el visor.
        Sup_Arrancar();
    }

    /// true cuando ya se intento leer resultados.json (haya salido bien o
    /// no). Desde ahi Anexo es el archivo leido, o null si no se pudo.
    public bool LecturaTerminada { get; private set; }

    /// VisorEstructura carga su modelo en su propio Start, que tambien
    /// es asincrono (LectorStreaming): el orden entre los
    /// dos no esta garantizado y un frame ya no alcanza. Se espera a que
    /// diga Listo.
    IEnumerator PrepararCuandoElVisorEsteListo()
    {
        yield return null;
        if (visor == null) visor = FindAnyObjectByType<VisorEstructura>();
        if (visor != null && !visor.Listo)
        {
            // Si el modelo no carga nunca (falta el JSON), el panel se
            // queda con este aviso en vez de callado.
            Aviso = "esperando que VisorEstructura cargue el modelo ...";
            yield return new WaitUntil(() => visor == null || visor.Listo);
        }
        ComprobarModelo();
        if (string.IsNullOrEmpty(casoActivo) || !casoPorNombre.ContainsKey(casoActivo))
            casoActivo = Anexo.info != null ? Anexo.info.caso_por_defecto : "";
        if (!casoPorNombre.ContainsKey(casoActivo ?? "") && Anexo.casos.Count > 0)
            casoActivo = Anexo.casos[0].nombre;
        versionCasoAplicada = versionCasos;
        Redibujar();
    }

    // Los campos del Inspector se aplican en caliente con el mismo
    // mecanismo que los otros visores: OnValidate no puede destruir
    // objetos, asi que solo levanta la bandera y Update redibuja.
    void OnValidate()
    {
        if (Application.isPlaying && Anexo != null) necesitaRedibujar = true;
    }

    void Update()
    {
        if (redibujarVisorPendiente)
        {
            redibujarVisorPendiente = false;
            if (visor != null) visor.Redibujar();
        }
        if (necesitaRedibujar) { necesitaRedibujar = false; refrescarPendiente = false; Redibujar(); }
        if (refrescarPendiente) { refrescarPendiente = false; Refrescar(); }
        if (avisarCambioCasoPendiente)
        {
            avisarCambioCasoPendiente = false;
            if (CambioCasoActivo != null) CambioCasoActivo();
        }
        Sup_Actualizar();
    }

    // ============================================================
    // CARGA
    // ============================================================

    /// Arma los resultados con el texto que leyo LectorStreaming. 'error' no
    /// vacio = no se pudo leer (en Windows, casi siempre que no existe).
    bool Cargar(string texto, string error)
    {
        if (!string.IsNullOrEmpty(error) || texto == null)
        {
            Anexo = null;
            Aviso = "Falta " + ARCHIVO + " en StreamingAssets o no se pudo leer. Generalo y copialo con:\n"
                  + "  python sap.py preparar\n(" + error + ")";
            Debug.LogError("VisorResultados: " + Aviso);
            return false;
        }
        try
        {
            Anexo = JsonUtility.FromJson<Resultados>(texto);
        }
        catch (System.Exception ex)
        {
            Anexo = null;
            Aviso = "No pude leer " + ARCHIVO + ": " + ex.Message;
            Debug.LogError("VisorResultados: " + Aviso);
            return false;
        }
        if (Anexo == null || Anexo.casos == null || Anexo.elementos == null)
        {
            Anexo = null;
            Aviso = ARCHIVO + " no trae casos o elementos: vuelve a exportarlo.";
            Debug.LogError("VisorResultados: " + Aviso);
            return false;
        }
        Aviso = "";
        ConstruirIndices();
        return true;
    }

    void ConstruirIndices()
    {
        elementoPorId.Clear();
        casoPorNombre.Clear();
        esfuerzos.Clear();
        demandas.Clear();

        foreach (ElementoOpenSees e in Anexo.elementos) elementoPorId[e.id] = e;
        foreach (CasoLab c in Anexo.casos) IndexarCaso(c);
    }

    /// Los tres indices de UN caso. Lo usan la carga y RegistrarCasoExterno:
    /// una sola forma de indexar, para que un caso externo se busque igual
    /// que uno del anexo.
    void IndexarCaso(CasoLab c)
    {
        if (c == null || string.IsNullOrEmpty(c.nombre)) return;
        casoPorNombre[c.nombre] = c;

        var porId = new Dictionary<int, EsfuerzosBarra>();
        if (c.esfuerzos != null)
            foreach (EsfuerzosBarra s in c.esfuerzos) if (s != null) porId[s.id] = s;
        esfuerzos[c.nombre] = porId;

        var dem = new Dictionary<int, Demanda>();
        if (c.demandas != null)
            foreach (Demanda d in c.demandas) if (d != null) dem[d.id] = d;
        demandas[c.nombre] = dem;
    }

    /// El anexo tiene que ser del MISMO modelo que dibuja el visor. Si se
    /// exporto otro edificio, los ids existen igual pero son otras barras:
    /// el panel mostraria los esfuerzos de una barra sobre otra, sin error.
    void ComprobarModelo()
    {
        AnexoCalzaConElModelo = false;
        if (Anexo == null) return;
        if (AnexoDesactualizado)
        {
            Aviso = TextoDesactualizado();
            return;
        }
        if (visor == null || visor.Modelo == null || visor.Modelo.elementos == null)
        {
            Aviso = "No hay un VisorEstructura con modelo cargado.";
            return;
        }

        var delModelo = new Dictionary<int, Elemento>();
        foreach (Elemento e in visor.Modelo.elementos) delModelo[e.id] = e;

        int distintos = 0;
        foreach (ElementoOpenSees a in Anexo.elementos)
        {
            Elemento m;
            if (!delModelo.TryGetValue(a.id, out m) || m.n1 != a.n1
                || m.n2 != a.n2 || m.seccion != a.seccion)
                distintos++;
        }

        AnexoCalzaConElModelo = delModelo.Count == Anexo.elementos.Count && distintos == 0;
        if (AnexoCalzaConElModelo)
        {
            Aviso = "";
            return;
        }
        string ed = Anexo.info != null ? Anexo.info.edificio : "?";
        Aviso = $"Los resultados son de otro modelo: '{ed}', {Anexo.elementos.Count} elementos; "
              + $"el visor tiene {delModelo.Count} y {distintos} no calzan.\n"
              + "Vuelve a exportar y copiar:\n"
              + "  python sap.py preparar";
        Debug.LogWarning("VisorResultados: " + Aviso);
    }

    // ============================================================
    // MODELO EDITADO Y VISTA
    // ============================================================

    string TextoDesactualizado()
    {
        return "Resultados del modelo ORIGINAL: el modelo se edito ("
             + (string.IsNullOrEmpty(MotivoDesactualizado) ? "sin motivo" : MotivoDesactualizado)
             + "). Los casos de resultados.json, E1..E3 y LIBRE no son de esta geometria. "
             + "Recalcula con el servidor (pestana Modificar) o re-exporta: python sap.py preparar";
    }

    /// EventosVisor.ModeloEditado. Puede llegar en cada frame de un
    /// arrastre: solo cambia banderas y textos; el redibujo va a Update.
    void AlEditarModelo(string motivo)
    {
        bool primeraVez = !AnexoDesactualizado;
        AnexoDesactualizado = true;
        MotivoDesactualizado = motivo ?? "";
        AnexoCalzaConElModelo = false;
        Aviso = TextoDesactualizado();

        // La deformada del caso es del modelo original. El editor ya
        // limpia la suya; si la puso este script se suelta aca, y el
        // visor se redibuja en Update por si el editor no lo hace.
        if (deformadaPuesta)
        {
            deformadaPuesta = false;
            if (visor != null) visor.LimpiarDeformada();
            redibujarVisorPendiente = true;
        }
        if (primeraVez)
        {
            Debug.LogWarning("VisorResultados: " + Aviso);
            texturaPMFirma = null;
            necesitaRedibujar = true;
            // A PanelVisor se le avisa en Update: el editor puede avisar
            // ModeloEditado desde su OnGUI, y cambiar el panel a mitad de
            // un evento de IMGUI descuadra el Layout.
            avisarCambioCasoPendiente = true;
        }
    }

    /// EventosVisor.VistaCambio (filtro de piso, capas): los diagramas se
    /// rehacen si cambio su firma. En Update, porque el aviso puede venir
    /// desde un OnGUI.
    void AlCambiarVista()
    {
        refrescarPendiente = true;
    }

    // ============================================================
    // API QUE USA PanelVisor
    // ============================================================
    public CasoLab CasoActivo()
    {
        CasoLab c;
        return (Anexo != null && casoPorNombre.TryGetValue(casoActivo ?? "", out c)) ? c : null;
    }

    public ElementoOpenSees ElementoPorId(int id)
    {
        ElementoOpenSees e;
        return elementoPorId.TryGetValue(id, out e) ? e : null;
    }

    /// Esfuerzos de la barra en el caso activo, o null.
    public EsfuerzosBarra EsfuerzosDe(int id)
    {
        Dictionary<int, EsfuerzosBarra> porId;
        EsfuerzosBarra s;
        return (esfuerzos.TryGetValue(casoActivo ?? "", out porId)
                && porId.TryGetValue(id, out s)) ? s : null;
    }

    public Demanda DemandaDe(int id, string caso)
    {
        Dictionary<int, Demanda> dem;
        Demanda d;
        return (demandas.TryGetValue(caso ?? "", out dem)
                && dem.TryGetValue(id, out d)) ? d : null;
    }

    /// Cambia el caso activo. Con el MISMO nombre solo se salta el trabajo
    /// si ademas no cambio versionCasos: LIBRE se reemplaza con otros
    /// numeros y hay que volver a dibujarlo.
    public void ElegirCaso(string nombre)
    {
        if (Anexo == null || string.IsNullOrEmpty(nombre) || !casoPorNombre.ContainsKey(nombre))
            return;
        if (nombre == casoActivo && versionCasoAplicada == versionCasos)
            return;
        casoActivo = nombre;
        AplicarCasoActivo();
    }

    /// Lo que sigue a cambiar (o reemplazar) el caso activo: deformada si
    /// este script la tenia puesta, diagramas, P-M y aviso a PanelVisor.
    void AplicarCasoActivo()
    {
        versionCasoAplicada = versionCasos;
        texturaPMFirma = null;
        if (deformadaPuesta) AplicarDeformadaDelCaso();
        Redibujar();
        if (CambioCasoActivo != null) CambioCasoActivo();
    }

    /// La implementacion de RegistrarCasoExterno (declarado abajo, en los
    /// puntos de enganche).
    /// Agrega el caso o reemplaza el que tenga su nombre, lo indexa como
    /// a los del anexo y sube versionCasos, que esta en la firma de todo lo
    /// que cachea un caso. No toca un numero del caso: llega completo de
    /// Python (el bloque superposicion o POST /combinar).
    partial void Hook_RegistrarCasoExterno(CasoLab caso)
    {
        if (Anexo == null || Anexo.casos == null)
        {
            Debug.LogWarning($"VisorResultados: no hay anexo cargado; no registro el caso '{caso.nombre}'.");
            return;
        }
        int k = Anexo.casos.FindIndex(x => x != null && x.nombre == caso.nombre);
        if (k >= 0 && Anexo.casos[k].tipo != TIPO_SUPERPOSICION)
        {
            // Un caso de resultados.json (G, S3, 1.2G+1.6Q...) no se pisa desde
            // afuera: sus numeros son los que comprobo la verificacion.
            Debug.LogWarning($"VisorResultados: '{caso.nombre}' ya es un caso de {ARCHIVO} "
                             + $"(tipo '{Anexo.casos[k].tipo}'); no lo reemplazo.");
            return;
        }
        if (k >= 0) Anexo.casos[k] = caso;
        else Anexo.casos.Add(caso);
        IndexarCaso(caso);
        versionCasos++;

        if (caso.nombre == casoActivo) AplicarCasoActivo();
    }

    /// Lo llama PanelVisor al seleccionar una barra, y los botones de demo.
    public void Seleccionar(int id)
    {
        Seleccionado = id;
        texturaPMFirma = null;
        Redibujar();
    }

    /// La deformada del caso activo, con los desplazamientos del anexo.
    /// PanelVisor la pide con el modo "Caso activo". Con el modelo
    /// editado no se aplica: son desplazamientos de otra geometria y
    /// taparian la deformada del reanalisis.
    public void AplicarDeformadaDelCaso()
    {
        CasoLab c = CasoActivo();
        if (visor == null || c == null || c.desplazamientos == null) return;
        if (AnexoDesactualizado) return;
        visor.mostrarDeformada = true;
        visor.AplicarDeformada(c.desplazamientos);      // ya redibuja
        deformadaPuesta = true;
    }

    /// Solo quita la deformada si la puso ESTE script. La de gravedad y la
    /// de sismo las ponen otros, y borrarlas aca las apagaria en el mismo
    /// frame en que se eligen: el mismo cuidado que VisorCargasYArmadura.
    public void QuitarDeformada()
    {
        if (!deformadaPuesta || visor == null) return;
        deformadaPuesta = false;
        visor.LimpiarDeformada();
        visor.Redibujar();
    }

    public bool MouseSobreVentana(Vector2 posGUI)
    {
        return VentanaPMVisible() && ventanaPM.Contains(posGUI);
    }

    /// Centra la camara orbital en la barra: sirve en la demo para no
    /// buscar la columna a mano en un edificio de 50 m.
    public void EnfocarElemento(int id)
    {
        if (camara == null || visor == null || visor.Modelo == null) return;
        Elemento e = null;
        foreach (Elemento x in visor.Modelo.elementos)
            if (x.id == id) { e = x; break; }
        if (e == null) return;

        Nodo a = visor.Modelo.NodoPorId(e.n1);
        Nodo b = visor.Modelo.NodoPorId(e.n2);
        if (a == null || b == null) return;

        Vector3 pa = Ejes.PosicionDe(a), pb = Ejes.PosicionDe(b);
        camara.centro = (pa + pb) * 0.5f;
        ElementoOpenSees s = ElementoPorId(id);
        float tam = Mathf.Max(Vector3.Distance(pa, pb),
                              s != null ? Mathf.Max(s.b, s.h) : 0f);
        camara.distancia = Mathf.Clamp(tam * 3.5f, 8f, 80f);
    }

    // ============================================================
    // PUNTOS DE ENGANCHE ENTRE LAS PARTES (versionCasos, ContarDemandas,
    // RegistrarCasoExterno, DibujarPMEnLinea)
    // ============================================================

    /// Sube cada vez que cambian los CASOS que se pueden dibujar (se
    /// registra o reemplaza uno externo, como LIBRE). Quien cachea algo
    /// que depende de un caso -- la textura de la P-M, la firma de los
    /// diagramas, el mapa D/C -- la incluye en su firma: con el mismo
    /// nombre de caso, los numeros pueden ser otros.
    /// Solo lo modifica RegistrarCasoExterno.
    [System.NonSerialized]
    public int versionCasos = 0;

    /// Los controles de superposicion (sliders de lambda, E1..E3, boton
    /// "Combinar en Python"). Lo implementa
    /// VisorResultados.Superposicion.cs; lo llama DibujarControles
    /// (VisorResultados.Panel.cs), UNA vez, dentro de la seccion de casos.
    partial void Hook_DibujarSuperposicion();

    /// La curva P-M de la barra seleccionada dibujada DENTRO del panel
    /// (no en la ventana flotante). La implementa VisorResultados.PM.cs.
    partial void Hook_DibujarPMEnLinea();

    /// Lo llama PanelVisor en la pestana Elemento, dentro de su area y
    /// su scroll. Solo GUILayout.
    public void DibujarPMEnLinea()
    {
        Hook_DibujarPMEnLinea();
    }

    /// Cuantas demandas trae un caso, cuantas NO PASAN (pasa == false del
    /// JSON) y cuantas de esas son "P fuera de la curva" (u = 9999). Solo
    /// cuenta lo que escribio Python; no revisa nada. La cabecera del
    /// panel y la leyenda del mapa D/C usan esta, para que
    /// "NO PASA n/m" sea el mismo numero en los dos lugares.
    public static void ContarDemandas(CasoLab caso, out int noPasan, out int fueraDeCurva, out int total)
    {
        noPasan = 0;
        fueraDeCurva = 0;
        total = 0;
        if (caso == null || caso.demandas == null) return;
        foreach (Demanda d in caso.demandas)
        {
            total++;
            if (!d.pasa) noPasan++;
            if (d.u >= PanelUI.U_FUERA_DE_CURVA) fueraDeCurva++;
        }
    }

    /// La implementacion de RegistrarCasoExterno esta arriba, junto a los
    /// indices privados casoPorNombre, esfuerzos y demandas.
    partial void Hook_RegistrarCasoExterno(CasoLab caso);

    /// Agrega un caso que no vino en la lista de casos -- la combinacion LIBRE
    /// que devuelve POST /combinar -- o reemplaza el que tenga el mismo
    /// nombre. Despues de llamarlo, ElegirCaso(caso.nombre) lo muestra en
    /// el panel, los diagramas, la deformada y la P-M.
    ///
    /// El caso tiene que venir COMPLETO de Python, con la forma de
    /// CasoLab (desplazamientos de todos los nodos, esfuerzos de todas las
    /// barras con sus estaciones, demandas de las que tienen fierro): aca
    /// no se completa ni se combina nada.
    public void RegistrarCasoExterno(CasoLab caso)
    {
        if (caso == null || string.IsNullOrEmpty(caso.nombre)) return;
        Hook_RegistrarCasoExterno(caso);
    }

    // Sigue en VisorResultados.Diagramas.cs, .Mapa.cs, .PM.cs, .Panel.cs,
    // .Superposicion.cs e .Instantanea.cs.
}
