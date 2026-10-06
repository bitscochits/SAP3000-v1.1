/*
================================================================
 AnalizadorEstructural.cs
================================================================
 Manda el modelo al servidor OpenSees (Python/Flask) y le entrega
 los desplazamientos al VisorEstructura para que los dibuje.

 No dibuja nada por su cuenta ni define clases de datos: usa
 ModeloEstructural.cs y delega el dibujo en VisorEstructura.cs. Los
 botones y el texto del resultado los dibuja EditorEstructura, en la
 pestana "Modificar".

 COMO USAR
  1. Ten corriendo el servidor:  python semana05/servidor_s5.py
     (comprobar http://localhost:5000/ping)
  2. Crea un GameObject vacio, llamalo "Analizador".
  3. Arrastra este script sobre el.
  4. En el Inspector, arrastra el objeto "Visor" al campo 'visor'.
  5. Play. En la pestana Modificar: "Recalcular en el servidor" o Enter.

 Para cambiar de caso (G, Q, EX, EY) usa MostrarCaso("EX"): NO
 vuelve a consultar al servidor, los 4 casos ya estan en memoria.

 ----------------------------------------------------------------
 PARA AUTOMATIZAR (CapturaSemana05, la M1 desde el exe)
 ----------------------------------------------------------------
     bool listo = false, ok = false;
     editor.BorrarElementoPorId(69);
     analizador.Analizar(r => { ok = r; listo = true; });
     yield return new WaitUntil(() => listo);
     analizador.MostrarCaso("G");
     DespNodo d = analizador.DesplazamientoDe(186);            // m
     EquilibrioCaso eq = analizador.ResultadoDe("G").equilibrio;
     string xlsx = analizador.ExcelReanalisis;                  // o ExcelError

   - Analizar llama a 'fin' EXACTAMENTE una vez: false si no se pudo
     mandar (ya habia uno en vuelo, no hay modelo) o si el servidor
     respondio con error; el motivo queda en UltimoError.
   - No encola: si Ocupado es true, esperar antes de llamar.

 ----------------------------------------------------------------
 EL EQUILIBRIO NO SE SUMA ACA
 ----------------------------------------------------------------
 Hasta la Semana 4 este script sumaba TODAS las reacciones y las
 mostraba como "deben igualar la carga aplicada". Esta mal: en un nodo
 de diafragma nodeReaction trae la fuerza interna de la restriccion, y
 la suma dobla el corte basal (CLAUDE.md, seccion 4, "Reacciones"). La
 separacion por grado de libertad vive en Python (calcular.equilibrio)
 y el servidor la devuelve en cada caso; aca solo se muestra.

 ----------------------------------------------------------------
 NOTA: el JSON se serializa con JsonUtility.ToJson sobre el mismo
 objeto que se leyo del archivo. Antes se armaba a mano con un
 StringBuilder, y eso tenia un bug feo: float.ToString() usa la
 cultura del sistema, asi que en un Windows en espanol 0.5 salia
 como "0,5" y el JSON quedaba corrupto. JsonUtility siempre usa
 punto decimal. Por lo mismo, los numeros que se muestran en el
 panel se formatean con InvariantCulture.
 ----------------------------------------------------------------

 REQUIERE: Unity 2020+ (UnityWebRequest) y el servidor en :5000
================================================================
*/

using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

public class AnalizadorEstructural : MonoBehaviour
{
    /// La direccion de siempre. El panel tiene un boton para volver a
    /// ella despues de escribir otra (servidor en otro equipo, --lan).
    public const string URL_POR_DEFECTO = "http://localhost:5000/analizar";

    [Header("Servidor")]
    public string urlServidor = URL_POR_DEFECTO;
    public float timeoutSegundos = 30f;

    [Header("Referencias")]
    [Tooltip("Arrastra aca el GameObject que tiene VisorEstructura. "
           + "De ahi sale el modelo y ahi se dibuja la deformada.")]
    public VisorEstructura visor;

    [Header("Casos de carga")]
    [Tooltip("Caso a dibujar cuando llega la respuesta. Si no calza "
           + "ninguno se usa el primero.")]
    public string casoActivo = "G";

