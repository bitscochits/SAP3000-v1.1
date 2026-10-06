/*
================================================================
  VisorQA.cs
================================================================
  El PANEL del visor y las capas de CONTROL DE CALIDAD sobre el
  modelo que dibuja VisorEstructura: apoyos, diafragmas, IDs, ejes
  locales, areas tributarias y la seleccion.

  El viewer no es decoracion. Existe para poder contestar, senalando
  con el mouse:

      - que elemento o nodo estoy mirando y que tag tiene;
      - donde esta (coordenadas, cota, piso);
      - como esta apoyado (los 6 GDL en palabras, no "se ve empotrado");
      - como esta orientado (sus ejes locales);
      - que lo carga (area tributaria, cargas nodales);
      - como se deforma y que fuerzas y capacidad tiene (Semana 4).

  ----------------------------------------------------------------
  EL PANEL (Semana 5)
  ----------------------------------------------------------------
  La misma informacion de antes, ordenada en pestanas:

      cabecera fija   edificio, caso activo, desplazamiento maximo,
                      NO PASA n de m, avisos, la seleccion y el boton
                      "Abrir Excel de resultados"
      Vista           realista / tecnica, suelo, camara, filtro de piso
      Capas           estructura, control de calidad (con leyenda de
                      apoyos) y las capas de la Semana 3
      Caso            deformada y los controles de la Semana 4
      Elemento        el inspector de la seleccion (nodo o barra)
      Modificar, Carga movil, ...  un IPanelIncrustable cada una

  Antes todo iba en un solo scroll de 430 px y lo seleccionado quedaba
  al FINAL, debajo de todos los controles: en 1080p habia que bajar
  para leer lo que se acababa de clickear.

  Estilos de PanelUI (escalados por DPI, sin GUI.matrix: los Rect
  siguen en pixeles reales y MouseSobreUI no cambia).

  ----------------------------------------------------------------
  UNA SOLA SELECCION
  ----------------------------------------------------------------
  VisorQA es la unica fuente: click (nodo, barra o simbolo de apoyo),
  "Ir a ID" o un boton del inspector. Avisa EventosVisor.SeleccionCambio
  y el editor la sigue. Esc o click en el vacio la limpian. Antes el
  editor llevaba otra y los dos paneles se contradecian. Un click en el
  modelo desde Vista o Capas abre la pestana Elemento.

  ----------------------------------------------------------------
  IMGUI Y EL "Getting control N's position"
  ----------------------------------------------------------------
  OnGUI se llama una vez por evento, y cada evento repite el Layout.
  Si un click agrega o quita controles EN MEDIO de un evento, IMGUI
  reclama. Por eso:
    - lo que cambia la escena o la cantidad de controles se DIFIERE a
      Update (Diferir);
    - lo que dibuja el panel (pestanas, seleccion, bloques del
      inspector) se lee de una FOTO que se toma en el evento Layout.

  ----------------------------------------------------------------
  REGLA QUE NO SE ROMPE: aca no se calcula estructura. Los ejes
  locales, las areas, las cargas, los desplazamientos y la demanda
  vienen calculados de Python en los JSON. Este script solo los dibuja
  y los escribe en pantalla.

  OJO: CapturaSemana04 lee por reflexion los campos privados 'scroll'
  (Vector2) y 'refrescar' (bool). No renombrarlos ni cambiarles el tipo.
================================================================
*/

using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.Rendering;

[RequireComponent(typeof(VisorEstructura))]
public partial class VisorQA : MonoBehaviour
{
    [Header("Referencias")]
    public VisorEstructura visor;
    public Camera camara;
    [Tooltip("Se busca sola si no se asigna. Sirve para no seleccionar "
           + "cuando el click fue en realidad un arrastre de camara.")]
    public CamaraOrbital orbital;

    [Header("Panel")]
    [Tooltip("Ancho del panel en pixeles de diseno (96 dpi). Se escala con "
           + "PanelUI.Px y se acota al 45 % de la pantalla.")]
    public float anchoPanel = 400f;

    [Tooltip("La tecla H lo oculta y lo vuelve a mostrar.")]
    public bool panelVisible = true;

    // CapturaSemana04 lo fija por reflexion: nombre y tipo congelados.
    private Vector2 scroll;

    [Header("Capas QA")]
    public bool verApoyos = true;
    public bool verDiafragmas = false;
    public bool verEjesLocales = false;
    public bool verAreasTributarias = false;
    public bool verIDs = false;

    [Header("Filtro de piso  (-1 = todos)")]
    [Tooltip("Con 1200 elementos, mirar un piso a la vez es la unica "
           + "forma de revisar algo. -1 muestra el edificio completo. Se "
           + "copia a AjustesVista.cotaVisible, que es lo que leen el "
           + "visor, los diagramas y el mapa D/C.")]
    public int soloNivel = -1;

    [Header("Apariencia")]
    public float tamanoApoyo = 0.45f;
    public float largoEje = 1.2f;
    public float grosorLinea = 0.04f;
    [Tooltip("Los IDs son texto 3D: con miles a la vez Unity se arrastra. "
           + "Solo se dibujan los de los elementos mas cercanos a la camara.")]
    public int maxIDs = 120;

    [Header("Colores")]
    [Tooltip("Apoyo empotrado [1 1 1 1 1 1]: cubo.")]
    public Color colorApoyo = new Color(0.10f, 0.80f, 0.35f);
    [Tooltip("Apoyo en terreno [0 0 1 1 1 0]: placa.")]
    public Color colorApoyoTerreno = new Color(0.78f, 0.52f, 0.22f);
    [Tooltip("Cualquier otra combinacion de restricciones: rombo.")]
    public Color colorApoyoOtro = new Color(0.70f, 0.45f, 1.00f);
    public Color colorDiafragma = new Color(1f, 0.85f, 0.15f);
    public Color colorEjeX = new Color(1f, 0.25f, 0.25f);   // rojo
    public Color colorEjeY = new Color(0.25f, 1f, 0.25f);   // verde
    public Color colorEjeZ = new Color(0.35f, 0.55f, 1f);   // azul
    public Color colorTributaria = new Color(1f, 0.55f, 0.10f, 0.85f);
    [Tooltip("Cian: no se confunde con el amarillo de la deformada ni de "
           + "los diafragmas, ni con los colores del mapa D/C.")]
    [SerializeField] private Color colorResaltado = new Color(0.10f, 0.90f, 1.00f);

    /// El color de la seleccion. Es propiedad y no campo a proposito:
    /// SampleScene.unity guardo el campo 'colorSeleccion' con el magenta de
    /// antes (1, 0, 0.85), y un campo serializado con ese nombre tomaria el
    /// valor de la escena en vez del cian del codigo. Con otro nombre
    /// serializado el valor viejo de la escena se ignora, y el nombre
    /// publico sigue existiendo para quien lo use.
    public Color colorSeleccion
    {
        get { return colorResaltado; }
        set { colorResaltado = value; }
    }

    // --- Nombres de las pestanas fijas. Los de las incrustables los da
    //     cada panel (IPanelIncrustable.TituloPestana). ---
    public const string PESTANA_VISTA = "Vista";
    public const string PESTANA_CAPAS = "Capas";
    public const string PESTANA_CASO = "Caso";
    public const string PESTANA_ELEMENTO = "Elemento";
    public const string PESTANA_MODIFICAR = "Modificar";
    public const string PESTANA_CARGA_MOVIL = "Carga movil";

    // Las que se esperan aunque su panel no este en la escena: en vez de
    // desaparecer sin explicacion, la pestana dice por que esta vacia.
    private static readonly string[] PESTANAS_ESPERADAS = { PESTANA_MODIFICAR, PESTANA_CARGA_MOVIL };

    // Hasta cuando "sin modelo" se lee como "cargando" y no como error. Es
    // un margen amplio para un telefono lento, no un tiempo medido: pasado,
    // el panel manda a mirar la consola.
    private const float SEGUNDOS_DE_CARGA = 10f;

    // ============================================================
    // ESTADO
    // ============================================================
    private readonly List<GameObject> creados = new List<GameObject>();

    // CapturaSemana04 lo fija por reflexion: nombre y tipo congelados.
    private bool refrescar = true;

    // La seleccion: tipo (EventosVisor.TIPO_*) e id de OpenSees.
    private string selTipo = EventosVisor.TIPO_NINGUNO;
    private int selId = -1;

    // El inspector ya armado, en bloques plegables. Se rehace en Update
    // (nunca dentro de OnGUI) y se reemplaza entero, no se modifica.
    private List<BloqueTexto> bloques = new List<BloqueTexto>();
    private bool inspectorSucio = true;
    private int versionCasosVista = -1;

    private string pestana = PESTANA_CASO;
    private string pestanaPendiente = null;
    private readonly List<IPanelIncrustable> incrustables = new List<IPanelIncrustable>();
    private List<string> titulosPestanas = new List<string>();

    // Lo que se difiere a Update.
    private System.Action pendientes;

    // Aviso de la cabecera cuando el editor cambia el modelo.
    private string avisoEdicion = "";
    private string mensajeExcel = "";
    private bool mensajeExcelEsError = false;
    private string mensajeIrA = "";
    private string campoIrA = "";

    // Las capas de Semana 3: cargas, deformada sismica y enfierradura.
    // Es opcional -- la escena puede no tenerlo -- asi que todo lo que
    // dependa de el va detras de un null.
    private VisorSemana03 s3;
    private ModoDeformada modo = ModoDeformada.Sin;

    // Semana 4: esfuerzos del caso activo, diagramas, curva P-M y
    // trazabilidad. Si la escena no lo trae, se agrega en Start.
    private VisorSemana04 s4;

    private EditorEstructura editor;

    // --- La foto que se toma en el Layout (ver cabecera del archivo) ---
    private bool fotoPanelVisible = true;
    private string fotoPestana = PESTANA_CASO;
    private List<string> fotoPestanas = new List<string>();
    private string fotoSelTipo = EventosVisor.TIPO_NINGUNO;
    private int fotoSelId = -1;
    private List<BloqueTexto> fotoBloques = new List<BloqueTexto>();
    private ModoDeformada fotoModo = ModoDeformada.Sin;
    private string fotoCabeceraCaso = "", fotoCabeceraDesp = "", fotoCabeceraDemanda = "";
    private bool fotoDemandaPasa = true, fotoHayDemanda = false;
    private string fotoAvisoAnexo = "", fotoAvisoS3 = "", fotoReanalisisCasos = "";
    private bool fotoAnexoPorEdicion = false;
    private AnalizadorEstructural analizador;
    private string fotoAvisoEdicion = "", fotoMensajeExcel = "", fotoMensajeIrA = "";
    private bool fotoMensajeExcelEsError = false;

    /// Un bloque plegable del inspector.
    private class BloqueTexto
    {
        public string clave;
        public string titulo;
        public string cuerpo;
        public bool abiertoPorDefecto;
        public bool mono, aviso;
        public string nota;            // linea tenue bajo el cuerpo; vacia = no se dibuja
        public List<Enlace> enlaces;
    }

    /// Un boton del inspector que selecciona otra cosa (un nodo de la
    /// barra, una barra que llega al nodo).
    private class Enlace
    {
        public string tipo;
        public int id;
        public string texto;
    }

    private enum TipoApoyo { Ninguno, Empotrado, Terreno, Otro }

    // ============================================================
    void Reset()
    {
        visor = GetComponent<VisorEstructura>();
        camara = Camera.main;
    }

    void OnEnable()
    {
        EventosVisor.ModeloCargado += AlCargarModelo;
        EventosVisor.Redibujado += AlRedibujar;
        EventosVisor.ModeloEditado += AlEditarModelo;
        EventosVisor.SeleccionCambio += AlCambiarSeleccionDeOtro;
        EventosVisor.VistaCambio += AlCambiarVista;
    }

    void OnDisable()
    {
        EventosVisor.ModeloCargado -= AlCargarModelo;
        EventosVisor.Redibujado -= AlRedibujar;
        EventosVisor.ModeloEditado -= AlEditarModelo;
        EventosVisor.SeleccionCambio -= AlCambiarSeleccionDeOtro;
        EventosVisor.VistaCambio -= AlCambiarVista;
    }

    void Start()
    {
        if (visor == null) visor = GetComponent<VisorEstructura>();
        if (camara == null) camara = Camera.main;
        if (orbital == null && camara != null)
            orbital = camara.GetComponent<CamaraOrbital>();
        s3 = FindAnyObjectByType<VisorSemana03>();
        // El panel manda sobre la deformada, asi que arranca coherente
        // con lo que este script cree: sin deformar.
        if (s3 != null) s3.aplicarDeformada = false;

        s4 = FindAnyObjectByType<VisorSemana04>();
        if (s4 == null) s4 = gameObject.AddComponent<VisorSemana04>();
        s4.CambioCasoActivo += AlCambiarCasoActivo;

        BuscarIncrustables();
    }

    void OnDestroy()
    {
        if (s4 != null) s4.CambioCasoActivo -= AlCambiarCasoActivo;
    }

    void OnValidate()
    {
        if (Application.isPlaying) refrescar = true;
    }

    void Update()
    {
        if (visor == null || visor.Modelo == null) return;

        if (pendientes != null)
        {
            System.Action a = pendientes;
            pendientes = null;
            a();
        }

        SincronizarPiso();
        LeerTeclas();
        LeerClick();

        if (s4 != null && s4.versionCasos != versionCasosVista)
        {
            versionCasosVista = s4.versionCasos;
            inspectorSucio = true;
        }
        if (inspectorSucio) ReconstruirInspector();

        if (refrescar)
        {
            refrescar = false;
            Redibujar();
        }
    }

    void Diferir(System.Action accion) { pendientes += accion; }

    // ============================================================
    // EVENTOS
    // ============================================================
    void AlCargarModelo()
    {
        cotasDelModelo = null;
        conteoApoyos = null;
        // Otro modelo puede tener otras cotas: el indice soloNivel se vuelve
        // a copiar a AjustesVista.cotaVisible en el Update siguiente.
        nivelSincronizado = int.MinValue;
        inspectorSucio = true;
        refrescar = true;
    }

    /// El visor rehizo sus objetos: la seleccion resaltada, los apoyos y
    /// la trazabilidad (que mira el GameObject real) se rehacen tambien.
    /// Aca NO se llama a visor.Redibujar(): seria un lazo.
    void AlRedibujar()
    {
        refrescar = true;
        inspectorSucio = true;
    }

    void AlEditarModelo(string motivo)
    {
        avisoEdicion = string.IsNullOrEmpty(motivo) ? "modelo editado" : motivo;
        cotasDelModelo = null;
        conteoApoyos = null;
        // Mover un nodo a una z nueva agrega una cota y corre los indices de
        // las de arriba: soloNivel (indice) dejaria de decir lo mismo que
        // AjustesVista.cotaVisible (cota). Se vuelve a buscar el indice de la
        // cota filtrada; si esa cota ya no existe, queda en "todos" y
        // SincronizarPiso lo avisa en el Update siguiente.
        if (soloNivel >= 0)
        {
            soloNivel = NivelDeCota(AjustesVista.cotaVisible);
            nivelSincronizado = int.MinValue;
        }
        // Si lo seleccionado ya no existe (se borro), se suelta.
        if (!SeleccionExiste(selTipo, selId)) FijarSeleccion(EventosVisor.TIPO_NINGUNO, -1, true);
        inspectorSucio = true;
        refrescar = true;
    }

    /// Otro script aviso una seleccion. VisorQA es la fuente, asi que solo
    /// se copia (sin volver a avisar: seria un lazo) si es distinta.
    void AlCambiarSeleccionDeOtro(string tipo, int id)
    {
        if (tipo == selTipo && id == selId) return;
        FijarSeleccion(tipo, id, false);
    }

    /// Si otro cambio AjustesVista.cotaVisible, el indice soloNivel lo
    /// sigue. Si fue este mismo script, ya calza y no hace nada.
    void AlCambiarVista()
    {
        float cotaMia = soloNivel < 0 ? float.NaN : CotaDeNivel(soloNivel);
        if (MismaCota(cotaMia, AjustesVista.cotaVisible)) return;
        soloNivel = NivelDeCota(AjustesVista.cotaVisible);
        nivelSincronizado = soloNivel;
        refrescar = true;
        inspectorSucio = true;
    }

    /// El texto del panel depende del caso activo, y si se esta mirando
    /// la deformada del caso activo hay que cambiarla tambien.
    void AlCambiarCasoActivo()
    {
        if (modo == ModoDeformada.CasoActivo && s4 != null) s4.AplicarDeformadaDelCaso();
        inspectorSucio = true;
        refrescar = true;
    }

