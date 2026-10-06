/*
================================================================
  VisorSemana04.Superposicion.cs   (parte de VisorSemana04)
================================================================
  Superposicion de casos EN EL VISOR, sin sumar nada en C#.

  Dos fuentes de numeros, las dos de Python:

    E1, E2, E3   precalculados por semana05/superposicion.py en
                 StreamingAssets/superposicion.json. Funcionan SIN
                 servidor (el .exe, el telefono).
    LIBRE        los factores de los sliders, combinados por
                 semana05/servidor_s5.py (POST /combinar). Solo con
                 servidor.

  Los dos llegan como un CasoS4 COMPLETO (desplazamientos de todos los
  nodos, esfuerzos con sus estaciones, demandas con Mn y u) y se
  registran con RegistrarCasoExterno: desde ahi el panel, los
  diagramas, la deformada y la P-M los tratan igual que a un caso del
  anexo. El panel dice de donde salio cada caso (OrigenDe).

  ----------------------------------------------------------------
  POR QUE NO SE SUMA EN C#
  ----------------------------------------------------------------
  Desplazamientos y fuerzas de extremo SI se superponen linealmente,
  pero lo que se muestra no es solo eso:
   - las estaciones de los diagramas no son las mismas en todos los
     casos (en el LT2, 220 de 378 barras tienen 9 estaciones en G y 2
     en EX): no se pueden sumar posicion a posicion;
   - la demanda/capacidad NO es lineal: P y M combinados caen en otro
     punto de la curva, el extremo que manda puede cambiar y Mn es el
     de ESE P. En el muro 9 con 1.2G+1.0Q-1.4EY la suma de las u de
     cada caso da -0.863 y la u real es 0.416 (auditoria de la
     Semana 5).
  Hacerlo aca seria una segunda implementacion de demanda_capacidad.py,
  sin verificar (regla de oro del CLAUDE.md). Python combina y
  semana05/verificar_superposicion.py lo compara con una corrida
  explicita de OpenSees.

  Lo unico que este archivo hace con los factores: mostrarlos, llevar
  el slider al paso (0.05) y escribirlos en el pedido.

  ----------------------------------------------------------------
  SIN SERVIDOR
  ----------------------------------------------------------------
  Al arrancar se pide GET /estados (3 s de espera). Si no responde, el
  panel lo dice, los sliders quedan apagados, E1..E3 siguen andando y
  se vuelve a probar solo cada 10 s (o con el boton Conectar).
  Ningun fallo de red tira una excepcion: se escribe en el panel.

  El contrato de los JSON y del servidor esta en semana05/CONTRATO.md
  (secciones 3 y 6).
================================================================
*/

using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;


// ================================================================
// CONTRATO: superposicion.json, GET /estados y POST /combinar
// ----------------------------------------------------------------
// Mismas reglas que las clases de VisorSemana04.cs: cada nombre es la
// clave exacta del JSON (JsonUtility no avisa si no calza), un campo por
// linea y nada de metodos. CasoS4 y DespNodo se reusan, no se redefinen.
// ================================================================

/// Los cuatro factores de un estado: "lambdas": {"G": 1.2, ...}.
[System.Serializable]
public class LambdasS5
{
    public float G;
    public float Q;
    public float EX;
    public float EY;
}

[System.Serializable]
public class InfoSuperposicionS5
{
    public string edificio;
    public string descripcion;
    public string generado_por;
    public string[] parametros;
}

/// Un estado de la entrega (E1, E2, E3). En superposicion.json trae su
/// caso completo y su equilibrio; en GET /estados viene sin los dos.
[System.Serializable]
public class EstadoS5
{
    public string nombre;
    public string descripcion;
    public LambdasS5 lambdas;
    public CasoS4 caso;
    public EquilibrioCaso equilibrio;
}

/// Nivel superior de StreamingAssets/superposicion.json.
[System.Serializable]
public class AnexoSuperposicionS5
{
    public InfoSuperposicionS5 info;
    public List<EstadoS5> estados;
}

/// Cuerpo de POST /combinar.
[System.Serializable]
public class PeticionCombinar
{
    public string edificio;
    public float G;
    public float Q;
    public float EX;
    public float EY;
}

/// Respuesta de POST /combinar. 'caso' viene con nombre LIBRE y tipo
/// "superposicion". 'equilibrio' lo agrega semana05/superposicion.py
/// (calcular.equilibrio de la combinacion); si no viene, queda vacio.
[System.Serializable]
public class RespuestaCombinar
{
    public bool ok;
    public string error;
    public string edificio;
    public string[] parametros;
    public CasoS4 caso;
    public EquilibrioCaso equilibrio;
}

/// Rango de un slider: "G": {"min": 0.0, "max": 1.6, "paso": 0.05}.
[System.Serializable]
public class RangoS5
{
    public float min;
    public float max;
    public float paso;
}

[System.Serializable]
public class RangosS5
{
    public RangoS5 G;
    public RangoS5 Q;
    public RangoS5 EX;
    public RangoS5 EY;
}

/// Respuesta de GET /estados.
[System.Serializable]
public class RespuestaEstados
{
    public bool ok;
    public string error;
    public List<EstadoS5> estados;
    public RangosS5 rangos;
}


// ================================================================
// LA PARTE DEL VISOR
// ================================================================
public partial class VisorSemana04
{
    [Header("Superposicion (Semana 5)")]
    [Tooltip("E1..E3 precalculados por semana05/superposicion.py, en StreamingAssets.")]
    public string archivoSuperposicion = "superposicion.json";

    [Tooltip("Raiz del servidor de la Semana 5 (python semana05/servidor_s5.py). " +
             "Se le agregan /estados y /combinar. En el telefono, la IP del PC.")]
    public string urlServidorS5 = "http://localhost:5000";

    [Tooltip("Segundos de espera de POST /combinar. La primera peticion arma la " +
             "base de G, Q, EX y EY en el servidor y tarda mas (contrato: 30 o mas).")]
    public float timeoutCombinar = 90f;

    [Tooltip("Pedir /combinar solo, un momento despues de dejar de mover un slider.")]
    public bool combinarAlMover = true;