    [Tooltip("Mandar todos los casos del modelo en una sola peticion. "
           + "Si lo apagas, se manda solo 'casoActivo'.")]
    public bool mandarTodosLosCasos = true;

    [Header("Comportamiento")]
    public bool analizarAlIniciar = true;

    // --- Estado ---
    private List<CasoResultado> ultimosCasos = new List<CasoResultado>();
    private Dictionary<int, DespNodo> ultimosDesp = new Dictionary<int, DespNodo>();
    private Dictionary<int, FuerzaElemento> ultimasFuerzas = new Dictionary<int, FuerzaElemento>();
    private bool enVuelo = false;
    private bool probandoServidor = false;

    /// true mientras hay una peticion en curso (para no encimar dos).
    public bool Ocupado { get { return enVuelo; } }

    /// true mientras se prueba /ping.
    public bool ProbandoServidor { get { return probandoServidor; } }

    /// Una linea para el panel: que paso con la ultima peticion
    /// ("Sin analizar", "Analizando...", "OK: 4 casos [G, Q, EX, EY] en 1.3 s").
    public string Estado { get; private set; }

    /// Por que fallo la ultima peticion, o "" si no fallo. Antes solo iba
    /// a Debug.LogError: en el exe no hay consola y el usuario veia que
    /// "no pasaba nada".
    public string UltimoError { get; private set; }

    /// Resultado de "Probar conexion" (/ping), o "".
    public string EstadoPing { get; private set; }

    /// Avisos del servidor (etiquetas 'tipo' que no calzan con la
    /// geometria). No son errores: el modelo se resolvio igual.
    public List<string> Avisos { get; private set; }

    /// Ruta ABSOLUTA del Excel que escribio el servidor para este
    /// reanalisis (results/excel/reanalisis_<ed>.xlsx), o "".
    public string ExcelReanalisis { get; private set; }

    /// Por que el servidor no escribio el Excel, o "".
    public string ExcelError { get; private set; }

    /// true si el modelo se edito despues de la ultima respuesta: los
    /// resultados en memoria son del modelo ANTERIOR a la edicion.
    public bool Desactualizado { get; private set; }

    /// Cuanto tardo la ultima peticion completa (s), o 0.
    public float SegundosUltimoAnalisis { get; private set; }

    /// true si hay casos resueltos en memoria.
    public bool HayResultados { get { return ultimosCasos.Count > 0; } }

    // El edificio para ?edificio= (nombre del Excel) si el modelo no trae info.edificio. Se toma
    // del anexo de la Semana 4 SOLO mientras calza con el modelo, y se guarda: despues de
    // editar, el anexo deja de calzar justo cuando mas hace falta.
    private VisorSemana04 s4;
    private string edificioDelAnexo = "";
    private float proximaBusquedaEdificio = 0f;

    // Cuantas ediciones avisaron ModeloEditado, y cuantas iban al mandar
    // la peticion en vuelo. Si difieren al llegar la respuesta, el usuario
    // edito mientras el servidor resolvia: los numeros son del modelo de
    // ANTES y no se dibujan sobre la geometria nueva.
    private int edicionesVistas = 0;
    private int edicionAlEnviar = 0;

    void Awake()
    {
        Estado = "Sin analizar.";
        UltimoError = "";
        EstadoPing = "";
        ExcelReanalisis = "";
        ExcelError = "";
        Avisos = new List<string>();
    }

    void OnEnable() { EventosVisor.ModeloEditado += AlEditarModelo; }
    void OnDisable() { EventosVisor.ModeloEditado -= AlEditarModelo; }

    void Start()
    {
        if (visor == null) visor = FindAnyObjectByType<VisorEstructura>();
        if (visor == null)
        {
            UltimoError = "No hay VisorEstructura en la escena: de ahi sale el modelo.";
            Debug.LogError("No hay VisorEstructura en la escena. Asignalo en "
                           + "el Inspector: de ahi sale el modelo.");
            return;
        }
        if (analizarAlIniciar) StartCoroutine(AnalizarCuandoHayaModelo());
    }

