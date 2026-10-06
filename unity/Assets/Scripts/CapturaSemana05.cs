/*
================================================================
  CapturaSemana05.cs
================================================================
  Capturas y REGISTRO NUMERICO de la Semana 5, sin intervencion y
  desde la app de Windows:

      build/LaboratorioEstructural.exe -capturarS5 <carpeta>
            -screen-width 1600 -screen-height 900 -screen-fullscreen 0

  Sin ese argumento no hace nada: ni siquiera crea su objeto. Es una
  herramienta de verificacion, no parte del visor.

  Deja en <carpeta>:
    NN_tema.jpg    una foto por escena: vista realista y tecnica, una
                   por pestana del panel, las seis preguntas del visor
                   (donde esta, como esta apoyado, que lo carga, como se
                   deforma, que fuerzas tiene, cuanta capacidad tiene),
                   E1..E3 precalculados, E3 pedido al servidor, dos
                   posiciones de la carga movil y la M1.
    registro.txt   lo que Unity CARGO y MUESTRA, en lineas
                   "DATO clave = valor". semana05/comparar_unity.py las
                   cruza con Python: superposicion_lt2_control.csv,
                   reanalisis_demo.py y carga_movil_lt2.json.

  ----------------------------------------------------------------
  REGLA QUE NO SE ROMPE: aca no se calcula estructura
  ----------------------------------------------------------------
  Cada numero del registro es un campo leido tal cual: del JSON que
  cargo el visor o de la respuesta del servidor. Van con "G9", que
  escribe el float de 32 bits de forma que vuelve exacto: la
  comparacion en Python ve lo que tenia Unity en memoria, no un
  redondeo de pantalla. Lo unico que aca se ELIGE son la viga y el
  nodo de control de la superposicion, con la regla escrita en
  semana05/estados_s5.json (mayor |My| y mayor desplazamiento bajo E1);
  comparar_unity.py comprueba que salen los mismos ids que en Python.

  ----------------------------------------------------------------
  EL ORDEN IMPORTA
  ----------------------------------------------------------------
  Primero lo que funciona sin servidor (vista, panel, preguntas, E1..E3
  precalculados, carga movil), despues LIBRE (POST /combinar) y al
  FINAL la M1: borrar la columna 69 deja el anexo desactualizado y
  apaga la carga movil, y desde ahi ya no se puede mostrar nada
  precalculado. Sin servidor (/ping no responde) LIBRE y M1 quedan en
  el registro como no hechas y la captura termina igual.

  Como CapturaSemana04, toca miembros privados por reflexion (el scroll
  y "Ir a ID" de VisorQA, su modo de deformada, el texto de los bloques
  del inspector, el angulo de la camara) solo para que la foto muestre
  lo que se pregunta y el registro diga lo que el panel escribio. Si
  alguno cambio de nombre, la foto sale igual y registro.txt dice
  "AVISO reflexion" en vez de callar.

  Termina con Application.Quit(0). Una excepcion queda escrita en el
  registro y la app sale con Quit(2).
================================================================
*/

using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

public class CapturaSemana05 : MonoBehaviour
{
    // 1600x900 en ventana: cabe en un monitor de 1080p y deja el panel
    // (a 125 % de escala mide unos 520 px) sin tapar medio edificio.
    const int ANCHO = 1600;
    const int ALTO = 900;
    const int CALIDAD_JPG = 90;

    // Tope de toda la captura: un servidor que se cuelga o un archivo que
    // no llega no pueden dejar el exe abierto (la integracion espera a
    // que el proceso muera).
    const float TOPE_TOTAL_S = 900f;

    // La M1 de la decision 5 (semana05/MODIFICACIONES.md): los ids son del
    // LT2 y solo se usan con ese edificio.
    const string EDIFICIO_M1 = "lt2";
    const int COLUMNA_M1 = 69;
    const int NODO_M1 = 186;
    // La barra extra que muestra semana05/reanalisis_demo.py (--elemento 337).
    const int BARRA_EXTRA_M1 = 337;

    // La posicion de la carga movil que CARGA_MOVIL.md usa en la defensa
    // (P a mitad de la viga 205). La otra es la de mayor flecha bajo la
    // carga, que el JSON dice cual es (info.indice_uz_bajo_carga_min).
    const int POSICION_DEFENSA = 12;

    private string carpeta;
    private readonly StringBuilder registro = new StringBuilder();
    private readonly List<string> erroresDelLog = new List<string>();
    private int nErroresDelLog = 0;
    private int nFotos = 0;
    private bool saliendo = false;
    private float inicio = -1f;

    private VisorEstructura visor;
    private VisorQA qa;
    private VisorSemana04 s4;
    private VisorSemana03 s3;
    private CamaraOrbital cam;
    private EditorEstructura editor;
    private AnalizadorEstructural analizador;
    private VisorCargaMovil movil;
    private bool hayServidor = false;