    /// El nombre del caso que devuelve POST /combinar.
    public const string CASO_LIBRE = "LIBRE";

    // --- lo que se lee desde afuera (CapturaSemana05, la cabecera) ---

    /// Los estados con boton: los de superposicion.json, o los de GET
    /// /estados si el archivo no esta.
    public IReadOnlyList<EstadoS5> EstadosSuperposicion { get { return Sup_estados; } }

    /// true cuando ya se intento leer superposicion.json (haya o no haya).
    public bool SuperposicionLeida { get; private set; }

    /// Por que E1..E3 no estan o que tienen raro. Vacio = todo bien.
    public string AvisoSuperposicion { get { return Sup_avisoArchivo; } }

    public bool ServidorS5Conectado { get { return Sup_conexion == Sup_Conexion.Conectado; } }
    public bool CombinandoEnPython { get { return Sup_combinando; } }
    public string MensajeCombinar { get { return Sup_textoCombinar; } }

    /// true si el caso vino de superposicion.json (sin servidor).
    public bool EsPrecalculado(string nombre)
    {
        return !string.IsNullOrEmpty(nombre) && Sup_precalculados.Contains(nombre);
    }

    // --- estado ---
    private enum Sup_Conexion { SinProbar, Probando, Conectado, SinServidor }

    private const string Sup_CLAVE_URL = "s5_url_servidor";
    private const float Sup_ESPERA_AL_MOVER = 0.6f;
    private const int Sup_TIMEOUT_ESTADOS = 3;
    // Sin servidor se vuelve a probar solo cada tantos segundos: en la
    // demo el servidor suele arrancarse DESPUES de abrir el visor, y asi
    // los sliders se encienden sin buscar el boton Conectar.
    private const float Sup_REINTENTO_SIN_SERVIDOR = 10f;
    private static readonly string[] Sup_NOMBRES = { "G", "Q", "EX", "EY" };
    private static readonly string[] Sup_FINALES_DE_RUTA = { "/combinar", "/estados", "/analizar", "/ping" };

    private bool Sup_arrancado = false;
    private readonly List<EstadoS5> Sup_estados = new List<EstadoS5>();
    private readonly List<EstadoS5> Sup_estadosServidor = new List<EstadoS5>();
    private readonly HashSet<string> Sup_precalculados = new HashSet<string>();
    private readonly Dictionary<string, string> Sup_origenes = new Dictionary<string, string>();
    private readonly Dictionary<string, EquilibrioCaso> Sup_equilibrios =
        new Dictionary<string, EquilibrioCaso>();
    private string Sup_avisoArchivo = "";
    private string Sup_avisoEstados = "";

    private Sup_Conexion Sup_conexion = Sup_Conexion.SinProbar;
    private string Sup_textoServidor = "servidor sin probar";
    private RangosS5 Sup_rangos = Sup_RangosPorDefecto();

    // G, Q, EX, EY. Arranca en E1 (1.0G + 1.0Q): un estado de servicio.
    private readonly float[] Sup_lambda = { 1f, 1f, 0f, 0f };
    private bool Sup_cambioSinPedir = false;
    private float Sup_ultimoMovimiento = 0f;
    private float Sup_ultimoIntento = 0f;
    private bool Sup_combinando = false;
    private string Sup_textoCombinar = "";
    private System.Action Sup_accionPendiente;

    // Lo que decide CUANTOS controles se dibujan, tomado en el evento
    // Layout. Si cambiara entre el Layout y el click (el editor avisa
    // ModeloEditado desde su OnGUI), IMGUI reclamaria.
    private bool Sup_hayDesactualizadoEnLayout, Sup_hayLibreEnLayout, Sup_hayActivoEnLayout;
    private int Sup_estadosEnLayout;

    // ============================================================
    // ARRANQUE (lo llama VisorSemana04.CargarYPreparar)
    // ============================================================
    void Sup_Arrancar()
    {
        if (Sup_arrancado || Anexo == null) return;
        Sup_arrancado = true;
        // La URL que se escribio en el panel la ultima vez: en el telefono
        // es la IP del PC, y reescribirla en cada arranque es un tramite.
        try
        {
            string guardada = PlayerPrefs.GetString(Sup_CLAVE_URL, "");
            if (!string.IsNullOrEmpty(guardada)) urlServidorS5 = guardada;
        }
        catch (System.Exception) { }
        StartCoroutine(Sup_LeerPrecalculados());
        StartCoroutine(Sup_PedirEstados());
    }

    /// Lo llama VisorSemana04.Update.
    void Sup_Actualizar()
    {
        if (Sup_accionPendiente != null)
        {
            System.Action a = Sup_accionPendiente;
            Sup_accionPendiente = null;
            a();
        }
        if (combinarAlMover && Sup_cambioSinPedir && !Sup_combinando
            && Sup_conexion == Sup_Conexion.Conectado
            && Time.unscaledTime - Sup_ultimoMovimiento >= Sup_ESPERA_AL_MOVER)
        {
            Sup_cambioSinPedir = false;
            Sup_IniciarCombinar();
        }
        if (Sup_arrancado && Sup_conexion == Sup_Conexion.SinServidor && !Sup_combinando
            && Time.unscaledTime - Sup_ultimoIntento >= Sup_REINTENTO_SIN_SERVIDOR)
            StartCoroutine(Sup_PedirEstados(true));
    }

    /// Lo llama VisorSemana04.OnDisable: una corrutina cortada deja las
    /// banderas en "ocupado" para siempre.
    void Sup_AlDeshabilitar()
    {
        Sup_combinando = false;
        if (Sup_conexion == Sup_Conexion.Probando) Sup_conexion = Sup_Conexion.SinServidor;
    }

    /// Cambiar de caso dentro de OnGUI rompe IMGUI (VisorSemana04.Panel.cs):
    /// los botones anotan la accion y Update la ejecuta.
    void Sup_Diferir(System.Action accion) { Sup_accionPendiente += accion; }