    // VisorEstructura puede cargar en una corrutina (Semana 5): en el
    // Start de este script el modelo quiza no esta todavia.
    IEnumerator AnalizarCuandoHayaModelo()
    {
        float limite = Time.realtimeSinceStartup + 20f;
        while ((visor == null || visor.Modelo == null) && Time.realtimeSinceStartup < limite)
            yield return null;
        EnviarModelo();
    }

    void Update() { if (edificioDelAnexo.Length == 0 && !Desactualizado) BuscarEdificioDelAnexo(); }
    // FindAnyObjectByType una vez por segundo hasta hallar VisorSemana04; hallado, se mira en
    // CADA frame: buscando cada segundo, una M1 automatizada que borra apenas carga el anexo
    // lo hallaba ya sin calzar y el libro salia reanalisis_modelo.xlsx.
    void BuscarEdificioDelAnexo()
    {
        if (s4 == null && Time.realtimeSinceStartup >= proximaBusquedaEdificio)
        { proximaBusquedaEdificio = Time.realtimeSinceStartup + 1f; s4 = FindAnyObjectByType<VisorSemana04>(); }
        if (s4 != null && s4.Anexo != null && s4.Anexo.info != null
            && s4.AnexoCalzaConElModelo && !string.IsNullOrEmpty(s4.Anexo.info.edificio))
            edificioDelAnexo = s4.Anexo.info.edificio;
    }
    void AlEditarModelo(string motivo)   // si este aviso llega antes que el de VisorSemana04, el anexo aun calza
    {
        if (edificioDelAnexo.Length == 0) BuscarEdificioDelAnexo();
        edicionesVistas++; if (HayResultados) Desactualizado = true;
    }

    // ------------------------------------------------------------
    // ENVIO
    // ------------------------------------------------------------

    /// Lo de siempre (boton, tecla Enter). Igual que Analizar(null).
    public void EnviarModelo()
    {
        Analizar(null);
    }

    /// Manda el modelo al servidor. 'fin' se llama una sola vez con true
    /// si la respuesta llego y se pudo mostrar, o false (el motivo queda
    /// en UltimoError). Devuelve si la peticion salio.
    public bool Analizar(Action<bool> fin)
    {
        if (enVuelo)
        {
            // No se toca UltimoError: describe la peticion que SI esta en
            // vuelo, y pisarla confundiria.
            Debug.LogWarning("Ya hay un analisis en curso; se ignora.");
            Terminar(fin, false);
            return false;
        }
        if (visor == null || visor.Modelo == null)
        {
            UltimoError = "No hay modelo cargado todavia: el Visor tiene que leer el JSON antes de analizar.";
            Estado = "Sin analizar.";
            Debug.LogError(UltimoError);
            Terminar(fin, false);
            return false;
        }

        ModeloEstructural m = visor.Modelo;

        // Si solo queremos un caso, se manda una copia con ese caso.
        // El modelo original NO se toca.
        string json;
        if (mandarTodosLosCasos || m.casos_de_carga == null
            || m.casos_de_carga.Count <= 1)
        {
            json = JsonUtility.ToJson(m);
        }
        else
        {
            CasoDeCarga uno = m.CasoPorNombre(casoActivo);
            if (uno == null)
            {
                Debug.LogWarning($"No existe el caso '{casoActivo}'; se mandan "
                                 + "todos.");
                json = JsonUtility.ToJson(m);
            }
            else
            {
                List<CasoDeCarga> original = m.casos_de_carga;
                m.casos_de_carga = new List<CasoDeCarga> { uno };
                json = JsonUtility.ToJson(m);
                m.casos_de_carga = original;   // restaurar siempre
            }
        }

        string url = UrlConEdificio(m);
        enVuelo = true;   // antes del StartCoroutine: un segundo Enter en el mismo frame no pasa
        edicionAlEnviar = edicionesVistas;
        UltimoError = "";
        Estado = $"Analizando {m.nodos.Count} nodos y {m.elementos.Count} barras...";
        StartCoroutine(EnviarCoroutine(json, url, fin));
        return true;
    }