    // ============================================================
    // TECLAS Y SELECCION
    // ============================================================
    void LeerTeclas()
    {
        // Mientras se escribe en un campo (Ir a ID, coordenadas del
        // editor) las letras son texto, no atajos.
        if (GUIUtility.keyboardControl != 0) return;

        if (Input.GetKeyDown(KeyCode.H)) panelVisible = !panelVisible;
        if (Input.GetKeyDown(KeyCode.Escape) && selTipo != EventosVisor.TIPO_NINGUNO)
            LimpiarSeleccion();
        if (Input.GetKeyDown(KeyCode.C)) CentrarSeleccion();
    }

    void LeerClick()
    {
        // Se selecciona al SOLTAR, no al presionar, y solo si no hubo
        // arrastre: el mismo boton izquierdo lo usa CamaraOrbital para
        // orbitar. Si se seleccionara en GetMouseButtonDown, cada vez
        // que giras la vista seleccionarias lo que hubiera debajo del
        // cursor. Es la misma convencion que ya usa EditorEstructura.
        if (!Input.GetMouseButtonUp(0)) return;
        if (camara == null) return;
        if (orbital != null && orbital.HuboArrastre) return;

        // Un click sobre el panel de la UI no debe atravesar y
        // seleccionar la barra que haya detras.
        if (MouseSobrePanel()) return;

        // Soltar el nodo que el editor venia arrastrando no es un click de
        // seleccion: con la camara bloqueada HuboArrastre no se entera, y el
        // raycast al soltar podia caer en el vacio y soltar el nodo recien
        // movido. MouseSobrePanel ya busco el editor.
        if (editor != null && editor.ArrastrandoNodo) return;

        Ray rayo = camara.ScreenPointToRay(Input.mousePosition);
        RaycastHit hit;
        if (!Physics.Raycast(rayo, out hit, 10000f))
        {
            // Click en el vacio: suelta la seleccion.
            if (selTipo != EventosVisor.TIPO_NINGUNO) LimpiarSeleccion();
            return;
        }

        DatoElemento de = hit.collider.GetComponentInParent<DatoElemento>();
        if (de != null) { SeleccionarElemento(de.idElemento); MostrarInspectorTrasClick(); return; }

        // Un nodo, o el simbolo de un apoyo (que lleva DatoNodo): antes
        // solo se aceptaban barras y el click en un apoyo no decia nada.
        DatoNodo dn = hit.collider.GetComponentInParent<DatoNodo>();
        if (dn != null) { SeleccionarNodo(dn.idNodo); MostrarInspectorTrasClick(); }
        // Otro objeto con collider (no es del modelo): no se toca nada.
    }

    /// Un click en el modelo desde Vista o Capas (pestanas de ajustes, que
    /// no dicen nada de lo seleccionado) abre el inspector: es la respuesta
    /// a "que es esto". Desde Caso, Modificar o Carga movil NO se cambia:
    /// ahi el click es parte de lo que se esta haciendo (ver el diagrama de
    /// otra barra, elegir el nodo a mover) y la cabecera ya muestra la
    /// seleccion con su boton "Ver". SeleccionarElemento/Nodo no cambian de
    /// pestana: los usan las capturas y los botones de demo.
    void MostrarInspectorTrasClick()
    {
        if (selTipo == EventosVisor.TIPO_NINGUNO) return;
        if (pestana == PESTANA_VISTA || pestana == PESTANA_CAPAS) pestanaPendiente = PESTANA_ELEMENTO;
    }

    /// Selecciona una barra por su elementTag, igual que un click. Lo usan
    /// tambien los botones de demo de Semana 4 y la lista de criticos.
    public void SeleccionarElemento(int id)
    {
        FijarSeleccion(EventosVisor.TIPO_ELEMENTO, id, true);
    }

    /// Selecciona un nodo por su nodeTag, igual que un click.
    public void SeleccionarNodo(int id)
    {
        FijarSeleccion(EventosVisor.TIPO_NODO, id, true);
    }

    public void LimpiarSeleccion()
    {
        FijarSeleccion(EventosVisor.TIPO_NINGUNO, -1, true);
    }

    /// "elemento", "nodo" o "" (EventosVisor.TIPO_*).
    public string TipoSeleccionado { get { return selTipo; } }

    /// El id de OpenSees de lo seleccionado, o -1.
    public int IdSeleccionado { get { return selId; } }

    void FijarSeleccion(string tipo, int id, bool avisar)
    {
        if (tipo != EventosVisor.TIPO_ELEMENTO && tipo != EventosVisor.TIPO_NODO)
        {
            tipo = EventosVisor.TIPO_NINGUNO;
            id = -1;
        }
        else if (!SeleccionExiste(tipo, id))
        {
            mensajeIrA = $"No existe {(tipo == EventosVisor.TIPO_NODO ? "el nodo" : "el elemento")} {id} en este modelo.";
            tipo = EventosVisor.TIPO_NINGUNO;
            id = -1;
        }
        else
        {
            mensajeIrA = "";   // el "No existe" de un intento anterior ya no aplica
        }

        selTipo = tipo;
        selId = id;
        // Semana 4 dibuja el diagrama y la P-M de "la seleccionada": con
        // un nodo o sin nada no hay barra.
        if (s4 != null) s4.Seleccionar(tipo == EventosVisor.TIPO_ELEMENTO ? id : -1);
        inspectorSucio = true;
        refrescar = true;
        if (avisar) EventosVisor.AvisarSeleccionCambio(tipo, id);
    }

    bool SeleccionExiste(string tipo, int id)
    {
        ModeloEstructural m = visor != null ? visor.Modelo : null;
        if (m == null) return false;
        if (tipo == EventosVisor.TIPO_ELEMENTO) return m.ElementoPorId(id) != null;
        if (tipo == EventosVisor.TIPO_NODO) return m.NodoPorId(id) != null;
        return tipo == EventosVisor.TIPO_NINGUNO;
    }

    /// Pide a la camara que centre lo seleccionado (EventosVisor.PedirCentrar;
    /// la camara es quien escucha).
    public void CentrarSeleccion()
    {
        ModeloEstructural m = visor != null ? visor.Modelo : null;
        if (m == null) return;
        if (selTipo == EventosVisor.TIPO_NODO)
        {
            Nodo n = m.NodoPorId(selId);
            if (n != null) EventosVisor.AvisarPedirCentrar(visor.PosicionActual(n), 8f);
        }
        else if (selTipo == EventosVisor.TIPO_ELEMENTO)
        {
            Elemento e = m.ElementoPorId(selId);
            Nodo a = e != null ? m.NodoPorId(e.n1) : null;
            Nodo b = e != null ? m.NodoPorId(e.n2) : null;
            if (a == null || b == null) return;
            Vector3 pa = visor.PosicionActual(a), pb = visor.PosicionActual(b);
            // El tamano a encuadrar: la barra, o el muro en planta si es
            // mas largo que alto.
            float tam = Mathf.Max(Vector3.Distance(pa, pb), e.largo, 3f);
            EventosVisor.AvisarPedirCentrar((pa + pb) * 0.5f, tam);
        }
    }

    /// El origen de GUI esta arriba-izquierda y el de Input.mousePosition
    /// abajo-izquierda: hay que invertir la Y antes de comparar.
    ///
    /// Se consulta tambien el panel del EDITOR (que vive a la derecha si
    /// dibuja el suyo): un click sobre el no debe atravesar y seleccionar
    /// la barra que haya detras.
    /// Lo mismo, para quien no es VisorQA: la camara pregunta antes de
    /// orbitar o hacer zoom. Arrastrar la barra de scroll de este panel
    /// no puede mover el modelo.
    public bool MouseSobreUI()
    {
        return MouseSobrePanel();
    }

    bool MouseSobrePanel()
    {
        Vector2 p = new Vector2(Input.mousePosition.x,
                                Screen.height - Input.mousePosition.y);
        if (RectPanel().Contains(p)) return true;
        // La ventana de la curva P-M de Semana 4 tampoco se atraviesa.
        if (s4 != null && s4.MouseSobreVentana(p)) return true;

        if (editor == null) editor = FindAnyObjectByType<EditorEstructura>();
        return editor != null && editor.MouseSobrePanel();
    }

    /// El rectangulo del panel en pixeles reales de pantalla (origen
    /// arriba-izquierda, como GUI). Oculto, es el del boton "Panel".
    /// Publico para que una ventana flotante se abra a su derecha.
    public Rect RectPanel()
    {
        if (!panelVisible)
            return new Rect(10f, 10f, PanelUI.Px(110f), PanelUI.AltoBoton);
        // A lo mas el 45 % de la pantalla: con dpi alto en una ventana de
        // 1280 px, Px(400) se comeria la mitad del modelo.
        float ancho = Mathf.Min(PanelUI.Px(anchoPanel),
                                Mathf.Max(300f, Screen.width * 0.45f),
                                Screen.width - 20f);
        return new Rect(10f, 10f, ancho, Screen.height - 20f);
    }

    // ============================================================
    // PISOS
    // ============================================================
    public bool NivelVisible(float z)
    {
        return soloNivel < 0
               || Mathf.Abs(z - CotaDeNivel(soloNivel)) < AjustesVista.TOLERANCIA_COTA;
    }

    /// Filtra un piso por su indice (0 = el mas bajo; -1 = todos) y lo
    /// copia en el acto a AjustesVista. Es lo que usan los botones y las
    /// capturas: asignar soloNivel a mano tambien sirve, pero el visor se
    /// entera recien en el Update siguiente.
    public void ElegirPiso(int nivel)
    {
        soloNivel = nivel;
        SincronizarPiso();
    }

    private int nivelSincronizado = int.MinValue;

    /// soloNivel (indice, lo usan los diagramas y las capturas de la
    /// Semana 4) y AjustesVista.cotaVisible (cota, lo que leen el visor y
    /// el mapa D/C) dicen lo mismo. Se avisa VistaCambio solo si la cota
    /// cambio de verdad: al arrancar los dos dicen "todos" y no hace falta
    /// redibujar el edificio.
    void SincronizarPiso()
    {
        if (soloNivel == nivelSincronizado) return;
        List<float> cotas = CotasDelModelo();
        if (cotas.Count == 0) return;
        soloNivel = Mathf.Clamp(soloNivel, -1, cotas.Count - 1);
        nivelSincronizado = soloNivel;

        float cota = soloNivel < 0 ? float.NaN : cotas[soloNivel];
        refrescar = true;
        inspectorSucio = true;
        if (MismaCota(cota, AjustesVista.cotaVisible)) return;
        AjustesVista.cotaVisible = cota;
        EventosVisor.AvisarVistaCambio();
    }

    static bool MismaCota(float a, float b)
    {
        if (float.IsNaN(a) || float.IsNaN(b)) return float.IsNaN(a) && float.IsNaN(b);
        return Mathf.Abs(a - b) < AjustesVista.TOLERANCIA_COTA;
    }

    /// El piso de lo seleccionado con la regla del filtro (la cota MENOR de
    /// la barra, AjustesVista.ElementoEnCotaVisible); -1 sin seleccion.
    public int NivelDeLaSeleccion()
    {
        if (visor == null || visor.Modelo == null) return -1;
        ModeloEstructural m = visor.Modelo;
        if (selTipo == EventosVisor.TIPO_ELEMENTO)
        {
            Elemento e = m.ElementoPorId(selId);
            Nodo a = e != null ? m.NodoPorId(e.n1) : null;
            Nodo b = e != null ? m.NodoPorId(e.n2) : null;
            return a != null && b != null ? NivelDeCota(Mathf.Min(a.z, b.z)) : -1;
        }
        if (selTipo == EventosVisor.TIPO_NODO)
        {
            Nodo n = m.NodoPorId(selId);
            return n != null ? NivelDeCota(n.z) : -1;
        }
        return -1;
    }

    int NivelDeCota(float cota)
    {
        if (float.IsNaN(cota)) return -1;
        List<float> cotas = CotasDelModelo();
        for (int i = 0; i < cotas.Count; i++)
            if (Mathf.Abs(cotas[i] - cota) < AjustesVista.TOLERANCIA_COTA) return i;
        return -1;
    }

    // Cotas reales del modelo, de abajo hacia arriba. Se calculan una
    // vez y se rehacen si el modelo cambia.
    private List<float> cotasDelModelo;
    private int nodosAlCalcularCotas = -1;

    /// <summary>
    /// Las cotas de piso, SACADAS DEL MODELO.
    ///
    /// Antes eran una lista fija { 0, 4, 7.5, 11, ... } que no
    /// corresponde a ningun edificio de este proyecto: el LT2 y el de
    /// Ingenieria van de -7.97 a +11.83 en pasos de 3.96. O sea que
    /// filtrar por piso no mostraba NADA, y en silencio -- el toggle
    /// respondia, la pantalla quedaba vacia y parecia que al modelo le
    /// faltaban los datos.
    ///
    /// Las cotas tienen que salir del JSON por la misma razon que todo
    /// lo demas: el visor DIBUJA, no supone.
    /// </summary>
    List<float> CotasDelModelo()
    {
        ModeloEstructural m = visor != null ? visor.Modelo : null;
        if (m == null || m.nodos == null) return new List<float>();

        if (cotasDelModelo != null && nodosAlCalcularCotas == m.nodos.Count)
            return cotasDelModelo;

        List<float> cotas = new List<float>();
        foreach (Nodo n in m.nodos)
        {
            bool esta = false;
            foreach (float z in cotas)
                if (Mathf.Abs(z - n.z) < AjustesVista.TOLERANCIA_COTA) { esta = true; break; }
            if (!esta) cotas.Add(n.z);
        }
        cotas.Sort();
        cotasDelModelo = cotas;
        nodosAlCalcularCotas = m.nodos.Count;
        return cotas;
    }

    float CotaDeNivel(int nivel)
    {
        List<float> cotas = CotasDelModelo();
        return (nivel >= 0 && nivel < cotas.Count) ? cotas[nivel] : -999f;
    }

    // ============================================================
    // APOYOS: que tipo es y como se dice
    // ============================================================
    static bool EsApoyo(Nodo n)
    {
        // Un nodo AUXILIAR no es un apoyo del edificio, aunque traiga
        // restricciones. El maestro de un diafragma las trae siempre:
        // sus GDL fuera del plano (uz, rx, ry) van restringidos porque
        // el diafragma no los toca y dejarian la matriz singular.
        // Pintarlo de verde lo hacia parecer una fundacion flotando en
        // el centro de cada piso. El maestro ya se dibuja en su propia
        // capa, la de diafragmas.
        if (n.auxiliar) return false;
        if (n.fijo) return true;
        if (n.restricciones == null) return false;
        foreach (int r in n.restricciones) if (r != 0) return true;
        return false;
    }

    /// Los 6 GDL [ux,uy,uz,rx,ry,rz]; sin lista, manda 'fijo'.
    static int[] Restricciones(Nodo n)
    {
        if (n.restricciones != null && n.restricciones.Length >= 6) return n.restricciones;
        int v = n.fijo ? 1 : 0;
        return new[] { v, v, v, v, v, v };
    }

    static bool Es(int[] r, int ux, int uy, int uz, int rx, int ry, int rz)
    {
        return r[0] == ux && r[1] == uy && r[2] == uz && r[3] == rx && r[4] == ry && r[5] == rz;
    }

    static TipoApoyo Clasificar(Nodo n)
    {
        if (!EsApoyo(n)) return TipoApoyo.Ninguno;
        int[] r = Restricciones(n);
        if (Es(r, 1, 1, 1, 1, 1, 1)) return TipoApoyo.Empotrado;
        if (Es(r, 0, 0, 1, 1, 1, 0)) return TipoApoyo.Terreno;
        return TipoApoyo.Otro;
    }

    /// Los 6 GDL en el orden [ux,uy,uz,rx,ry,rz]. Un apoyo es una lista
    /// explicita de restricciones, no "lo que parece en el dibujo".
    static string Fixity(Nodo n)
    {
        int[] r = Restricciones(n);
        return $"[{r[0]} {r[1]} {r[2]} {r[3]} {r[4]} {r[5]}]";
    }

    static readonly string[] GDL = { "ux", "uy", "uz", "rx", "ry", "rz" };