    // ============================================================
    // E1..E3 PRECALCULADOS
    // ============================================================
    IEnumerator Sup_LeerPrecalculados()
    {
        string texto = null, error = null;
        yield return LectorStreaming.Leer(archivoSuperposicion, t => texto = t, e => error = e);
        try
        {
            Sup_ProcesarPrecalculados(texto, error);
        }
        catch (System.Exception ex)
        {
            Sup_avisoArchivo = "Fallo al registrar " + archivoSuperposicion + ": " + ex.Message;
            Debug.LogError("VisorSemana04.Superposicion: " + ex);
        }
        SuperposicionLeida = true;
        Sup_CompararEstados();
    }

    void Sup_ProcesarPrecalculados(string texto, string error)
    {
        string ed = Sup_EdificioDelAnexo();
        if (!string.IsNullOrEmpty(error) || texto == null)
        {
            Sup_avisoArchivo = $"Sin {archivoSuperposicion}: E1..E3 solo con servidor. Generalo con "
                             + $"python semana05/superposicion.py {ed} y copialo con "
                             + $"python comun/lanzar_unity.py sincronizar {ed}.\n({error})";
            Debug.LogWarning("VisorSemana04.Superposicion: " + Sup_avisoArchivo);
            return;
        }

        AnexoSuperposicionS5 sup;
        try
        {
            sup = JsonUtility.FromJson<AnexoSuperposicionS5>(texto);
        }
        catch (System.Exception ex)
        {
            Sup_avisoArchivo = $"No pude leer {archivoSuperposicion}: {ex.Message}";
            Debug.LogError("VisorSemana04.Superposicion: " + Sup_avisoArchivo);
            return;
        }
        if (sup == null || sup.info == null || sup.estados == null || sup.estados.Count == 0)
        {
            Sup_avisoArchivo = $"{archivoSuperposicion} no trae info o estados: vuelve a generarlo "
                             + $"(python semana05/superposicion.py {ed}).";
            return;
        }
        // Un archivo de otro edificio tiene los mismos ids en otras barras:
        // se ignora con aviso en vez de mostrarse mal (CONTRATO, seccion 7).
        if ((sup.info.edificio ?? "") != ed)
        {
            Sup_avisoArchivo = $"{archivoSuperposicion} es de '{sup.info.edificio}' y semana04.json de "
                             + $"'{ed}': no lo uso. python semana05/superposicion.py {ed}";
            Debug.LogWarning("VisorSemana04.Superposicion: " + Sup_avisoArchivo);
            return;
        }

        var avisos = new List<string>();
        if (!Sup_MismasLineas(sup.info.parametros, Sup_ParametrosDelAnexo()))
            avisos.Add("sus parametros no son los de semana04.json (otro --cs, --q o --patron): "
                       + "E1..E3 se armaron con otros supuestos que G, Q, EX y EY del anexo");

        Sup_estados.Clear();
        Sup_precalculados.Clear();
        string generador = string.IsNullOrEmpty(sup.info.generado_por)
            ? "semana05/superposicion.py" : sup.info.generado_por;
        foreach (EstadoS5 e in sup.estados)
        {
            if (e == null || string.IsNullOrEmpty(e.nombre)) continue;
            Sup_estados.Add(e);
            string motivo = Sup_MotivoParaNoRegistrar(e.caso, e.nombre);
            if (motivo != "")
            {
                avisos.Add(e.nombre + ": " + motivo);
                continue;
            }
            string incompleto = Sup_Incompleto(e.caso);
            if (incompleto != "") avisos.Add(e.nombre + ": " + incompleto);

            RegistrarCasoExterno(e.caso);
            CasoS4 registrado;
            if (casoPorNombre.TryGetValue(e.nombre, out registrado) && registrado == e.caso)
            {
                Sup_precalculados.Add(e.nombre);
                Sup_equilibrios[e.nombre] = e.equilibrio;
                Sup_origenes[e.nombre] = $"precalculado por {generador} (StreamingAssets/{archivoSuperposicion}), "
                                       + $"sin servidor. Factores: {Sup_TextoFactores(e.caso.factores)}.";
            }
        }
        Sup_avisoArchivo = string.Join("\n", avisos);
        Debug.Log($"VisorSemana04.Superposicion: {Sup_precalculados.Count} estados precalculados "
                  + $"registrados de {archivoSuperposicion} ({generador})");
    }

    /// "" si el caso se puede registrar; si no, por que. Solo mira la
    /// forma: nombre, tipo y que no pise un caso de semana04.json.
    string Sup_MotivoParaNoRegistrar(CasoS4 c, string nombreEsperado)
    {
        if (c == null || string.IsNullOrEmpty(c.nombre)) return "no trae caso";
        if (nombreEsperado != null && c.nombre != nombreEsperado)
            return $"el caso se llama '{c.nombre}' y no '{nombreEsperado}'";
        // Con otro tipo, el panel lo dibujaria entre los casos del anexo y
        // RegistrarCasoExterno no lo dejaria reemplazar despues.
        if (c.tipo != TIPO_SUPERPOSICION)
            return $"tipo '{c.tipo}', se esperaba '{TIPO_SUPERPOSICION}'";
        CasoS4 existente;
        if (casoPorNombre.TryGetValue(c.nombre, out existente) && existente.tipo != TIPO_SUPERPOSICION)
            return $"'{c.nombre}' ya es un caso de {nombreArchivo}; no lo piso";
        return "";
    }

    /// Cuenta, no calcula: el caso tiene que traer lo mismo que los del
    /// anexo (todas las barras, todos los nodos, todas las demandas). Si
    /// falta algo, el panel lo dice en vez de mostrar barras sin esfuerzos.
    string Sup_Incompleto(CasoS4 c)
    {
        var faltas = new List<string>();
        int nElementos = Anexo.elementos != null ? Anexo.elementos.Count : 0;
        int nEsfuerzos = c.esfuerzos != null ? c.esfuerzos.Count : 0;
        if (nEsfuerzos != nElementos)
            faltas.Add($"esfuerzos de {nEsfuerzos} barras de {nElementos}");

        CasoS4 referencia = Anexo.casos.Find(x => x != null && x.tipo != TIPO_SUPERPOSICION
                                                   && x.desplazamientos != null);
        if (referencia != null)
        {
            int nNodos = referencia.desplazamientos.Count;
            int nDesp = c.desplazamientos != null ? c.desplazamientos.Count : 0;
            if (nDesp != nNodos) faltas.Add($"desplazamientos de {nDesp} nodos de {nNodos}");
            int nDemRef = referencia.demandas != null ? referencia.demandas.Count : 0;
            int nDem = c.demandas != null ? c.demandas.Count : 0;
            if (nDem != nDemRef) faltas.Add($"demandas de {nDem} barras de {nDemRef}");
        }
        return faltas.Count == 0 ? "" : "incompleto: " + string.Join(", ", faltas);
    }