    static void Terminar(Action<bool> fin, bool ok)
    {
        if (fin == null) return;
        try { fin(ok); }
        catch (Exception ex) { Debug.LogException(ex); }
    }

    // El servidor nombra el Excel con info.edificio; si el modelo no lo
    // trae (hoy data/unity/lt2.json no lo trae), con ?edificio=. Sin
    // ninguno de los dos el libro se llama reanalisis_modelo.xlsx.
    string UrlConEdificio(ModeloEstructural m)
    {
        string url = (urlServidor ?? "").Trim();
        if (m.info != null && !string.IsNullOrEmpty(m.info.edificio)) return url;
        if (edificioDelAnexo.Length == 0 || url.Contains("edificio=")) return url;
        return url + (url.Contains("?") ? "&" : "?")
               + "edificio=" + UnityWebRequest.EscapeURL(edificioDelAnexo);
    }

    IEnumerator EnviarCoroutine(string json, string url, Action<bool> fin)
    {
        float t0 = Time.realtimeSinceStartup;
        bool exito = false;
        UnityWebRequest req = null;
        try
        {
            req = new UnityWebRequest(url, "POST");
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            req.timeout = Mathf.Max(1, Mathf.RoundToInt(timeoutSegundos));
        }
        catch (Exception ex)
        {
            // Una URL mal escrita en el panel ("localhost 5000") revienta
            // aca, antes de salir. Sin el catch, enVuelo quedaria en true
            // para siempre y el boton no volveria a funcionar.
            if (req != null) req.Dispose();
            enVuelo = false;
            Fallo($"URL invalida '{url}': {ex.Message}");
            Terminar(fin, false);
            yield break;
        }

        using (req)
        {
            yield return req.SendWebRequest();
            SegundosUltimoAnalisis = Time.realtimeSinceStartup - t0;

            if (req.result == UnityWebRequest.Result.Success)
            {
                // Una excepcion al mostrar (un suscriptor de Redibujado, un
                // caso raro del JSON) no puede dejar enVuelo en true: el
                // boton y el Enter quedarian muertos para siempre.
                try
                {
                    exito = ProcesarRespuesta(req.downloadHandler.text);
                }
                catch (Exception ex)
                {
                    Debug.LogException(ex);
                    Fallo("La respuesta llego pero no se pudo mostrar: " + ex.Message);
                    exito = false;
                }
            }
            else if (req.result == UnityWebRequest.Result.ProtocolError)
            {
                // El servidor SI respondio, pero con codigo 4xx/5xx.
                // El cuerpo trae el motivo real (ej: nodo fuera del plano
                // del diafragma). Sin esto solo veriamos "HTTP/1.1 400".
                Fallo($"El servidor rechazo el modelo (HTTP {req.responseCode}): "
                      + MotivoDelCuerpo(req.downloadHandler != null ? req.downloadHandler.text : ""));
            }
            else
            {
                Fallo($"No pude conectar con {url}: {req.error}. "
                      + "Esta corriendo 'python semana05/servidor_s5.py'?");
            }
        }
        enVuelo = false;
        Terminar(fin, exito);
    }

    void Fallo(string motivo)
    {
        UltimoError = motivo;
        Estado = "Error.";
        Debug.LogError(motivo);
    }

    // Los errores del servidor son JSON {"ok": false, "error": "..."}
    // (servidor_opensees.py). Un 500 de Flask sin atrapar es HTML: se
    // muestra el principio, recortado.
    static string MotivoDelCuerpo(string cuerpo)
    {
        if (string.IsNullOrEmpty(cuerpo)) return "(sin cuerpo)";
        try
        {
            RespuestaServidor r = JsonUtility.FromJson<RespuestaServidor>(cuerpo);
            if (r != null && !string.IsNullOrEmpty(r.error)) return r.error;
        }
        catch (Exception) { }
        string t = cuerpo.Trim();
        return t.Length > 300 ? t.Substring(0, 300) + "..." : t;
    }

