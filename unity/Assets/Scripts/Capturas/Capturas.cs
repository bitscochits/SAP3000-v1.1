/*
================================================================
  Capturas.cs
================================================================
  La app de Windows saca sus fotos y su REGISTRO sola, sin que nadie
  toque nada:

      build/LaboratorioEstructural.exe -capturar <modo> <carpeta>
                                       [-m1 <columna>,<nodo>,<viga>]

  La lanza 'python sap.py capturar <modo>' (herramientas/lanzador.py,
  capturar), que pone la carpeta (verificacion/registros/capturas/<modo>)
  y, en el modo visor, los ids de la M1 de entrada/laboratorio.json
  (modificaciones.M1). Sin -capturar no hace nada: ni siquiera crea su
  objeto. Es una herramienta de verificacion, no parte del visor.

  LOS CUATRO MODOS (cada uno con el formato de registro.txt de siempre)
    visor      vista realista y tecnica, una foto por pestana, las seis
               preguntas del visor (donde esta, como esta apoyado, que lo
               carga, como se deforma, que fuerzas tiene, cuanta capacidad
               tiene), E1..E3 precalculados, LIBRE pedido al servidor, los
               sliders instantaneos, dos posiciones de la carga movil y la
               M1. registro.txt en lineas "DATO clave = valor" que
               verificacion/capturas.py (bloque visor) cruza con Python.
    diagramas  los diagramas de esfuerzos y la P-M: columna demo, My, N,
               wz y Vz de un piso, una viga con su parabola, las capas, el
               muro demo y la deformada de una combinacion, con el texto
               del inspector de cada barra (VisorResultados.DescribirElemento).
    persona    la pestana Persona con su deformada: el registro lleva lo
               que Unity SUMO (VisorPersona.Captura_Registro, float en G9),
               que verificacion/persona.py (bloque registro) cruza con
               OpenSees resolviendo esa misma carga directo.
    relieve    el relieve del sitio: cuatro fotos y lo que dice
               AjustesVista.relieveEstado; verificacion/capturas.py (bloque
               relieve) lo compara con relieve.json.

  TODOS terminan el registro con
      DATO archivos.<nombre>.md5 = ...   el md5 de cada archivo que la app
                                         lee de StreamingAssets (los nombres
                                         de calculo/rutas.NOMBRES_EN_UNITY):
                                         asi se ve un registro VENCIDO, hecho
                                         con otros datos que los de salidas/
      DATO log.errores = N               errores y excepciones del log
      DATO salida = codigo
  y la app sale con Application.Quit(codigo): 0 si salio bien; 2 si falto
  algo, hubo una excepcion o se paso el tope de tiempo (TOPE_TOTAL_S).

  ----------------------------------------------------------------
  REGLA QUE NO SE ROMPE: aca no se calcula estructura
  ----------------------------------------------------------------
  Cada numero del registro es un campo leido tal cual: del JSON que
  cargo el visor o de la respuesta del servidor. Van con "G9", que
  escribe el float de 32 bits de forma que vuelve exacto: la
  comparacion en Python ve lo que tenia Unity en memoria, no un
  redondeo de pantalla. Lo unico que aca se ELIGE son la viga y el
  nodo de control de la superposicion, con la regla escrita en
  entrada/laboratorio.json (superposicion.control.reglas: mayor |My| y
  mayor desplazamiento bajo E1); verificacion/capturas.py comprueba que
  salen los mismos ids que en Python.

  ----------------------------------------------------------------
  EL ORDEN DEL MODO VISOR IMPORTA
  ----------------------------------------------------------------
  Primero lo que funciona sin servidor (vista, panel, preguntas, E1..E3
  precalculados, sliders instantaneos, carga movil), despues LIBRE (POST
  /combinar) y al FINAL la M1: borrar la columna deja los resultados
  desactualizados y apaga la carga movil, y desde ahi ya no se puede
  mostrar nada precalculado. Sin servidor (/ping no responde) LIBRE y M1
  quedan en el registro como no hechas y la captura termina igual.

  Lo que toca del panel y de la camara va por API publica
  (PanelVisor.Capturas_*, VisorResultados.EquilibriosDeSuperposicion,
  CamaraOrbital.FijarAngulos, VisorPersona.Captura_*), no por reflexion:
  si algo cambia de nombre, la app no compila, en vez de sacar una foto
  de otra parte del panel sin avisar.
================================================================
*/

using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

public class Capturas : MonoBehaviour
{
    public const string MODO_VISOR = "visor";
    public const string MODO_DIAGRAMAS = "diagramas";
    public const string MODO_PERSONA = "persona";
    public const string MODO_RELIEVE = "relieve";
    static readonly string[] MODOS = { MODO_VISOR, MODO_DIAGRAMAS, MODO_PERSONA, MODO_RELIEVE };

    // 1600x900 en ventana: cabe en un monitor de 1080p y deja el panel (a
    // 125 % de escala mide unos 520 px) sin tapar medio edificio. Los
    // diagramas van a 1920x1080, como siempre: el inspector de la barra es
    // largo y la P-M va al fondo del panel.
    const int ANCHO = 1600, ALTO = 900;
    const int ANCHO_DIAGRAMAS = 1920, ALTO_DIAGRAMAS = 1080;
    const int CALIDAD_JPG = 90;

    // Tope de toda la captura: un servidor que se cuelga o un archivo que
    // no llega no pueden dejar el exe abierto (el lanzador espera a que el
    // proceso muera, y corta a los 1200 s).
    const float TOPE_TOTAL_S = 900f;

    // Persona y relieve: cuanto se espera a que carguen el modelo y su JSON.
    const float TOPE_ESPERA_S = 90f;

    // La posicion de la carga movil de la defensa (P en la viga 200205 del
    // recorrido). La otra es la de mayor flecha bajo la carga, que el JSON
    // dice cual es (info.indice_uz_bajo_carga_min).
    const int POSICION_DEFENSA = 12;

    // El peso de la persona en su captura.
    const float P_PERSONA_KN = 100f;

    private string modo;
    private string carpeta;
    private string textoM1;                 // lo que vino tras -m1, o null
    private int columnaM1 = -1, nodoM1 = -1, barraM1 = -1;
    private readonly StringBuilder registro = new StringBuilder();
    private readonly List<string> erroresDelLog = new List<string>();
    private int nErroresDelLog = 0;
    private int nFotos = 0;
    private int anchoFoto, altoFoto;       // el tamano de la ultima foto (el de la textura)
    private bool saliendo = false;
    private bool huboError = false;         // algo fallo pero la captura siguio: sale con 2
    private float inicio = -1f;

    private VisorEstructura visor;
    private PanelVisor qa;
    private VisorResultados s4;
    private VisorCargasYArmadura s3;
    private CamaraOrbital cam;
    private EditorEstructura editor;
    private ClienteReanalisis analizador;
    private VisorCargaMovil movil;
    private VisorPersona persona;
    private bool hayServidor = false;

    // La pestana y el scroll que se fijaron para la foto que viene.
    private string pestanaEsperada;
    private float scrollEsperado;