    // ============================================================
    // SERVIDOR: GET /estados
    // ============================================================
    /// 'silencioso': el reintento automatico no cambia el texto del panel
    /// mientras espera (si no, parpadea cada 10 s).
    IEnumerator Sup_PedirEstados(bool silencioso = false)
    {
        if (Sup_conexion == Sup_Conexion.Probando) yield break;
        Sup_conexion = Sup_Conexion.Probando;
        Sup_ultimoIntento = Time.unscaledTime;
        string url = Sup_Url("estados");
        if (!silencioso) Sup_textoServidor = "probando " + url + " ...";

        UnityWebRequest req;
        string fallo;
        UnityWebRequestAsyncOperation op = Sup_Enviar(url, null, Sup_TIMEOUT_ESTADOS, out req, out fallo);
        using (req)
        {
            if (op != null) yield return op;
            // Se escribio otra URL mientras se esperaba: esta respuesta es de
            // la vieja y no dice nada de la nueva. Sin esto, un servidor que
            // SI estaba en la vieja dejaba "Conectado a <nueva>" y los sliders
            // encendidos, y el cierre de abajo pisaba el Probando de la prueba
            // que se lanzo con la nueva. Se descarta sin tocar el estado.
            if (url != Sup_Url("estados")) yield break;
            try
            {
                Sup_ProcesarEstados(req, fallo, url);
            }
            catch (System.Exception ex)
            {
                Sup_conexion = Sup_Conexion.SinServidor;
                Sup_textoServidor = "Fallo al leer la respuesta de " + url + ": " + ex.Message;
                Debug.LogError("VisorSemana04.Superposicion: " + ex);
            }
        }
        if (Sup_conexion == Sup_Conexion.Probando) Sup_conexion = Sup_Conexion.SinServidor;
        Sup_CompararEstados();
    }

    void Sup_ProcesarEstados(UnityWebRequest req, string fallo, string url)
    {
        string arranque = "Arrancalo con: python semana05/servidor_s5.py. E1..E3 funcionan sin el.";
        if (req == null || fallo != null)
        {
            Sup_conexion = Sup_Conexion.SinServidor;
            Sup_textoServidor = $"No pude pedir {url}: {Sup_ExplicarFallo(fallo)}. {arranque}";
            return;
        }
        if (req.result == UnityWebRequest.Result.ConnectionError)
        {
            Sup_conexion = Sup_Conexion.SinServidor;
            Sup_textoServidor = $"Sin servidor en {url} ({req.error}). {arranque}";
            return;
        }

        string errorJson;
        RespuestaEstados r = Sup_Leer<RespuestaEstados>(Sup_Cuerpo(req), out errorJson);
        if (r == null)
        {
            // Un 404 en HTML: hay algo en el puerto, pero no es el servidor de
            // la Semana 5 (p. ej. comun/servidor_opensees.py solo).
            Sup_conexion = Sup_Conexion.SinServidor;
            Sup_textoServidor = $"{url} respondio {req.responseCode} sin un JSON legible{errorJson}: "
                              + $"no parece servidor_s5. {arranque}";
            return;
        }
        if (!r.ok)
        {
            Sup_conexion = Sup_Conexion.SinServidor;
            Sup_textoServidor = $"{url} respondio con error: {r.error}";
            return;
        }

        Sup_conexion = Sup_Conexion.Conectado;
        if (Sup_RangosValidos(r.rangos)) Sup_rangos = r.rangos;
        Sup_estadosServidor.Clear();
        if (r.estados != null)
            foreach (EstadoS5 e in r.estados)
                if (e != null && !string.IsNullOrEmpty(e.nombre)) Sup_estadosServidor.Add(e);
        // Sin superposicion.json, los botones E1..E3 salen del servidor y
        // piden /combinar con sus factores.
        if (Sup_precalculados.Count == 0 && Sup_estadosServidor.Count > 0)
        {
            Sup_estados.Clear();
            Sup_estados.AddRange(Sup_estadosServidor);
        }
        Sup_textoServidor = $"Conectado a {Sup_Raiz()}: {Sup_estadosServidor.Count} estados. "
                          + "Los sliders piden POST /combinar.";
    }

    /// Los factores de E1..E3 del servidor (semana05/estados_s5.json) y los
    /// del archivo precalculado tienen que ser los mismos: si no, un boton
    /// E2 sin servidor y uno con servidor mostrarian estados distintos.
    void Sup_CompararEstados()
    {
        Sup_avisoEstados = "";
        if (Sup_estadosServidor.Count == 0 || Sup_precalculados.Count == 0) return;
        var distintos = new List<string>();
        foreach (EstadoS5 s in Sup_estadosServidor)
        {
            EstadoS5 f = Sup_estados.Find(x => x.nombre == s.nombre);
            if (f != null && !Sup_MismosFactores(f.lambdas, s.lambdas)) distintos.Add(s.nombre);
        }
        if (distintos.Count > 0)
            Sup_avisoEstados = $"{string.Join(", ", distintos)}: los factores del servidor no son los de "
                             + $"{archivoSuperposicion}. Regeneralo: python semana05/superposicion.py "
                             + Sup_EdificioDelAnexo();
    }

    // ============================================================
    // SERVIDOR: POST /combinar
    // ============================================================