    /// Pide /ping al mismo servidor, para saber si esta vivo sin mandar
    /// el modelo. El resultado queda en EstadoPing.
    public void ProbarServidor()
    {
        if (probandoServidor) return;
        StartCoroutine(PingCoroutine());
    }

    /// La URL de /ping que corresponde a urlServidor.
    public string UrlPing()
    {
        string url = (urlServidor ?? "").Trim();
        try
        {
            return new Uri(url).GetLeftPart(UriPartial.Authority) + "/ping";
        }
        catch (Exception)
        {
            return url;
        }
    }

    IEnumerator PingCoroutine()
    {
        probandoServidor = true;
        string url = UrlPing();
        EstadoPing = "Probando " + url + " ...";
        UnityWebRequest req = null;
        try
        {
            req = UnityWebRequest.Get(url);
            req.timeout = 5;
        }
        catch (Exception ex)
        {
            if (req != null) req.Dispose();
            EstadoPing = $"URL invalida '{url}': {ex.Message}";
            probandoServidor = false;
            yield break;
        }
        using (req)
        {
            yield return req.SendWebRequest();
            if (req.result == UnityWebRequest.Result.Success)
            {
                string t = req.downloadHandler.text ?? "";
                EstadoPing = t.Contains("vivo")
                    ? "Servidor vivo en " + url
                    : "Respondio, pero no parece el servidor OpenSees: " + Recortar(t, 120);
            }
            else
            {
                EstadoPing = $"Sin respuesta de {url}: {req.error}";
            }
        }
        probandoServidor = false;
    }

    static string Recortar(string t, int n)
    {
        t = (t ?? "").Trim();
        return t.Length > n ? t.Substring(0, n) + "..." : t;
    }

    // ------------------------------------------------------------
    // RESPUESTA
    // ------------------------------------------------------------
    bool ProcesarRespuesta(string jsonRespuesta)
    {
        RespuestaServidor resp;
        try
        {
            resp = JsonUtility.FromJson<RespuestaServidor>(jsonRespuesta);
        }
        catch (Exception ex)
        {
            Fallo("No pude leer la respuesta del servidor: " + ex.Message);
            return false;
        }

        if (resp == null)
        {
            Fallo("La respuesta del servidor vino vacia.");
            return false;
        }

        // ComoCasos() normaliza las dos formas de respuesta (plana y
        // multi-caso) a una sola lista.
        List<CasoResultado> casos = resp.ComoCasos();
        if (!resp.ok && casos.Count == 0)
        {
            Fallo("El servidor no pudo resolver el modelo: "
                  + (string.IsNullOrEmpty(resp.error) ? "(sin motivo)" : resp.error));
            return false;
        }
        if (casos.Count == 0)
        {
            Fallo("El servidor no devolvio desplazamientos.");
            return false;
        }

        ultimosCasos = casos;
        Desactualizado = edicionesVistas != edicionAlEnviar;

        Avisos = resp.avisos != null ? resp.avisos : new List<string>();
        foreach (string a in Avisos) Debug.LogWarning("[modelo] " + a);

        ExcelReanalisis = resp.excel ?? "";
        ExcelError = resp.excel_error ?? "";
        if (ExcelError.Length > 0) Debug.LogWarning("[excel] " + ExcelError);
        else if (ExcelReanalisis.Length > 0) Debug.Log("[excel] " + ExcelReanalisis);

        string nombres = string.Join(", ", CasosDisponibles().ToArray());
        Estado = $"OK: {casos.Count} caso(s) [{nombres}] en "
                 + F(SegundosUltimoAnalisis, "0.0") + " s"
                 + (Desactualizado ? ". Editaste mientras resolvia: son del modelo anterior." : "");
        Debug.Log($"Respuesta OK: {casos.Count} caso(s) [{nombres}]");

        // ok = false con casos: la respuesta trae numeros, pero algun caso
        // no convergio. Se muestran igual y se dice cual, en vez de callar.
        // Estado sigue diciendo OK (hay numeros que mirar); el aviso va en
        // UltimoError, que el panel pinta en rojo.
        if (!resp.ok)
        {
            List<string> malos = new List<string>();
            foreach (CasoResultado c in casos) if (!c.ok) malos.Add(c.nombre);
            UltimoError = "El analisis no convergio en: "
                  + (malos.Count > 0 ? string.Join(", ", malos.ToArray()) : "(sin detalle)")
                  + (string.IsNullOrEmpty(resp.error) ? "" : ". Servidor: " + resp.error);
            Debug.LogError(UltimoError);
        }

        // Editado en vuelo: se guardan los numeros (el panel los marca como
        // del modelo anterior) pero la deformada no se dibuja.
        bool dibujar = !Desactualizado;
        if (!ElegirCaso(casoActivo, dibujar))
            ElegirCaso(ultimosCasos[0].nombre, dibujar);
        return resp.ok;
    }