    // La pestana y el scroll que se fijaron para la foto que viene.
    private string pestanaEsperada;
    private float scrollEsperado;

    const BindingFlags PRIVADO = BindingFlags.NonPublic | BindingFlags.Instance;

    // ============================================================
    // ARRANQUE
    // ============================================================
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Arrancar()
    {
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
        {
            if (args[i] != "-capturarS5") continue;
            var go = new GameObject("CapturaSemana05");
            go.AddComponent<CapturaSemana05>().carpeta = args[i + 1];
            return;
        }
    }

    void OnEnable() { Application.logMessageReceived += AlLog; }
    void OnDisable() { Application.logMessageReceived -= AlLog; }

    /// Los errores y excepciones de cualquier script durante la captura
    /// van al registro: una foto puede salir bien con un suscriptor
    /// reventando por detras.
    void AlLog(string texto, string pila, LogType tipo)
    {
        if (tipo != LogType.Error && tipo != LogType.Exception && tipo != LogType.Assert) return;
        nErroresDelLog++;
        if (erroresDelLog.Count < 25) erroresDelLog.Add(tipo + ": " + Recortar(texto, 300));
    }

    void Update()
    {
        if (saliendo || inicio < 0f) return;
        if (Time.realtimeSinceStartup - inicio <= TOPE_TOTAL_S) return;
        saliendo = true;
        Linea("ERROR: la captura paso el tope de " + TOPE_TOTAL_S + " s; se corta aca.");
        Escribir();
        Application.Quit(2);
    }

    /// Corre Capturar() a mano, con las corrutinas anidadas en una pila,
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
        Screen.SetResolution(ANCHO, ALTO, FullScreenMode.Windowed);
        Directory.CreateDirectory(carpeta);