    // ============================================================
    // ARRANQUE
    // ============================================================
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Arrancar()
    {
        string[] args = Environment.GetCommandLineArgs();
        string modo = null, carpeta = null, m1 = null;
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "-capturar" && i + 2 < args.Length)
            {
                modo = args[i + 1];
                carpeta = args[i + 2];
            }
            else if (args[i] == "-m1" && i + 1 < args.Length)
            {
                m1 = args[i + 1];
            }
        }
        if (modo == null) return;
        var go = new GameObject("Capturas");
        Capturas c = go.AddComponent<Capturas>();
        c.modo = modo;
        c.carpeta = carpeta;
        c.textoM1 = m1;
    }

    void OnEnable() { Application.logMessageReceived += AlLog; }
    void OnDisable() { Application.logMessageReceived -= AlLog; }

    /// Los errores y excepciones de cualquier script durante la captura van
    /// al registro: una foto puede salir bien con un suscriptor reventando
    /// por detras. Persona y relieve los escriben en el momento, como
    /// siempre; el relieve, ademas, lo que informa AmbienteVisor.
    void AlLog(string texto, string pila, LogType tipo)
    {
        bool error = tipo == LogType.Error || tipo == LogType.Exception || tipo == LogType.Assert;
        if (error)
        {
            nErroresDelLog++;
            if (modo == MODO_PERSONA || modo == MODO_RELIEVE) Linea("ERROR del log: " + texto);
            else if (erroresDelLog.Count < 25) erroresDelLog.Add(tipo + ": " + Recortar(texto, 300));
        }
        else if (modo == MODO_RELIEVE && texto.StartsWith("AmbienteVisor:"))
        {
            Linea(texto);
        }
    }

    void Update()
    {
        if (saliendo || inicio < 0f) return;
        if (Time.realtimeSinceStartup - inicio <= TOPE_TOTAL_S) return;
        saliendo = true;
        Linea("ERROR: la captura paso el tope de " + TOPE_TOTAL_S + " s; se corta aca.");
        Cierre(2);
        Escribir();
        Application.Quit(2);
    }

    /// Corre la captura a mano, con las corrutinas anidadas en una pila,
    /// para atrapar una excepcion en CUALQUIER paso: un iterador de C# no
    /// deja poner yield dentro de un try con catch, y una excepcion en una
    /// corrutina de Unity solo se loguea y la deja muerta (el exe quedaria
    /// abierto sin registro).
    IEnumerator Start()
    {
        inicio = Time.realtimeSinceStartup;
        // Sin foco la app se pausa (runInBackground = 0 en el proyecto): la
        // captura no puede depender de que nadie toque otra ventana.
        Application.runInBackground = true;
        if (modo == MODO_DIAGRAMAS) Screen.SetResolution(ANCHO_DIAGRAMAS, ALTO_DIAGRAMAS, FullScreenMode.Windowed);
        else Screen.SetResolution(ANCHO, ALTO, FullScreenMode.Windowed);

        if (string.IsNullOrEmpty(carpeta) || Array.IndexOf(MODOS, modo) < 0)
        {
            // Sin carpeta valida no hay donde escribir: se dice en el log.
            Debug.LogError("Capturas: uso -capturar <" + string.Join("|", MODOS) + "> <carpeta> "
                           + "[-m1 columna,nodo,viga]; vino modo '" + modo + "', carpeta '" + carpeta + "'");
            if (!string.IsNullOrEmpty(carpeta))
            {
                Directory.CreateDirectory(carpeta);
                Linea("ERROR: modo desconocido '" + modo + "' (son: " + string.Join(", ", MODOS) + ")");
                Cierre(2);
                Escribir();
            }
            Application.Quit(2);
            yield break;
        }
        Directory.CreateDirectory(carpeta);

        IEnumerator captura = modo == MODO_VISOR ? CapturarVisor()
                            : modo == MODO_DIAGRAMAS ? CapturarDiagramas()
                            : modo == MODO_PERSONA ? CapturarPersona()
                            : CapturarRelieve();
        var pila = new Stack<IEnumerator>();
        pila.Push(captura);
        while (pila.Count > 0)
        {
            IEnumerator arriba = pila.Peek();
            bool sigue;
            string error = null;
            try
            {
                sigue = arriba.MoveNext();
            }
            catch (Exception ex)
            {
                sigue = false;
                error = ex.ToString();
            }
            if (error != null)
            {
                Linea("ERROR: excepcion en la captura: " + error);
                yield return Salir(2);
                yield break;
            }
            if (!sigue) { pila.Pop(); continue; }
            IEnumerator sub = arriba.Current as IEnumerator;
            if (sub != null) { pila.Push(sub); continue; }
            yield return arriba.Current;
        }
        if (!saliendo) yield return Salir(huboError ? 2 : 0);
    }

    IEnumerator Salir(int codigo)
    {
        if (saliendo) yield break;
        saliendo = true;
        Cierre(codigo);
        Escribir();
        yield return new WaitForSecondsRealtime(0.5f);
        Application.Quit(codigo);
    }

    /// Las ultimas lineas de todo registro: con que datos se hizo y como salio.
    void Cierre(int codigo)
    {
        Linea("");
        Archivos();
        Dato("log.errores", nErroresDelLog);
        Dato("salida", codigo);
    }

    /// El md5 de cada archivo que la app lee de StreamingAssets, con el
    /// nombre corto de calculo/rutas.NOMBRES_EN_UNITY. verificacion/capturas.py
    /// los compara con salidas/: si no calzan, el registro es de otros datos.
    void Archivos()
    {
        string[,] archivos = {
            { "modelo", VisorEstructura.ARCHIVO },
            { "resultados", VisorResultados.ARCHIVO },
            { "carga_movil", VisorCargaMovil.ARCHIVO },
            { "persona", VisorPersona.ARCHIVO },
            { "relieve", AmbienteVisor.ARCHIVO },
            { "excel", LectorStreaming.EXCEL_RESULTADOS },
        };
        for (int i = 0; i < archivos.GetLength(0); i++)
        {
            string ruta = Path.Combine(Application.streamingAssetsPath, archivos[i, 1]);
            string md5 = "falta";
            try
            {
                if (File.Exists(ruta))
                {
                    using (MD5 h = MD5.Create())
                    using (FileStream f = File.OpenRead(ruta))
                    {
                        byte[] b = h.ComputeHash(f);
                        var sb = new StringBuilder(32);
                        foreach (byte x in b) sb.Append(x.ToString("x2", CultureInfo.InvariantCulture));
                        md5 = sb.ToString();
                    }
                }
            }
            catch (Exception ex)
            {
                md5 = "no se pudo leer: " + ex.Message;
            }
            Dato("archivos." + archivos[i, 0] + ".md5", md5);
        }
    }

    void Buscar()
    {
        if (visor == null) visor = FindAnyObjectByType<VisorEstructura>();
        if (qa == null) qa = FindAnyObjectByType<PanelVisor>();
        if (s4 == null) s4 = FindAnyObjectByType<VisorResultados>();
        if (s3 == null) s3 = FindAnyObjectByType<VisorCargasYArmadura>();
        if (cam == null) cam = FindAnyObjectByType<CamaraOrbital>();
        if (editor == null) editor = FindAnyObjectByType<EditorEstructura>();
        if (analizador == null) analizador = FindAnyObjectByType<ClienteReanalisis>();
        if (movil == null) movil = FindAnyObjectByType<VisorCargaMovil>();
        if (persona == null) persona = FindAnyObjectByType<VisorPersona>();
    }

    // ============================================================
    // MODO VISOR
    // ============================================================
    IEnumerator CapturarVisor()
    {
        Linea("CAPTURA VISOR   "
              + DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss", CultureInfo.InvariantCulture));
        Linea("Numeros leidos de lo que Unity cargo (float de 32 bits, formato G9).");

        // Todos los lectores son corrutinas (LectorStreaming): se espera a
        // que cada uno termine, con tope, en vez de un tiempo fijo.
        yield return new WaitForSecondsRealtime(2f);
        float tope = Time.realtimeSinceStartup + 60f;
        yield return new WaitUntil(() => Time.realtimeSinceStartup > tope || TodoLeido());
        Buscar();
        if (visor == null || qa == null || s4 == null || cam == null || !visor.Listo || s4.Anexo == null)
        {
            Linea("ERROR: falta VisorEstructura listo, PanelVisor, VisorResultados con resultados o CamaraOrbital. "
                  + "Aviso de los resultados: " + (s4 != null ? s4.Aviso : "(sin VisorResultados)"));
            yield return Salir(2);
            yield break;
        }

        yield return ProbarServidor();
        // VisorResultados pide GET /estados al arrancar y reintenta cada 10 s:
        // con servidor se le da ese margen para que el panel diga "conectado".
        if (hayServidor)
        {
            float topeEstados = Time.realtimeSinceStartup + 12f;
            yield return new WaitUntil(() => s4.ServidorConectado || Time.realtimeSinceStartup > topeEstados);
        }

        InfoResultados info = s4.Anexo.info;
        string ed = info != null ? (info.edificio ?? "") : "";
        Encabezado(ed);
        Escribir();

        // Punto de partida comun: sin seleccion, sin deformada, sin
        // diagramas ni ventana P-M (la P-M sale DENTRO del panel, en la
        // pestana Elemento; la ventana flotante taparia el modelo).
        if (s3 != null && s3.jaulaDetalle) { s3.jaulaDetalle = false; s3.Redibujar(); }
        s4.mostrarPM = false;
        s4.mostrarDiagramas = false;
        s4.multiplicadorEscala = 1f;
        s4.soloSeleccionado = true;
        qa.verApoyos = true;
        qa.ElegirPiso(-1);
        qa.LimpiarSeleccion();
        Modo(ModoDeformada.Sin);
        if (!string.IsNullOrEmpty(info.caso_por_defecto)) s4.ElegirCaso(info.caso_por_defecto);
        yield return null;

        yield return VistaGeneral();
        yield return PestanasDelPanel(info);
        yield return Preguntas(info);
        yield return Superposicion(info);
        yield return SuperposicionInstantanea(info);
        yield return CargaMovil();
        yield return M1();

        Seccion("FIN");
        Dato("fotos", nFotos);
        Dato("segundos", Time.realtimeSinceStartup - inicio);
        foreach (string e in erroresDelLog) Linea("  log | " + e);
    }

    bool TodoLeido()
    {
        Buscar();
        bool movilListo = movil == null || movil.Anexo != null || !string.IsNullOrEmpty(movil.Aviso);
        return visor != null && visor.Listo && s4 != null && s4.Anexo != null
               && s4.SuperposicionLeida && movilListo;
    }

    IEnumerator ProbarServidor()
    {
        string url = analizador != null ? analizador.UrlPing() : (s4.urlServidor ?? "").TrimEnd('/') + "/ping";
        using (UnityWebRequest req = UnityWebRequest.Get(url))
        {
            req.timeout = 5;
            yield return req.SendWebRequest();
            hayServidor = req.result == UnityWebRequest.Result.Success;
            Dato("servidor.url", url);
            Dato("servidor.responde", hayServidor);
            if (!hayServidor) Dato("servidor.error", req.error);
        }
    }

    void Encabezado(string ed)
    {
        Seccion("EQUIPO Y DATOS CARGADOS");
        Dato("edificio", ed);
        Dato("equipo.modelo", SystemInfo.deviceModel);
        Dato("equipo.cpu", SystemInfo.processorType + " (" + SystemInfo.processorCount + " hilos)");
        Dato("equipo.so", SystemInfo.operatingSystem);
        Dato("equipo.gpu", SystemInfo.graphicsDeviceName + " (" + SystemInfo.graphicsDeviceVersion + ")");
        Dato("equipo.ram_mb", SystemInfo.systemMemorySize);
        Dato("equipo.vram_mb", SystemInfo.graphicsMemorySize);
        Dato("pantalla", Screen.width + "x" + Screen.height);
        Dato("pantalla.dpi", Screen.dpi);
        Dato("panel.escala", PanelUI.Escala());
        Dato("panel.rect", qa.RectPanel().ToString());
        Dato("unity", Application.unityVersion);
        Dato("plataforma", Application.platform.ToString());

        // El boton "Abrir Excel de resultados" usa esta misma ruta.
        string ruta = LectorStreaming.RutaExcelResultados();
        string mostrada = ruta ?? Path.Combine(Application.streamingAssetsPath, LectorStreaming.EXCEL_RESULTADOS);
        bool existe = ruta != null && File.Exists(ruta);
        Linea("Excel: " + mostrada + " existe=" + existe);
        Dato("excel.ruta", mostrada);
        Dato("excel.existe", existe);

        ModeloEstructural m = visor.Modelo;
        Dato("modelo.nodos", m.nodos.Count);
        Dato("modelo.elementos", m.elementos.Count);
        Dato("modelo.cota_terreno", m.info != null ? m.info.cota_terreno : -9999f);
        Dato("anexo.edificio", ed);
        Dato("anexo.casos", s4.Anexo.casos.Count);
        Dato("anexo.calza", s4.AnexoCalzaConElModelo);
        Dato("anexo.aviso", s4.Aviso);
        Dato("anexo.caso_por_defecto", s4.Anexo.info.caso_por_defecto);
        Dato("anexo.columna_demo", s4.Anexo.info.columna_demo);
        Dato("anexo.muro_demo", s4.Anexo.info.muro_demo);
        Dato("superposicion.estados", s4.EstadosSuperposicion.Count);
        var nombres = new List<string>();
        foreach (EstadoSuperposicion e in s4.EstadosSuperposicion)
            nombres.Add(e.nombre + (s4.EsPrecalculado(e.nombre) ? "(precalculado)" : ""));
        Dato("superposicion.nombres", string.Join(",", nombres.ToArray()));
        Dato("superposicion.aviso", s4.AvisoSuperposicion);
        Dato("superposicion.servidor_conectado", s4.ServidorConectado);
        Dato("movil.hay", movil != null);
        Dato("movil.posiciones", movil != null ? movil.CantidadPosiciones : 0);
        Dato("movil.aviso", movil != null ? movil.Aviso : "(no hay VisorCargaMovil en la escena)");
        Dato("pestanas", string.Join("|", qa.Capturas_TitulosPestanas().ToArray()));
    }

    // ------------------------------------------------------------
    // A. VISTA GENERAL
    // ------------------------------------------------------------
    IEnumerator VistaGeneral()
    {
        Seccion("A. VISTA GENERAL");
        AjustesVista.realista = true;
        AjustesVista.suelo = true;
        AjustesVista.relieve = false;      // el relieve del sitio tiene su propio modo
        EventosVisor.AvisarVistaCambio();
        EncuadreGeneral();
        Pestana(PanelVisor.PESTANA_VISTA);
        yield return Foto("01_vista_general_realista_con_suelo");

        AjustesVista.realista = false;
        EventosVisor.AvisarVistaCambio();
        Pestana(PanelVisor.PESTANA_VISTA);
        yield return Foto("02_vista_general_tecnica");

        // El resto con la vista por defecto, la realista.
        AjustesVista.realista = true;
        EventosVisor.AvisarVistaCambio();
    }

    // ------------------------------------------------------------
    // B. UNA FOTO POR PESTANA
    // ------------------------------------------------------------
    IEnumerator PestanasDelPanel(InfoResultados info)
    {
        Seccion("B. PANEL: UNA FOTO POR PESTANA");
        // Con la columna demo elegida: Elemento y Modificar tienen algo que decir.
        qa.SeleccionarElemento(info.columna_demo);
        EncuadreGeneral();
        string[] pestanas = {
            PanelVisor.PESTANA_VISTA, PanelVisor.PESTANA_CAPAS, PanelVisor.PESTANA_CASO,
            PanelVisor.PESTANA_ELEMENTO, PanelVisor.PESTANA_MODIFICAR, PanelVisor.PESTANA_CARGA_MOVIL };
        for (int i = 0; i < pestanas.Length; i++)
        {
            Pestana(pestanas[i]);
            yield return Foto((3 + i).ToString("00") + "_panel_" + ParaArchivo(pestanas[i]));
        }
    }

    // ------------------------------------------------------------
    // C. LAS PREGUNTAS DEL VISOR
    // ------------------------------------------------------------
    IEnumerator Preguntas(InfoResultados info)
    {
        Seccion("C. LAS PREGUNTAS DEL VISOR");
        ModeloEstructural m = visor.Modelo;
        int col = info.columna_demo;

        // --- 09. Donde esta: "Ir a ID" (campo + boton), centrar e inspector.
        qa.LimpiarSeleccion();
        PlegarInspectorElemento();
        PanelUI.FijarPlegable("qa.elem.identificacion", true);
        Pestana(PanelVisor.PESTANA_ELEMENTO);
        // Alto (38 grados): la columna demo esta en el subterraneo, y con las
        // secciones solidas de la vista realista solo se ve mirando dentro
        // del hoyo.
        Angulo(38f, 35f);
        qa.Capturas_IrA(EventosVisor.TIPO_ELEMENTO, col);
        // "Su piso" (el filtro de piso de la seleccion): lo de arriba queda en
        // lineas grises y la columna se ve. Se vuelve a "todos" antes de la 12.
        qa.ElegirPiso(qa.NivelDeLaSeleccion());
        yield return null;
        // "Ir a ID" acerca hasta que la barra llena la vista; se aleja para
        // que se vea en que parte del edificio esta (el centro no cambia).
        cam.distancia = Mathf.Max(cam.distancia, 28f);
        Elemento ec = m.ElementoPorId(col);
        yield return Foto("09_donde_esta_columna_" + col, "Identificacion");
        Dato("ux.donde.seleccion", qa.TipoSeleccionado + " " + qa.IdSeleccionado);
        if (ec != null)
        {
            Dato("ux.donde.tipo", ec.tipo);
            Dato("ux.donde.seccion", ec.seccion);
            NodoXYZ("ux.donde.n1", m.NodoPorId(ec.n1));
            NodoXYZ("ux.donde.n2", m.NodoPorId(ec.n2));
            Dato("ux.donde.unity_n1", Ejes.PosicionDe(m.NodoPorId(ec.n1)).ToString("F3"));
            Dato("ux.donde.unity_n2", Ejes.PosicionDe(m.NodoPorId(ec.n2)).ToString("F3"));
        }
        Dato("ux.donde.camara_centro", cam.centro.ToString("F3"));

        // --- 10. Como esta apoyado: el nodo de apoyo de la columna demo.
        int apoyo = -1;
        if (ec != null)
        {
            Nodo a = m.NodoPorId(ec.n1), b = m.NodoPorId(ec.n2);
            if (a != null && b != null) apoyo = a.z <= b.z ? a.id : b.id;
        }
        if (apoyo >= 0)
        {
            PlegarInspectorNodo();
            PanelUI.FijarPlegable("qa.nodo.ubicacion", true);
            PanelUI.FijarPlegable("qa.nodo.apoyo", true);
            PanelUI.FijarPlegable("qa.nodo.diafragma", true);
            qa.SeleccionarNodo(apoyo);
            qa.ElegirPiso(qa.NivelDeLaSeleccion());
            // Desde arriba del borde del hoyo: a 18 grados el terreno tapaba
            // el apoyo del subterraneo.
            Angulo(40f, 35f);
            qa.CentrarSeleccion();
            yield return null;
            cam.distancia = Mathf.Max(cam.distancia, 22f);
            Pestana(PanelVisor.PESTANA_ELEMENTO);
            yield return Foto("10_como_esta_apoyado_nodo_" + apoyo, "Donde esta", "Como esta apoyado", "Diafragma");
            Nodo n = m.NodoPorId(apoyo);
            Dato("ux.apoyo.nodo", apoyo);
            Dato("ux.apoyo.fijo", n.fijo);
            Dato("ux.apoyo.restricciones", n.restricciones);
            Dato("ux.apoyo.auxiliar", n.auxiliar);
            NodoXYZ("ux.apoyo", n);
        }

        // --- 11. Que lo carga: area tributaria y carga repartida de una viga.
        int viga = VigaConTributaria(m, VigaControl());
        if (viga >= 0)
        {
            string casoG = s4.Anexo.casos.Exists(x => x != null && x.nombre == "G") ? "G" : info.caso_por_defecto;
            s4.ElegirCaso(casoG);
            s4.mostrarDiagramas = true;
            s4.soloSeleccionado = true;
            s4.magnitud = "wz";
            qa.verAreasTributarias = true;
            qa.Capturas_Refrescar();
            qa.SeleccionarElemento(viga);
            qa.ElegirPiso(qa.NivelDeLaSeleccion());
            s4.Redibujar();
            s4.EnfocarElemento(viga);
            Encuadrar(cam.centro, Mathf.Max(cam.distancia, 16f), 48f, 30f);
            PlegarInspectorElemento();
            PanelUI.FijarPlegable("qa.elem.tributaria", true);
            PanelUI.FijarPlegable("qa.s4.esfuerzos", true);
            Pestana(PanelVisor.PESTANA_ELEMENTO);
            yield return Foto("11_que_lo_carga_viga_" + viga + "_area_tributaria_y_w_" + casoG,
                              "Que lo carga", "Esfuerzos");
            Dato("ux.carga.viga", viga);
            Dato("ux.carga.caso", s4.casoActivo);
            List<AreaTributaria> trib = m.TributariasDe(viga);
            Dato("ux.carga.entradas", trib.Count);
            Dato("ux.carga.area_total_m2", m.AreaTributariaTotal(viga));
            for (int i = 0; i < trib.Count; i++)
            {
                string p = "ux.carga.trib" + i;
                Dato(p + ".area_m2", trib[i].area);
                Dato(p + ".qG_kN_m2", trib[i].qG);
                Dato(p + ".carga_total_kN", trib[i].carga_total);
                Dato(p + ".w_kN_m", trib[i].w);                        // w_losa
                Dato(p + ".w_peso_propio_kN_m", trib[i].w_peso_propio);
                Dato(p + ".w_total_G_kN_m", trib[i].w_total_G);        // lo que recibe OpenSees en G
                Dato(p + ".luz_m", trib[i].luz);
                Dato(p + ".n_poligonos", trib[i].n_poligonos);
            }
            if (m.casos_de_carga != null)
                foreach (CasoDeCarga c in m.casos_de_carga)
                {
                    if (c.cargas_distribuidas == null) continue;
                    foreach (CargaDistribuida q in c.cargas_distribuidas)
                        if (q.elemento == viga)
                            Dato("ux.carga.distribuida." + c.nombre, new[] { q.wx, q.wy, q.wz });
                }
            EsfuerzosBarra sw = s4.EsfuerzosDe(viga);
            if (sw != null) Dato("ux.carga.anexo_w_local." + s4.casoActivo, sw.w);
            Dato("ux.carga.motivo_sin_diagrama", s4.MotivoSinDiagrama);
            qa.verAreasTributarias = false;
            qa.Capturas_Refrescar();
        }

        // --- 12. Como se deforma: la deformada del caso activo y el nodo de control.
        qa.ElegirPiso(-1);
        s4.mostrarDiagramas = false;
        s4.ElegirCaso(info.caso_por_defecto);
        s4.Redibujar();
        qa.FijarEscalaAMano(300f);   // la captura fija la suya, no la recomendada
        Modo(ModoDeformada.CasoActivo);
        int nodo = NodoControl();
        PlegarInspectorNodo();
        PanelUI.FijarPlegable("qa.nodo.desplazamiento", true);
        if (nodo >= 0) qa.SeleccionarNodo(nodo);
        EncuadreGeneral();
        Pestana(PanelVisor.PESTANA_ELEMENTO);
        yield return Foto("12_como_se_deforma_" + s4.casoActivo + "_nodo_" + nodo, "Desplazamiento");
        CasoLab activo = s4.CasoActivo();
        Dato("ux.deforma.caso", s4.casoActivo);
        if (activo != null)
        {
            Dato("ux.deforma.descripcion", activo.descripcion);
            Dato("ux.deforma.max_desplazamiento_mm", activo.max_desplazamiento_mm);
            DespNodo d = Desp(activo.desplazamientos, nodo);
            if (d != null)
            {
                Dato("ux.deforma.nodo", nodo);
                Dato("ux.deforma.ux_m", d.ux);
                Dato("ux.deforma.uy_m", d.uy);
                Dato("ux.deforma.uz_m", d.uz);
                Dato("ux.deforma.rx_rad", d.rx);
                Dato("ux.deforma.ry_rad", d.ry);
                Dato("ux.deforma.rz_rad", d.rz);
            }
        }
        Dato("ux.deforma.hay_deformada", visor.mostrarDeformada && visor.HayDeformada);
        Dato("ux.deforma.escala", visor.factorEscala);
        Nodo nd = nodo >= 0 ? m.NodoPorId(nodo) : null;
        if (nd != null)
        {
            // Donde lo dibuja el visor contra donde esta en el modelo: prueba
            // que la deformada puesta es la de este caso (no calcula nada).
            Dato("ux.deforma.dibujado_unity", visor.PosicionActual(nd).ToString("F4"));
            Dato("ux.deforma.original_unity", Ejes.PosicionDe(nd).ToString("F4"));
        }
        Modo(ModoDeformada.Sin);

        // --- 13. Que fuerzas tiene: diagrama My de la viga y la tabla del inspector.
        if (viga >= 0)
        {
            s4.mostrarDiagramas = true;
            s4.soloSeleccionado = true;
            s4.magnitud = "My";
            qa.SeleccionarElemento(viga);
            qa.ElegirPiso(qa.NivelDeLaSeleccion());
            s4.Redibujar();
            s4.EnfocarElemento(viga);
            // 24 y no 12 grados: con vigas solidas (realista) las del frente
            // tapaban la parte del diagrama que cuelga bajo la viga.
            Encuadrar(cam.centro, cam.distancia, 24f, 20f);
            PlegarInspectorElemento();
            PanelUI.FijarPlegable("qa.s4.esfuerzos", true);
            Pestana(PanelVisor.PESTANA_ELEMENTO);
            yield return Foto("13_que_fuerzas_tiene_viga_" + viga + "_My_" + s4.casoActivo, "Esfuerzos");
            Dato("ux.fuerzas.viga", viga);
            Dato("ux.fuerzas.caso", s4.casoActivo);
            Dato("ux.fuerzas.magnitud", s4.magnitud);
            Esfuerzos("ux.fuerzas", s4.EsfuerzosDe(viga));
            Dato("ux.fuerzas.motivo_sin_diagrama", s4.MotivoSinDiagrama);
            Dato("ux.fuerzas.aviso_de_lectura", s4.AvisoDeLectura);
            s4.mostrarDiagramas = false;
            s4.Redibujar();
        }
        // El mapa D/C de la 14 y todo lo que sigue es con el edificio entero.
        qa.ElegirPiso(-1);

        // --- 14. Cuanta capacidad tiene: P-M de la columna demo y mapa D/C en
        //         la combinacion con mas NO PASA.
        string masNoPasa = s4.CasoConMasNoPasa();
        if (!string.IsNullOrEmpty(masNoPasa)) s4.ElegirCaso(masNoPasa);
        s4.MostrarMapaDC(true);
        qa.SeleccionarElemento(col);
        PlegarInspectorElemento();
        PanelUI.FijarPlegable("qa.s4.demanda / capacidad", true);
        PanelUI.FijarPlegable("qa.elem.pm", true);
        EncuadreGeneral();
        Pestana(PanelVisor.PESTANA_ELEMENTO);
        // La curva P-M va bajo "Demanda / capacidad": se lleva el scroll ahi
        // para que la foto muestre las dos.
        yield return ScrollA("qa.s4.demanda / capacidad", 6f);
        yield return Foto("14_capacidad_columna_" + col + "_PM_y_mapa_DC_" + s4.casoActivo, "Demanda");
        CasoLab cc = s4.CasoActivo();
        Dato("ux.capacidad.caso_con_mas_no_pasa", masNoPasa);
        Dato("ux.capacidad.mapa_activo", s4.MapaDCActivo);
        Dato("ux.capacidad.mapa_pintadas", s4.MapaDCPintadas);
        if (cc != null)
        {
            int noPasan, fuera, total;
            VisorResultados.ContarDemandas(cc, out noPasan, out fuera, out total);
            Dato("ux.capacidad.no_pasan", noPasan);
            Dato("ux.capacidad.fuera_de_curva", fuera);
            Dato("ux.capacidad.con_fierro", total);
            Demanda("ux.capacidad.elem." + col, s4.DemandaDe(col, cc.nombre));
            ElementoOpenSees e4 = s4.ElementoPorId(col);
            if (e4 != null && e4.familia >= 0 && s4.Anexo.familias != null && e4.familia < s4.Anexo.familias.Count)
                Dato("ux.capacidad.familia", s4.Anexo.familias[e4.familia].clave);
            NoPasan("ux.capacidad", cc);
        }

        // 14b. La leyenda del mapa y la lista de criticos, en la pestana Caso.
        PlegarPestanaCaso();
        PanelUI.FijarPlegable("mapa.dc", true);
        PanelUI.FijarPlegable("mapa.criticos", true);
        Pestana(PanelVisor.PESTANA_CASO);
        yield return Foto("14b_mapa_DC_leyenda_y_criticos_" + s4.casoActivo);
        s4.MostrarMapaDC(false);
        qa.LimpiarSeleccion();
    }

    // ------------------------------------------------------------
    // D. SUPERPOSICION: E1..E3 precalculados y E3 pedido al servidor
    // ------------------------------------------------------------
    IEnumerator Superposicion(InfoResultados info)
    {
        Seccion("D. SUPERPOSICION");
        int col = info.columna_demo, mur = info.muro_demo;
        int viga = VigaControl(), nodo = NodoControl();
        Dato("control.columna", col);
        Dato("control.muro", mur);
        Dato("control.viga", viga);
        Dato("control.nodo", nodo);
        int[] elementos = { col, mur, viga };

        qa.LimpiarSeleccion();
        s4.mostrarDiagramas = false;
        qa.FijarEscalaAMano(200f);   // la captura fija la suya, no la recomendada
        s4.MostrarMapaDC(true);
        PlegarPestanaCaso();
        PanelUI.FijarPlegable("sup.superposicion", true);
        PanelUI.FijarPlegable("mapa.dc", true);

        int n = 15;
        EstadoSuperposicion ultimo = null;
        bool deformadaPuesta = false;
        foreach (EstadoSuperposicion est in new List<EstadoSuperposicion>(s4.EstadosSuperposicion))
        {
            if (est == null) continue;
            if (!s4.EsPrecalculado(est.nombre))
            {
                Linea("AVISO: " + est.nombre + " no esta precalculado: " + s4.AvisoSuperposicion);
                continue;
            }
            ultimo = est;
            s4.ElegirCaso(est.nombre);
            if (!deformadaPuesta) { Modo(ModoDeformada.CasoActivo); deformadaPuesta = true; }
            EncuadreGeneral();
            Pestana(PanelVisor.PESTANA_CASO);
            yield return Foto(n + "_superposicion_" + est.nombre + "_precalculado");
            n++;
            Estado("sup.pre." + est.nombre, s4.CasoActivo(), est.equilibrio, elementos, nodo);
            Escribir();
        }

        // LIBRE: los factores del ultimo estado (E3), combinados por Python.
        if (!hayServidor || ultimo == null || ultimo.lambdas == null)
        {
            Dato("sup.libre.hecho", false);
            Linea("LIBRE no se pidio: " + (!hayServidor ? "sin servidor (/ping no respondio)" : "no hay estado precalculado"));
        }
        else
        {
            Lambdas l = ultimo.lambdas;
            float t0 = Time.realtimeSinceStartup;
            bool salio = s4.CombinarEnPython(l.G, l.Q, l.EX, l.EY);
            Dato("sup.libre.estado_de_referencia", ultimo.nombre);
            Dato("sup.libre.lambdas", new[] { l.G, l.Q, l.EX, l.EY });
            Dato("sup.libre.pedido_salio", salio);
            yield return null;
            float tope = Time.realtimeSinceStartup + 120f;
            yield return new WaitUntil(() => !s4.CombinandoEnPython || Time.realtimeSinceStartup > tope);
            yield return null;
            Dato("sup.libre.segundos", Time.realtimeSinceStartup - t0);
            Dato("sup.libre.mensaje", s4.MensajeCombinar);
            CasoLab libre = s4.CasoActivo();
            bool hecho = libre != null && libre.nombre == VisorResultados.CASO_LIBRE;
            Dato("sup.libre.hecho", hecho);
            if (hecho)
            {
                EncuadreGeneral();
                Pestana(PanelVisor.PESTANA_CASO);
                // Los sliders de los factores libres, que quedaban bajo el borde.
                yield return ScrollA("sup.factores_libres", 90f);
                yield return Foto(n + "_superposicion_" + ultimo.nombre + "_LIBRE_servidor");
                n++;
                Estado("sup.libre." + ultimo.nombre, libre, EquilibrioDe(libre.nombre), elementos, nodo);
            }
        }
        s4.MostrarMapaDC(false);
        Modo(ModoDeformada.Sin);
        Escribir();
    }

    // ------------------------------------------------------------
    // D2. SUPERPOSICION INSTANTANEA: Unity combina los casos base
    // ------------------------------------------------------------
    /// Mueve los sliders instantaneos DE VERDAD -- Ins_Lambdas + Ins_Aplicar,
    /// desde esta corrutina (contexto Update, no OnGUI) -- con los juegos de
    /// lambdas de E1..E3 (los del bloque superposicion de resultados.json,
    /// los mismos de los botones) y uno feo a proposito, y deja lo que Unity
    /// CALCULO: la version (tiene que subir en cada juego; con tipo =
    /// "combinacion" subia una sola vez y todo quedaba congelado), los
    /// milisegundos, y el mismo bloque Estado(...) de los precalculados.
    /// verificacion/capturas.py (bloque visor) cruza esos numeros -- float de
    /// 32 bits, los que Unity dibuja -- con la combinacion de Python.
    IEnumerator SuperposicionInstantanea(InfoResultados info)
    {
        Seccion("D2. SUPERPOSICION INSTANTANEA (Unity combina los casos base)");
        int col = info.columna_demo, mur = info.muro_demo;
        int viga = VigaControl(), nodo = NodoControl();
        int[] elementos = { col, mur, viga };

        var juegos = new List<float[]>();
        var nombres = new List<string>();
        foreach (EstadoSuperposicion e in s4.Ins_Estados())
        {
            juegos.Add(new[] { e.lambdas.G, e.lambdas.Q, e.lambdas.EX, e.lambdas.EY });
            nombres.Add(e.nombre);
        }
        if (juegos.Count == 0) Linea("AVISO: resultados.json no trae estados de superposicion: solo el juego feo.");
        juegos.Add(new[] { -0.5f, 0.35f, 1.05f, -0.7f });   // feo a proposito: negativos
        nombres.Add("feo");
        int iFeo = juegos.Count - 1;
        int iE3 = nombres.IndexOf("E3");

        qa.LimpiarSeleccion();
        s4.mostrarDiagramas = false;
        s4.MostrarMapaDC(true);
        Modo(ModoDeformada.CasoActivo);
        Dato("ins.version_antes", s4.Ins_Version);
        for (int k = 0; k < juegos.Count; k++)
        {
            FijarLambdas(juegos[k]);
            s4.Ins_Aplicar();
            yield return null;   // el redibujo del caso va en LateUpdate
            string p = "ins." + nombres[k];
            Dato(p + ".lambdas", juegos[k]);
            Dato(p + ".version", s4.Ins_Version);
            Dato(p + ".ms", s4.Ins_MsUltima);
            Dato(p + ".caso_activo", s4.casoActivo);
            Dato(p + ".mapa_pintadas", s4.MapaDCPintadas);
            Estado(p, s4.CasoActivo(), null, elementos, nodo);
            Escribir();
        }
        Dato("ins.version_despues", s4.Ins_Version);
        Dato("ins.combinaciones_pedidas", juegos.Count);

        // 18b. E3 por el camino de Unity, con el panel en los sliders y el
        //      mapa D/C: la misma foto que la 17 (E3 precalculado por Python).
        if (iE3 >= 0)
        {
            FijarLambdas(juegos[iE3]);
            s4.Ins_Aplicar();
            yield return null;
            EncuadreGeneral();
            PlegarPestanaCaso();
            PanelUI.FijarPlegable("sup.superposicion", true);
            Pestana(PanelVisor.PESTANA_CASO);
            yield return ScrollA("ins.sliders", 30f);
            yield return Foto("18b_superposicion_instantanea_E3_en_Unity");
            Dato("ins.foto_E3.version", s4.Ins_Version);
            Dato("ins.foto_E3.ms", s4.Ins_MsUltima);
        }

        // 18c. El juego feo con la columna demo seleccionada y su P-M: el
        //      punto de demanda que se movio con los sliders.
        FijarLambdas(juegos[iFeo]);
        s4.Ins_Aplicar();
        yield return null;
        qa.SeleccionarElemento(col);
        PlegarInspectorElemento();
        PanelUI.FijarPlegable("qa.s4.demanda / capacidad", true);
        PanelUI.FijarPlegable("qa.elem.pm", true);
        EncuadreGeneral();
        Pestana(PanelVisor.PESTANA_ELEMENTO);
        yield return ScrollA("qa.s4.demanda / capacidad", 6f);
        yield return Foto("18c_capacidad_columna_" + col + "_PM_con_sliders_instantaneos_feo", "Demanda");
        Dato("ins.foto_feo.version", s4.Ins_Version);
        CasoLab cf = s4.CasoActivo();
        if (cf != null) Demanda("ins.foto_feo.elem." + col, s4.DemandaDe(col, cf.nombre));

        s4.MostrarMapaDC(false);
        qa.LimpiarSeleccion();
        Modo(ModoDeformada.Sin);
        if (!string.IsNullOrEmpty(info.caso_por_defecto)) s4.ElegirCaso(info.caso_por_defecto);
        Escribir();
    }

    void FijarLambdas(float[] juego)
    {
        float[] lam = s4.Ins_Lambdas;
        for (int c = 0; c < 4; c++) lam[c] = juego[c];
    }

    // ------------------------------------------------------------
    // F. CARGA MOVIL
    // ------------------------------------------------------------
    IEnumerator CargaMovil()
    {
        Seccion("F. CARGA MOVIL");
        if (movil == null || movil.Anexo == null || movil.CantidadPosiciones == 0)
        {
            Dato("movil.hecho", false);
            Dato("movil.aviso", movil != null ? movil.Aviso : "(no hay VisorCargaMovil)");
            yield break;
        }
        qa.LimpiarSeleccion();
        s4.mostrarDiagramas = false;
        movil.Activar();
        yield return null;
        Dato("movil.activo", movil.Activo);
        Dato("movil.P_kN", movil.Anexo.P_kN);
        Dato("movil.escala_json", movil.Anexo.info.escala_deformada);
        Dato("movil.recorrido", movil.Anexo.recorrido.elementos);
        Dato("movil.largo_m", movil.Anexo.recorrido.largo_m);
        Dato("movil.indice_uz_bajo_carga_min", movil.Anexo.info.indice_uz_bajo_carga_min);
        if (!movil.Activo)
        {
            Dato("movil.hecho", false);
            Dato("movil.aviso", movil.Aviso);
            yield break;
        }

        PanelUI.FijarPlegable("movil.donde", true);
        PanelUI.FijarPlegable("movil.reparto", true);
        PanelUI.FijarPlegable("movil.conservacion", true);
        PanelUI.FijarPlegable("movil.respuesta", true);
        PanelUI.FijarPlegable("movil.verificaciones", false);

        int otra = movil.Anexo.info.indice_uz_bajo_carga_min;
        var indices = new List<int> { POSICION_DEFENSA };
        if (otra >= 0 && otra < movil.CantidadPosiciones && otra != POSICION_DEFENSA) indices.Add(otra);
        PosicionMovil medio = movil.Anexo.posiciones[movil.CantidadPosiciones / 2];
        int n = 19;
        foreach (int i in indices)
        {
            movil.ElegirPosicion(i);
            PosicionMovil p = movil.Anexo.posiciones[movil.Indice];
            // Encuadre del recorrido completo, desde el lado y un poco arriba:
            // se ve la flecha, la viga cargada y la deformada del eje.
            Encuadrar(Ejes.AUnity(medio.x, medio.y, medio.z), movil.Anexo.recorrido.largo_m * 1.25f, 20f, 15f);
            Pestana(PanelVisor.PESTANA_CARGA_MOVIL);
            yield return Foto(n + "_carga_movil_posicion_" + i + "_viga_" + p.elemento);
            n++;
            Posicion("movil.p" + i, p);
            Escribir();
        }
        Dato("movil.hecho", true);
        movil.Apagar();
        yield return null;
    }

    // ------------------------------------------------------------
    // E. M1: borrar la columna y reanalizar en el servidor
    // ------------------------------------------------------------
    /// Los ids de -m1 "<columna>,<nodo>,<viga>". null si estan bien; si no,
    /// por que.
    string LeerM1()
    {
        if (textoM1 == null) return "sin -m1 <columna>,<nodo>,<viga> (lo pone sap.py capturar visor)";
        string[] partes = textoM1.Split(',');
        int a, b, c;
        if (partes.Length != 3
            || !int.TryParse(partes[0].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out a)
            || !int.TryParse(partes[1].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out b)
            || !int.TryParse(partes[2].Trim(), NumberStyles.Integer, CultureInfo.InvariantCulture, out c))
            return "-m1 '" + textoM1 + "' no son tres enteros separados por coma";
        columnaM1 = a; nodoM1 = b; barraM1 = c;
        return null;
    }

    IEnumerator M1()
    {
        string malM1 = LeerM1();
        Seccion("E. M1: BORRAR LA COLUMNA " + (columnaM1 >= 0 ? columnaM1.ToString(CultureInfo.InvariantCulture) : "?")
                + " Y REANALIZAR");
        if (malM1 != null && textoM1 != null)
        {
            // Vino -m1 pero mal escrito: es un error del que lanzo la captura.
            Linea("ERROR: " + malM1);
            huboError = true;
        }
        if (malM1 != null || !hayServidor || editor == null || analizador == null
            || visor.Modelo.ElementoPorId(columnaM1) == null)
        {
            Dato("m1.hecho", false);
            Linea("M1 no se hizo: " + (malM1 != null ? malM1 : !hayServidor ? "sin servidor"
                  : editor == null ? "sin EditorEstructura" : analizador == null ? "sin ClienteReanalisis"
                  : "no existe la columna " + columnaM1));
            yield break;
        }
        Dato("m1.columna", columnaM1);
        Dato("m1.nodo", nodoM1);
        Dato("m1.barra_extra", barraM1);
        qa.LimpiarSeleccion();
        Modo(ModoDeformada.Sin);
        qa.FijarEscalaAMano(100f);   // la captura fija la suya, no la recomendada
        // El Excel del reanalisis se escribe dentro de /analizar: con 30 s de
        // la escena un libro lento cortaria la peticion.
        analizador.timeoutSegundos = Mathf.Max(analizador.timeoutSegundos, 120f);
        Dato("m1.url", analizador.urlServidor);
        Dato("m1.timeout_s", analizador.timeoutSegundos);

        yield return Analizar("m1.antes");

        bool borrado = editor.BorrarElementoPorId(columnaM1);
        yield return null;
        yield return null;
        Dato("m1.borrado", borrado);
        Dato("m1.elementos_despues", visor.Modelo.elementos.Count);
        Dato("m1.existe_columna", visor.Modelo.ElementoPorId(columnaM1) != null);
        Dato("m1.anexo_desactualizado", s4.AnexoDesactualizado);
        Dato("m1.motivo", s4.MotivoDesactualizado);
        Dato("m1.aviso_anexo", s4.Aviso);
        Dato("m1.anexo_calza", s4.AnexoCalzaConElModelo);
        if (movil != null) Dato("m1.movil_aviso", movil.Aviso);

        yield return Analizar("m1.despues");
        Dato("m1.desactualizado_analizador", analizador.Desactualizado);
        Dato("m1.excel", analizador.ExcelReanalisis);
        Dato("m1.excel_existe", !string.IsNullOrEmpty(analizador.ExcelReanalisis) && File.Exists(analizador.ExcelReanalisis));
        Dato("m1.excel_error", analizador.ExcelError);
        Dato("m1.caso_mostrado", analizador.casoActivo);
        Dato("m1.hay_deformada", visor.mostrarDeformada && visor.HayDeformada);
        Dato("m1.escala", visor.factorEscala);
        Dato("m1.hecho", true);

        Nodo nodo = visor.Modelo.NodoPorId(nodoM1);
        Vector3 centro = nodo != null ? Ejes.PosicionDe(nodo) : cam.centro;

        PanelUI.FijarPlegable("editor.reanalisis", true);
        PanelUI.FijarPlegable("editor.seleccion", false);
        PanelUI.FijarPlegable("editor.crear", false);
        PanelUI.FijarPlegable("editor.secciones", false);
        PanelUI.FijarPlegable("editor.controles", false);
        Encuadrar(centro + Vector3.down * 6f, 42f, 22f, 35f);
        Pestana(PanelVisor.PESTANA_MODIFICAR);
        // El equilibrio va bajo "Caso mostrado": que entre entero en la foto.
        yield return ScrollA("editor.caso_mostrado", 70f);
        yield return Foto("21_M1_sin_columna_" + columnaM1 + "_deformada_G_y_equilibrio");

        qa.SeleccionarNodo(nodoM1);
        PanelUI.FijarPlegable("editor.reanalisis", false);
        PanelUI.FijarPlegable("editor.seleccion", true);
        Pestana(PanelVisor.PESTANA_MODIFICAR);
        yield return Foto("22_M1_nodo_" + nodoM1 + "_UZ_G");
        Dato("m1.seleccion_editor", "nodo " + editor.NodoSeleccionado + ", elemento " + editor.ElementoSeleccionado);
    }

    /// Manda el modelo al servidor como el boton "Recalcular" y registra lo
    /// que volvio: desplazamientos del nodo de la M1, equilibrio por caso
    /// (el de opensees.equilibrio, tal cual llega) y las barras del nodo.
    IEnumerator Analizar(string prefijo)
    {
        float tope = Time.realtimeSinceStartup + 30f;
        yield return new WaitUntil(() => !analizador.Ocupado || Time.realtimeSinceStartup > tope);
        bool? resultado = null;
        float t0 = Time.realtimeSinceStartup;
        bool salio = analizador.Analizar(ok => resultado = ok);
        Dato(prefijo + ".peticion_salio", salio);
        float tope2 = Time.realtimeSinceStartup + analizador.timeoutSegundos + 15f;
        yield return new WaitUntil(() => resultado.HasValue || Time.realtimeSinceStartup > tope2);
        yield return null;
        Dato(prefijo + ".ok", resultado.HasValue && resultado.Value);
        Dato(prefijo + ".segundos", Time.realtimeSinceStartup - t0);
        Dato(prefijo + ".estado", analizador.Estado);
        Dato(prefijo + ".error", analizador.UltimoError);
        Dato(prefijo + ".elementos_enviados", visor.Modelo.elementos.Count);

        // Las barras que llegan al nodo (sin la borrada) y la extra de la M1.
        var barras = new List<int>();
        foreach (Elemento e in visor.Modelo.elementos)
            if ((e.n1 == nodoM1 || e.n2 == nodoM1) && e.id != columnaM1) barras.Add(e.id);
        if (!barras.Contains(barraM1)) barras.Add(barraM1);
        barras.Sort();

        foreach (string caso in analizador.CasosDisponibles())
        {
            CasoResultado c = analizador.ResultadoDe(caso);
            if (c == null) continue;
            string p = prefijo + "." + caso;
            Dato(p + ".ok", c.ok);
            Dato(p + ".max_desplazamiento_m", c.max_desplazamiento);
            DespNodo d = Desp(c.desplazamientos, nodoM1);
            if (d != null)
            {
                Dato(p + ".nodo." + nodoM1 + ".ux_m", d.ux);
                Dato(p + ".nodo." + nodoM1 + ".uy_m", d.uy);
                Dato(p + ".nodo." + nodoM1 + ".uz_m", d.uz);
            }
            if (ClienteReanalisis.TieneEquilibrio(c))
            {
                Dato(p + ".equilibrio.aplicada_kN", c.equilibrio.aplicada_kN);
                Dato(p + ".equilibrio.reaccion_kN", c.equilibrio.reaccion_kN);
                Dato(p + ".equilibrio.error_kN", c.equilibrio.error_kN);
                Dato(p + ".equilibrio.confiable", c.equilibrio.confiable);
                Dato(p + ".equilibrio.nodos_en_diafragma", c.equilibrio.nodos_en_diafragma);
            }
            else
            {
                Dato(p + ".equilibrio.vino", false);
            }
            if (caso != "G" || c.fuerzas_elementos == null) continue;
            foreach (int id in barras)
            {
                FuerzaElemento f = c.fuerzas_elementos.Find(x => x.id == id);
                if (f == null || f.f == null || f.f.Length < 12) continue;
                string q = p + ".elem." + id;
                Dato(q + ".N_i", f.f[0]);
                Dato(q + ".Vz_i", f.f[2]);
                Dato(q + ".My_i", f.f[4]);
                Dato(q + ".My_j", f.f[10]);
            }
        }
        Escribir();
    }

    // ============================================================
    // MODO DIAGRAMAS
    // ============================================================
    /// Cada escena se arma con la MISMA API que usan los botones del panel
    /// (SeleccionarElemento, ElegirCaso, EnfocarElemento), asi que lo que se
    /// captura es lo que ve quien hace la demo. Junto a cada imagen deja el
    /// texto del inspector de la barra: un diagrama puede compilar, leer
    /// bien el JSON y aun asi dibujarse del lado equivocado, y eso solo se
    /// ve en la foto.
    IEnumerator CapturarDiagramas()
    {
        // Los visores cargan en su Start y esperan un frame: margen amplio, y
        // despues se espera a que el modelo y los resultados esten leidos.
        yield return new WaitForSecondsRealtime(5f);
        float tope = Time.realtimeSinceStartup + 30f;
        yield return new WaitUntil(() =>
        {
            Buscar();
            return Time.realtimeSinceStartup > tope
                || (visor != null && visor.Listo && s4 != null && s4.Anexo != null);
        });
        Buscar();
        if (qa == null || s4 == null || cam == null || s4.Anexo == null)
        {
            Linea("ERROR: falta PanelVisor, VisorResultados, CamaraOrbital o los resultados. Aviso: "
                  + (s4 != null ? s4.Aviso : "(sin VisorResultados)"));
            yield return Salir(2);
            yield break;
        }

        InfoResultados info = s4.Anexo.info;
        int col = info.columna_demo;
        int mur = info.muro_demo;
        Linea("edificio " + info.edificio + "  caso por defecto " + info.caso_por_defecto);
        Linea("aviso del anexo: '" + s4.Aviso + "'  calza con el modelo: " + s4.AnexoCalzaConElModelo);
        Linea("");

        Angulo(28f, 35f);
        // La lamina ampliada de la armadura queda detras del panel: fuera.
        if (s3 != null && s3.jaulaDetalle) { s3.jaulaDetalle = false; s3.Redibujar(); }
        s4.mostrarDiagramas = true;
        s4.mostrarPM = true;
        s4.multiplicadorEscala = 1f;

        // 1. La columna demo: panel con material, esfuerzos, trazabilidad y P-M.
        //    Pestana Elemento al fondo: las ultimas secciones del inspector y
        //    la curva P-M dentro del panel.
        s4.ElegirCaso(info.caso_por_defecto);
        s4.magnitud = "My";
        s4.soloSeleccionado = true;
        qa.SeleccionarElemento(col);
        s4.EnfocarElemento(col);
        PestanaDiagramas(PanelVisor.PESTANA_ELEMENTO, 100000f);
        yield return FotoDiagramas("01_columna_" + col + "_panel_y_PM", col);

        // 2. Momento My de las vigas de un piso: el lado traccionado a la vista.
        //    ElegirPiso y no soloNivel a mano: copia la cota a AjustesVista en
        //    el acto, y el visor filtra el piso antes de la foto.
        s4.soloSeleccionado = false;
        s4.magnitud = "My";
        qa.ElegirPiso(2);
        s4.Redibujar();
        EncuadrarNivel();
        PestanaDiagramas(PanelVisor.PESTANA_CASO, 0f);
        yield return FotoDiagramas("02_My_todas_piso_2", -1);

        // 3. Una viga cargada con su parabola y sus etiquetas.
        int viga = VigaConParabola(info.caso_por_defecto);
        if (viga >= 0)
        {
            s4.soloSeleccionado = true;
            qa.ElegirPiso(-1);
            qa.SeleccionarElemento(viga);
            s4.EnfocarElemento(viga);
            Angulo(12f, 20f);
            PestanaDiagramas(PanelVisor.PESTANA_CASO, 0f);
            yield return FotoDiagramas("03_viga_" + viga + "_My_etiquetas", viga);
            Angulo(28f, 35f);
        }

        // 4. Axial N en todo el edificio: traccion y compresion por color.
        s4.soloSeleccionado = false;
        s4.magnitud = "N";
        qa.ElegirPiso(-1);
        s4.Redibujar();
        cam.EncuadrarTodo();
        PestanaDiagramas(PanelVisor.PESTANA_CASO, 0f);
        yield return FotoDiagramas("04_N_todas", -1);

        // 4b. La carga repartida del mismo piso: la causa del diagrama.
        s4.magnitud = "wz";
        qa.ElegirPiso(2);
        s4.Redibujar();
        EncuadrarNivel();
        PestanaDiagramas(PanelVisor.PESTANA_CASO, 0f);
        yield return FotoDiagramas("04b_wz_todas_piso_2", -1);

        // 5. Corte Vz de un piso.
        s4.magnitud = "Vz";
        qa.ElegirPiso(2);
        s4.Redibujar();
        EncuadrarNivel();
        PestanaDiagramas(PanelVisor.PESTANA_CASO, 0f);
        yield return FotoDiagramas("05_Vz_todas_piso_2", -1);

        // 5b. Capas: areas tributarias y cargas G del mismo piso, sin diagramas.
        //     Pestana Capas: la leyenda de apoyos y el conteo de areas.
        s4.mostrarDiagramas = false;
        s4.mostrarPM = false;
        s4.Redibujar();
        qa.verAreasTributarias = true;
        qa.Capturas_Refrescar();
        PestanaDiagramas(PanelVisor.PESTANA_CAPAS, 0f);
        if (s3 != null)
        {
            s3.mostrarCargas = true;
            s3.cargasConLaDeformada = false;
            s3.casoCarga = "G";
            s3.Redibujar();
        }
        yield return FotoDiagramas("05b_capas_areas_y_cargas_G_piso_2", -1);
        qa.verAreasTributarias = false;
        qa.Capturas_Refrescar();
        if (s3 != null)
        {
            s3.cargasConLaDeformada = true;
            s3.casoCarga = "EX";
            s3.Redibujar();
        }
        s4.mostrarDiagramas = true;
        s4.mostrarPM = true;

        // 6. El muro demo con su P-M, en la combinacion con sismo en Y.
        s4.soloSeleccionado = true;
        s4.magnitud = EnSuPlano(mur);
        qa.ElegirPiso(-1);
        s4.ElegirCaso("1.2G+1.0Q+1.4EY");
        qa.SeleccionarElemento(mur);
        s4.EnfocarElemento(mur);
        PestanaDiagramas(PanelVisor.PESTANA_ELEMENTO, 100000f);
        yield return FotoDiagramas("06_muro_" + mur + "_" + s4.magnitud + "_PM_1.2G+1.0Q+1.4EY", mur);

        // 9. Deformada de una combinacion.
        s4.mostrarPM = false;
        s4.mostrarDiagramas = false;
        s4.ElegirCaso("1.2G+1.0Q+1.4EY");
        s4.AplicarDeformadaDelCaso();
        s4.Redibujar();
        cam.EncuadrarTodo();
        PestanaDiagramas(PanelVisor.PESTANA_CASO, 0f);
        yield return FotoDiagramas("09_deformada_1.2G+1.0Q+1.4EY", -1);
    }

    IEnumerator FotoDiagramas(string nombre, int id)
    {
        // El scroll se vuelve a fijar un frame despues de la pestana: PanelVisor
        // arma el inspector de la seleccion nueva en su Update, que corre
        // DESPUES de esta corrutina; en el OnGUI de ese mismo frame el panel
        // todavia tiene los bloques de antes y el ScrollView recorta el scroll
        // a lo que cabe (la foto "panel y P-M" salia sin la P-M).
        yield return null;
        qa.Capturas_FijarScroll(scrollEsperado);
        // Que se rehagan mallas, texturas y el OnGUI con el estado nuevo.
        yield return new WaitForSecondsRealtime(1.5f);
        yield return Disparar(nombre);

        Linea("=== " + nombre + " ===");
        // Solo si algo cambio la pestana entre la pestana fijada y la foto.
        if (!string.IsNullOrEmpty(pestanaEsperada) && qa.Pestana != pestanaEsperada)
            Linea("AVISO pestana: se fijo '" + pestanaEsperada + "' y la foto salio con '" + qa.Pestana + "'");
        Linea($"caso {s4.casoActivo}  magnitud {s4.magnitud}  "
              + $"solo seleccionada {s4.soloSeleccionado}  seleccionado {s4.Seleccionado}");
        if (id >= 0) Linea(s4.DescribirElemento(id));
        Linea("");
        Escribir();
    }

    /// Fija la pestana del panel y despues su scroll. En el inspector la
    /// trazabilidad viene plegada; esta captura la muestra al fondo del
    /// panel, junto a la P-M (la app se cierra al terminar: no deja el
    /// plegable cambiado).
    void PestanaDiagramas(string titulo, float scrollY)
    {
        if (titulo == PanelVisor.PESTANA_ELEMENTO) PanelUI.FijarPlegable("qa.s4.trazabilidad", true);
        Pestana(titulo, scrollY);
    }

    /// La viga cuyo momento mas se curva por su propia carga: su diagrama es
    /// una parabola que se lee sola. Solo elige que mostrar.
    int VigaConParabola(string caso)
    {
        int mejor = -1;
        float mayor = 0f;
        foreach (ElementoOpenSees e in s4.Anexo.elementos)
        {
            if (e.tipo == null || !e.tipo.StartsWith("viga") || !e.cargada) continue;
            CasoLab c = s4.Anexo.casos.Find(x => x.nombre == caso);
            if (c == null) return -1;
            EsfuerzosBarra s = c.esfuerzos.Find(x => x.id == e.id);
            if (s == null || s.My == null || s.My.Length < 3) continue;
            float medio = Mathf.Abs(s.My[s.My.Length / 2] - 0.5f * (s.My[0] + s.My[s.My.Length - 1]));
            if (medio > mayor) { mayor = medio; mejor = e.id; }
        }
        return mejor;
    }

    /// Centra la camara en los nodos del piso filtrado, para que sus
    /// diagramas se lean. Solo elige el encuadre.
    void EncuadrarNivel()
    {
        if (visor == null || visor.Modelo == null || visor.Modelo.nodos == null) { cam.EncuadrarTodo(); return; }
        bool hay = false;
        Bounds b = default;
        foreach (Nodo n in visor.Modelo.nodos)
        {
            if (!qa.NivelVisible((float)n.z)) continue;
            Vector3 p = Ejes.PosicionDe(n);
            if (!hay) { b = new Bounds(p, Vector3.zero); hay = true; }
            else b.Encapsulate(p);
        }
        if (!hay) { cam.EncuadrarTodo(); return; }
        cam.centro = b.center;
        cam.distancia = Mathf.Clamp(b.extents.magnitude * 1.5f, 10f, 150f);
    }

    /// El momento del plano del muro, tal como lo trae el JSON.
    string EnSuPlano(int id)
    {
        ElementoOpenSees e = s4.ElementoPorId(id);
        return e != null && e.momento_en_el_plano == "My" ? "My" : "Mz";
    }

    // ============================================================
    // MODO PERSONA
    // ============================================================
    /// Espera el modelo y persona.json, pone al caminante (100 kN) en el
    /// primer piso, en la region tributaria mas grande de una viga, saca
    /// fotos, lo hace caminar 3 m, sube un piso y vuelve a sacar, y termina
    /// en la cabina. En el registro deja lo que Unity SUMO en cada lugar.
    IEnumerator CapturarPersona()
    {
        float tope = Time.realtimeSinceStartup + TOPE_ESPERA_S;
        while (Time.realtimeSinceStartup < tope)
        {
            Buscar();
            if (visor != null && persona != null && cam != null && visor.Modelo != null) break;
            yield return new WaitForSecondsRealtime(0.5f);
        }
        if (visor == null || persona == null || cam == null || visor.Modelo == null)
        {
            Linea("ERROR: no cargo el modelo, la persona o la camara antes de " + TOPE_ESPERA_S + " s");
            Linea("errores del log: " + nErroresDelLog);
            yield return Salir(2);
            yield break;
        }
        AjustesVista.realista = true;
        AjustesVista.suelo = true;
        AjustesVista.relieve = false;
        EventosVisor.AvisarVistaCambio();
        yield return new WaitForSecondsRealtime(1f);

        if (!persona.Captura_Poner(1, P_PERSONA_KN))
        {
            Linea("ERROR: no se pudo poner la persona en el piso 2");
            Linea("errores del log: " + nErroresDelLog);
            yield return Salir(2);
            yield break;
        }
        while (!persona.Captura_InfluenciasListas && Time.realtimeSinceStartup < tope)
            yield return new WaitForSecondsRealtime(0.25f);
        Linea("influencias: " + persona.Captura_Estado);
        if (!persona.Captura_InfluenciasListas)
        {
            Linea("ERROR: no se leyo " + VisorPersona.ARCHIVO);
            Linea("errores del log: " + nErroresDelLog);
            yield return Salir(2);
            yield break;
        }
        persona.Captura_Poner(1, P_PERSONA_KN);           // de nuevo, ya con los casos leidos
        yield return new WaitForSecondsRealtime(1f);
        Linea(persona.Captura_Registro());
        if (qa != null) qa.ElegirPestana(persona.TituloPestana);

        cam.EncuadrarTodo();
        float d = cam.distancia;
        Vector3 donde = persona.Captura_Donde;
        // De costado a la viga cargada (y un poco en diagonal): ahi se ve su flecha.
        float lado = persona.Captura_RumboViga + 90f + 15f;
        yield return FotoOrbital("persona_1_edificio", cam.centro, d * 1.2f, 25f, 215f);
        yield return FotoOrbital("persona_2_cerca", donde, 14f, 12f, lado);

        persona.Captura_Caminar(new Vector2(3f, 0f));
        yield return new WaitForSecondsRealtime(1f);
        Linea(persona.Captura_Registro());
        yield return FotoOrbital("persona_3_camino", persona.Captura_Donde, 14f, 12f, persona.Captura_RumboViga + 105f);

        // Sube un piso (el ascensor tarda 0.7 s) y vuelve a sumar alla.
        bool subio = persona.Captura_CambiarPiso(+1);
        yield return new WaitForSecondsRealtime(1.5f);
        Linea("piso: " + (subio ? "subio a " : "NO subio, sigue en ") + persona.Captura_Piso);
        Linea(persona.Captura_Registro());
        yield return FotoOrbital("persona_4_otro_piso", persona.Captura_Donde, 16f, 18f, persona.Captura_RumboViga + 105f);

        // Desde la cabina: la camara la maneja la persona, asi que la foto
        // va sin mover la orbital. Camina 2 m para ver el paso.
        persona.Captura_Cabina(true);
        persona.Captura_Caminar(new Vector2(0f, 2f));
        persona.Captura_Mirar(persona.Captura_RumboViga + 180f, 15f);   // a lo largo de la viga, hacia adentro
        yield return new WaitForSecondsRealtime(1.5f);
        Linea("cabina: " + (persona.Captura_EnCabina ? "adentro" : "NO entro") + ", camara en "
              + Camera.main.transform.position.ToString("F2"));
        yield return Disparar("persona_5_cabina");
        Linea("foto persona_5_cabina: la camara de la cabina");
        persona.Captura_Cabina(false);
        yield return new WaitForSecondsRealtime(0.5f);

        if (nErroresDelLog > 0 || registro.ToString().Contains("sin deformada")) huboError = true;
        Linea("errores del log: " + nErroresDelLog);
    }

    // ============================================================
    // MODO RELIEVE
    // ============================================================
    /// Espera a que el modelo y el relieve esten cargados, pone la vista
    /// realista con el suelo y el relieve, y saca cuatro fotos: dos
    /// isometricas opuestas, la planta y una de cerca del edificio. Mueve
    /// solo la camara y las capas.
    IEnumerator CapturarRelieve()
    {
        float tope = Time.realtimeSinceStartup + TOPE_ESPERA_S;
        while (Time.realtimeSinceStartup < tope)
        {
            Buscar();
            bool relieveListo = AjustesVista.relieveEstado.StartsWith("Relieve del sitio")
                             || AjustesVista.relieveEstado.StartsWith("Sin relieve");
            if (visor != null && cam != null && visor.Modelo != null && relieveListo) break;
            yield return new WaitForSecondsRealtime(0.5f);
        }
        Linea("relieveEstado: " + AjustesVista.relieveEstado);
        if (visor == null || cam == null || visor.Modelo == null)
        {
            Linea("ERROR: no cargo el modelo o la camara antes de " + TOPE_ESPERA_S + " s");
            Linea("errores del log: " + nErroresDelLog);
            yield return Salir(2);
            yield break;
        }
        Linea("edificio: " + (visor.Modelo.info != null ? visor.Modelo.info.edificio : "?"));

        AjustesVista.realista = true;
        AjustesVista.suelo = true;
        AjustesVista.relieve = true;
        EventosVisor.AvisarVistaCambio();
        yield return new WaitForSecondsRealtime(1f);

        cam.EncuadrarTodo();
        Vector3 centro = cam.centro;
        float d = cam.distancia;
        yield return FotoOrbital("relieve_1_iso_suroeste", centro, d * 2.6f, 28f, 225f);
        yield return FotoOrbital("relieve_2_iso_noreste", centro, d * 2.6f, 28f, 45f);
        yield return FotoOrbital("relieve_3_planta", centro, d * 3.0f, 89f, 0f);
        yield return FotoOrbital("relieve_4_cerca", centro, d * 1.1f, 18f, 200f);

        Linea("errores del log: " + nErroresDelLog);
        if (nErroresDelLog > 0 || !AjustesVista.relieveEstado.StartsWith("Relieve del sitio")) huboError = true;
    }

    // ============================================================
    // FOTOS
    // ============================================================
    /// Saca la foto al final del cuadro (con el IMGUI dibujado) y la guarda
    /// como <carpeta>/<nombre>.jpg.
    IEnumerator Disparar(string nombre)
    {
        yield return new WaitForEndOfFrame();
        Texture2D tex = ScreenCapture.CaptureScreenshotAsTexture();
        anchoFoto = tex.width;
        altoFoto = tex.height;
        try
        {
            File.WriteAllBytes(Path.Combine(carpeta, nombre + ".jpg"), tex.EncodeToJPG(CALIDAD_JPG));
        }
        finally
        {
            Destroy(tex);
        }
        nFotos++;
    }

    /// Modo visor: espera a que se rehagan mallas, materiales y el panel,
    /// saca la foto y anota el estado de la escena y, si se piden, los
    /// bloques del inspector cuyo titulo empieza con esos textos: lo que la
    /// foto muestra, en texto.
    IEnumerator Foto(string nombre, params string[] bloques)
    {
        // El scroll se vuelve a fijar un cuadro despues (PanelVisor arma el
        // inspector en su Update, despues de esta corrutina).
        yield return null;
        qa.Capturas_FijarScroll(scrollEsperado);
        yield return new WaitForSecondsRealtime(1.5f);
        yield return Disparar(nombre);

        string archivo = nombre + ".jpg";
        Linea("");
        Linea("=== FOTO " + archivo + " ===");
        string f = "foto." + nombre;
        Dato(f + ".tamano", anchoFoto + "x" + altoFoto);
        Dato(f + ".pestana", qa.Pestana);
        if (!string.IsNullOrEmpty(pestanaEsperada) && qa.Pestana != pestanaEsperada)
            Linea("AVISO pestana: se fijo '" + pestanaEsperada + "' y la foto salio con '" + qa.Pestana + "'");
        Dato(f + ".vista", AjustesVista.realista ? "realista" : "tecnica");
        Dato(f + ".suelo", AjustesVista.suelo);
        Dato(f + ".piso", AjustesVista.HayFiltroDePiso ? AjustesVista.cotaVisible.ToString("0.00", CultureInfo.InvariantCulture) : "todos");
        Dato(f + ".caso_activo", s4.casoActivo);
        Dato(f + ".seleccion", qa.TipoSeleccionado + " " + qa.IdSeleccionado);
        Dato(f + ".deformada", visor.mostrarDeformada && visor.HayDeformada);
        Dato(f + ".escala", visor.factorEscala);
        Dato(f + ".diagramas", s4.mostrarDiagramas ? s4.magnitud : "no");
        Dato(f + ".mapa_dc", s4.MapaDCActivo ? "si, " + s4.MapaDCPintadas + " barras pintadas" : "no");
        Dato(f + ".carga_movil", movil != null && movil.Activo ? "posicion " + movil.Indice : "no");
        // De donde dice la cabecera que sale lo que se ve (anexo, reanalisis o
        // carga_movil) y su texto: verificacion/capturas.py los cruza con Python.
        Dato(f + ".cabecera.fuente", qa.FuenteCabecera);
        Dato(f + ".cabecera.texto", qa.TextoCabecera);
        Dato(f + ".camara", "centro " + cam.centro.ToString("F2") + " distancia "
                           + cam.distancia.ToString("0.0", CultureInfo.InvariantCulture));
        if (bloques != null && bloques.Length > 0)
        {
            List<string> texto = qa.Capturas_TextoBloques(bloques);
            if (texto.Count == 0) texto.Add("(ningun bloque del inspector empieza con: " + string.Join(", ", bloques) + ")");
            foreach (string linea in texto) Linea("  panel | " + linea);
        }
        Escribir();
    }

    /// Persona y relieve: la camara orbital en (centro, distancia, pitch,
    /// yaw), la foto y una linea con el encuadre.
    IEnumerator FotoOrbital(string nombre, Vector3 centro, float distancia, float pitch, float yaw)
    {
        Angulo(pitch, yaw);
        cam.centro = centro;
        cam.distancia = distancia;
        yield return new WaitForSecondsRealtime(1.5f);
        yield return Disparar(nombre);
        Linea(string.Format(CultureInfo.InvariantCulture,
            "foto {0}: distancia {1:F1} m, pitch {2:F0}, yaw {3:F0}", nombre, distancia, pitch, yaw));
        Escribir();
    }

    // ============================================================
    // PANEL Y CAMARA
    // ============================================================
    /// Fija la pestana y despues el scroll (ElegirPestana vuelve el scroll
    /// arriba: al reves se perderia).
    void Pestana(string titulo, float scrollY = 0f)
    {
        qa.ElegirPestana(titulo);
        pestanaEsperada = titulo;
        scrollEsperado = scrollY;
        qa.Capturas_FijarScroll(scrollY);
    }

    /// Cierra los bloques del inspector de una barra: cada foto abre solo
    /// los que contestan su pregunta, asi la respuesta queda arriba sin
    /// depender de un scroll medido a mano. "qa.s4.resultados" es el bloque
    /// "Resultados" del inspector (su clave sale del titulo).
    static void PlegarInspectorElemento()
    {
        string[] claves = {
            "qa.elem.identificacion", "qa.elem.ejes", "qa.elem.tributaria", "qa.elem.pm",
            "qa.s4.resultados", "qa.s4.material", "qa.s4.seccion", "qa.s4.condiciones",
            "qa.s4.esfuerzos", "qa.s4.demanda / capacidad", "qa.s4.trazabilidad" };
        foreach (string c in claves) PanelUI.FijarPlegable(c, false);
    }

    static void PlegarInspectorNodo()
    {
        string[] claves = {
            "qa.nodo.ubicacion", "qa.nodo.apoyo", "qa.nodo.diafragma",
            "qa.nodo.desplazamiento", "qa.nodo.cargas", "qa.nodo.barras" };
        foreach (string c in claves) PanelUI.FijarPlegable(c, false);
    }

    static void PlegarPestanaCaso()
    {
        string[] claves = {
            "qa.caso.deformada", "qa.caso.avanzado", "s4.casos", "sup.superposicion",
            "s4.diagramas", "s4.pm", "mapa.dc", "mapa.criticos" };
        foreach (string c in claves) PanelUI.FijarPlegable(c, false);
    }

    void EncuadreGeneral()
    {
        cam.EncuadrarTodo();
        Encuadrar(cam.centro, cam.distancia * 0.9f, 24f, 35f);
    }

    /// Mira a 'centro' desde (pitch, yaw) a 'distancia'. Solo elige el
    /// encuadre: el corrimiento por el panel lo hace CamaraOrbital
    /// (CorrimientoPorPanel), igual que para F, C e "Ir a ID" en la app. Si
    /// se corriera tambien aca, lo mirado quedaria dos veces corrido.
    void Encuadrar(Vector3 centro, float distancia, float pitch, float yaw)
    {
        Angulo(pitch, yaw);
        cam.centro = centro;
        cam.distancia = distancia;
    }

    void Angulo(float pitch, float yaw)
    {
        cam.FijarAngulos(pitch, yaw);
    }

    /// Lleva el scroll del panel hasta la seccion 'clave' (un Plegable o un
    /// PanelUI.Marcar), dejando 'antesPx' de lo que hay arriba. La posicion
    /// la anota PanelUI al dibujar, asi que se esperan dos cuadros con la
    /// pestana ya puesta. Llamar DESPUES de Pestana(...).
    IEnumerator ScrollA(string clave, float antesPx)
    {
        PanelUI.OlvidarPosiciones();
        yield return null;
        yield return null;
        yield return null;
        float y = PanelUI.PosicionDe(clave);
        Dato("scroll." + clave, y < 0f ? "no se dibujo" : y.ToString("0", CultureInfo.InvariantCulture));
        if (y < 0f) yield break;
        scrollEsperado = Mathf.Max(0f, y - PanelUI.Px(antesPx));
        qa.Capturas_FijarScroll(scrollEsperado);
    }

    /// El mismo camino que los botones de la pestana Caso (PanelVisor.AplicarModo):
    /// una sola fuente de deformada, y el boton activo en la foto es el que se ve.
    void Modo(ModoDeformada m)
    {
        qa.Capturas_AplicarModo(m);
    }

    /// El equilibrio que mando Python para un caso de superposicion (lo
    /// guarda VisorResultados para su panel; aca solo se lee).
    EquilibrioCaso EquilibrioDe(string nombre)
    {
        EquilibrioCaso eq;
        return s4.EquilibriosDeSuperposicion.TryGetValue(nombre ?? "", out eq) ? eq : null;
    }

    // ============================================================
    // REGISTRO DE UN CASO, UNA POSICION, UN ESFUERZO
    // ============================================================
    void Estado(string p, CasoLab c, EquilibrioCaso eq, int[] elementos, int nodo)
    {
        if (c == null) { Dato(p + ".hay", false); return; }
        Dato(p + ".nombre", c.nombre);
        Dato(p + ".tipo", c.tipo);
        Dato(p + ".descripcion", c.descripcion);
        Dato(p + ".factores", c.factores);
        Dato(p + ".max_desplazamiento_mm", c.max_desplazamiento_mm);
        int noPasan, fuera, total;
        VisorResultados.ContarDemandas(c, out noPasan, out fuera, out total);
        Dato(p + ".no_pasan", noPasan);
        Dato(p + ".fuera_de_curva", fuera);
        Dato(p + ".con_fierro", total);
        Dato(p + ".desplazamientos", c.desplazamientos != null ? c.desplazamientos.Count : 0);
        Dato(p + ".esfuerzos", c.esfuerzos != null ? c.esfuerzos.Count : 0);
        DespNodo d = Desp(c.desplazamientos, nodo);
        if (d != null)
        {
            Dato(p + ".nodo." + nodo + ".ux_m", d.ux);
            Dato(p + ".nodo." + nodo + ".uy_m", d.uy);
            Dato(p + ".nodo." + nodo + ".uz_m", d.uz);
        }
        foreach (int id in elementos)
        {
            if (id < 0) continue;
            EsfuerzosBarra s = c.esfuerzos != null ? c.esfuerzos.Find(x => x != null && x.id == id) : null;
            Esfuerzos(p + ".elem." + id, s);
            Demanda dm = c.demandas != null ? c.demandas.Find(x => x != null && x.id == id) : null;
            if (dm != null) Demanda(p + ".elem." + id, dm);
        }
        NoPasan(p, c);
        if (eq != null && eq.aplicada_kN != null && eq.aplicada_kN.Length == 3)
        {
            Dato(p + ".equilibrio.aplicada_kN", eq.aplicada_kN);
            Dato(p + ".equilibrio.reaccion_kN", eq.reaccion_kN);
            Dato(p + ".equilibrio.error_kN", eq.error_kN);
            Dato(p + ".equilibrio.confiable", eq.confiable);
        }
        else
        {
            Dato(p + ".equilibrio.vino", false);
        }
        Dato(p + ".origen", s4.OrigenDe(c));
        Dato(p + ".caso_activo", s4.casoActivo);
    }

    /// Los extremos de las estaciones (lo que escribe la tabla del
    /// inspector) y donde esta el mayor |My| (lo que etiqueta el diagrama).
    void Esfuerzos(string p, EsfuerzosBarra s)
    {
        if (s == null) { Dato(p + ".esfuerzos", false); return; }
        Dato(p + ".estaciones", s.x != null ? s.x.Length : 0);
        Extremos(p, "N", s.N);
        Extremos(p, "Vy", s.Vy);
        Extremos(p, "Vz", s.Vz);
        Extremos(p, "T", s.T);
        Extremos(p, "My", s.My);
        Extremos(p, "Mz", s.Mz);
        if (s.w != null) Dato(p + ".w_local", s.w);
        if (s.My != null && s.x != null && s.My.Length == s.x.Length && s.My.Length > 0)
        {
            int k = 0;
            for (int i = 1; i < s.My.Length; i++)
                if (Mathf.Abs(s.My[i]) > Mathf.Abs(s.My[k])) k = i;
            Dato(p + ".My_max_abs_valor", s.My[k]);
            Dato(p + ".My_max_abs_x", s.x[k]);
        }
    }

    void Extremos(string p, string nombre, float[] v)
    {
        if (v == null || v.Length == 0) return;
        Dato(p + "." + nombre + "_i", v[0]);
        Dato(p + "." + nombre + "_j", v[v.Length - 1]);
    }

    void Demanda(string p, Demanda d)
    {
        if (d == null) { Dato(p + ".demanda", false); return; }
        Dato(p + ".P", d.P);
        Dato(p + ".M", d.M);
        Dato(p + ".Mn", d.Mn);
        Dato(p + ".u", d.u);
        Dato(p + ".extremo", d.extremo);
        Dato(p + ".pasa", d.pasa);
        Dato(p + ".familia", d.familia);
    }

    void NoPasan(string p, CasoLab c)
    {
        var ids = new List<string>();
        if (c.demandas != null)
            foreach (Demanda d in c.demandas)
            {
                if (d == null || d.pasa) continue;
                ids.Add(d.id.ToString(CultureInfo.InvariantCulture));
                Dato(p + ".no_pasa." + d.id + ".u", d.u);
            }
        Dato(p + ".no_pasa.ids", string.Join(",", ids.ToArray()));
    }

    void Posicion(string p, PosicionMovil q)
    {
        Dato(p + ".indice", q.indice);
        Dato(p + ".indice_mostrado", movil.Indice);
        Dato(p + ".elemento", q.elemento);
        Dato(p + ".xL", q.xL);
        Dato(p + ".a_m", q.a_m);
        Dato(p + ".L_m", q.L_m);
        Dato(p + ".s_m", q.s_m);
        Dato(p + ".x", q.x);
        Dato(p + ".y", q.y);
        Dato(p + ".z", q.z);
        Dato(p + ".Pz_local_kN", q.Pz_local_kN);
        Dato(p + ".max_desplazamiento_mm", q.max_desplazamiento_mm);
        Dato(p + ".nodo_max_desplazamiento", q.nodo_max_desplazamiento);
        Dato(p + ".uz_min_mm", q.uz_min_mm);
        Dato(p + ".nodo_uz_min", q.nodo_uz_min);
        Dato(p + ".uz_bajo_carga_mm", q.uz_bajo_carga_mm);
        Dato(p + ".M_bajo_carga_kNm", q.M_bajo_carga_kNm);
        Dato(p + ".u_carga_m", q.u_carga_m);
        DespNodo d = Desp(q.desplazamientos, q.nodo_uz_min);
        if (d != null) Dato(p + ".desplazamiento_nodo_uz_min.uz_m", d.uz);
        RepartoMovil r = q.reparto;
        if (r != null)
        {
            Dato(p + ".reparto.nodo_i", r.nodo_i);
            Dato(p + ".reparto.nodo_j", r.nodo_j);
            Dato(p + ".reparto.V_i_kN", r.V_i_kN);
            Dato(p + ".reparto.V_j_kN", r.V_j_kN);
            Dato(p + ".reparto.porcentaje_i", r.porcentaje_i);
            Dato(p + ".reparto.porcentaje_j", r.porcentaje_j);
            Dato(p + ".reparto.palanca_i_kN", r.palanca_i_kN);
            Dato(p + ".reparto.palanca_j_kN", r.palanca_j_kN);
            Dato(p + ".reparto.My_i_kNm", r.My_i_kNm);
            Dato(p + ".reparto.My_j_kNm", r.My_j_kNm);
            Dato(p + ".reparto.momentos_sobre_L_kN", r.momentos_sobre_L_kN);
        }
        ConservacionMovil c = q.conservacion;
        if (c != null)
        {
            Dato(p + ".conservacion.P_kN", c.P_kN);
            Dato(p + ".conservacion.suma_Rz_kN", c.suma_Rz_kN);
            Dato(p + ".conservacion.error_kN", c.error_kN);
            Dato(p + ".conservacion.cota_kN", c.cota_kN);
            Dato(p + ".conservacion.suma_Rx_kN", c.suma_Rx_kN);
            Dato(p + ".conservacion.suma_Ry_kN", c.suma_Ry_kN);
            Dato(p + ".conservacion.cumple", c.cumple);
        }
        if (q.equilibrio != null && q.equilibrio.aplicada_kN != null && q.equilibrio.aplicada_kN.Length == 3)
        {
            Dato(p + ".equilibrio.aplicada_kN", q.equilibrio.aplicada_kN);
            Dato(p + ".equilibrio.reaccion_kN", q.equilibrio.reaccion_kN);
            Dato(p + ".equilibrio.error_kN", q.equilibrio.error_kN);
        }
        Dato(p + ".hay_deformada", visor.mostrarDeformada && visor.HayDeformada);
        Dato(p + ".escala", visor.factorEscala);
    }

    // ============================================================
    // ELEGIR QUE MOSTRAR (no calcula: busca en lo que vino del JSON)
    // ============================================================
    CasoLab CasoE1()
    {
        foreach (EstadoSuperposicion e in s4.EstadosSuperposicion)
            if (e != null && e.nombre == "E1" && e.caso != null) return e.caso;
        return null;
    }

    /// entrada/laboratorio.json, superposicion.control.reglas.viga: la barra
    /// de tipo viga* con mayor |My| en alguna estacion bajo E1.
    int VigaControl()
    {
        CasoLab e1 = CasoE1();
        if (e1 == null || e1.esfuerzos == null) return -1;
        int mejor = -1;
        float mayor = -1f;
        foreach (EsfuerzosBarra s in e1.esfuerzos)
        {
            if (s == null || s.My == null) continue;
            ElementoOpenSees e = s4.ElementoPorId(s.id);
            if (e == null || e.tipo == null || !e.tipo.StartsWith("viga")) continue;
            foreach (float v in s.My)
                if (Mathf.Abs(v) > mayor) { mayor = Mathf.Abs(v); mejor = s.id; }
        }
        return mejor;
    }

    /// entrada/laboratorio.json, superposicion.control.reglas.nodo: el nodo
    /// con mayor desplazamiento (norma de ux, uy, uz) bajo E1. Se compara el
    /// cuadrado: solo ordena, no escribe ningun numero.
    int NodoControl()
    {
        CasoLab e1 = CasoE1();
        if (e1 == null || e1.desplazamientos == null) return -1;
        int mejor = -1;
        double mayor = -1.0;
        foreach (DespNodo d in e1.desplazamientos)
        {
            double q = (double)d.ux * d.ux + (double)d.uy * d.uy + (double)d.uz * d.uz;
            if (q > mayor) { mayor = q; mejor = d.id; }
        }
        return mejor;
    }

    /// La viga de control si recibe carga de losa; si no, la primera que
    /// la reciba (la pregunta "que lo carga" necesita un area tributaria).
    static int VigaConTributaria(ModeloEstructural m, int preferida)
    {
        if (preferida >= 0 && m.TributariasDe(preferida).Count > 0) return preferida;
        if (m.areas_tributarias == null) return preferida;
        foreach (AreaTributaria t in m.areas_tributarias)
            if (t.qG > 0f && m.ElementoPorId(t.elemento) != null) return t.elemento;
        return preferida;
    }

    static DespNodo Desp(List<DespNodo> lista, int id)
    {
        if (lista == null || id < 0) return null;
        foreach (DespNodo d in lista) if (d != null && d.id == id) return d;
        return null;
    }

    // ============================================================
    // TEXTO
    // ============================================================
    void Seccion(string titulo)
    {
        Linea("");
        Linea("==================== " + titulo + " ====================");
        Escribir();
    }

    void Linea(string texto) { registro.AppendLine(texto); }

    void NodoXYZ(string p, Nodo n)
    {
        if (n == null) return;
        Dato(p + ".id", n.id);
        Dato(p + ".xyz_m", new[] { n.x, n.y, n.z });
    }

    /// Una linea "DATO clave = valor". Los float con G9 (el float de 32 bits
    /// exacto); los arreglos separados por coma; el texto en una linea.
    void Dato(string clave, object valor)
    {
        registro.Append("DATO ").Append(clave).Append(" = ").AppendLine(Formato(valor));
    }

    static string Formato(object v)
    {
        if (v == null) return "";
        if (v is float) return ((float)v).ToString("G9", CultureInfo.InvariantCulture);
        if (v is double) return ((double)v).ToString("G17", CultureInfo.InvariantCulture);
        if (v is bool) return (bool)v ? "True" : "False";
        if (v is int) return ((int)v).ToString(CultureInfo.InvariantCulture);
        if (v is float[])
        {
            float[] a = (float[])v;
            var partes = new string[a.Length];
            for (int i = 0; i < a.Length; i++) partes[i] = a[i].ToString("G9", CultureInfo.InvariantCulture);
            return string.Join(",", partes);
        }
        if (v is int[])
        {
            int[] a = (int[])v;
            var partes = new string[a.Length];
            for (int i = 0; i < a.Length; i++) partes[i] = a[i].ToString(CultureInfo.InvariantCulture);
            return string.Join(",", partes);
        }
        return Convert.ToString(v, CultureInfo.InvariantCulture).Replace("\r", "").Replace("\n", " | ");
    }

    static string Recortar(string t, int n)
    {
        t = (t ?? "").Replace("\r", "").Replace("\n", " | ");
        return t.Length > n ? t.Substring(0, n) + "..." : t;
    }

    static string ParaArchivo(string t)
    {
        return (t ?? "").ToLowerInvariant().Replace(' ', '_');
    }

    void Escribir()
    {
        if (string.IsNullOrEmpty(carpeta)) return;
        try
        {
            File.WriteAllText(Path.Combine(carpeta, "registro.txt"), registro.ToString(), new UTF8Encoding(false));
        }
        catch (Exception ex)
        {
            Debug.LogWarning("Capturas: no pude escribir registro.txt: " + ex.Message);
        }
    }
}