    /// Pide a Python la combinacion de estos factores y, si llega bien, la
    /// muestra como caso LIBRE. false si no se pudo empezar (ya hay una en
    /// camino, no hay anexo o un factor no es un numero).
    public bool CombinarEnPython(float G, float Q, float EX, float EY)
    {
        if (Anexo == null || Sup_combinando) return false;
        float[] lam = { G, Q, EX, EY };
        foreach (float v in lam)
        {
            if (float.IsNaN(v) || float.IsInfinity(v))
            {
                Sup_textoCombinar = "Un factor no es un numero: no pido nada.";
                return false;
            }
        }
        for (int i = 0; i < 4; i++) Sup_lambda[i] = lam[i];
        Sup_cambioSinPedir = false;
        StartCoroutine(Sup_Combinar(lam));
        return true;
    }

    void Sup_IniciarCombinar()
    {
        CombinarEnPython(Sup_lambda[0], Sup_lambda[1], Sup_lambda[2], Sup_lambda[3]);
    }

    IEnumerator Sup_Combinar(float[] lam)
    {
        Sup_combinando = true;
        var pet = new PeticionCombinar
        {
            edificio = Sup_EdificioDelAnexo(),
            G = lam[0],
            Q = lam[1],
            EX = lam[2],
            EY = lam[3],
        };
        string url = Sup_Url("combinar");
        string pedido = Sup_Descripcion(lam);
        Sup_textoCombinar = $"Combinando en Python: {pedido} ... (la primera peticion arma la base "
                          + "de G, Q, EX y EY y puede tardar)";
        float t0 = Time.realtimeSinceStartup;

        UnityWebRequest req;
        string fallo;
        UnityWebRequestAsyncOperation op = Sup_Enviar(url, Sup_JsonDe(pet),
            Mathf.Max(30, Mathf.RoundToInt(timeoutCombinar)), out req, out fallo);
        using (req)
        {
            if (op != null) yield return op;
            try
            {
                Sup_ProcesarCombinar(req, fallo, url, pet, pedido, Time.realtimeSinceStartup - t0);
            }
            catch (System.Exception ex)
            {
                Sup_textoCombinar = "Fallo al mostrar la respuesta de /combinar: " + ex.Message;
                Debug.LogError("VisorSemana04.Superposicion: " + ex);
            }
        }
        Sup_combinando = false;
    }

    void Sup_ProcesarCombinar(UnityWebRequest req, string fallo, string url,
                              PeticionCombinar pet, string pedido, float segundos)
    {
        if (req == null || fallo != null)
        {
            Sup_textoCombinar = $"No pude pedir {url}: {Sup_ExplicarFallo(fallo)}";
            return;
        }
        if (req.result == UnityWebRequest.Result.ConnectionError)
        {
            Sup_conexion = Sup_Conexion.SinServidor;
            Sup_textoServidor = $"Sin servidor en {url} ({req.error}). Arrancalo con: "
                              + "python semana05/servidor_s5.py";
            Sup_textoCombinar = $"No se combino {pedido}: sin servidor. E1..E3 siguen funcionando "
                              + "(precalculados).";
            return;
        }

        // Los errores del servidor tambien son JSON ({"ok": false, "error": ...}
        // con 400 o 500): se lee el cuerpo aunque sea ProtocolError.
        string errorJson;
        RespuestaCombinar r = Sup_Leer<RespuestaCombinar>(Sup_Cuerpo(req), out errorJson);
        if (r == null)
        {
            Sup_textoCombinar = $"{url} respondio {req.responseCode} sin un JSON legible{errorJson}";
            return;
        }
        if (!r.ok)
        {
            Sup_textoCombinar = $"Python no pudo combinar {pedido}: {r.error}";
            return;
        }
        if ((r.edificio ?? "") != pet.edificio)
        {
            Sup_textoCombinar = $"El servidor combino '{r.edificio}' y el anexo es '{pet.edificio}': "
                              + "no lo muestro.";
            return;
        }
        string motivo = Sup_MotivoParaNoRegistrar(r.caso, null);
        if (motivo != "")
        {
            Sup_textoCombinar = "No registro la respuesta de /combinar: " + motivo;
            return;
        }

        Sup_conexion = Sup_Conexion.Conectado;
        CasoS4 c = r.caso;
        var avisos = new List<string>();
        string incompleto = Sup_Incompleto(c);
        if (incompleto != "") avisos.Add(incompleto);
        if (!Sup_MismasLineas(r.parametros, Sup_ParametrosDelAnexo()))
            avisos.Add("el servidor armo la base con otros parametros que semana04.json "
                       + "(otro --cs, --q o --patron)");

        Sup_origenes[c.nombre] = "combinado por semana05/servidor_s5.py (Python, POST " + url + ") a las "
                               + System.DateTime.Now.ToString("HH:mm:ss", CultureInfo.InvariantCulture)
                               + $", en {F(segundos, "0.00")} s. Factores que uso Python: "
                               + $"{Sup_TextoFactores(c.factores)}.";
        Sup_equilibrios[c.nombre] = r.equilibrio;
        RegistrarCasoExterno(c);
        ElegirCaso(c.nombre);
        Sup_textoCombinar = $"{c.nombre} = {c.descripcion}"
                          + (avisos.Count > 0 ? "\nAVISO: " + string.Join("; ", avisos) : "");
    }