    /// Las restricciones EN PALABRAS. Lo que dice el vector, sin suponer:
    /// en un apoyo en terreno [0 0 1 1 1 0] ux, uy y rz no estan fijos en
    /// el nodo; si el nodo es esclavo de un diafragma, los amarra el piso.
    static string EnPalabras(Nodo n, int maestroDeSuDiafragma, bool esMaestro)
    {
        int[] r = Restricciones(n);
        string piso = maestroDeSuDiafragma >= 0
            ? $"los amarra el diafragma rigido del piso (maestro {maestroDeSuDiafragma}) y se mueven con la losa"
            : "";

        if (Es(r, 1, 1, 1, 1, 1, 1))
            return "Empotrado: los 6 grados de libertad restringidos (no se traslada ni gira).";
        if (Es(r, 0, 0, 1, 1, 1, 0))
        {
            if (esMaestro)
                return "Maestro de diafragma: uz, rx y ry fijos porque el diafragma rigido "
                     + "solo mueve el piso en su plano (libres, la matriz quedaria singular). "
                     + "ux, uy y rz son los 3 grados de libertad del piso.";
            return "Apoyo en terreno: uz, rx y ry restringidos (no baja ni gira fuera del plano). "
                 + "ux, uy y rz no estan fijos en el nodo"
                 + (piso != "" ? "; " + piso + "." : " y quedan libres.");
        }
        if (Es(r, 0, 0, 0, 0, 0, 0))
            return "Sin apoyo: ningun grado de libertad restringido en el nodo"
                 + (piso != "" ? "; ux, uy y rz " + piso + "." : ".");
        if (Es(r, 1, 1, 1, 0, 0, 0))
            return "Rotula: no se traslada (ux, uy, uz restringidos) pero gira libre (rx, ry, rz).";

        var fijos = new List<string>();
        var libres = new List<string>();
        for (int k = 0; k < 6; k++) (r[k] != 0 ? fijos : libres).Add(GDL[k]);
        return $"Restringidos: {string.Join(", ", fijos)}. Libres: {string.Join(", ", libres)}."
             + (piso != "" ? " Los del plano (ux, uy, rz) " + piso + "." : "");
    }

    // Cuantos apoyos de cada tipo, para la leyenda.
    private int[] conteoApoyos;
    private int nodosAlContarApoyos = -1;

    int[] ContarApoyos(ModeloEstructural m)
    {
        if (conteoApoyos != null && nodosAlContarApoyos == m.nodos.Count) return conteoApoyos;
        conteoApoyos = new int[4];
        foreach (Nodo n in m.nodos) conteoApoyos[(int)Clasificar(n)]++;
        nodosAlContarApoyos = m.nodos.Count;
        return conteoApoyos;
    }

    // ============================================================
    // INSPECTOR: el texto, armado en Update
    // ============================================================
    void ReconstruirInspector()
    {
        inspectorSucio = false;
        var nuevos = new List<BloqueTexto>();
        ModeloEstructural m = visor != null ? visor.Modelo : null;
        if (m != null)
        {
            if (selTipo == EventosVisor.TIPO_ELEMENTO)
            {
                Elemento e = m.ElementoPorId(selId);
                if (e != null) InspectorElemento(m, e, nuevos);
            }
            else if (selTipo == EventosVisor.TIPO_NODO)
            {
                Nodo n = m.NodoPorId(selId);
                if (n != null) InspectorNodo(m, n, nuevos);
            }
        }
        bloques = nuevos;   // se reemplaza la lista: la foto del Layout sigue valida
    }

    static BloqueTexto Bloque(string clave, string titulo, string cuerpo, bool abierto)
    {
        return new BloqueTexto { clave = clave, titulo = titulo, cuerpo = cuerpo, abiertoPorDefecto = abierto };
    }

    static string F(float v, string formato)
    {
        return v.ToString(formato, CultureInfo.InvariantCulture);
    }

    static string Cota(float z) { return F(z, "+0.00;-0.00;0.00"); }

    string TextoPiso(float z)
    {
        List<float> cotas = CotasDelModelo();
        for (int i = 0; i < cotas.Count; i++)
            if (Mathf.Abs(cotas[i] - z) < AjustesVista.TOLERANCIA_COTA)
                return $"cota {Cota(z)} m, nivel {i + 1} de {cotas.Count} contando desde abajo";
        return $"cota {Cota(z)} m (no es una cota de piso del modelo)";
    }

    /// Arma lo que contesta la defensa sobre una barra. Las lineas de la
    /// identificacion son las de antes; lo de la Semana 4 es el texto de
    /// VisorSemana04.DescribirElemento tal cual, partido en sus secciones.
    void InspectorElemento(ModeloEstructural m, Elemento e, List<BloqueTexto> salida)
    {
        StringBuilder sb = new StringBuilder();
        sb.AppendLine($"tipo      {e.tipo}");
        sb.AppendLine($"seccion   {e.seccion}");
        sb.AppendLine($"nodos     {e.n1} -> {e.n2}");

        Nodo a = m.NodoPorId(e.n1);
        Nodo b = m.NodoPorId(e.n2);
        var enlaces = new List<Enlace>();
        if (a != null && b != null)
        {
            float L = Mathf.Sqrt((b.x - a.x) * (b.x - a.x)
                               + (b.y - a.y) * (b.y - a.y)
                               + (b.z - a.z) * (b.z - a.z));
            sb.AppendLine($"largo     {F(L, "0.000")} m");
            sb.AppendLine(LineaNodo(a));
            sb.AppendLine(LineaNodo(b));
            sb.AppendLine("piso      " + TextoPiso(Mathf.Min(a.z, b.z)) + " (su nodo mas bajo)");
            enlaces.Add(new Enlace { tipo = EventosVisor.TIPO_NODO, id = a.id, texto = "Nodo " + a.id });
            enlaces.Add(new Enlace { tipo = EventosVisor.TIPO_NODO, id = b.id, texto = "Nodo " + b.id });
        }
        BloqueTexto id = Bloque("qa.elem.identificacion", "Identificacion y ubicacion", sb.ToString(), true);
        id.enlaces = enlaces;
        salida.Add(id);

        if (e.localX != null && e.localX.Length == 3)
        {
            sb.Length = 0;
            sb.AppendLine($"local x   {Vec(e.localX)}");
            sb.AppendLine($"local y   {Vec(e.localY)}");
            sb.AppendLine($"local z   {Vec(e.localZ)}");
            sb.Append("(rojo x, verde y, azul z en la capa 'Ejes locales')");
            BloqueTexto ej = Bloque("qa.elem.ejes", "Ejes locales (OpenSees)", sb.ToString(), false);
            ej.mono = true;
            salida.Add(ej);
        }

        BloqueTexto carga = Bloque("qa.elem.tributaria", "Que lo carga (losa, peso propio y total en G)", TextoTributaria(m, e), true);
        carga.nota = NotaQueLoCarga(m, e); salida.Add(carga);   // la nota, al final de la clase

        // Semana 4: material, restricciones, esfuerzos del caso activo,
        // demanda-capacidad y la cadena de trazabilidad.
        if (s4 != null && (s4.Anexo != null || !string.IsNullOrEmpty(s4.Aviso)))
            PartirTextoSemana04(s4.DescribirElemento(e.id), salida);
    }

    string LineaNodo(Nodo n)
    {
        string apoyo = "";
        switch (Clasificar(n))
        {
            case TipoApoyo.Empotrado: apoyo = "   APOYO " + Fixity(n) + " empotrado"; break;
            case TipoApoyo.Terreno: apoyo = "   APOYO " + Fixity(n) + " en terreno"; break;
            case TipoApoyo.Otro: apoyo = "   APOYO " + Fixity(n); break;
        }
        return $"nodo {n.id}   ({F(n.x, "0.00")}, {F(n.y, "0.00")}, {F(n.z, "0.00")})" + apoyo;
    }

    /// "Que lo carga", en el orden en que se arma la carga de la barra: area
    /// tributaria, q y w de la losa; peso propio; = la w total que recibe
    /// OpenSees en G (la del diagrama wz); y la Q del modelo. Todos los
    /// numeros son del JSON (w_peso_propio y w_total_G los escribe Python,
    /// edificios/lt2/exportar_unity.py): aca no se suma ni se multiplica.
    string TextoTributaria(ModeloEstructural m, Elemento e)
    {
        List<AreaTributaria> entradas = m.TributariasDe(e.id);
        float total = m.AreaTributariaTotal(e.id);
        StringBuilder sb = new StringBuilder();
        if (entradas.Count == 0 && total <= 0f)
            sb.AppendLine("A_trib    no recibe losa");
        else
        {
            int panos = 0;
            foreach (AreaTributaria t in entradas) panos += Mathf.Max(1, t.n_poligonos);
            sb.AppendLine($"A_trib    {F(total, "0.000")} m2   ({entradas.Count} entrada(s), {panos} pano(s))");
        }
        for (int i = 0; i < entradas.Count; i++)
        {
            AreaTributaria t = entradas[i];
            if (entradas.Count > 1)
                sb.AppendLine($"-- entrada {i + 1}: A {F(t.area, "0.000")} m2, cota {Cota(t.z)}");
            if (t.qG == 0f && t.carga_total == 0f) continue;   // sin q ni w: lo dice la nota
            sb.AppendLine($"q_G       {F(t.qG, "0.00")} kN/m2 de losa  ->  {F(t.carga_total, "0.00")} kN");
            if (e.EsMuro)
            {
                sb.AppendLine($"          va PUNTUAL en su nodo {e.n2} (el muro es una columna ancha);");
                sb.AppendLine("          su peso propio va nodal, mitad en cada extremo: no hay w repartida");
                continue;
            }
            sb.AppendLine($"w_losa    {F(t.w, "0.000")} kN/m sobre la barra (luz {F(t.luz, "0.00")} m)");
            if (t.w_total_G <= 0f) continue;                   // el edificio no lo exporta: lo dice la nota
            sb.AppendLine($"w_pp      {F(t.w_peso_propio, "0.000")} kN/m de peso propio"
                          + (e.EsBrazo ? " (el brazo no lleva: va en el muro)" : " de la barra"));
            sb.AppendLine($"= w_G     {F(t.w_total_G, "0.000")} kN/m, la w total que recibe OpenSees en G");
        }
        CargaDistribuida g = CargaRepartidaDe(m, "G", e.id), q = CargaRepartidaDe(m, "Q", e.id);
        if (g != null)
            sb.AppendLine($"wz en G   {F(g.wz, "0.000")} kN/m (casos_de_carga; diagrama wz)");
        if (q != null)
            sb.AppendLine($"Q         wz {F(q.wz, "0.000")} kN/m (Q del modelo, la de /analizar)");
        return sb.ToString().TrimEnd();
    }

    /// Parte el texto de VisorSemana04.DescribirElemento en sus secciones
    /// "--- titulo ---". El texto NO se toca (va a registro.txt y se cruza
    /// con semana04/trazabilidad.py): solo se reparte en plegables.
    void PartirTextoSemana04(string texto, List<BloqueTexto> salida)
    {
        string[] lineas = texto.Replace("\r", "").Split('\n');
        string titulo = "Semana 4";
        var cuerpo = new StringBuilder();

        foreach (string linea in lineas)
        {
            string l = linea.Trim();
            bool encabezado = l.Length > 6 && l.StartsWith("---") && l.EndsWith("---");
            bool banda = l.StartsWith("=====");
            if (banda) continue;   // "=========== SEMANA 4 ===========": ya lo dice cada titulo
            if (encabezado)
            {
                AgregarSeccionS4(titulo, cuerpo.ToString(), salida);
                cuerpo.Length = 0;
                titulo = l.Trim('-', ' ');
                continue;
            }
            if (linea.Length > 0) cuerpo.AppendLine(linea);
        }
        AgregarSeccionS4(titulo, cuerpo.ToString(), salida);
    }

    void AgregarSeccionS4(string titulo, string cuerpo, List<BloqueTexto> salida)
    {
        cuerpo = cuerpo.TrimEnd();
        if (cuerpo.Length == 0) return;

        // La clave no puede llevar el caso ("esfuerzos, caso activo S3"):
        // si no, cambiar de caso reabriria o cerraria la seccion.
        string corto = titulo;
        int corte = corto.IndexOfAny(new[] { ',', '[' });
        if (corte > 0) corto = corto.Substring(0, corte);
        corto = corto.Trim().ToLowerInvariant();

        // Abiertas: lo que se pregunta en la defensa. Cerradas: lo que se
        // consulta (material, seccion, trazabilidad).
        bool abierto = corto.StartsWith("condiciones") || corto.StartsWith("esfuerzos")
                       || corto.StartsWith("demanda") || corto == "semana 4";
        string visible = titulo.Length > 0
            ? char.ToUpperInvariant(titulo[0]) + titulo.Substring(1) : titulo;
        BloqueTexto b = Bloque("qa.s4." + corto, visible, cuerpo, abierto);
        // La tabla de esfuerzos esta alineada con espacios: fuente de ancho fijo.
        b.mono = corto.StartsWith("esfuerzos") || corto.StartsWith("condiciones");
        b.aviso = corto == "semana 4" && cuerpo.Contains("AVISO");
        salida.Add(b);
    }

    /// Lo que se sabe de un nodo: donde esta, como esta apoyado, a que
    /// diafragma pertenece, cuanto se mueve en el caso activo, que lo
    /// carga y que barras llegan.
    void InspectorNodo(ModeloEstructural m, Nodo n, List<BloqueTexto> salida)
    {
        StringBuilder sb = new StringBuilder();
        sb.AppendLine($"OpenSees  (x, y, z) = ({F(n.x, "0.000")}, {F(n.y, "0.000")}, {F(n.z, "0.000")}) m");
        sb.AppendLine("          " + TextoPiso(n.z));
        Vector3 u = Ejes.PosicionDe(n);
        sb.AppendLine($"Unity     ({F(u.x, "0.00")}, {F(u.y, "0.00")}, {F(u.z, "0.00")})  (Y vertical)");
        if (n.auxiliar)
            sb.AppendLine("auxiliar: no es un nudo del marco (intermedio de viga o maestro de diafragma)");
        salida.Add(Bloque("qa.nodo.ubicacion", "Donde esta", sb.ToString().TrimEnd(), true));

        // Diafragma: maestro o esclavo.
        int maestroDeSuDiafragma = -1;
        Diafragma propio = null;
        if (m.diafragmas != null)
            foreach (Diafragma d in m.diafragmas)
            {
                if (d.nodo_maestro == n.id) propio = d;
                if (d.nodos != null && System.Array.IndexOf(d.nodos, n.id) >= 0)
                    maestroDeSuDiafragma = d.nodo_maestro;
            }

        sb.Length = 0;
        sb.AppendLine("[ux uy uz rx ry rz] = " + Fixity(n) + (n.fijo ? "   (fijo)" : ""));
        sb.Append(EnPalabras(n, maestroDeSuDiafragma, propio != null));
        BloqueTexto apoyo = Bloque("qa.nodo.apoyo", "Como esta apoyado", sb.ToString(), true);
        salida.Add(apoyo);

        sb.Length = 0;
        if (propio != null)
            sb.Append($"Maestro del diafragma de la cota {Cota(n.z)}: "
                      + $"{(propio.nodos != null ? propio.nodos.Length : 0)} nodos esclavos.");
        else if (maestroDeSuDiafragma >= 0)
            sb.Append($"Esclavo del diafragma rigido del maestro {maestroDeSuDiafragma}: "
                      + "su ux, uy y rz siguen al piso (ux_i = ux_m - rz*(y_i - y_m)).");
        else
            sb.Append("Fuera de todo diafragma: se mueve solo con sus barras.");
        BloqueTexto diaf = Bloque("qa.nodo.diafragma", "Diafragma", sb.ToString(), true);
        if (maestroDeSuDiafragma >= 0)
            diaf.enlaces = new List<Enlace> {
                new Enlace { tipo = EventosVisor.TIPO_NODO, id = maestroDeSuDiafragma,
                             texto = "Maestro " + maestroDeSuDiafragma } };
        salida.Add(diaf);

        // Desplazamiento en el caso activo, LEIDO del anexo.
        sb.Length = 0;
        string tituloDesp = "Desplazamiento";
        CasoS4 caso = s4 != null ? s4.CasoActivo() : null;
        if (caso == null)
        {
            sb.Append(s4 != null && !string.IsNullOrEmpty(s4.Aviso)
                ? "Sin anexo de la Semana 4: " + s4.Aviso
                : "Sin anexo de la Semana 4 (semana04.json).");
        }
        else
        {
            tituloDesp = "Desplazamiento, caso activo " + caso.nombre;
            DespNodo d = null;
            if (caso.desplazamientos != null)
                foreach (DespNodo x in caso.desplazamientos)
                    if (x.id == n.id) { d = x; break; }
            if (d == null)
            {
                sb.Append($"El caso {caso.nombre} no trae desplazamientos de este nodo.");
            }
            else
            {
                sb.AppendLine(caso.descripcion);
                sb.AppendLine($"ux {F(d.ux * 1000f, "0.000"),9} mm   rx {F(d.rx, "0.000e+00")} rad");
                sb.AppendLine($"uy {F(d.uy * 1000f, "0.000"),9} mm   ry {F(d.ry, "0.000e+00")} rad");
                sb.Append($"uz {F(d.uz * 1000f, "0.000"),9} mm   rz {F(d.rz, "0.000e+00")} rad");
            }
            if (!string.IsNullOrEmpty(avisoEdicion))
                sb.Append("\nOJO: el modelo se edito; estos son los del modelo original.");
        }
        BloqueTexto desp = Bloque("qa.nodo.desplazamiento", tituloDesp, sb.ToString(), true);
        desp.mono = true;
        salida.Add(desp);

        // Cargas nodales del JSON del modelo en este nodo.
        sb.Length = 0;
        if (m.casos_de_carga != null)
            foreach (CasoDeCarga c in m.casos_de_carga)
            {
                if (c.cargas_nodales == null) continue;
                foreach (CargaNodal q in c.cargas_nodales)
                {
                    if (q.nodo != n.id) continue;
                    sb.AppendLine($"{c.nombre,-3} F ({F(q.fx, "0.00")}, {F(q.fy, "0.00")}, {F(q.fz, "0.00")}) kN");
                    if (q.mx != 0f || q.my != 0f || q.mz != 0f)
                        sb.AppendLine($"    M ({F(q.mx, "0.00")}, {F(q.my, "0.00")}, {F(q.mz, "0.00")}) kN*m");
                }
            }
        BloqueTexto cargas = Bloque("qa.nodo.cargas", "Cargas nodales (ejes globales)",
            sb.Length > 0 ? sb.ToString().TrimEnd() : "Ninguna en los casos del modelo.", true);
        cargas.mono = sb.Length > 0;
        salida.Add(cargas);

        // Barras que llegan.
        var llegan = new List<Enlace>();
        if (m.elementos != null)
            foreach (Elemento e in m.elementos)
                if (e.n1 == n.id || e.n2 == n.id)
                    llegan.Add(new Enlace { tipo = EventosVisor.TIPO_ELEMENTO, id = e.id,
                                            texto = $"{e.id}  {e.tipo}" });
        BloqueTexto barras = Bloque("qa.nodo.barras", $"Barras que llegan ({llegan.Count})",
            llegan.Count == 0 ? "Ninguna." : "Click para inspeccionarla:", true);
        barras.enlaces = llegan;
        salida.Add(barras);
    }