    // ------------------------------------------------------------
    // Cambia el caso dibujado SIN volver a consultar al servidor:
    // los resultados de todos los casos ya estan en memoria.
    // ------------------------------------------------------------
    public bool MostrarCaso(string nombre)
    {
        return ElegirCaso(nombre, true);
    }

    bool ElegirCaso(string nombre, bool dibujar)
    {
        foreach (CasoResultado c in ultimosCasos)
        {
            if (c.nombre != nombre) continue;

            casoActivo = nombre;

            ultimosDesp.Clear();
            if (c.desplazamientos != null)
                foreach (DespNodo d in c.desplazamientos) ultimosDesp[d.id] = d;

            ultimasFuerzas.Clear();
            if (c.fuerzas_elementos != null)
                foreach (FuerzaElemento fe in c.fuerzas_elementos)
                    ultimasFuerzas[fe.id] = fe;

            // El dibujo es responsabilidad del Visor. mostrarDeformada va
            // ANTES: editar el modelo la apaga (LimpiarDeformada) y
            // AplicarDeformada no la vuelve a prender, asi que la deformada
            // del reanalisis no se veia sola (semana05/CONTRATO.md 2.3).
            if (dibujar && visor != null && c.desplazamientos != null)
            {
                visor.mostrarDeformada = true;
                visor.AplicarDeformada(c.desplazamientos);
            }

            // Mismo texto que antes de la Semana 5 (lo cita
            // semana05/reanalisis_demo.py), ahora con punto decimal siempre.
            Debug.Log($"[{nombre}] Max desplazamiento = "
                      + F(c.max_desplazamiento * 1000f, "F5") + " mm (mayor componente)");
            Debug.Log($"[{nombre}] " + DescribirEquilibrio(c));
            return true;
        }
        return false;
    }

    public List<string> CasosDisponibles()
    {
        List<string> n = new List<string>();
        foreach (CasoResultado c in ultimosCasos) n.Add(c.nombre);
        return n;
    }

    /// El caso resuelto con ese nombre, o null. Para leer su equilibrio o
    /// sus reacciones sin cambiar lo que se dibuja.
    public CasoResultado ResultadoDe(string nombre)
    {
        foreach (CasoResultado c in ultimosCasos)
            if (c.nombre == nombre) return c;
        return null;
    }

    /// El caso que se esta mostrando (el de DesplazamientoDe y FuerzaDe).
    public CasoResultado CasoMostrado { get { return ResultadoDe(casoActivo); } }

    // ------------------------------------------------------------
    // Consultas para la UI (clickear un nodo o una barra)
    // ------------------------------------------------------------
    public DespNodo DesplazamientoDe(int idNodo)
    {
        DespNodo d;
        return ultimosDesp.TryGetValue(idNodo, out d) ? d : null;
    }

    public FuerzaElemento FuerzaDe(int idElemento)
    {
        FuerzaElemento f;
        return ultimasFuerzas.TryGetValue(idElemento, out f) ? f : null;
    }

    // ------------------------------------------------------------
    // EQUILIBRIO (lo calcula Python; aca solo se lee y se escribe)
    // ------------------------------------------------------------