    // ============================================================
    // PANEL (lo llama U2b desde DibujarControles, una vez)
    // ============================================================
    partial void Hook_DibujarSuperposicion()
    {
        PanelUI.Preparar();
        if (!PanelUI.Plegable("sup.superposicion", "Superposicion (Semana 5)", true)) return;

        GUIStyle texto = PanelUI.Texto ?? GUI.skin.label;
        GUIStyle tenue = PanelUI.Tenue ?? GUI.skin.label;
        GUIStyle aviso = PanelUI.Aviso ?? GUI.skin.label;

        if (Event.current.type == EventType.Layout)
        {
            Sup_hayDesactualizadoEnLayout = AnexoDesactualizado;
            Sup_hayLibreEnLayout = casoPorNombre.ContainsKey(CASO_LIBRE);
            Sup_hayActivoEnLayout = CasoActivo() != null;
            Sup_estadosEnLayout = Sup_estados.Count;
        }

        GUILayout.Label("E1..E3 vienen precalculados por Python (sin servidor) y LIBRE lo combina "
                        + "el servidor con los factores de los sliders: son la REFERENCIA. Mas "
                        + "abajo, los sliders instantaneos escalan y suman en Unity los mismos "
                        + "casos base ya resueltos, y se contrastan contra Python.", tenue);
        if (Sup_hayDesactualizadoEnLayout)
            GUILayout.Label("AVISO: el modelo se edito (" + MotivoDesactualizado + "). Estos "
                            + "resultados son del modelo ORIGINAL: el servidor combina el edificio "
                            + "exportado, no el editado.", aviso);

        // --- el caso activo y de donde sale ---
        CasoS4 act = CasoActivo();
        GUILayout.Label("Caso activo: " + casoActivo
                        + (act != null ? "  =  " + act.descripcion : ""), texto);
        if (Sup_hayActivoEnLayout)
        {
            string origen = act != null ? OrigenDe(act) : "";
            string resumen = "";
            if (act != null)
            {
                int noPasan, fuera, total;
                ContarDemandas(act, out noPasan, out fuera, out total);
                resumen = $"max desplazamiento {F(act.max_desplazamiento_mm, "0.000")} mm   "
                        + PanelUI.TextoDemanda(noPasan, fuera, total)
                        + Sup_TextoEquilibrio(act.nombre);
            }
            GUILayout.Label(origen, tenue);
            GUILayout.Label(resumen, tenue);
        }

        // --- E1..E3: funcionan sin servidor ---
        GUILayout.Space(PanelUI.Px(4f));
        GUILayout.Label("Estados de la entrega", texto);
        for (int k = 0; k < Sup_estadosEnLayout && k < Sup_estados.Count; k++)
        {
            EstadoS5 est = Sup_estados[k];
            bool pre = Sup_precalculados.Contains(est.nombre);
            string etiqueta = $"{est.nombre}   {est.descripcion}" + (pre ? "" : "   (con servidor)");
            if (PanelUI.Opcion(casoActivo == est.nombre, etiqueta))
                Sup_Diferir(() => Sup_ElegirEstado(est));
        }
        if (Sup_hayLibreEnLayout)
        {
            CasoS4 libre;
            casoPorNombre.TryGetValue(CASO_LIBRE, out libre);
            if (PanelUI.Opcion(casoActivo == CASO_LIBRE,
                               CASO_LIBRE + "   " + (libre != null ? libre.descripcion : "")))
                Sup_Diferir(() => ElegirCaso(CASO_LIBRE));
        }
        if (Sup_avisoArchivo != "") GUILayout.Label(Sup_avisoArchivo, aviso);
        if (Sup_avisoEstados != "") GUILayout.Label(Sup_avisoEstados, aviso);

        // --- factores libres: solo con servidor ---
        GUILayout.Space(PanelUI.Px(4f));
        GUILayout.Label("Factores libres (servidor Python)", texto);
        PanelUI.Marcar("sup.factores_libres");   // CapturaSemana05 lleva el scroll hasta aca
        GUILayout.BeginHorizontal();
        GUILayout.Label("URL", tenue, GUILayout.Width(PanelUI.Px(40f)));
        string nueva = GUILayout.TextField(urlServidorS5 ?? "");
        GUILayout.EndHorizontal();
        if (nueva != urlServidorS5)
        {
            urlServidorS5 = nueva;
            Sup_conexion = Sup_Conexion.SinProbar;
            Sup_textoServidor = "URL cambiada: pulsa Conectar";
            try { PlayerPrefs.SetString(Sup_CLAVE_URL, nueva); }
            catch (System.Exception) { }
        }
        bool probando = Sup_conexion == Sup_Conexion.Probando;
        if (GUILayout.Button(probando ? "Probando ..." : "Conectar (GET /estados)",
                             PanelUI.Boton ?? GUI.skin.button) && !probando)
            Sup_Diferir(() => StartCoroutine(Sup_PedirEstados()));
        GUILayout.Label(Sup_textoServidor,
                        Sup_conexion == Sup_Conexion.Conectado ? tenue : aviso);

        bool antes = GUI.enabled;
        GUI.enabled = antes && Sup_conexion == Sup_Conexion.Conectado;
        RangoS5[] rangos = { Sup_rangos.G, Sup_rangos.Q, Sup_rangos.EX, Sup_rangos.EY };
        for (int i = 0; i < 4; i++)
        {
            RangoS5 r = rangos[i];
            // El rango se estira para contener el factor actual: un preset
            // fuera del rango no se recorta solo al dibujar el slider.
            float min = Mathf.Min(r.min, Sup_lambda[i]);
            float max = Mathf.Max(r.max, Sup_lambda[i]);
            GUILayout.Label($"lambda {Sup_NOMBRES[i]} = {F(Sup_lambda[i], "0.00")}   "
                            + $"({F(r.min, "0.00")} a {F(r.max, "0.00")}, paso {F(r.paso, "0.00")})", texto);
            float v = GUILayout.HorizontalSlider(Sup_lambda[i], min, max);
            if (v != Sup_lambda[i])
            {
                float alPaso = Sup_AlPaso(v, r);
                if (alPaso != Sup_lambda[i])
                {
                    Sup_lambda[i] = alPaso;
                    Sup_cambioSinPedir = true;
                    Sup_ultimoMovimiento = Time.unscaledTime;
                }
            }
        }
        // No es "al soltar": IMGUI no avisa cuando se suelta un slider. Pide
        // /combinar cuando el slider lleva Sup_ESPERA_AL_MOVER sin moverse.
        combinarAlMover = GUILayout.Toggle(combinarAlMover,
            $"combinar solo ({F(Sup_ESPERA_AL_MOVER, "0.0")} s despues de dejar de mover un slider)",
            PanelUI.Casilla ?? GUI.skin.toggle);
        GUILayout.Label("Pedido: " + Sup_Descripcion(Sup_lambda)
                        + (Sup_cambioSinPedir ? "   (sin combinar todavia)" : ""), tenue);
        bool puede = !Sup_combinando;
        GUI.enabled = GUI.enabled && puede;
        if (GUILayout.Button(Sup_combinando ? "Combinando en Python ..." : "Combinar en Python",
                             PanelUI.Boton ?? GUI.skin.button))
            Sup_Diferir(Sup_IniciarCombinar);
        GUI.enabled = antes;
        GUILayout.Label(Sup_textoCombinar, Sup_textoCombinar.Contains("AVISO")
                                           || Sup_textoCombinar.StartsWith("No ")
                                           || Sup_textoCombinar.StartsWith("Python no")
                                           ? aviso : tenue);

        // Los sliders que responden en el momento y sin servidor
        // (VisorSemana05.Instantanea.cs). Van al final para que se lean
        // despues de E1..E3 y de LIBRE, que son la referencia de Python.
        GUILayout.Space(PanelUI.Px(6f));
        Ins_DibujarControles();
    }