    static string Vec(float[] v)
    {
        if (v == null || v.Length < 3) return "-";
        return $"({F(v[0], "+0.000;-0.000")}, {F(v[1], "+0.000;-0.000")}, {F(v[2], "+0.000;-0.000")})";
    }

    // ============================================================
    // DIBUJO DE LAS CAPAS
    // ============================================================
    void Redibujar()
    {
        foreach (GameObject g in creados) if (g != null) Destroy(g);
        creados.Clear();

        ModeloEstructural m = visor.Modelo;
        if (m == null) return;

        if (verApoyos) DibujarApoyos(m);
        if (verDiafragmas) DibujarDiafragmas(m);
        if (verEjesLocales) DibujarEjesLocales(m);
        if (verAreasTributarias) DibujarTributarias(m);
        if (verIDs) DibujarIDs(m);
        Resaltar(m);
        // Los diagramas de Semana 4 respetan el filtro de piso: solo se
        // rehacen si algo de lo que los define cambio.
        if (s4 != null) s4.Refrescar();
    }

    /// Una barra es del piso visible si su nodo MAS BAJO esta en la cota
    /// (la losa y lo que nace de ella). La misma regla que el visor, los
    /// diagramas y el mapa D/C (AjustesVista.ElementoEnCotaVisible).
    bool BarraVisible(Nodo a, Nodo b)
    {
        return NivelVisible(Mathf.Min(a.z, b.z));
    }

    // --- Apoyos ---
    // Un simbolo por TIPO: el empotramiento y el apoyo en terreno eran el
    // mismo cubo verde, y [0 0 1 1 1 0] no es un empotramiento.
    /// El mayor b o h (m, del JSON) de las barras con perfil que llegan al
    /// nodo, sin muros ni brazos (el muro ya se ve como placa). Dibujo: fija
    /// el tamano del simbolo del apoyo.
    static float SeccionMayorEnNodo(ModeloEstructural m, int idNodo)
    {
        float mayor = 0f;
        if (m.elementos == null) return mayor;
        foreach (Elemento e in m.elementos)
        {
            if (e == null || (e.n1 != idNodo && e.n2 != idNodo) || e.EsMuro || e.EsBrazo) continue;
            Seccion s = m.SeccionPorNombre(e.seccion);
            if (s != null && s.TienePerfil) mayor = Mathf.Max(mayor, Mathf.Max(s.b, s.h));
        }
        return mayor;
    }

    void DibujarApoyos(ModeloEstructural m)
    {
        foreach (Nodo n in m.nodos)
        {
            TipoApoyo tipo = Clasificar(n);
            if (tipo == TipoApoyo.Ninguno) continue;
            if (!NivelVisible(n.z)) continue;

            GameObject c = GameObject.CreatePrimitive(PrimitiveType.Cube);
            c.name = $"Apoyo_{n.id}";
            Vector3 p = visor.PosicionActual(n);
            switch (tipo)
            {
                case TipoApoyo.Empotrado:
                    // Mas grande que lo que nace del nodo (la columna de 0.70 m
                    // con perfiles, o la jaula de enfierradura de la Semana 3):
                    // un cubo de 0.45 m quedaba adentro y no se veia el apoyo.
                    c.transform.position = p;
                    c.transform.localScale = Vector3.one * Mathf.Max(tamanoApoyo, 1.3f * SeccionMayorEnNodo(m, n.id));
                    Pintar(c, colorApoyo);
                    break;
                case TipoApoyo.Terreno:
                    // Una placa bajo el nodo: apoya, no empotra.
                    float alto = tamanoApoyo * 0.25f;
                    c.transform.position = p - Vector3.up * alto * 0.5f;
                    c.transform.localScale = new Vector3(tamanoApoyo * 1.8f, alto, tamanoApoyo * 1.8f);
                    Pintar(c, colorApoyoTerreno);
                    break;
                default:
                    // Un rombo: cualquier otra combinacion (rotula, rodillo).
                    c.transform.position = p;
                    c.transform.rotation = Quaternion.Euler(45f, 0f, 45f);
                    c.transform.localScale = Vector3.one * tamanoApoyo * 0.8f;
                    Pintar(c, colorApoyoOtro);
                    break;
            }
            // Conserva el collider: un click en el simbolo selecciona el nodo.
            c.AddComponent<DatoNodo>().idNodo = n.id;
            creados.Add(c);
        }
    }

    // --- Diafragmas ---
    // Se dibuja el nodo maestro y un radio a cada esclavo: se ve de
    // inmediato que piso esta ligado a que maestro, y si algun nodo
    // quedo fuera del diafragma.
    void DibujarDiafragmas(ModeloEstructural m)
    {
        if (m.diafragmas == null) return;
        foreach (Diafragma d in m.diafragmas)
        {
            Nodo maestro = m.NodoPorId(d.nodo_maestro);
            if (maestro == null) continue;
            if (!NivelVisible(maestro.z)) continue;

            Vector3 pm = visor.PosicionActual(maestro);
            GameObject e = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            e.name = $"Maestro_{d.nodo_maestro}";
            e.transform.position = pm;
            e.transform.localScale = Vector3.one * tamanoApoyo * 1.6f;
            Pintar(e, colorDiafragma);
            e.AddComponent<DatoNodo>().idNodo = d.nodo_maestro;
            creados.Add(e);

            if (d.nodos == null) continue;
            foreach (int idEsclavo in d.nodos)
            {
                Nodo s = m.NodoPorId(idEsclavo);
                if (s == null) continue;
                creados.Add(Linea(pm, visor.PosicionActual(s),
                                  grosorLinea * 0.5f, colorDiafragma,
                                  $"Diaf_{d.nodo_maestro}_{idEsclavo}"));
            }
        }
    }

    // --- Ejes locales ---
    void DibujarEjesLocales(ModeloEstructural m)
    {
        foreach (Elemento e in m.elementos)
        {
            if (e.localX == null || e.localX.Length < 3) continue;
            Nodo a = m.NodoPorId(e.n1);
            Nodo b = m.NodoPorId(e.n2);
            if (a == null || b == null) continue;
            if (!BarraVisible(a, b)) continue;

            // Centro de la barra, en coordenadas OpenSees -> Unity.
            Vector3 c = (visor.PosicionActual(a) + visor.PosicionActual(b)) * 0.5f;
            DibujarFlecha(c, e.localX, colorEjeX, $"E{e.id}_x");
            DibujarFlecha(c, e.localY, colorEjeY, $"E{e.id}_y");
            DibujarFlecha(c, e.localZ, colorEjeZ, $"E{e.id}_z");
        }
    }

    void DibujarFlecha(Vector3 origenUnity, float[] dirOpenSees,
                       Color color, string nombre)
    {
        if (dirOpenSees == null || dirOpenSees.Length < 3) return;
        // El vector viene en ejes OpenSees: hay que pasarlo por el
        // MISMO swap que las posiciones, si no las flechas apuntan mal.
        Vector3 d = Ejes.AUnity(dirOpenSees[0], dirOpenSees[1], dirOpenSees[2]);
        creados.Add(Linea(origenUnity, origenUnity + d * largoEje,
                          grosorLinea, color, nombre));
    }

    // --- Areas tributarias ---
    void DibujarTributarias(ModeloEstructural m)
    {
        if (m.areas_tributarias == null) return;
        foreach (AreaTributaria t in m.areas_tributarias)
        {
            if (!NivelVisible(t.z)) continue;
            if (t.vertices == null || t.vertices.Length < 3) continue;
            // Si el filtro esta en "todos", solo se dibujan las de la
            // barra seleccionada (TODAS sus entradas): 656 poligonos a la
            // vez no se leen.
            if (soloNivel < 0 &&
                (selTipo != EventosVisor.TIPO_ELEMENTO || selId != t.elemento))
                continue;

            DibujarPoligonos(t);
        }
    }

    void DibujarPoligonos(AreaTributaria t)
    {
        // Cada poligono se cierra sobre SI MISMO. La particion viene de
        // AreaTributaria.Poligonos(), que usa los tamanos reales: antes
        // se dividia vertices.Length entre n_poligonos y, cuando una
        // viga tomaba un trapecio (4 vertices) de un pano y un triangulo
        // (3) del otro, la division entera 7/2 = 3 mezclaba vertices de
        // ambos y aparecian lineas cruzadas inexistentes.
        foreach (int[] rango in t.Poligonos())
        {
            int inicio = rango[0], cuantos = rango[1];
            for (int k = 0; k < cuantos; k++)
            {
                VerticePlanta v1 = t.vertices[inicio + k];
                VerticePlanta v2 = t.vertices[inicio + (k + 1) % cuantos];
                // El poligono esta en PLANTA (x, y de OpenSees) a la
                // cota del piso.
                Vector3 a = Ejes.AUnity(v1.x, v1.y, t.z);
                Vector3 b = Ejes.AUnity(v2.x, v2.y, t.z);
                creados.Add(Linea(a, b, grosorLinea * 0.8f, colorTributaria,
                                  $"Trib_{t.elemento}"));
            }
        }
    }

    // --- IDs ---
    void DibujarIDs(ModeloEstructural m)
    {
        Vector3 cam = (camara != null) ? camara.transform.position : Vector3.zero;

        // Solo los mas cercanos: dibujar miles de TextMesh mata el frame.
        List<KeyValuePair<float, Elemento>> cerca =
            new List<KeyValuePair<float, Elemento>>();

        foreach (Elemento e in m.elementos)
        {
            Nodo a = m.NodoPorId(e.n1);
            Nodo b = m.NodoPorId(e.n2);
            if (a == null || b == null) continue;
            if (!BarraVisible(a, b)) continue;
            Vector3 c = (visor.PosicionActual(a) + visor.PosicionActual(b)) * 0.5f;
            cerca.Add(new KeyValuePair<float, Elemento>(
                (c - cam).sqrMagnitude, e));
        }

        cerca.Sort((p, q) => p.Key.CompareTo(q.Key));

        int cuantos = Mathf.Min(maxIDs, cerca.Count);
        for (int i = 0; i < cuantos; i++)
        {
            Elemento e = cerca[i].Value;
            Nodo a = m.NodoPorId(e.n1);
            Nodo b = m.NodoPorId(e.n2);
            Vector3 c = (visor.PosicionActual(a) + visor.PosicionActual(b)) * 0.5f;
            creados.Add(Etiqueta(c, e.id.ToString(CultureInfo.InvariantCulture), Color.white));
        }
    }

    GameObject Etiqueta(Vector3 pos, string texto, Color color)
    {
        GameObject go = new GameObject("ID_" + texto);
        go.transform.position = pos;
        TextMesh tm = go.AddComponent<TextMesh>();
        tm.text = texto;
        tm.characterSize = 0.16f;
        tm.fontSize = 60;
        tm.color = color;
        tm.anchor = TextAnchor.MiddleCenter;
        go.AddComponent<MirarCamara>();
        return go;
    }

    // --- Resaltado de la seleccion ---
    // Objetos superpuestos en cian, sin tocar el sharedMaterial de la
    // estructura (ese lo manejan el ambiente y el mapa D/C, CONTRATO §8).
    // Siguen la deformada: se dibujan en PosicionActual.
    void Resaltar(ModeloEstructural m)
    {
        if (selTipo == EventosVisor.TIPO_ELEMENTO)
        {
            Elemento e = m.ElementoPorId(selId);
            Nodo a = e != null ? m.NodoPorId(e.n1) : null;
            Nodo b = e != null ? m.NodoPorId(e.n2) : null;
            if (a == null || b == null) return;
            // Sin perfiles la barra es un cilindro de 5 cm, y lo que la envuelve
            // (la jaula de enfierradura de la Semana 3) tapaba la linea cian. La
            // linea toma el ancho de la seccion (dibujo, max(b, h) del JSON). Con
            // perfiles no hace falta: la caja lleva sus aristas cian.
            float grosorSel = grosorLinea * 3f;
            Seccion sec = m.SeccionPorNombre(e.seccion);
            if (!visor.DibujaPerfiles && !e.EsMuro && !e.EsBrazo && sec != null && sec.TienePerfil)
                grosorSel = Mathf.Max(grosorSel, Mathf.Max(sec.b, sec.h) * 1.08f);
            creados.Add(Linea(visor.PosicionActual(a), visor.PosicionActual(b),
                              grosorSel, colorSeleccion, "Seleccion"));
            // En un muro o un perfil la linea del eje queda DENTRO de la
            // placa: se marcan tambien sus aristas.
            GameObject go = visor.ObjetoDeElemento(e.id);
            if (go != null) ResaltarAristas(go);
        }
        else if (selTipo == EventosVisor.TIPO_NODO)
        {
            Nodo n = m.NodoPorId(selId);
            if (n == null) return;
            Vector3 p = visor.PosicionActual(n);
            GameObject esfera = GameObject.CreatePrimitive(PrimitiveType.Sphere);
            esfera.name = "Seleccion";
            Collider col = esfera.GetComponent<Collider>();
            if (col != null) Destroy(col);
            esfera.transform.position = p;
            esfera.transform.localScale = Vector3.one * Mathf.Max(visor.radioNodo * 3f, tamanoApoyo * 0.9f);
            Pintar(esfera, colorSeleccion);
            creados.Add(esfera);
            // Una cruz de 3 m: se encuentra aunque este lejos o tapado.
            float l = 1.5f;
            creados.Add(Linea(p - Vector3.right * l, p + Vector3.right * l, grosorLinea * 1.5f, colorSeleccion, "Seleccion_x"));
            creados.Add(Linea(p - Vector3.up * l, p + Vector3.up * l, grosorLinea * 1.5f, colorSeleccion, "Seleccion_y"));
            creados.Add(Linea(p - Vector3.forward * l, p + Vector3.forward * l, grosorLinea * 1.5f, colorSeleccion, "Seleccion_z"));
        }
    }