    /// true si el servidor mando el equilibrio de este caso. JsonUtility
    /// deja el objeto null o vacio cuando la clave no viene: se pregunta
    /// por el largo del arreglo (semana05/CONTRATO.md 2.1).
    public static bool TieneEquilibrio(CasoResultado c)
    {
        return c != null && c.equilibrio != null
               && c.equilibrio.aplicada_kN != null && c.equilibrio.aplicada_kN.Length == 3
               && c.equilibrio.reaccion_kN != null && c.equilibrio.reaccion_kN.Length == 3
               && c.equilibrio.error_kN != null && c.equilibrio.error_kN.Length == 3;
    }

    /// Tabla aplicada / reaccion / error por eje (kN), alineada para una
    /// fuente de ancho fijo (PanelUI.Mono). "" si el servidor no mando el
    /// equilibrio de este caso: en ese caso solo va NotaEquilibrio.
    /// Sin veredicto "cierra / no cierra": una tolerancia se mide contra
    /// su causa (CLAUDE.md, regla 3) y esa cuenta no se hace en C#.
    public static string TablaEquilibrio(CasoResultado c)
    {
        if (!TieneEquilibrio(c)) return "";

        EquilibrioCaso e = c.equilibrio;
        StringBuilder sb = new StringBuilder();
        sb.AppendLine("Equilibrio de " + (c.nombre ?? "?") + " (calcular.equilibrio), kN");
        sb.Append("     aplicada   reaccion      error");
        string[] ejes = { "Fx", "Fy", "Fz" };
        for (int i = 0; i < 3; i++)
        {
            // Los numeros tal como llegan: aplicada y reaccion con 2
            // decimales (el servidor redondea las fuerzas a 4), el error con
            // 4 para que se vea el residuo y no un 0.00 que lo esconda.
            sb.Append("\n" + ejes[i]
                      + F(e.aplicada_kN[i], "0.00").PadLeft(11)
                      + F(e.reaccion_kN[i], "0.00").PadLeft(11)
                      + F(e.error_kN[i], "0.0000").PadLeft(11));
        }
        return sb.ToString();
    }

    /// Lo que acompana a la tabla: si el equilibrio es confiable y por que
    /// no se cuentan todas las reacciones. Si el servidor no mando el
    /// equilibrio, explica por que la suma directa de las reacciones NO lo
    /// reemplaza (CLAUDE.md, seccion 4, "Reacciones").
    public static string NotaEquilibrio(CasoResultado c)
    {
        if (c == null) return "Sin caso.";
        if (!TieneEquilibrio(c))
        {
            return "El servidor no mando 'equilibrio' para el caso " + (c.nombre ?? "?")
                 + " (servidor viejo o fallo al calcularlo: ver los avisos). La suma "
                 + "directa de las reacciones NO es el equilibrio: en un nodo de "
                 + "diafragma nodeReaction trae la fuerza interna de la restriccion y "
                 + "sumarla dobla el corte basal (CLAUDE.md, seccion 4). Se calcula en "
                 + "Python con calcular.equilibrio; aca no se suma nada.";
        }
        EquilibrioCaso e = c.equilibrio;
        string diafragma = $"{e.nodos_en_diafragma} nodo(s) en diafragma: sus reacciones "
                         + "en los ejes que ata el diafragma (Fx y Fy en uno horizontal) no "
                         + "cuentan, son la fuerza interna de la restriccion; los nodos "
                         + "maestros no cuentan en ningun eje. error = aplicada + reaccion.";
        return e.confiable
            ? "Confiable. " + diafragma
            : $"NO confiable: {e.cargas_sin_convertir} carga(s) sin convertir a ejes globales "
              + "quedaron fuera de 'aplicada'. " + diafragma;
    }

    /// Tabla y nota juntas (para la consola y quien automatice).
    public static string DescribirEquilibrio(CasoResultado c)
    {
        string tabla = TablaEquilibrio(c);
        string nota = NotaEquilibrio(c);
        return tabla.Length > 0 ? tabla + "\n" + nota : nota;
    }

    static string F(float v, string formato)
    {
        return v.ToString(formato, CultureInfo.InvariantCulture);
    }
}