    /// Boton E1..E3: el precalculado si esta; si no, con servidor. Los
    /// sliders toman sus factores, para seguir desde ahi.
    void Sup_ElegirEstado(EstadoS5 est)
    {
        if (est == null) return;
        if (est.lambdas != null)
        {
            Sup_lambda[0] = est.lambdas.G;
            Sup_lambda[1] = est.lambdas.Q;
            Sup_lambda[2] = est.lambdas.EX;
            Sup_lambda[3] = est.lambdas.EY;
            Sup_cambioSinPedir = false;
        }
        if (Sup_precalculados.Contains(est.nombre) && casoPorNombre.ContainsKey(est.nombre))
            ElegirCaso(est.nombre);
        else if (Sup_conexion == Sup_Conexion.Conectado)
            Sup_IniciarCombinar();
        else
            Sup_textoCombinar = $"No hay {est.nombre}: no esta en {archivoSuperposicion} y no hay servidor.";
    }

    /// De donde salio el caso, en una linea para el panel.
    public string OrigenDe(CasoS4 c)
    {
        if (c == null) return "";
        string origen;
        if (Sup_origenes.TryGetValue(c.nombre ?? "", out origen)) return origen;
        string gen = (Anexo != null && Anexo.info != null && !string.IsNullOrEmpty(Anexo.info.generado_por))
            ? Anexo.info.generado_por : "semana04/exportar_unity.py";
        return c.tipo == "combinacion"
            ? $"combinado en Python por {gen} ({nombreArchivo}). Factores: {Sup_TextoFactores(c.factores)}."
            : $"caso resuelto con OpenSees y exportado por {gen} ({nombreArchivo}).";
    }

    /// El equilibrio que mando Python para un caso de superposicion, en
    /// una linea mas del resumen. Se copian los tres vectores tal como
    /// vienen de calcular.equilibrio (la regla por GDL que no dobla el
    /// corte basal): aca no se suma ninguna reaccion.
    string Sup_TextoEquilibrio(string nombre)
    {
        EquilibrioCaso eq;
        if (string.IsNullOrEmpty(nombre) || !Sup_equilibrios.TryGetValue(nombre, out eq)) return "";
        if (eq == null || eq.aplicada_kN == null || eq.aplicada_kN.Length != 3
            || eq.reaccion_kN == null || eq.reaccion_kN.Length != 3
            || eq.error_kN == null || eq.error_kN.Length != 3)
            return "\nequilibrio: no vino en la respuesta de Python";
        return "\nequilibrio (calcular.equilibrio en Python), kN [Fx, Fy, Fz]:"
             + "\n  aplicada " + Sup_Vector(eq.aplicada_kN, "0.00")
             + "\n  reaccion " + Sup_Vector(eq.reaccion_kN, "0.00")
             + "\n  error    " + Sup_Vector(eq.error_kN, "0.0000")
             + (eq.confiable ? "" : $"   NO confiable: {eq.cargas_sin_convertir} cargas sin convertir");
    }

    static string Sup_Vector(float[] v, string formato)
    {
        return "[" + F(v[0], formato) + ", " + F(v[1], formato) + ", " + F(v[2], formato) + "]";
    }

    // ============================================================
    // AYUDAS (texto y red; ninguna toca un resultado)
    // ============================================================
    string Sup_EdificioDelAnexo()
    {
        return (Anexo != null && Anexo.info != null && Anexo.info.edificio != null)
            ? Anexo.info.edificio : "";
    }

    string[] Sup_ParametrosDelAnexo()
    {
        return (Anexo != null && Anexo.info != null) ? Anexo.info.parametros : null;
    }

    /// El texto de una excepcion al mandar, con la salida si se conoce.
    /// "Insecure connection not allowed": el proyecto tiene 'Allow
    /// downloads over HTTP' en Not allowed, y http a la IP de otro equipo
    /// (el telefono contra el PC) se corta antes de salir.
    static string Sup_ExplicarFallo(string fallo)
    {
        if (string.IsNullOrEmpty(fallo)) return "error desconocido";
        if (fallo.IndexOf("Insecure", System.StringComparison.OrdinalIgnoreCase) >= 0)
            return fallo + " (Unity bloquea http a otro equipo: Player Settings > Other Settings > "
                 + "Allow downloads over HTTP)";
        return fallo;
    }

    /// La raiz del servidor, sin barra final ni ruta: se acepta que se
    /// escriba "localhost:5000", ".../" o la URL entera de /combinar.
    string Sup_Raiz()
    {
        string u = (urlServidorS5 ?? "").Trim();
        if (u.Length == 0) u = "http://localhost:5000";
        if (!u.Contains("://")) u = "http://" + u;
        u = u.TrimEnd('/');
        foreach (string fin in Sup_FINALES_DE_RUTA)
        {
            if (u.EndsWith(fin, System.StringComparison.OrdinalIgnoreCase))
            {
                u = u.Substring(0, u.Length - fin.Length);
                break;
            }
        }
        return u;
    }

    string Sup_Url(string ruta) { return Sup_Raiz() + "/" + ruta; }