    void ResaltarAristas(GameObject go)
    {
        MeshFilter mf = go.GetComponent<MeshFilter>();
        if (mf == null || mf.sharedMesh == null) return;
        Bounds lb = mf.sharedMesh.bounds;
        Vector3 tam = Vector3.Scale(lb.size, go.transform.lossyScale);
        float menor = Mathf.Min(Mathf.Abs(tam.x), Mathf.Min(Mathf.Abs(tam.y), Mathf.Abs(tam.z)));
        if (menor < 0.12f) return;   // barra delgada: basta la linea del eje

        // Las 8 esquinas de la caja de la malla, un poco afuera para que
        // la arista no quede dentro de la cara.
        Vector3[] esquina = new Vector3[8];
        for (int k = 0; k < 8; k++)
        {
            Vector3 signo = new Vector3((k & 4) != 0 ? 1f : -1f, (k & 2) != 0 ? 1f : -1f, (k & 1) != 0 ? 1f : -1f);
            esquina[k] = go.transform.TransformPoint(lb.center + Vector3.Scale(lb.extents * 1.04f, signo));
        }
        // Dos esquinas forman arista si difieren en un solo bit.
        for (int k = 0; k < 8; k++)
            for (int bit = 1; bit <= 4; bit <<= 1)
                if ((k & bit) == 0)
                    creados.Add(Linea(esquina[k], esquina[k | bit], grosorLinea * 1.5f,
                                      colorSeleccion, "Seleccion_arista"));
    }

    // ============================================================
    // PRIMITIVAS
    // ============================================================
    GameObject Linea(Vector3 desde, Vector3 hasta, float grosor,
                     Color color, string nombre)
    {
        GameObject cil = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        cil.name = nombre;
        Collider col = cil.GetComponent<Collider>();
        if (col != null) Destroy(col);   // no debe estorbar al raycast

        Vector3 d = hasta - desde;
        float largo = d.magnitude;
        cil.transform.position = (desde + hasta) * 0.5f;
        cil.transform.localScale = new Vector3(grosor, largo * 0.5f, grosor);
        if (largo > 1e-6f) cil.transform.up = d.normalized;
        Pintar(cil, color);
        return cil;
    }

    private readonly Dictionary<Color, Material> cache =
        new Dictionary<Color, Material>();

    void Pintar(GameObject go, Color color)
    {
        Material mat;
        if (!cache.TryGetValue(color, out mat))
        {
            mat = new Material(VisorEstructura.ShaderCompatible());
            mat.color = color;
            if (mat.HasProperty("_BaseColor")) mat.SetColor("_BaseColor", color);
            cache[color] = mat;
        }
        Renderer r = go.GetComponent<Renderer>();
        if (r == null) return;
        r.sharedMaterial = mat;
        // Las capas QA son marcas, no objetos: no proyectan sombra sobre
        // la estructura ni la reciben (en la vista realista ensuciaban).
        r.shadowCastingMode = ShadowCastingMode.Off;
        r.receiveShadows = false;
    }

    // ============================================================
    // DEFORMADA: UNA SOLA FUENTE A LA VEZ
    // ============================================================
    /// Cambia de que viene la deformada. Es el unico sitio que la pone o
    /// la quita: VisorSemana03 solo limpia lo que puso el mismo, asi que
    /// elegir "Cargas G" no se apaga solo en el frame siguiente.
    void AplicarModo(ModoDeformada m)
    {
        modo = m;
        bool sismo = (m == ModoDeformada.SismoEX || m == ModoDeformada.SismoEY);
        bool casoS4 = (m == ModoDeformada.CasoActivo);

        // Semana 4 suelta la suya antes de que otra fuente ponga otra: solo
        // limpia lo que puso ella, asi que no apaga las de los demas.
        if (s4 != null && !casoS4) s4.QuitarDeformada();

        // PRIMERO Semana 3, y despues la de gravedad. Al reves, su
        // redibujo -- que limpia la deformada cuando el modo ya no es
        // sismo -- borraria la que se acaba de poner aca.
        if (s3 != null)
        {
            s3.aplicarDeformada = sismo;
            if (sismo)
            {
                s3.casoDeformada = (m == ModoDeformada.SismoEX) ? "EX" : "EY";
                // Las flechas que se muestran son las que producen ESTA
                // deformada; si no, se veria empujar en X una estructura
                // deformada en Y.
                s3.casoCarga = s3.casoDeformada;
            }
            s3.Redibujar();     // aplica el sismo, o suelta lo que tenia
        }

        if (m == ModoDeformada.Gravedad)
        {
            visor.UsarDeformadaPrecalculada();
            visor.mostrarDeformada = true;
            visor.Redibujar();
        }
        else if (m == ModoDeformada.Sin)
        {
            visor.LimpiarDeformada();
            visor.Redibujar();
        }
        else if (casoS4 && s4 != null)
        {
            // Caso base o combinacion: los desplazamientos vienen en el
            // anexo de Semana 4, ya combinados en Python.
            s4.AplicarDeformadaDelCaso();
        }
        // El caso sismico ya lo aplico VisorSemana03 mas arriba.

        refrescar = true;
    }

    // ============================================================
    // EXCEL DE RESULTADOS
    // ============================================================
    /// El edificio de los resultados: el del anexo de Semana 4 (el que se
    /// exporto a Excel con el mismo exportador); si no hay anexo, el del
    /// modelo.
    string EdificioActivo()
    {
        if (s4 != null && s4.Anexo != null && s4.Anexo.info != null
            && !string.IsNullOrEmpty(s4.Anexo.info.edificio))
            return s4.Anexo.info.edificio;
        if (visor != null && visor.Modelo != null && visor.Modelo.info != null
            && !string.IsNullOrEmpty(visor.Modelo.info.edificio))
            return visor.Modelo.info.edificio;
        return "";
    }

    /// Abre StreamingAssets/resultados.xlsx (en el editor, si falta, el
    /// versionado data/excel/<ed>_resultados.xlsx). Si no hay, dice con que
    /// comando se genera: el visor no inventa un Excel.
    void AbrirExcelResultados()
    {
        string ed = EdificioActivo();
        string ruta = LectorStreaming.RutaExcelResultados(ed);
        if (ruta == null && Application.isEditor && !string.IsNullOrEmpty(ed))
            ruta = BuscarExcelSubiendo(ed);

        if (ruta == null)
        {
            string edTexto = string.IsNullOrEmpty(ed) ? "<edificio>" : ed;
            mensajeExcelEsError = true;
            if (Application.isMobilePlatform || Application.platform == RuntimePlatform.WebGLPlayer)
                mensajeExcel = "En esta plataforma la app no abre archivos: el libro esta en "
                             + $"data/excel/{edTexto}_resultados.xlsx del repositorio.";
            else
                mensajeExcel = "No hay Excel de resultados ("
                             + Path.Combine(Application.streamingAssetsPath, LectorStreaming.EXCEL_RESULTADOS)
                             + "). Generalo con:\n"
                             + $"  python semana05/exportar_excel.py {edTexto}\n"
                             + "y copialo a la app con:\n"
                             + $"  python comun/lanzar_unity.py sincronizar {edTexto}";
            return;
        }

        string error;
        if (LectorStreaming.AbrirArchivo(ruta, out error))
        {
            mensajeExcelEsError = false;
            mensajeExcel = "Abriendo " + ruta;
        }
        else
        {
            mensajeExcelEsError = true;
            mensajeExcel = error;
        }
    }

    /// Respaldo del editor: sube desde Assets hasta encontrar
    /// data/excel/<ed>_resultados.xlsx, en vez de contar carpetas (la misma
    /// regla que comun/rutas.py). LectorStreaming supone que el proyecto de
    /// Unity esta dos niveles bajo la raiz del repo.
    static string BuscarExcelSubiendo(string edificio)
    {
        try
        {
            DirectoryInfo dir = new DirectoryInfo(Application.dataPath);
            for (int i = 0; i < 8 && dir != null; i++, dir = dir.Parent)
            {
                string ruta = Path.Combine(dir.FullName, "data", "excel", edificio + "_resultados.xlsx");
                if (File.Exists(ruta)) return ruta;
            }
        }
        catch (System.Exception) { }
        return null;
    }

    // ============================================================
    // PESTANAS INCRUSTABLES
    // ============================================================
    /// Todo MonoBehaviour que implemente IPanelIncrustable (el editor, la
    /// carga movil, ...) pasa a ser una pestana y deja de dibujar su propio
    /// panel. Se busca al arrancar y cada vez que se cambia de pestana,
    /// asi uno que aparezca despues tambien entra.
    void BuscarIncrustables()
    {
        incrustables.Clear();
        foreach (MonoBehaviour mb in FindObjectsByType<MonoBehaviour>())
        {
            IPanelIncrustable p = mb as IPanelIncrustable;
            if (p == null || ReferenceEquals(mb, this)) continue;
            try { p.PanelPropio = false; }
            catch (System.Exception ex) { Debug.LogWarning("VisorQA: " + mb.GetType().Name + ".PanelPropio: " + ex.Message); }
            incrustables.Add(p);
        }
        incrustables.Sort((x, y) =>
        {
            int ox = OrdenIncrustable(TituloDe(x)), oy = OrdenIncrustable(TituloDe(y));
            return ox != oy ? ox.CompareTo(oy) : string.CompareOrdinal(TituloDe(x), TituloDe(y));
        });

        var titulos = new List<string> { PESTANA_VISTA, PESTANA_CAPAS, PESTANA_CASO, PESTANA_ELEMENTO };
        foreach (string esperada in PESTANAS_ESPERADAS) titulos.Add(esperada);
        foreach (IPanelIncrustable p in incrustables)
        {
            string t = TituloDe(p);
            if (!titulos.Contains(t)) titulos.Add(t);
        }
        titulosPestanas = titulos;
    }

    static string TituloDe(IPanelIncrustable p)
    {
        try { return string.IsNullOrEmpty(p.TituloPestana) ? p.GetType().Name : p.TituloPestana; }
        catch (System.Exception) { return p.GetType().Name; }
    }

    static int OrdenIncrustable(string titulo)
    {
        int i = System.Array.IndexOf(PESTANAS_ESPERADAS, titulo);
        return i >= 0 ? i : PESTANAS_ESPERADAS.Length;
    }

    IPanelIncrustable IncrustableDe(string titulo)
    {
        foreach (IPanelIncrustable p in incrustables)
        {
            // Un componente destruido sigue en la lista hasta la proxima busqueda.
            if (p is MonoBehaviour mb && mb == null) continue;
            if (TituloDe(p) == titulo) return p;
        }
        return null;
    }

    /// La pestana que se esta mirando.
    public string Pestana { get { return pestana; } }

    /// Cambia de pestana EN EL ACTO y vuelve el scroll arriba. Para codigo
    /// que corre fuera de OnGUI (las capturas); los clicks del panel pasan
    /// por pestanaPendiente y se aplican en el Layout siguiente.
    public void ElegirPestana(string titulo)
    {
        if (string.IsNullOrEmpty(titulo)) return;
        pestanaPendiente = null;
        pestana = titulo;
        scroll = Vector2.zero;
        BuscarIncrustables();
    }

    // ============================================================
    // PANEL EN PANTALLA
    // ============================================================
    // Estilos derivados de GUI.skin a la escala de PanelUI. Se rehacen
    // cuando PanelUI rehace los suyos (cambia la referencia de Texto).
    private GUIStyle estToggle, estCampo, estMono, estTextoRef;

    void PrepararEstilos()
    {
        if (PanelUI.Texto == null || ReferenceEquals(estTextoRef, PanelUI.Texto)) return;
        estTextoRef = PanelUI.Texto;

        // La casilla escalada de PanelUI: la del skin mide 9 px a cualquier escala.
        estToggle = new GUIStyle(PanelUI.Casilla ?? GUI.skin.toggle);
        estToggle.fontSize = PanelUI.Texto.fontSize;
        estToggle.wordWrap = false;
        foreach (GUIStyleState s in new[] { estToggle.normal, estToggle.hover, estToggle.active, estToggle.focused,
                                            estToggle.onNormal, estToggle.onHover, estToggle.onActive, estToggle.onFocused })
            s.textColor = PanelUI.ColorTexto;

        estCampo = new GUIStyle(GUI.skin.textField);
        estCampo.fontSize = PanelUI.Texto.fontSize;
        estCampo.fixedHeight = PanelUI.AltoBoton;
        estCampo.alignment = TextAnchor.MiddleLeft;

        // Ancho fijo pero con salto de linea: la tabla de esfuerzos se
        // alinea y las lineas largas no abren un scroll horizontal.
        estMono = new GUIStyle(PanelUI.Mono);
        estMono.wordWrap = true;
    }

    /// Todo lo que decide CUANTOS controles hay se lee aca, en el Layout,
    /// y se mantiene hasta el Layout siguiente.
    void TomarFoto()
    {
        if (pestanaPendiente != null)
        {
            pestana = pestanaPendiente;
            pestanaPendiente = null;
            scroll = Vector2.zero;
            BuscarIncrustables();
        }
        // Fuera de Elemento el campo no se dibuja y su foco quedaria pegado.
        if (pestana != PESTANA_ELEMENTO && focoEnIrA) SoltarFocoIrA();
        fotoPanelVisible = panelVisible;
        fotoPestana = pestana;
        fotoPestanas = titulosPestanas;
        fotoSelTipo = selTipo;
        fotoSelId = selId;
        fotoBloques = bloques;
        fotoModo = modo;
        // Los avisos agregan o quitan una fila. Pueden cambiar fuera de
        // Update (un panel incrustado que avise ModeloEditado desde su
        // DibujarPanel corre dentro de este OnGUI): por eso van en la foto.
        fotoAvisoEdicion = avisoEdicion;
        fotoMensajeExcel = mensajeExcel;
        fotoMensajeExcelEsError = mensajeExcelEsError;
        fotoMensajeIrA = mensajeIrA;

        // Cabecera: lo que se lee del caso activo, sin calcular nada.
        fotoAvisoAnexo = s4 != null ? (s4.Aviso ?? "") : "";
        // El aviso del anexo es por la edicion (y la linea de la edicion ya lo
        // dice) o es de otra cosa (otro edificio, archivo que falta).
        fotoAnexoPorEdicion = avisoEdicion.Length > 0 && s4 != null && s4.AnexoDesactualizado;
        // Reanalisis vigente = el analizador tiene resultados y no quedaron
        // viejos por una edicion posterior. Solo se lee su estado.
        if (analizador == null && Time.frameCount % 60 == 0) analizador = FindAnyObjectByType<AnalizadorEstructural>();
        fotoReanalisisCasos = avisoEdicion.Length > 0 && analizador != null && analizador.HayResultados
                              && !analizador.Desactualizado
            ? string.Join(", ", analizador.CasosDisponibles().ToArray()) : "";
        // Un semana03.json de otro modelo no se dibuja: sin esta fila, el modo
        // Sismo de la pestana Caso no mostraria nada y no diria por que.
        fotoAvisoS3 = s3 != null ? (s3.Aviso ?? "") : "";
        // La cabecera dice la FUENTE de lo que se ve en 3D (final de la clase).
        fotoFuenteCabecera = FuenteDeLoQueSeVe();
        if (fotoFuenteCabecera != FUENTE_ANEXO) { CabeceraDeOtraFuente(); return; }
        CasoS4 c = s4 != null ? s4.CasoActivo() : null;
        if (c == null)
        {
            fotoCabeceraCaso = "Caso activo  " + (s4 != null && s4.Anexo == null ? "Sin anexo de la Semana 4" : "Sin caso activo");
            fotoCabeceraDesp = "";
            fotoCabeceraDemanda = "";
            fotoHayDemanda = false;
            return;
        }
        fotoCabeceraCaso = "Caso activo  " + c.nombre + (string.IsNullOrEmpty(c.descripcion) || c.descripcion == c.nombre
                                        ? "" : "   " + c.descripcion);
        // Corto a proposito: comparte la fila con la insignia "NO PASA n/m".
        fotoCabeceraDesp = $"Desp. max {F(c.max_desplazamiento_mm, "0.00")} mm";
        int noPasan, fuera, total;
        VisorSemana04.ContarDemandas(c, out noPasan, out fuera, out total);
        fotoHayDemanda = total > 0;
        fotoDemandaPasa = noPasan == 0;
        // El mismo texto que la leyenda del mapa D/C (VisorSemana04.Mapa):
        // quien compara la cabecera con el mapa ve el mismo "n/m". Con todo
        // pasando dice "PASAN m/m" (PanelUI.TextoDemanda).
        fotoCabeceraDemanda = PanelUI.TextoDemanda(noPasan, fuera, total);
    }