        var pila = new Stack<IEnumerator>();
        pila.Push(Capturar());
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
    }

    IEnumerator Salir(int codigo)
    {
        if (saliendo) yield break;
        saliendo = true;
        Dato("salida", codigo);
        Escribir();
        yield return new WaitForSecondsRealtime(0.5f);
        Application.Quit(codigo);
    }

    // ============================================================
    // LA CAPTURA
    // ============================================================
    IEnumerator Capturar()
    {
        Linea("CAPTURA SEMANA 5   "
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
            Linea("ERROR: falta VisorEstructura listo, VisorQA, VisorSemana04 con anexo o CamaraOrbital. "
                  + "Aviso del anexo: " + (s4 != null ? s4.Aviso : "(sin VisorSemana04)"));
            yield return Salir(2);
            yield break;
        }

        yield return ProbarServidor();
        // VisorSemana04 pide GET /estados al arrancar y reintenta cada 10 s:
        // con servidor se le da ese margen para que el panel diga "conectado".
        if (hayServidor)
        {
            float topeEstados = Time.realtimeSinceStartup + 12f;
            yield return new WaitUntil(() => s4.ServidorS5Conectado || Time.realtimeSinceStartup > topeEstados);
        }

        InfoSemana04 info = s4.Anexo.info;
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
        yield return M1(ed);

        Seccion("FIN");
        Dato("fotos", nFotos);
        Dato("segundos", Time.realtimeSinceStartup - inicio);
        Dato("log.errores", nErroresDelLog);
        foreach (string e in erroresDelLog) Linea("  log | " + e);
        yield return Salir(0);
    }

    bool TodoLeido()
    {
        Buscar();
        bool movilListo = movil == null || movil.Anexo != null || !string.IsNullOrEmpty(movil.Aviso);
        return visor != null && visor.Listo && s4 != null && s4.Anexo != null
               && s4.SuperposicionLeida && movilListo;
    }

    void Buscar()
    {
        if (visor == null) visor = FindAnyObjectByType<VisorEstructura>();
        if (qa == null) qa = FindAnyObjectByType<VisorQA>();
        if (s4 == null) s4 = FindAnyObjectByType<VisorSemana04>();
        if (s3 == null) s3 = FindAnyObjectByType<VisorSemana03>();
        if (cam == null) cam = FindAnyObjectByType<CamaraOrbital>();
        if (editor == null) editor = FindAnyObjectByType<EditorEstructura>();
        if (analizador == null) analizador = FindAnyObjectByType<AnalizadorEstructural>();
        if (movil == null) movil = FindAnyObjectByType<VisorCargaMovil>();
    }

    IEnumerator ProbarServidor()
    {
        string url = analizador != null ? analizador.UrlPing() : (s4.urlServidorS5 ?? "").TrimEnd('/') + "/ping";
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
        string ruta = LectorStreaming.RutaExcelResultados(ed);
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
        foreach (EstadoS5 e in s4.EstadosSuperposicion)
            nombres.Add(e.nombre + (s4.EsPrecalculado(e.nombre) ? "(precalculado)" : ""));
        Dato("superposicion.nombres", string.Join(",", nombres.ToArray()));
        Dato("superposicion.aviso", s4.AvisoSuperposicion);
        Dato("superposicion.servidor_conectado", s4.ServidorS5Conectado);
        Dato("movil.hay", movil != null);
        Dato("movil.posiciones", movil != null ? movil.CantidadPosiciones : 0);
        Dato("movil.aviso", movil != null ? movil.Aviso : "(no hay VisorCargaMovil en la escena)");
        Dato("pestanas", string.Join("|", TitulosPestanas()));
    }

    // ------------------------------------------------------------
    // A. VISTA GENERAL
    // ------------------------------------------------------------
    IEnumerator VistaGeneral()
    {
        Seccion("A. VISTA GENERAL");
        AjustesVista.realista = true;
        AjustesVista.suelo = true;
        AjustesVista.relieve = false;      // las fotos de la Semana 5 son sin el relieve del sitio
        EventosVisor.AvisarVistaCambio();
        EncuadreGeneral();
        Pestana(VisorQA.PESTANA_VISTA);
        yield return Foto("01_vista_general_realista_con_suelo");

        AjustesVista.realista = false;
        EventosVisor.AvisarVistaCambio();
        Pestana(VisorQA.PESTANA_VISTA);
        yield return Foto("02_vista_general_tecnica");

        // El resto con la vista por defecto (decision 7).
        AjustesVista.realista = true;
        EventosVisor.AvisarVistaCambio();
    }

    // ------------------------------------------------------------
    // B. UNA FOTO POR PESTANA
    // ------------------------------------------------------------
    IEnumerator PestanasDelPanel(InfoSemana04 info)
    {
        Seccion("B. PANEL: UNA FOTO POR PESTANA");
        // Con la columna demo elegida: Elemento y Modificar tienen algo que decir.
        qa.SeleccionarElemento(info.columna_demo);
        EncuadreGeneral();
        string[] pestanas = {
            VisorQA.PESTANA_VISTA, VisorQA.PESTANA_CAPAS, VisorQA.PESTANA_CASO,
            VisorQA.PESTANA_ELEMENTO, VisorQA.PESTANA_MODIFICAR, VisorQA.PESTANA_CARGA_MOVIL };
        for (int i = 0; i < pestanas.Length; i++)
        {
            Pestana(pestanas[i]);
            yield return Foto((3 + i).ToString("00") + "_panel_" + ParaArchivo(pestanas[i]));
        }
    }

    // ------------------------------------------------------------
    // C. LAS PREGUNTAS DEL VISOR
    // ------------------------------------------------------------
    IEnumerator Preguntas(InfoSemana04 info)
    {
        Seccion("C. LAS PREGUNTAS DEL VISOR");
        ModeloEstructural m = visor.Modelo;
        int col = info.columna_demo;

        // --- 09. Donde esta: "Ir a ID" (campo + boton), centrar e inspector.
        qa.LimpiarSeleccion();
        PlegarInspectorElemento();
        PanelUI.FijarPlegable("qa.elem.identificacion", true);
        Pestana(VisorQA.PESTANA_ELEMENTO);
        // Mas alto que antes (26): la columna demo esta en el subterraneo, y
        // con las secciones solidas de la vista realista solo se ve mirando
        // dentro del hoyo.
        Angulo(38f, 35f);
        IrA(EventosVisor.TIPO_ELEMENTO, col);
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
            Pestana(VisorQA.PESTANA_ELEMENTO);
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
            Refrescar();
            qa.SeleccionarElemento(viga);
            qa.ElegirPiso(qa.NivelDeLaSeleccion());
            s4.Redibujar();
            s4.EnfocarElemento(viga);
            Encuadrar(cam.centro, Mathf.Max(cam.distancia, 16f), 48f, 30f);
            PlegarInspectorElemento();
            PanelUI.FijarPlegable("qa.elem.tributaria", true);
            PanelUI.FijarPlegable("qa.s4.esfuerzos", true);
            Pestana(VisorQA.PESTANA_ELEMENTO);
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
            EsfuerzosS4 sw = s4.EsfuerzosDe(viga);
            if (sw != null) Dato("ux.carga.anexo_w_local." + s4.casoActivo, sw.w);
            Dato("ux.carga.motivo_sin_diagrama", s4.MotivoSinDiagrama);
            qa.verAreasTributarias = false;
            Refrescar();
        }

        // --- 12. Como se deforma: la deformada del caso activo y el nodo de control.
        qa.ElegirPiso(-1);
        s4.mostrarDiagramas = false;
        s4.ElegirCaso(info.caso_por_defecto);
        s4.Redibujar();
        qa.FijarEscalaAMano(300f);   // la captura fija la suya, no la del anexo
        Modo(ModoDeformada.CasoActivo);
        int nodo = NodoControl();
        PlegarInspectorNodo();
        PanelUI.FijarPlegable("qa.nodo.desplazamiento", true);
        if (nodo >= 0) qa.SeleccionarNodo(nodo);
        EncuadreGeneral();
        Pestana(VisorQA.PESTANA_ELEMENTO);
        yield return Foto("12_como_se_deforma_" + s4.casoActivo + "_nodo_" + nodo, "Desplazamiento");
        CasoS4 activo = s4.CasoActivo();
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
            Pestana(VisorQA.PESTANA_ELEMENTO);
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
        Pestana(VisorQA.PESTANA_ELEMENTO);
        // La curva P-M va bajo "Demanda / capacidad": se lleva el scroll ahi
        // para que la foto muestre las dos (antes salia solo el texto).
        yield return ScrollA("qa.s4.demanda / capacidad", 6f);
        yield return Foto("14_capacidad_columna_" + col + "_PM_y_mapa_DC_" + s4.casoActivo, "Demanda");
        CasoS4 cc = s4.CasoActivo();
        Dato("ux.capacidad.caso_con_mas_no_pasa", masNoPasa);
        Dato("ux.capacidad.mapa_activo", s4.MapaDCActivo);
        Dato("ux.capacidad.mapa_pintadas", s4.MapaDCPintadas);
        if (cc != null)
        {
            int noPasan, fuera, total;
            VisorSemana04.ContarDemandas(cc, out noPasan, out fuera, out total);
            Dato("ux.capacidad.no_pasan", noPasan);
            Dato("ux.capacidad.fuera_de_curva", fuera);
            Dato("ux.capacidad.con_fierro", total);
            Demanda("ux.capacidad.elem." + col, s4.DemandaDe(col, cc.nombre));
            ElementoS4 e4 = s4.ElementoPorId(col);
            if (e4 != null && e4.familia >= 0 && s4.Anexo.familias != null && e4.familia < s4.Anexo.familias.Count)
                Dato("ux.capacidad.familia", s4.Anexo.familias[e4.familia].clave);
            NoPasan("ux.capacidad", cc);
        }

        // 14b. La leyenda del mapa y la lista de criticos, en la pestana Caso.
        PlegarPestanaCaso();
        PanelUI.FijarPlegable("mapa.dc", true);
        PanelUI.FijarPlegable("mapa.criticos", true);
        Pestana(VisorQA.PESTANA_CASO);
        yield return Foto("14b_mapa_DC_leyenda_y_criticos_" + s4.casoActivo);
        s4.MostrarMapaDC(false);
        qa.LimpiarSeleccion();
    }

    // ------------------------------------------------------------
    // D. SUPERPOSICION: E1..E3 precalculados y E3 pedido al servidor
    // ------------------------------------------------------------
    IEnumerator Superposicion(InfoSemana04 info)
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
        qa.FijarEscalaAMano(200f);   // la captura fija la suya, no la del anexo
        s4.MostrarMapaDC(true);
        PlegarPestanaCaso();
        PanelUI.FijarPlegable("sup.superposicion", true);
        PanelUI.FijarPlegable("mapa.dc", true);

        int n = 15;
        EstadoS5 ultimo = null;
        bool deformadaPuesta = false;
        foreach (EstadoS5 est in new List<EstadoS5>(s4.EstadosSuperposicion))
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
            Pestana(VisorQA.PESTANA_CASO);
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
            LambdasS5 l = ultimo.lambdas;
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
            CasoS4 libre = s4.CasoActivo();
            bool hecho = libre != null && libre.nombre == VisorSemana04.CASO_LIBRE;
            Dato("sup.libre.hecho", hecho);
            if (hecho)
            {
                EncuadreGeneral();
                Pestana(VisorQA.PESTANA_CASO);
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
            Pestana(VisorQA.PESTANA_CARGA_MOVIL);
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
    // E. M1: borrar la columna 69 y reanalizar en el servidor
    // ------------------------------------------------------------
    IEnumerator M1(string ed)
    {
        Seccion("E. M1: BORRAR LA COLUMNA " + COLUMNA_M1 + " Y REANALIZAR");
        if (!hayServidor || editor == null || analizador == null || ed != EDIFICIO_M1
            || visor.Modelo.ElementoPorId(COLUMNA_M1) == null)
        {
            Dato("m1.hecho", false);
            Linea("M1 no se hizo: " + (!hayServidor ? "sin servidor"
                  : editor == null ? "sin EditorEstructura" : analizador == null ? "sin AnalizadorEstructural"
                  : ed != EDIFICIO_M1 ? "el edificio es '" + ed + "' y la M1 es del LT2"
                  : "no existe la columna " + COLUMNA_M1));
            yield break;
        }
        qa.LimpiarSeleccion();
        Modo(ModoDeformada.Sin);
        qa.FijarEscalaAMano(100f);   // la captura fija la suya, no la del anexo
        // El Excel del reanalisis se escribe dentro de /analizar: con 30 s de
        // la escena un libro lento cortaria la peticion.
        analizador.timeoutSegundos = Mathf.Max(analizador.timeoutSegundos, 120f);
        Dato("m1.url", analizador.urlServidor);
        Dato("m1.timeout_s", analizador.timeoutSegundos);

        yield return Analizar("m1.antes");

        bool borrado = editor.BorrarElementoPorId(COLUMNA_M1);
        yield return null;
        yield return null;
        Dato("m1.borrado", borrado);
        Dato("m1.elementos_despues", visor.Modelo.elementos.Count);
        Dato("m1.existe_columna", visor.Modelo.ElementoPorId(COLUMNA_M1) != null);
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

        Nodo nodo = visor.Modelo.NodoPorId(NODO_M1);
        Vector3 centro = nodo != null ? Ejes.PosicionDe(nodo) : cam.centro;

        PanelUI.FijarPlegable("editor.reanalisis", true);
        PanelUI.FijarPlegable("editor.seleccion", false);
        PanelUI.FijarPlegable("editor.crear", false);
        PanelUI.FijarPlegable("editor.secciones", false);
        PanelUI.FijarPlegable("editor.controles", false);
        Encuadrar(centro + Vector3.down * 6f, 42f, 22f, 35f);
        Pestana(VisorQA.PESTANA_MODIFICAR);
        // El equilibrio va bajo "Caso mostrado": que entre entero en la foto.
        yield return ScrollA("editor.caso_mostrado", 70f);
        yield return Foto("21_M1_sin_columna_" + COLUMNA_M1 + "_deformada_G_y_equilibrio");

        qa.SeleccionarNodo(NODO_M1);
        PanelUI.FijarPlegable("editor.reanalisis", false);
        PanelUI.FijarPlegable("editor.seleccion", true);
        Pestana(VisorQA.PESTANA_MODIFICAR);
        yield return Foto("22_M1_nodo_" + NODO_M1 + "_UZ_G");
        Dato("m1.seleccion_editor", "nodo " + editor.NodoSeleccionado + ", elemento " + editor.ElementoSeleccionado);
    }

    /// Manda el modelo al servidor como el boton "Recalcular" y registra lo
    /// que volvio: desplazamientos del nodo de la M1, equilibrio por caso
    /// (el de calcular.equilibrio, tal cual llega) y las barras del nodo.
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

        // Las barras que llegan al nodo (sin la borrada) y la extra de la demo.
        var barras = new List<int>();
        foreach (Elemento e in visor.Modelo.elementos)
            if ((e.n1 == NODO_M1 || e.n2 == NODO_M1) && e.id != COLUMNA_M1) barras.Add(e.id);
        if (!barras.Contains(BARRA_EXTRA_M1)) barras.Add(BARRA_EXTRA_M1);
        barras.Sort();

        foreach (string caso in analizador.CasosDisponibles())
        {
            CasoResultado c = analizador.ResultadoDe(caso);
            if (c == null) continue;
            string p = prefijo + "." + caso;
            Dato(p + ".ok", c.ok);
            Dato(p + ".max_desplazamiento_m", c.max_desplazamiento);
            DespNodo d = Desp(c.desplazamientos, NODO_M1);
            if (d != null)
            {
                Dato(p + ".nodo." + NODO_M1 + ".ux_m", d.ux);
                Dato(p + ".nodo." + NODO_M1 + ".uy_m", d.uy);
                Dato(p + ".nodo." + NODO_M1 + ".uz_m", d.uz);
            }
            if (AnalizadorEstructural.TieneEquilibrio(c))
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
    // REGISTRO DE UN CASO, UNA POSICION, UN ESFUERZO
    // ============================================================
    void Estado(string p, CasoS4 c, EquilibrioCaso eq, int[] elementos, int nodo)
    {
        if (c == null) { Dato(p + ".hay", false); return; }
        Dato(p + ".nombre", c.nombre);
        Dato(p + ".tipo", c.tipo);
        Dato(p + ".descripcion", c.descripcion);
        Dato(p + ".factores", c.factores);
        Dato(p + ".max_desplazamiento_mm", c.max_desplazamiento_mm);
        int noPasan, fuera, total;
        VisorSemana04.ContarDemandas(c, out noPasan, out fuera, out total);
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
            EsfuerzosS4 s = c.esfuerzos != null ? c.esfuerzos.Find(x => x != null && x.id == id) : null;
            Esfuerzos(p + ".elem." + id, s);
            DemandaS4 dm = c.demandas != null ? c.demandas.Find(x => x != null && x.id == id) : null;
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
    void Esfuerzos(string p, EsfuerzosS4 s)
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

    void Demanda(string p, DemandaS4 d)
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

    void NoPasan(string p, CasoS4 c)
    {
        var ids = new List<string>();
        if (c.demandas != null)
            foreach (DemandaS4 d in c.demandas)
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
    CasoS4 CasoE1()
    {
        foreach (EstadoS5 e in s4.EstadosSuperposicion)
            if (e != null && e.nombre == "E1" && e.caso != null) return e.caso;
        return null;
    }

    /// semana05/estados_s5.json, control.reglas.viga: la barra de tipo
    /// viga* con mayor |My| en alguna estacion bajo E1.
    int VigaControl()
    {
        CasoS4 e1 = CasoE1();
        if (e1 == null || e1.esfuerzos == null) return -1;
        int mejor = -1;
        float mayor = -1f;
        foreach (EsfuerzosS4 s in e1.esfuerzos)
        {
            if (s == null || s.My == null) continue;
            ElementoS4 e = s4.ElementoPorId(s.id);
            if (e == null || e.tipo == null || !e.tipo.StartsWith("viga")) continue;
            foreach (float v in s.My)
                if (Mathf.Abs(v) > mayor) { mayor = Mathf.Abs(v); mejor = s.id; }
        }
        return mejor;
    }

    /// semana05/estados_s5.json, control.reglas.nodo: el nodo con mayor
    /// desplazamiento (norma de ux, uy, uz) bajo E1. Se compara el cuadrado:
    /// solo ordena, no escribe ningun numero.
    int NodoControl()
    {
        CasoS4 e1 = CasoE1();
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
    // FOTO
    // ============================================================
    /// Espera a que se rehagan mallas, materiales y el panel, saca la foto
    /// al final del cuadro (con el IMGUI dibujado) y anota el estado de la
    /// escena y, si se piden, los bloques del inspector cuyo titulo empieza
    /// con esos textos: lo que la foto muestra, en texto.
    IEnumerator Foto(string nombre, params string[] bloques)
    {
        // El scroll se vuelve a fijar un cuadro despues (ver CapturaSemana04:
        // VisorQA arma el inspector en su Update, despues de esta corrutina).
        yield return null;
        Scroll(scrollEsperado);
        yield return new WaitForSecondsRealtime(1.5f);
        yield return new WaitForEndOfFrame();

        Texture2D tex = ScreenCapture.CaptureScreenshotAsTexture();
        string archivo = nombre + ".jpg";
        int ancho = tex.width, alto = tex.height;
        try
        {
            File.WriteAllBytes(Path.Combine(carpeta, archivo), tex.EncodeToJPG(CALIDAD_JPG));
        }
        finally
        {
            Destroy(tex);
        }
        nFotos++;

        Linea("");
        Linea("=== FOTO " + archivo + " ===");
        string f = "foto." + nombre;
        Dato(f + ".tamano", ancho + "x" + alto);
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
        // carga_movil) y su texto: comparar_unity.py [5] los cruza con Python.
        Dato(f + ".cabecera.fuente", qa.FuenteCabecera);
        Dato(f + ".cabecera.texto", qa.TextoCabecera);
        Dato(f + ".camara", "centro " + cam.centro.ToString("F2") + " distancia "
                           + cam.distancia.ToString("0.0", CultureInfo.InvariantCulture));
        if (bloques != null && bloques.Length > 0)
            foreach (string linea in TextoBloques(bloques)) Linea("  panel | " + linea);
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
        Scroll(scrollY);
    }

    /// Cierra los bloques del inspector de una barra: cada foto abre solo
    /// los que contestan su pregunta, asi la respuesta queda arriba sin
    /// depender de un scroll medido a mano.
    static void PlegarInspectorElemento()
    {
        string[] claves = {
            "qa.elem.identificacion", "qa.elem.ejes", "qa.elem.tributaria", "qa.elem.pm",
            "qa.s4.semana 4", "qa.s4.material", "qa.s4.seccion", "qa.s4.condiciones",
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
    /// encuadre: el corrimiento por el panel lo hace ahora CamaraOrbital
    /// (CorrimientoPorPanel), igual que para F, C e "Ir a ID" en la app. Si
    /// se corriera tambien aca, lo mirado quedaria dos veces corrido.
    void Encuadrar(Vector3 centro, float distancia, float pitch, float yaw)
    {
        Angulo(pitch, yaw);
        cam.centro = centro;
        cam.distancia = distancia;
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
        Scroll(scrollEsperado);
    }

    // ============================================================
    // REFLEXION (solo para que la foto muestre lo que se pregunta)
    // ============================================================
    void Scroll(float y)
    {
        FieldInfo f = typeof(VisorQA).GetField("scroll", PRIVADO);
        Fijar(f, qa, new Vector2(0f, y), "VisorQA.scroll (Vector2)");
    }

    void Refrescar()
    {
        FieldInfo f = typeof(VisorQA).GetField("refrescar", PRIVADO);
        Fijar(f, qa, true, "VisorQA.refrescar (bool)");
    }

    void Angulo(float pitch, float yaw)
    {
        const BindingFlags B = BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance;
        Fijar(typeof(CamaraOrbital).GetField("pitch", B), cam, pitch, "CamaraOrbital.pitch (float)");
        Fijar(typeof(CamaraOrbital).GetField("yaw", B), cam, yaw, "CamaraOrbital.yaw (float)");
    }

    /// Lo mismo que escribir el id en "Ir a ID" y apretar el boton: el campo
    /// queda con el numero en la foto, y el boton selecciona y centra. Si
    /// VisorQA cambio, se hace con la API publica y se avisa.
    void IrA(string tipo, int id)
    {
        FieldInfo campo = typeof(VisorQA).GetField("campoIrA", PRIVADO);
        MethodInfo metodo = typeof(VisorQA).GetMethod("IrA", PRIVADO);
        if (campo != null && metodo != null && campo.FieldType == typeof(string))
        {
            try
            {
                campo.SetValue(qa, id.ToString(CultureInfo.InvariantCulture));
                metodo.Invoke(qa, new object[] { tipo });
                return;
            }
            catch (Exception ex)
            {
                Avisar("AVISO reflexion: VisorQA.IrA fallo: " + ex.Message);
            }
        }
        else
        {
            Avisar("AVISO reflexion: no existe VisorQA.campoIrA (string) o VisorQA.IrA(string)");
        }
        if (tipo == EventosVisor.TIPO_NODO) qa.SeleccionarNodo(id); else qa.SeleccionarElemento(id);
        qa.CentrarSeleccion();
    }

    /// El mismo camino que los botones de la pestana Caso (VisorQA.AplicarModo):
    /// una sola fuente de deformada, y el boton activo en la foto es el que se ve.
    void Modo(ModoDeformada modo)
    {
        MethodInfo metodo = typeof(VisorQA).GetMethod("AplicarModo", PRIVADO);
        if (metodo != null)
        {
            try
            {
                metodo.Invoke(qa, new object[] { modo });
                return;
            }
            catch (Exception ex)
            {
                Avisar("AVISO reflexion: VisorQA.AplicarModo fallo: " + ex.Message);
            }
        }
        else
        {
            Avisar("AVISO reflexion: no existe VisorQA.AplicarModo(ModoDeformada)");
        }
        if (modo == ModoDeformada.CasoActivo) s4.AplicarDeformadaDelCaso();
        else { s4.QuitarDeformada(); visor.LimpiarDeformada(); visor.Redibujar(); }
    }

    /// El texto de los bloques del inspector cuyo titulo empieza con alguno
    /// de 'prefijos', tal como lo escribe el panel.
    List<string> TextoBloques(string[] prefijos)
    {
        var salida = new List<string>();
        FieldInfo f = typeof(VisorQA).GetField("bloques", PRIVADO);
        IEnumerable lista = f != null ? f.GetValue(qa) as IEnumerable : null;
        if (lista == null)
        {
            Avisar("AVISO reflexion: no existe VisorQA.bloques (lista)");
            return salida;
        }
        foreach (object b in lista)
        {
            if (b == null) continue;
            FieldInfo ft = b.GetType().GetField("titulo");
            FieldInfo fc = b.GetType().GetField("cuerpo");
            string titulo = ft != null ? ft.GetValue(b) as string : null;
            string cuerpo = fc != null ? fc.GetValue(b) as string : null;
            if (titulo == null) continue;
            bool pedido = false;
            foreach (string p in prefijos)
                if (titulo.StartsWith(p, StringComparison.OrdinalIgnoreCase)) { pedido = true; break; }
            if (!pedido) continue;
            salida.Add("[" + titulo + "]");
            foreach (string l in (cuerpo ?? "").Replace("\r", "").Split('\n')) salida.Add(l);
        }
        if (salida.Count == 0) salida.Add("(ningun bloque del inspector empieza con: " + string.Join(", ", prefijos) + ")");
        return salida;
    }

    List<string> TitulosPestanas()
    {
        FieldInfo f = typeof(VisorQA).GetField("titulosPestanas", PRIVADO);
        List<string> t = f != null ? f.GetValue(qa) as List<string> : null;
        if (t == null)
        {
            Avisar("AVISO reflexion: no existe VisorQA.titulosPestanas (List<string>)");
            return new List<string>();
        }
        return new List<string>(t);
    }

    /// El equilibrio que mando Python para un caso de superposicion (lo
    /// guarda VisorSemana04 para su panel; aca solo se lee).
    EquilibrioCaso EquilibrioDe(string nombre)
    {
        FieldInfo f = typeof(VisorSemana04).GetField("Sup_equilibrios", PRIVADO);
        var dic = f != null ? f.GetValue(s4) as Dictionary<string, EquilibrioCaso> : null;
        if (dic == null)
        {
            Avisar("AVISO reflexion: no existe VisorSemana04.Sup_equilibrios");
            return null;
        }
        EquilibrioCaso eq;
        return dic.TryGetValue(nombre ?? "", out eq) ? eq : null;
    }

    void Fijar(FieldInfo f, object objeto, object valor, string campo)
    {
        if (f == null) { Avisar("AVISO reflexion: no existe el campo " + campo); return; }
        if (!f.FieldType.IsInstanceOfType(valor)) { Avisar("AVISO reflexion: " + campo + " ahora es " + f.FieldType.Name); return; }
        try { f.SetValue(objeto, valor); }
        catch (Exception ex) { Avisar("AVISO reflexion: no pude asignar " + campo + ": " + ex.Message); }
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

    void Avisar(string texto)
    {
        registro.AppendLine(texto);
        Debug.LogWarning("CapturaSemana05: " + texto);
    }

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
        try
        {
            File.WriteAllText(Path.Combine(carpeta, "registro.txt"), registro.ToString(), new UTF8Encoding(false));
        }
        catch (Exception ex)
        {
            Debug.LogWarning("CapturaSemana05: no pude escribir registro.txt: " + ex.Message);
        }
    }

    // ------------------------------------------------------------
    // D2. SUPERPOSICION INSTANTANEA (LAB de la Semana 5): Unity combina
    // ------------------------------------------------------------
    /// Mueve los sliders instantaneos DE VERDAD -- Ins_Lambdas + Ins_Aplicar,
    /// desde esta corrutina (contexto Update, no OnGUI) -- con cuatro juegos
    /// de lambdas, y deja lo que Unity CALCULO: la version (tiene que subir
    /// en cada juego; con tipo = "combinacion" subia una sola vez y todo
    /// quedaba congelado), los milisegundos, y el mismo bloque Estado(...)
    /// de los precalculados. semana05_lab/verificar_instantanea.py
    /// --registro cruza esos numeros -- float de 32 bits, los que Unity
    /// dibuja -- con superposicion.caso_combinado() de Python.
    IEnumerator SuperposicionInstantanea(InfoSemana04 info)
    {
        Seccion("D2. SUPERPOSICION INSTANTANEA (Unity combina los casos base)");
        int col = info.columna_demo, mur = info.muro_demo;
        int viga = VigaControl(), nodo = NodoControl();
        int[] elementos = { col, mur, viga };

        float[][] juegos = {
            new[] { 1f, 1f, 0f, 0f },              // E1
            new[] { 1.2f, 1.6f, 0f, 0f },          // E2
            new[] { 1.2f, 1f, -1.4f, 0f },         // E3
            new[] { -0.5f, 0.35f, 1.05f, -0.7f },  // feo a proposito: negativos
        };
        string[] nombres = { "E1", "E2", "E3", "feo" };

        qa.LimpiarSeleccion();
        s4.mostrarDiagramas = false;
        s4.MostrarMapaDC(true);
        Modo(ModoDeformada.CasoActivo);
        Dato("ins.version_antes", s4.Ins_Version);
        for (int k = 0; k < juegos.Length; k++)
        {
            float[] lam = s4.Ins_Lambdas;
            for (int c = 0; c < 4; c++) lam[c] = juegos[k][c];
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
        Dato("ins.combinaciones_pedidas", juegos.Length);

        // 18b. E3 por el camino de Unity, con el panel en los sliders y el
        //      mapa D/C: la misma foto que la 17 (E3 precalculado por Python).
        {
            float[] lam = s4.Ins_Lambdas;
            for (int c = 0; c < 4; c++) lam[c] = juegos[2][c];
            s4.Ins_Aplicar();
            yield return null;
        }
        EncuadreGeneral();
        PlegarPestanaCaso();
        PanelUI.FijarPlegable("sup.superposicion", true);
        Pestana(VisorQA.PESTANA_CASO);
        yield return ScrollA("ins.sliders", 30f);
        yield return Foto("18b_superposicion_instantanea_E3_en_Unity");
        Dato("ins.foto_E3.version", s4.Ins_Version);
        Dato("ins.foto_E3.ms", s4.Ins_MsUltima);

        // 18c. El juego feo con la columna demo seleccionada y su P-M: el
        //      punto de demanda que se movio con los sliders.
        {
            float[] lam = s4.Ins_Lambdas;
            for (int c = 0; c < 4; c++) lam[c] = juegos[3][c];
            s4.Ins_Aplicar();
            yield return null;
        }
        qa.SeleccionarElemento(col);
        PlegarInspectorElemento();
        PanelUI.FijarPlegable("qa.s4.demanda / capacidad", true);
        PanelUI.FijarPlegable("qa.elem.pm", true);
        EncuadreGeneral();
        Pestana(VisorQA.PESTANA_ELEMENTO);
        yield return ScrollA("qa.s4.demanda / capacidad", 6f);
        yield return Foto("18c_capacidad_columna_" + col + "_PM_con_sliders_instantaneos_feo", "Demanda");
        Dato("ins.foto_feo.version", s4.Ins_Version);
        CasoS4 cf = s4.CasoActivo();
        if (cf != null) Demanda("ins.foto_feo.elem." + col, s4.DemandaDe(col, cf.nombre));

        s4.MostrarMapaDC(false);
        qa.LimpiarSeleccion();
        Modo(ModoDeformada.Sin);
        if (!string.IsNullOrEmpty(info.caso_por_defecto)) s4.ElegirCaso(info.caso_por_defecto);
        Escribir();
    }
}