    /// Arma y manda el pedido. Una URL mal escrita o "Insecure connection
    /// not allowed" (http a otra maquina con el ajuste por defecto de
    /// Unity) tiran excepcion AL MANDAR: se atrapa y vuelve como texto.
    static UnityWebRequestAsyncOperation Sup_Enviar(string url, string cuerpoJson, int timeout,
                                                    out UnityWebRequest req, out string fallo)
    {
        req = null;
        fallo = null;
        try
        {
            if (cuerpoJson == null)
            {
                req = UnityWebRequest.Get(url);
            }
            else
            {
                req = new UnityWebRequest(url, "POST");
                req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(cuerpoJson));
                req.downloadHandler = new DownloadHandlerBuffer();
                req.SetRequestHeader("Content-Type", "application/json");
            }
            req.timeout = timeout;
            return req.SendWebRequest();
        }
        catch (System.Exception ex)
        {
            fallo = ex.Message;
            return null;
        }
    }

    static string Sup_Cuerpo(UnityWebRequest req)
    {
        try
        {
            return (req != null && req.downloadHandler != null) ? req.downloadHandler.text : "";
        }
        catch (System.Exception)
        {
            return "";
        }
    }

    static T Sup_Leer<T>(string json, out string error) where T : class
    {
        error = "";
        if (string.IsNullOrEmpty(json)) return null;
        try
        {
            return JsonUtility.FromJson<T>(json);
        }
        catch (System.Exception ex)
        {
            error = " (" + ex.Message + ")";
            return null;
        }
    }

    /// El cuerpo de POST /combinar escrito a mano, para que lleve el factor
    /// del slider tal como se ve (1.2) sin depender de como JsonUtility
    /// escribe un float (su expansion en double seria 1.2000000476837158, y
    /// esa diferencia por 34 000 kN de G ya pasa la cota de redondeo del
    /// servidor). Las claves son las de PeticionCombinar.
    static string Sup_JsonDe(PeticionCombinar p)
    {
        var sb = new StringBuilder("{");
        sb.Append("\"edificio\": \"").Append(Sup_Escapar(p.edificio)).Append("\", ");
        sb.Append("\"G\": ").Append(Sup_Numero(p.G)).Append(", ");
        sb.Append("\"Q\": ").Append(Sup_Numero(p.Q)).Append(", ");
        sb.Append("\"EX\": ").Append(Sup_Numero(p.EX)).Append(", ");
        sb.Append("\"EY\": ").Append(Sup_Numero(p.EY));
        return sb.Append("}").ToString();
    }

    static string Sup_Numero(float v)
    {
        double d = System.Math.Round((double)v, 4);
        if (System.Math.Abs(d) < 5e-5) d = 0.0;
        return d.ToString("0.####", CultureInfo.InvariantCulture);
    }

    static string Sup_Escapar(string s)
    {
        return (s ?? "").Replace("\\", "\\\\").Replace("\"", "\\\"");
    }

    /// "1.20 G + 1.00 Q - 1.40 EX": solo texto, con los factores del pedido.
    static string Sup_Descripcion(float[] lam)
    {
        var sb = new StringBuilder();
        for (int i = 0; i < 4; i++)
        {
            double d = System.Math.Round((double)lam[i], 4);
            if (System.Math.Abs(d) < 5e-5) continue;
            string valor = System.Math.Abs(d).ToString("0.00", CultureInfo.InvariantCulture);
            if (sb.Length == 0) sb.Append(d < 0 ? "-" : "").Append(valor);
            else sb.Append(d < 0 ? " - " : " + ").Append(valor);
            sb.Append(' ').Append(Sup_NOMBRES[i]);
        }
        return sb.Length > 0 ? sb.ToString() : "0 (todos los factores en cero)";
    }

    /// Los factores que dice el caso (lo que uso Python), como texto.
    static string Sup_TextoFactores(float[] f)
    {
        if (f == null || f.Length < 4) return "(el caso no trae factores)";
        var partes = new string[4];
        for (int i = 0; i < 4; i++)
            partes[i] = Sup_NOMBRES[i] + " " + f[i].ToString("0.###", CultureInfo.InvariantCulture);
        return string.Join(", ", partes);
    }

    /// Lleva el valor del slider al paso del rango. Es la resolucion del
    /// control (0.05), no un calculo: el factor que viaja es este.
    static float Sup_AlPaso(float v, RangoS5 r)
    {
        if (r != null && r.paso > 0f) v = Mathf.Round(v / r.paso) * r.paso;
        return v;
    }

    static RangosS5 Sup_RangosPorDefecto()
    {
        // Los de semana05/CONTRATO.md seccion 3, por si GET /estados no
        // responde: G y Q de 0 a 1.6; los sismos con los dos signos.
        return new RangosS5
        {
            G = new RangoS5 { min = 0f, max = 1.6f, paso = 0.05f },
            Q = new RangoS5 { min = 0f, max = 1.6f, paso = 0.05f },
            EX = new RangoS5 { min = -1.4f, max = 1.4f, paso = 0.05f },
            EY = new RangoS5 { min = -1.4f, max = 1.4f, paso = 0.05f },
        };
    }

    static bool Sup_RangosValidos(RangosS5 r)
    {
        return r != null && Sup_RangoValido(r.G) && Sup_RangoValido(r.Q)
               && Sup_RangoValido(r.EX) && Sup_RangoValido(r.EY);
    }

    static bool Sup_RangoValido(RangoS5 r)
    {
        return r != null && r.max > r.min && r.paso > 0f;
    }

    static bool Sup_MismosFactores(LambdasS5 a, LambdasS5 b)
    {
        if (a == null || b == null) return a == b;
        return a.G == b.G && a.Q == b.Q && a.EX == b.EX && a.EY == b.EY;
    }

    /// Las lineas de parametros.describir: iguales = mismos supuestos.
    static bool Sup_MismasLineas(string[] a, string[] b)
    {
        int na = a != null ? a.Length : 0;
        int nb = b != null ? b.Length : 0;
        if (na != nb) return false;
        for (int i = 0; i < na; i++)
            if ((a[i] ?? "").Trim() != (b[i] ?? "").Trim()) return false;
        return true;
    }
}