    void OnGUI()
    {
        PanelUI.Preparar();
        PrepararEstilos();
        if (Event.current.type == EventType.Layout) TomarFoto();
        GUI.color = Color.white;

        // IMGUI no suelta el foco de un campo de texto al hacer click fuera
        // de todo control: despues de escribir en "Ir a ID" y clickear el
        // modelo, H, C y Esc seguirian escribiendo en el campo. Solo se
        // suelta si el foco es de ESE campo (los del editor son suyos).
        if (focoEnIrA && Event.current.type == EventType.MouseDown
            && !RectPanel().Contains(Event.current.mousePosition))
            SoltarFocoIrA();

        if (visor == null || visor.Modelo == null)
        {
            // VisorEstructura lee el JSON en una corrutina (LectorStreaming):
            // los primeros segundos "sin modelo" es que todavia esta leyendo,
            // no un error.
            bool cargando = visor != null && Time.timeSinceLevelLoad < SEGUNDOS_DE_CARGA;
            GUILayout.BeginArea(new Rect(10f, 10f, PanelUI.Px(360f), PanelUI.Px(90f)), PanelUI.Caja);
            GUILayout.Label(cargando ? "Cargando el modelo..." : "Sin modelo cargado", PanelUI.Titulo);
            if (!cargando)
                GUILayout.Label("Revisa la consola: VisorEstructura no pudo leer su JSON de StreamingAssets.",
                                PanelUI.Aviso);
            GUILayout.EndArea();
            return;
        }

        if (!fotoPanelVisible)
        {
            if (GUI.Button(RectPanel(), "Panel (H)", PanelUI.Boton)) Diferir(() => panelVisible = true);
            return;
        }

        Rect rect = RectPanel();
        GUILayout.BeginArea(rect, PanelUI.Caja);
        DibujarCabecera();
        DibujarPestanas(rect.width);

        scroll = GUILayout.BeginScrollView(scroll);
        float ancho = rect.width - PanelUI.Caja.padding.horizontal - PanelUI.Px(22f);
        switch (fotoPestana)
        {
            case PESTANA_VISTA: PestanaVista(ancho); break;
            case PESTANA_CAPAS: PestanaCapas(ancho); break;
            case PESTANA_CASO: PestanaCaso(); break;
            case PESTANA_ELEMENTO: PestanaElemento(ancho); break;
            default: PestanaIncrustable(fotoPestana); break;
        }
        GUILayout.Space(PanelUI.Px(10f));
        GUILayout.EndScrollView();
        GUILayout.EndArea();

        // Los toggles del OnGUI cambian los campos directamente, asi que
        // hay que pedir el redibujo cuando el usuario suelta el mouse.
        if (Event.current.type == EventType.MouseUp) refrescar = true;
    }

    void Espacio(float px) { GUILayout.Space(PanelUI.Px(px)); }

    // ------------------------------------------------------------
    // CABECERA FIJA
    // ------------------------------------------------------------
    void DibujarCabecera()
    {
        ModeloEstructural m = visor.Modelo;
        string ed = EdificioActivo();

        GUILayout.BeginHorizontal();
        GUILayout.Label(string.IsNullOrEmpty(ed) ? "Modelo" : ed.ToUpperInvariant(), PanelUI.Titulo,
                        GUILayout.ExpandWidth(false));
        GUILayout.Label($"  {m.nodos.Count} nodos, {m.elementos.Count} elementos", PanelUI.Tenue);
        GUILayout.FlexibleSpace();
        if (GUILayout.Button("Ocultar (H)", PanelUI.Boton, GUILayout.ExpandWidth(false)))
            Diferir(() => panelVisible = false);
        GUILayout.EndHorizontal();

        GUILayout.Label(fotoCabeceraCaso, PanelUI.Texto);   // la fuente la decide TomarFoto
        if (fotoCabeceraDesp.Length > 0 && fotoCabeceraDemanda.Length == 0)
            GUILayout.Label(fotoCabeceraDesp, PanelUI.Tenue);   // reanalisis o carga movil: la D/C no es de lo que se ve
        else if (fotoCabeceraDesp.Length > 0)
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label(fotoCabeceraDesp, PanelUI.Texto, GUILayout.ExpandWidth(false));
            GUILayout.FlexibleSpace();
            PanelUI.Insignia(fotoCabeceraDemanda, !fotoHayDemanda ? PanelUI.Tenue : (fotoDemandaPasa ? PanelUI.Pasa : PanelUI.NoPasa));
            GUILayout.EndHorizontal();
        }

        // Con el modelo editado, el aviso del anexo (s4.Aviso) dice lo mismo que la
        // linea de la edicion: una sola linea, que distingue si lo que se ve ya es el
        // reanalisis del servidor (antes eran tres avisos que decian "ORIGINAL").
        if (fotoAvisoAnexo.Length > 0 && !fotoAnexoPorEdicion)
            GUILayout.Label("AVISO: " + fotoAvisoAnexo, PanelUI.Aviso);
        if (fotoAvisoS3.Length > 0)
            GUILayout.Label("AVISO Semana 3: " + fotoAvisoS3, PanelUI.Aviso);
        if (fotoAvisoEdicion.Length > 0)
        {
            GUILayout.BeginHorizontal();
            if (fotoReanalisisCasos.Length > 0)
                GUILayout.Label("Modelo editado (" + fotoAvisoEdicion + "). Mostrando el reanalisis del "
                                + "servidor (" + fotoReanalisisCasos + "); el anexo S4 y E1-E3 siguen "
                                + "siendo del modelo original.", PanelUI.Tenue);
            else
                GUILayout.Label("Modelo editado (" + fotoAvisoEdicion + "): anexo S4 y E1-E3 = modelo "
                                + "original. Recalcula en la pestana Modificar.", PanelUI.Aviso);
            if (GUILayout.Button("ok", PanelUI.Boton, GUILayout.Width(PanelUI.Px(40f))))
                Diferir(() => avisoEdicion = "");
            GUILayout.EndHorizontal();
        }

        // La seleccion, siempre a la vista, con sus acciones.
        Espacio(2f);
        GUILayout.BeginHorizontal();
        if (fotoSelTipo == EventosVisor.TIPO_NINGUNO)
        {
            GUILayout.Label("Seleccion: nada (click en un nodo o una barra)", PanelUI.Tenue);
        }
        else
        {
            GUILayout.Label("Seleccion: " + TextoSeleccionCorto(), PanelUI.Texto);
            if (GUILayout.Button("Ver", PanelUI.Boton, GUILayout.ExpandWidth(false)))
                pestanaPendiente = PESTANA_ELEMENTO;
            if (GUILayout.Button("Centrar", PanelUI.Boton, GUILayout.ExpandWidth(false)))
                Diferir(CentrarSeleccion);
            if (GUILayout.Button("x", PanelUI.Boton, GUILayout.Width(PanelUI.Px(28f))))
                Diferir(LimpiarSeleccion);
        }
        GUILayout.EndHorizontal();

        Espacio(2f);
        if (GUILayout.Button("Abrir Excel de resultados", PanelUI.BotonActivo))
            Diferir(AbrirExcelResultados);
        if (fotoMensajeExcel.Length > 0)
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label(fotoMensajeExcel, fotoMensajeExcelEsError ? PanelUI.Aviso : PanelUI.Tenue);
            if (GUILayout.Button("ok", PanelUI.Boton, GUILayout.Width(PanelUI.Px(40f))))
                Diferir(() => mensajeExcel = "");
            GUILayout.EndHorizontal();
        }
    }

    string TextoSeleccionCorto()
    {
        ModeloEstructural m = visor.Modelo;
        if (fotoSelTipo == EventosVisor.TIPO_ELEMENTO)
        {
            Elemento e = m.ElementoPorId(fotoSelId);
            return e == null ? $"elemento {fotoSelId}" : $"elemento {e.id}  {e.tipo}  {e.seccion}";
        }
        Nodo n = m.NodoPorId(fotoSelId);
        return n == null ? $"nodo {fotoSelId}" : $"nodo {n.id}  cota {Cota(n.z)}";
    }

    void DibujarPestanas(float anchoPanelPx)
    {
        Espacio(4f);
        List<string> titulos = fotoPestanas;
        int columnas = titulos.Count <= 4 ? titulos.Count : 3;
        for (int i = 0; i < titulos.Count; i++)
        {
            if (i % columnas == 0) GUILayout.BeginHorizontal();
            string t = titulos[i];
            bool activa = t == fotoPestana;
            if (GUILayout.Button(t, activa ? PanelUI.BotonActivo : PanelUI.Boton) && !activa)
                pestanaPendiente = t;
            if (i % columnas == columnas - 1 || i == titulos.Count - 1) GUILayout.EndHorizontal();
        }
        Espacio(4f);
    }

    // ------------------------------------------------------------
    // PESTANA VISTA
    // ------------------------------------------------------------
    private string lineaEquipo = "";
    private int anchoLineaEquipo = -1, altoLineaEquipo = -1;

    void PestanaVista(float ancho)
    {
        if (PanelUI.Plegable("qa.vista.aspecto", "Aspecto", true))
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label("Vista:", PanelUI.Texto, GUILayout.Width(PanelUI.Px(60f)));
            if (PanelUI.Opcion(AjustesVista.realista, "Realista"))
                Diferir(() => { AjustesVista.realista = true; EventosVisor.AvisarVistaCambio(); });
            if (PanelUI.Opcion(!AjustesVista.realista, "Tecnica"))
                Diferir(() => { AjustesVista.realista = false; EventosVisor.AvisarVistaCambio(); });
            GUILayout.EndHorizontal();
            GUILayout.Label(AjustesVista.realista
                ? "Realista: columnas y vigas con su seccion b x h, losas por piso, hormigon y acero con "
                  + "textura (la columna en salmon). Los diagramas y el mapa D/C se leen igual."
                : "Tecnica: un color por tipo (columna azul, viga naranja, muro gris, acero rojo).",
                PanelUI.Tenue);

            // El mismo campo que la casilla de Capas: la realista siempre
            // dibuja las secciones, asi que aca decide solo la tecnica.
            GUILayout.BeginHorizontal();
            bool perfA = GUILayout.Toggle(visor.verPerfiles, "Perfiles reales (b x h) en la tecnica", estToggle,
                                          GUILayout.ExpandWidth(false));
            bool losasA = GUILayout.Toggle(AjustesVista.losas, "Losas", estToggle, GUILayout.ExpandWidth(false));
            GUILayout.EndHorizontal();
            if (perfA != visor.verPerfiles)
                Diferir(() => { visor.verPerfiles = perfA; visor.Redibujar(); refrescar = true; });
            if (losasA != AjustesVista.losas)
                Diferir(() => { AjustesVista.losas = losasA; EventosVisor.AvisarVistaCambio(); });

            bool suelo = GUILayout.Toggle(AjustesVista.suelo, "Suelo donde apoya el edificio", estToggle);
            if (suelo != AjustesVista.suelo)
                Diferir(() => { AjustesVista.suelo = suelo; EventosVisor.AvisarVistaCambio(); });
            InfoModelo info = visor.Modelo.info;
            GUILayout.Label(info != null && info.cota_terreno > -9000f
                ? $"Terreno en la cota {Cota(info.cota_terreno)} m: donde arranca la estructura, declarado en el perfil del edificio.{TextoTerrazas(info)}"
                : "Este JSON no trae cota de terreno: el suelo va en el apoyo mas bajo (respaldo de dibujo, ver consola).",
                PanelUI.Tenue); CasillaRelieve();     // VisorQA.Relieve.cs
        }

        if (PanelUI.Plegable("qa.vista.camara", "Camara", true))
        {
            if (orbital == null)
            {
                GUILayout.Label("No hay CamaraOrbital en la camara principal.", PanelUI.Aviso);
            }
            else
            {
                if (GUILayout.Button("Encuadrar todo el modelo (F)", PanelUI.Boton))
                    Diferir(orbital.EncuadrarTodo);
                GUILayout.BeginHorizontal();
                if (GUILayout.Button("Planta", PanelUI.Boton)) Diferir(orbital.VistaPlanta);
                if (GUILayout.Button("Elev. X", PanelUI.Boton)) Diferir(orbital.VistaElevX);
                if (GUILayout.Button("Elev. Y", PanelUI.Boton)) Diferir(orbital.VistaElevY);
                if (GUILayout.Button("Iso", PanelUI.Boton)) Diferir(orbital.VistaIso);
                GUILayout.EndHorizontal();
                GUILayout.Label("Elev. X mira el plano X-Z de OpenSees; Elev. Y el Y-Z.", PanelUI.Tenue);
            }
        }

        if (PanelUI.Plegable("qa.vista.piso", "Filtro de piso", true))
        {
            List<float> cotas = CotasDelModelo();
            GUILayout.Label(soloNivel < 0
                ? "Piso: todos"
                : $"Piso: nivel {soloNivel + 1} de {cotas.Count}, cota {Cota(CotaDeNivel(soloNivel))} m",
                PanelUI.Texto);
            GUILayout.BeginHorizontal();
            if (PanelUI.Opcion(soloNivel < 0, "Todos")) Diferir(() => ElegirPiso(-1));
            if (GUILayout.Button("bajar", PanelUI.Boton)) Diferir(() => ElegirPiso(Mathf.Max(-1, soloNivel - 1)));
            if (GUILayout.Button("subir", PanelUI.Boton))
                Diferir(() => ElegirPiso(Mathf.Min(CotasDelModelo().Count - 1, soloNivel + 1)));
            GUILayout.EndHorizontal();

            // Un boton por cota, de arriba hacia abajo como en un corte.
            if (cotas.Count <= 12)
            {
                int enFila = 0;
                for (int i = cotas.Count - 1; i >= 0; i--)
                {
                    if (enFila == 0) GUILayout.BeginHorizontal();
                    int nivel = i;
                    if (PanelUI.Opcion(soloNivel == i, Cota(cotas[i]), GUILayout.Width((ancho - PanelUI.Px(12f)) / 3f)))
                        Diferir(() => ElegirPiso(nivel));
                    enFila++;
                    if (enFila == 3 || i == 0) { GUILayout.EndHorizontal(); enFila = 0; }
                }
            }
            GUILayout.Label("Cada barra es del piso de su nodo MAS BAJO: la losa y lo que nace de ella. "
                            + "Filtra estructura, apoyos, ejes, IDs, areas y diagramas.", PanelUI.Tenue);
        }

        if (PanelUI.Plegable("qa.vista.controles", "Controles", false))
        {
            GUILayout.Label("Click: seleccionar nodo, barra o apoyo\n"
                            + "Arrastrar: orbitar     derecho o medio: mover\n"
                            + "Rueda: zoom     F: encuadrar     C: centrar seleccion\n"
                            + "Esc: soltar seleccion     H: ocultar el panel", PanelUI.Texto);
        }

        // Abierta: es la ultima seccion (no empuja nada) y la linea del equipo
        // es evidencia para el informe (en que maquina y a que escala se corrio).
        if (PanelUI.Plegable("qa.vista.equipo", "Tamano del texto y equipo", true))
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label($"Texto x{F(PanelUI.EscalaUsuario, "0.00")}", PanelUI.Texto, GUILayout.Width(PanelUI.Px(110f)));
            if (GUILayout.Button("A-", PanelUI.Boton)) Diferir(() => PanelUI.EscalaUsuario -= 0.1f);
            if (GUILayout.Button("A+", PanelUI.Boton)) Diferir(() => PanelUI.EscalaUsuario += 0.1f);
            GUILayout.EndHorizontal();

            // Evidencia de en que equipo se corrio (Semana 5, movil).
            if (anchoLineaEquipo != Screen.width || altoLineaEquipo != Screen.height || lineaEquipo.Length == 0)
            {
                anchoLineaEquipo = Screen.width;
                altoLineaEquipo = Screen.height;
                lineaEquipo = $"{SystemInfo.deviceModel} | {SystemInfo.operatingSystem}\n"
                            + $"{SystemInfo.graphicsDeviceName} ({SystemInfo.graphicsDeviceVersion})\n"
                            + $"RAM {SystemInfo.systemMemorySize} MB | pantalla {Screen.width}x{Screen.height} "
                            + $"a {F(Screen.dpi, "0")} dpi | escala del panel x{F(PanelUI.Escala(), "0.00")}";
            }
            GUILayout.Label(lineaEquipo, PanelUI.Tenue);
        }
    }

    // ------------------------------------------------------------
    // PESTANA CAPAS
    // ------------------------------------------------------------
    void PestanaCapas(float ancho)
    {
        float col = (ancho - PanelUI.Px(8f)) / 2f;

        if (PanelUI.Plegable("qa.capas.estructura", "Estructura", true))
        {
            GUILayout.BeginHorizontal();
            bool nod = GUILayout.Toggle(visor.verNodos, "Nodos", estToggle, GUILayout.Width(col));
            bool aux = GUILayout.Toggle(visor.verNodosAuxiliares, "Nodos aux.", estToggle, GUILayout.Width(col));
            GUILayout.EndHorizontal();
            GUILayout.BeginHorizontal();
            bool colu = GUILayout.Toggle(visor.verColumnas, "Columnas", estToggle, GUILayout.Width(col));
            bool vig = GUILayout.Toggle(visor.verVigas, "Vigas", estToggle, GUILayout.Width(col));
            GUILayout.EndHorizontal();
            GUILayout.BeginHorizontal();
            bool mur = GUILayout.Toggle(visor.verMuros, "Muros", estToggle, GUILayout.Width(col));
            bool brz = GUILayout.Toggle(visor.verBrazos, "Brazos rigidos", estToggle, GUILayout.Width(col));
            GUILayout.EndHorizontal();
            bool perf = GUILayout.Toggle(visor.verPerfiles, "Perfiles reales (b x h) en la vista tecnica", estToggle);
            // Las losas son DIBUJO (AmbienteVisor): los poligonos de las areas
            // tributarias del JSON, sin collider y solo en la vista realista.
            bool losas = GUILayout.Toggle(AjustesVista.losas, "Losas (dibujo de las areas tributarias)", estToggle);
            if (losas != AjustesVista.losas)
                Diferir(() => { AjustesVista.losas = losas; EventosVisor.AvisarVistaCambio(); });

            if (nod != visor.verNodos || aux != visor.verNodosAuxiliares || colu != visor.verColumnas
                || vig != visor.verVigas || mur != visor.verMuros || brz != visor.verBrazos
                || perf != visor.verPerfiles)
            {
                Diferir(() =>
                {
                    visor.verNodos = nod; visor.verNodosAuxiliares = aux;
                    visor.verColumnas = colu; visor.verVigas = vig;
                    visor.verMuros = mur; visor.verBrazos = brz;
                    visor.verPerfiles = perf;
                    visor.Redibujar();          // el modelo lo redibuja el Visor
                    refrescar = true;           // y las capas QA, este script
                });
            }
        }

        if (PanelUI.Plegable("qa.capas.qa", "Control de calidad", true))
        {
            // OJO: hay que PEDIR el redibujo. Estos toggles asignaban el
            // bool y nada mas, asi que marcar "Areas tributarias" no
            // dibujaba nada hasta que otra cosa forzara un refresco.
            GUILayout.BeginHorizontal();
            bool ap = GUILayout.Toggle(verApoyos, "Apoyos", estToggle, GUILayout.Width(col));
            bool di = GUILayout.Toggle(verDiafragmas, "Diafragmas", estToggle, GUILayout.Width(col));
            GUILayout.EndHorizontal();
            GUILayout.BeginHorizontal();
            bool ej = GUILayout.Toggle(verEjesLocales, "Ejes locales", estToggle, GUILayout.Width(col));
            bool id = GUILayout.Toggle(verIDs, "IDs", estToggle, GUILayout.Width(col));
            GUILayout.EndHorizontal();
            bool tr = GUILayout.Toggle(verAreasTributarias, "Areas tributarias", estToggle);

            if (ap != verApoyos || di != verDiafragmas || ej != verEjesLocales
                || tr != verAreasTributarias || id != verIDs)
            {
                Diferir(() =>
                {
                    verApoyos = ap; verDiafragmas = di; verEjesLocales = ej;
                    verAreasTributarias = tr; verIDs = id;
                    refrescar = true;
                });
            }

            ModeloEstructural m = visor.Modelo;
            int[] n = ContarApoyos(m);
            Espacio(4f);
            GUILayout.Label("Apoyos (click en el simbolo para ver el nodo)", PanelUI.Tenue);
            Muestra(colorApoyo, $"cubo: empotrado [1 1 1 1 1 1]  ({n[(int)TipoApoyo.Empotrado]})");
            Muestra(colorApoyoTerreno, $"placa: apoyo en terreno [0 0 1 1 1 0]  ({n[(int)TipoApoyo.Terreno]})");
            Muestra(colorApoyoOtro, $"rombo: otra combinacion  ({n[(int)TipoApoyo.Otro]})");
            Muestra(colorDiafragma, "esfera: maestro de diafragma, con radios a sus nodos");
            Muestra(colorSeleccion, "cian: la seleccion");
            GUILayout.Label("Ejes locales: rojo x, verde y, azul z (OpenSees).", PanelUI.Tenue);
            if (m.areas_tributarias != null)
                GUILayout.Label($"Areas tributarias: {m.areas_tributarias.Count} entradas. Con 'Piso: todos' "
                                + "se dibuja solo la de la barra seleccionada.", PanelUI.Tenue);
        }

        if (s3 != null && PanelUI.Plegable("qa.capas.s3", "Semana 3: cargas y enfierradura", false))
            PanelSemana03();
    }

    /// Un cuadrado de color y su texto: la leyenda de las capas.
    void Muestra(Color color, string texto)
    {
        GUILayout.BeginHorizontal();
        float lado = PanelUI.Px(12f);
        Rect r = GUILayoutUtility.GetRect(lado, lado, GUILayout.Width(lado), GUILayout.Height(lado));
        r.y += PanelUI.Px(3f);
        Color antes = GUI.color;
        GUI.color = color;
        GUI.DrawTexture(r, Texture2D.whiteTexture);
        GUI.color = antes;
        GUILayout.Label(texto, PanelUI.Texto);
        GUILayout.EndHorizontal();
    }

    /// Los controles de las capas de Semana 3, dentro del panel.
    void PanelSemana03()
    {
        // Los "if" que agregan controles preguntan por el estado de s3, no
        // por lo que devolvio el toggle en ESTE evento: el cambio se aplica
        // en Update (Diferir). Si preguntaran por el toggle, en el MouseUp
        // que lo marca aparecerian controles que el Layout no conto.
        bool flechas = GUILayout.Toggle(s3.mostrarCargas, "Flechas de carga", estToggle);
        string caso = s3.casoCarga;
        if (s3.mostrarCargas)
        {
            GUILayout.BeginHorizontal();
            foreach (string c in CASOS_DE_CARGA)
            {
                string etiqueta = (c == "COMBINACION") ? "COMB" : c;
                if (PanelUI.Opcion(c == s3.casoCarga, etiqueta)) caso = c;
            }
            GUILayout.EndHorizontal();
            bool esperando = s3.cargasConLaDeformada
                             && fotoModo != ModoDeformada.SismoEX
                             && fotoModo != ModoDeformada.SismoEY;
            if (esperando)
                GUILayout.Label("(aparecen al elegir una deformada de sismo, en Caso > Avanzado)", PanelUI.Tenue);
        }

        bool armadura = GUILayout.Toggle(s3.mostrarArmadura, "Enfierradura", estToggle);
        bool todas = s3.enfierrarTodas;
        bool lamina = s3.jaulaDetalle;
        if (s3.mostrarArmadura)
        {
            GUILayout.BeginHorizontal();
            todas = GUILayout.Toggle(todas, "en todas las columnas", estToggle);
            lamina = GUILayout.Toggle(lamina, "lamina ampliada", estToggle);
            GUILayout.EndHorizontal();
            if (AjustesVista.realista)
                GUILayout.Label("En la vista realista la columna es solida (b x h) y la jaula en sitio queda "
                                + "adentro: se ve en la tecnica o con 'lamina ampliada'.", PanelUI.Tenue);
        }

        if (flechas != s3.mostrarCargas || caso != s3.casoCarga ||
            armadura != s3.mostrarArmadura || todas != s3.enfierrarTodas ||
            lamina != s3.jaulaDetalle)
        {
            Diferir(() =>
            {
                s3.mostrarCargas = flechas;
                s3.casoCarga = caso;
                s3.mostrarArmadura = armadura;
                s3.enfierrarTodas = todas;
                s3.jaulaDetalle = lamina;
                s3.Redibujar();
                refrescar = true;
            });
        }
    }

    private static readonly string[] CASOS_DE_CARGA =
        { "G", "Q", "EX", "EY", "COMBINACION" };

    // ------------------------------------------------------------
    // PESTANA CASO
    // ------------------------------------------------------------
    void PestanaCaso()
    {
        // ---------- Deformada ----------
        // Una sola fuente a la vez. La principal es la del caso activo
        // (cualquier caso o combinacion del anexo de Semana 4); 'Cargas G'
        // y los sismos de Semana 3 repiten G, EX y EY y quedan en Avanzado.
        if (PanelUI.Plegable("qa.caso.deformada", "Deformada", true))
        {
            ModoDeformada elegido = fotoModo;
            GUILayout.BeginHorizontal();
            if (PanelUI.Opcion(fotoModo == ModoDeformada.Sin, "Sin deformar"))
                elegido = ModoDeformada.Sin;
            if (s4 != null && s4.Anexo != null)
            {
                if (PanelUI.Opcion(fotoModo == ModoDeformada.CasoActivo, "Caso activo: " + s4.casoActivo))
                    elegido = ModoDeformada.CasoActivo;
            }
            GUILayout.EndHorizontal();

            if (fotoModo != ModoDeformada.Sin)
            {
                // Los desplazamientos reales son de milimetros sobre un
                // edificio de decenas de metros: sin amplificar no se ve
                // NADA. El factor es puramente GRAFICO, no toca el
                // analisis: la estructura no se deforma mas por subirlo.
                // CUANTO amplificar depende del tamano del modelo y de su
                // mayor desplazamiento, asi que no puede ser el mismo
                // numero para todos (el x300 de la escena sirve en el LT2
                // y deja al conjunto como una carpa): el valor por defecto
                // lo calcula Python y viaja en el anexo, una por modelo.
                float reco = EscalaRecomendada();
                if (reco > 0f && !escalaDelAnexoPuesta) Diferir(FijarEscalaDelAnexo);
                float escala = visor.factorEscala;
                GUILayout.Label($"escala grafica x{F(escala, "0")}  (solo visual, no cambia el calculo)", PanelUI.Texto);
                GUILayout.Label(NotaEscalaRecomendada(reco), PanelUI.Tenue);
                escala = GUILayout.HorizontalSlider(escala, 1f, Mathf.Max(2000f, 2f * reco));
                Espacio(4f);
                GUILayout.BeginHorizontal();
                if (GUILayout.Button("x1", PanelUI.Boton)) escala = 1f;
                if (GUILayout.Button("x100", PanelUI.Boton)) escala = 100f;
                if (GUILayout.Button("x500", PanelUI.Boton)) escala = 500f;
                if (GUILayout.Button("x1000", PanelUI.Boton)) escala = 1000f;
                GUILayout.EndHorizontal();
                // Volver a la del anexo, como el "Escala del recorrido" de la
                // carga movil. Siempre: un control que aparece rompe el Layout.
                if (GUILayout.Button(reco > 0f ? $"Volver a la recomendada x{F(reco, "0")}"
                                     : "Este anexo no trae escala recomendada", PanelUI.Boton)
                    && reco > 0f) escala = reco;
                if (!Mathf.Approximately(escala, visor.factorEscala)) Diferir(() => FijarEscala(escala));
            }

            if (PanelUI.Plegable("qa.caso.avanzado", "Avanzado: otras fuentes de deformada", false))
            {
                GUILayout.Label("Repiten G, EX y EY con los datos de antes: la G precalculada del JSON "
                                + "del modelo y los sismos del anexo de la Semana 3 (con sus flechas).",
                                PanelUI.Tenue);
                GUILayout.BeginHorizontal();
                if (PanelUI.Opcion(fotoModo == ModoDeformada.Gravedad, "Cargas G"))
                    elegido = ModoDeformada.Gravedad;
                if (s3 != null)
                {
                    if (PanelUI.Opcion(fotoModo == ModoDeformada.SismoEX, "Sismo EX"))
                        elegido = ModoDeformada.SismoEX;
                    if (PanelUI.Opcion(fotoModo == ModoDeformada.SismoEY, "Sismo EY"))
                        elegido = ModoDeformada.SismoEY;
                }
                GUILayout.EndHorizontal();
                if (s3 == null)
                    GUILayout.Label("(no hay VisorSemana03 en la escena: sin sismo)", PanelUI.Tenue);
            }

            if (elegido != fotoModo)
            {
                ModoDeformada m = elegido;
                Diferir(() => AplicarModo(m));
            }
        }

        // ---------- Semana 4 ----------
        // Casos, combinaciones, superposicion, diagramas, mapa D/C y demos.
        Espacio(6f);
        if (s4 != null) s4.DibujarControles();
    }

    // ------------------------------------------------------------
    // PESTANA ELEMENTO (el inspector)
    // ------------------------------------------------------------
    void PestanaElemento(float ancho)
    {
        // Ir a ID
        GUILayout.BeginHorizontal();
        GUILayout.Label("Ir a ID", PanelUI.Texto, GUILayout.Width(PanelUI.Px(56f)));
        // Enter se lee ANTES del campo: en Windows el KeyDown de Return llega
        // sin caracter y el TextField enfocado lo consume (Event.Use), asi que
        // despues del campo el evento ya es Used y Enter no hacia nada.
        // focoEnIrA es el foco del Repaint anterior.
        bool enter = focoEnIrA && Event.current.type == EventType.KeyDown
                     && (Event.current.keyCode == KeyCode.Return || Event.current.keyCode == KeyCode.KeypadEnter);
        GUI.SetNextControlName("qa.irA");
        string campo = GUILayout.TextField(campoIrA, 7, estCampo, GUILayout.Width(PanelUI.Px(70f)));
        // Solo digitos: un id de OpenSees es un entero positivo.
        if (campo != campoIrA)
        {
            var sb = new StringBuilder();
            foreach (char ch in campo) if (char.IsDigit(ch)) sb.Append(ch);
            campoIrA = sb.ToString();
        }
        if (GUILayout.Button("Elemento", PanelUI.Boton) || enter) Diferir(() => IrA(EventosVisor.TIPO_ELEMENTO));
        if (GUILayout.Button("Nodo", PanelUI.Boton)) Diferir(() => IrA(EventosVisor.TIPO_NODO));
        GUILayout.EndHorizontal();
        if (Event.current.type == EventType.Repaint)
            focoEnIrA = GUI.GetNameOfFocusedControl() == "qa.irA";
        if (fotoMensajeIrA.Length > 0) GUILayout.Label(fotoMensajeIrA, PanelUI.Aviso);
        Espacio(4f);

        if (fotoSelTipo == EventosVisor.TIPO_NINGUNO)
        {
            GUILayout.Label("Nada seleccionado.", PanelUI.Titulo);
            GUILayout.Label("Click en un nodo, una barra o el simbolo de un apoyo, o escribe su ID arriba. "
                            + "El inspector contesta donde esta, como esta apoyado, que lo carga, "
                            + "como se deforma, que fuerzas tiene y cuanta capacidad le queda.",
                            PanelUI.Texto);
            return;
        }

        ModeloEstructural m = visor.Modelo;
        GUILayout.BeginHorizontal();
        if (fotoSelTipo == EventosVisor.TIPO_ELEMENTO)
        {
            Elemento e = m.ElementoPorId(fotoSelId);
            GUILayout.Label("Elemento " + fotoSelId, PanelUI.Titulo, GUILayout.ExpandWidth(false));
            GUILayout.FlexibleSpace();
            DemandaS4 d = s4 != null ? s4.DemandaDe(fotoSelId, s4.casoActivo) : null;
            if (d != null)
            {
                if (d.u >= PanelUI.U_FUERA_DE_CURVA) PanelUI.Insignia("FUERA DE CURVA", PanelUI.NoPasa);
                else PanelUI.Insignia(d.pasa);
            }
            GUILayout.EndHorizontal();
            if (e != null) GUILayout.Label($"{e.tipo}   {e.seccion}", PanelUI.Tenue);
        }
        else
        {
            Nodo n = m.NodoPorId(fotoSelId);
            GUILayout.Label("Nodo " + fotoSelId, PanelUI.Titulo, GUILayout.ExpandWidth(false));
            GUILayout.FlexibleSpace();
            if (n != null)
            {
                TipoApoyo t = Clasificar(n);
                if (t == TipoApoyo.Empotrado) PanelUI.Insignia("EMPOTRADO", PanelUI.Pasa);
                else if (t == TipoApoyo.Terreno) PanelUI.Insignia("APOYO EN TERRENO", PanelUI.Aviso);
                else if (t == TipoApoyo.Otro) PanelUI.Insignia("APOYO", PanelUI.Aviso);
            }
            GUILayout.EndHorizontal();
        }

        GUILayout.BeginHorizontal();
        if (GUILayout.Button("Centrar (C)", PanelUI.Boton)) Diferir(CentrarSeleccion);
        // Con secciones solidas (vista realista) una barra del interior o del
        // subterraneo queda tapada por las de arriba. "Su piso" usa el filtro
        // de piso de siempre (la cota mas baja de la seleccion): el resto del
        // edificio queda como lineas grises y lo elegido se ve.
        int nivelSel = NivelDeLaSeleccion();
        bool enSuPiso = nivelSel >= 0 && soloNivel == nivelSel;
        if (GUILayout.Button(enSuPiso ? "Todos los pisos" : "Su piso", PanelUI.Boton) && nivelSel >= 0)
            Diferir(() => ElegirPiso(enSuPiso ? -1 : nivelSel));
        if (GUILayout.Button("Soltar (Esc)", PanelUI.Boton)) Diferir(LimpiarSeleccion);
        GUILayout.EndHorizontal();
        Espacio(2f);

        // La curva P-M va justo despues de "Demanda / capacidad", que es la
        // pregunta que contesta. Al final quedaba bajo Trazabilidad, fuera
        // de la vista. Si ese bloque no esta (JSON sin anexo), al final.
        bool pmDibujada = false;
        foreach (BloqueTexto b in fotoBloques)
        {
            bool abierto = PanelUI.Plegable(b.clave, b.titulo, b.abiertoPorDefecto);
            if (abierto)
            {
                // TextoPlano solo al mostrar (%%C del DXF -> diametro): el
                // cuerpo del bloque es el texto de DescribirElemento, que
                // CapturaSemana04/05 escriben tal cual en registro.txt.
                GUILayout.Label(PanelUI.TextoPlano(b.cuerpo), b.aviso ? PanelUI.Aviso : (b.mono ? estMono : PanelUI.Texto));
                if (!string.IsNullOrEmpty(b.nota)) GUILayout.Label(b.nota, PanelUI.Tenue);
                if (b.enlaces != null && b.enlaces.Count > 0) Enlaces(b.enlaces, ancho);
            }
            if (!pmDibujada && b.clave == CLAVE_BLOQUE_DEMANDA) { CurvaPMEnPanel(); pmDibujada = true; }
        }
        if (!pmDibujada) CurvaPMEnPanel();
    }

    const string CLAVE_BLOQUE_DEMANDA = "qa.s4.demanda / capacidad";

    /// La curva P-M dentro del panel (la dibuja VisorSemana04.PM.cs).
    void CurvaPMEnPanel()
    {
        if (fotoSelTipo != EventosVisor.TIPO_ELEMENTO || s4 == null || s4.Anexo == null) return;
        ElementoS4 e4 = s4.ElementoPorId(fotoSelId);
        if (e4 != null && e4.familia >= 0
            && PanelUI.Plegable("qa.elem.pm", "Curva P-M, caso activo " + s4.casoActivo, true))
        {
            s4.DibujarPMEnLinea();
            GUILayout.Label("La ventana flotante 'Curva P-M' se prende en la pestana Caso.", PanelUI.Tenue);
        }
    }

    void Enlaces(List<Enlace> enlaces, float ancho)
    {
        const int POR_FILA = 2;
        float w = (ancho - PanelUI.Px(8f)) / POR_FILA;
        for (int i = 0; i < enlaces.Count; i++)
        {
            if (i % POR_FILA == 0) GUILayout.BeginHorizontal();
            Enlace en = enlaces[i];
            if (GUILayout.Button(en.texto, PanelUI.Boton, GUILayout.Width(w)))
            {
                string tipo = en.tipo;
                int id = en.id;
                Diferir(() => FijarSeleccion(tipo, id, true));
            }
            if (i % POR_FILA == POR_FILA - 1 || i == enlaces.Count - 1) GUILayout.EndHorizontal();
        }
    }

    void IrA(string tipo)
    {
        int id;
        if (!int.TryParse(campoIrA, NumberStyles.Integer, CultureInfo.InvariantCulture, out id))
        {
            mensajeIrA = "Escribe un numero de nodo o de elemento.";
            return;
        }
        mensajeIrA = "";
        SoltarFocoIrA();   // suelta el campo: las teclas vuelven a ser atajos
        FijarSeleccion(tipo, id, true);
        if (selTipo != EventosVisor.TIPO_NINGUNO) CentrarSeleccion();
    }

    // Si el foco del teclado es del campo "Ir a ID" (se mira en cada Repaint
    // de la pestana Elemento).
    private bool focoEnIrA = false;

    void SoltarFocoIrA()
    {
        GUIUtility.keyboardControl = 0;
        focoEnIrA = false;
    }

    // ------------------------------------------------------------
    // PESTANAS INCRUSTADAS (Modificar, Carga movil, ...)
    // ------------------------------------------------------------
    void PestanaIncrustable(string titulo)
    {
        IPanelIncrustable p = IncrustableDe(titulo);
        if (p == null)
        {
            GUILayout.Label(titulo, PanelUI.Titulo);
            string quien = titulo == PESTANA_MODIFICAR ? "EditorEstructura"
                         : titulo == PESTANA_CARGA_MOVIL ? "VisorCargaMovil" : "el componente";
            GUILayout.Label($"No hay un panel '{titulo}' en esta escena: {quien} no esta o todavia no "
                            + "implementa IPanelIncrustable. Si dibuja su propio panel, esta a la derecha.",
                            PanelUI.Aviso);
            return;
        }
        try
        {
            p.DibujarPanel();
        }
        catch (ExitGUIException)
        {
            throw;   // IMGUI la usa para cortar el evento: no es un error
        }
        catch (System.Exception ex)
        {
            GUILayout.Label($"El panel '{titulo}' fallo: {ex.Message}", PanelUI.Aviso);
            Debug.LogException(ex);
        }
    }

    // ------------------------------------------------------------
    // REVISION FINAL DE LA SEMANA 5: "QUE LO CARGA" Y LA FUENTE DE LA CABECERA
    // ------------------------------------------------------------
    // Va al final de la clase a proposito: el informe y los documentos de
    // semana05/ citan lineas de este archivo, y asi ninguna se corre.

    /// De donde sale lo que se ve en 3D. CapturaSemana05 lo registra por foto.
    public const string FUENTE_ANEXO = "anexo";
    public const string FUENTE_REANALISIS = "reanalisis";
    public const string FUENTE_CARGA_MOVIL = "carga_movil";

    private VisorCargaMovil cargaMovilCabecera;
    private string fotoFuenteCabecera = FUENTE_ANEXO;

    /// La fuente de la cabecera en la ultima foto del Layout (la que se dibuja).
    public string FuenteCabecera { get { return fotoFuenteCabecera; } }

    /// La cabecera tal como se dibuja, en una linea: "fila 1 | fila 2 | insignia"
    /// (el salto de linea dentro de la fila 1 se escribe " · ").
    public string TextoCabecera
    {
        get { return (fotoCabeceraCaso + " | " + fotoCabeceraDesp + " | " + fotoCabeceraDemanda).Replace("\n", " · "); }
    }

    /// Quien puso la deformada que se ve. La cabecera leia siempre el caso
    /// del ANEXO (Desp. max, NO PASA n/m), y con la carga movil o con el
    /// reanalisis del servidor el 3D muestra otra cosa: la foto de la M1
    /// decia "Caso activo LIBRE ... 24.63 mm, NO PASA 4/69" junto a un nodo
    /// que bajaba 21.60 mm. Mismo criterio que usan esos dos scripts:
    /// VisorCargaMovil aplica su deformada mientras esta Activo (y la quita al
    /// apagarse), y AnalizadorEstructural la del caso que muestra mientras sus
    /// resultados son del modelo editado (fotoReanalisisCasos).
    string FuenteDeLoQueSeVe()
    {
        if (cargaMovilCabecera == null && Time.frameCount % 60 == 0)
            cargaMovilCabecera = FindAnyObjectByType<VisorCargaMovil>();
        if (cargaMovilCabecera != null && cargaMovilCabecera.Activo && PosicionMovilActiva() != null)
            return FUENTE_CARGA_MOVIL;
        if (fotoReanalisisCasos.Length > 0 && analizador != null && analizador.CasoMostrado != null)
            return FUENTE_REANALISIS;
        return FUENTE_ANEXO;
    }

    /// La cabecera cuando lo que se ve NO es un caso del anexo. Solo copia
    /// numeros ya calculados: max_desplazamiento del servidor, la mayor COMPONENTE en mm
    /// (no la norma del "Desp. max" del anexo; rotulo de Modificar), y la posicion de
    /// carga_movil.json (Python). La insignia D/C se reemplaza por una linea
    /// tenue: la demanda-capacidad del anexo no es de lo que se ve.
    void CabeceraDeOtraFuente()
    {
        fotoCabeceraDemanda = "";
        fotoHayDemanda = false;
        if (fotoFuenteCabecera == FUENTE_CARGA_MOVIL)
        {
            PosicionMovil p = PosicionMovilActiva();
            fotoCabeceraCaso = $"Carga movil · posicion {cargaMovilCabecera.Indice + 1}/{cargaMovilCabecera.CantidadPosiciones}"
                               + $" · x = {F(p.x, "0.00")} m · P = {F(cargaMovilCabecera.Anexo.P_kN, "0.##")} kN"
                               + $"\nUZ max {F(p.uz_min_mm, "0.000")} mm (nodo {p.nodo_uz_min})";
            fotoCabeceraDesp = "D/C: no se calcula para la carga movil (el NO PASA es del anexo)";
            return;
        }
        CasoResultado c = analizador.CasoMostrado;
        fotoCabeceraCaso = $"Reanalisis del servidor (modelo editado) · caso {c.nombre}"
                           + $"\nMax. componente {F(c.max_desplazamiento * 1000f, "0.00")} mm";
        fotoCabeceraDesp = "D/C: sin recalcular (anexo del modelo original)";
    }

    /// La posicion que muestra la carga movil, o null si no hay.
    PosicionMovil PosicionMovilActiva()
    {
        VisorCargaMovil v = cargaMovilCabecera;
        if (v == null || v.Anexo == null || v.Anexo.posiciones == null) return null;
        return v.Indice >= 0 && v.Indice < v.Anexo.posiciones.Count ? v.Anexo.posiciones[v.Indice] : null;
    }

    /// La carga repartida de una barra en un caso, leida tal cual de
    /// casos_de_carga (null si no tiene). No suma: es la que recibe OpenSees.
    static CargaDistribuida CargaRepartidaDe(ModeloEstructural m, string caso, int elemento)
    {
        if (m.casos_de_carga == null) return null;
        foreach (CasoDeCarga c in m.casos_de_carga)
        {
            if (c.nombre != caso || c.cargas_distribuidas == null) continue;
            foreach (CargaDistribuida q in c.cargas_distribuidas)
                if (q.elemento == elemento) return q;
        }
        return null;
    }

    /// La linea tenue de "Que lo carga" cuando el JSON no trae el desglose:
    /// Ingenieria no exporta q ni w por entrada, ni peso propio ni w total en
    /// G. Se dice en vez de mostrar ceros (JsonUtility deja 0 si falta).
    string NotaQueLoCarga(ModeloEstructural m, Elemento e)
    {
        foreach (AreaTributaria t in m.TributariasDe(e.id))
        {
            if (t.qG == 0f && t.carga_total == 0f)
                return "Este JSON no trae q ni w de la losa, ni peso propio ni w total en G: no hay desglose."
                       + (e.w_gravedad > 0f ? $" w_gravedad del elemento: {F(e.w_gravedad, "0.000")} kN/m (Python)." : "");
            if (!e.EsMuro && t.w_total_G <= 0f)
                return "Este JSON no trae w_peso_propio ni w_total_G: no se separa la losa del peso propio.";
        }
        return "";
    }

    // ============================================================
    // LA ESCALA GRAFICA DE LA DEFORMADA
    // ============================================================
    // Va al final de la clase para no correr las lineas que citan los
    // informes (CLAUDE.md seccion 6). El campo tambien.

    /// La escala grafica de la deformada ya la decidio alguien: el anexo
    /// la primera vez que se prende una, o el usuario con el deslizador.
    /// Desde entonces el panel no la vuelve a poner en cada redibujo.
    private bool escalaDelAnexoPuesta = false;

    /// La exageracion que el anexo de la Semana 4 recomienda para ESTE
    /// modelo (info.escala_deformada, calculada en Python: el mayor
    /// desplazamiento de todos sus casos llevado a una fraccion del
    /// tamano del edificio). 0 = no hay anexo o no trae el dato, y
    /// entonces no se toca nada: manda el valor que guardo la escena.
    float EscalaRecomendada()
    {
        if (s4 == null || s4.Anexo == null || s4.Anexo.info == null) return 0f;
        float e = s4.Anexo.info.escala_deformada;
        return e > 0f ? e : 0f;
    }

    /// La linea tenue debajo del deslizador: de donde sale el valor por
    /// defecto y cual es. El criterio entero viaja en el anexo, en
    /// info._escala_deformada_por_que.
    string NotaEscalaRecomendada(float reco)
    {
        if (reco <= 0f)
            return "Este anexo no trae escala recomendada: manda la escala que guardo la escena.";
        return $"Recomendada x{F(reco, "0")} para este modelo (del anexo): el mayor "
               + "desplazamiento de todos sus casos, dibujado como una fraccion del "
               + "tamano del edificio. El deslizador manda sobre ella.";
    }

    /// Pone la escala grafica, redibuja y deja dicho que ya esta
    /// decidida. Es el unico sitio que la mueve desde el panel.
    void FijarEscala(float escala)
    {
        escalaDelAnexoPuesta = true;
        visor.factorEscala = escala;
        visor.Redibujar();
        // Las barras de armadura siguen la deformada, asi que se
        // redibujan con la misma escala.
        if (s3 != null) s3.Redibujar();
        refrescar = true;
    }

    /// El valor por defecto del anexo, la primera vez que se prende una
    /// deformada. Se difiere a Update porque cambia el dibujo, y se
    /// protege con la bandera porque OnGUI corre varias veces por frame
    /// y cada evento lo encolaria otra vez.
    void FijarEscalaDelAnexo()
    {
        if (escalaDelAnexoPuesta) return;
        float reco = EscalaRecomendada();
        if (reco > 0f) FijarEscala(reco);
    }

    /// Para las capturas (CapturaSemana04/05): fijan su propia escala y
    /// no pasan por los botones del panel, asi que tienen que decir que
    /// ya esta decidida o el panel les pondria la del anexo encima.
    public void FijarEscalaAMano(float escala)
    {
        escalaDelAnexoPuesta = true;
        visor.factorEscala = escala;
    }

    /// Lo que se agrega a la linea del terreno en la pestana Vista: las
    /// TERRAZAS de info.terrenos (el terreno en niveles, que dibuja
    /// AmbienteVisor.Terrazas.cs). Vacio si el JSON no trae ninguna. Va al
    /// final de la clase: los documentos citan lineas de arriba.
    static string TextoTerrazas(InfoModelo info)
    {
        if (info == null || info.terrenos == null) return "";
        List<string> partes = new List<string>();
        foreach (NivelTerreno t in info.terrenos)
            if (t != null && t.vertices != null && t.vertices.Count >= 3
                && t.z > info.cota_terreno + AjustesVista.TOLERANCIA_COTA)
                partes.Add($"{Cota(t.z)} m ({t.nombre})");
        return partes.Count == 0 ? ""
            : " Terraza en " + string.Join(", ", partes) + ": ahi el terreno sube, bajo los apoyos de esa cota.";
    }
}


/// De donde sale la deformada que se esta mirando. Solo una a la vez:
/// la de gravedad viene precalculada en el JSON del modelo, las de
/// sismo del anexo de Semana 3 y la del caso activo del de Semana 4.
public enum ModoDeformada { Sin, Gravedad, SismoEX, SismoEY, CasoActivo }


/// Mantiene el texto 3D mirando a la camara; si no, los IDs se leen
/// al reves desde la mitad de los angulos.
public class MirarCamara : MonoBehaviour
{
    void LateUpdate()
    {
        if (Camera.main == null) return;
        transform.rotation = Camera.main.transform.rotation;
    }
}
