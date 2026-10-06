/*
  VisorSemana03.cs
  ----------------
  Dibuja lo que agrega la Semana 3 sobre el modelo ya visible:

    - las cargas del caso elegido (G, Q, EX, EY o la combinacion), como
      flechas de largo proporcional a la fuerza;
    - la deformada sismica, que se le entrega al VisorEstructura;
    - la enfierradura: la jaula de la columna mas cargada, con sus
      barras, el estribo exterior y el estribo en rombo.

  NO calcula nada. Los numeros vienen resueltos desde Python en
  StreamingAssets/semana03.json, que produce semana03/exportar_unity.py.
  Esa es la regla del repositorio: OpenSees calcula, Unity muestra.

  ----------------------------------------------------------------
  LAS CARGAS VAN AL COSTADO, Y CON LA DEFORMADA
  ----------------------------------------------------------------
  Dibujadas sobre su punto de aplicacion quedan DENTRO de la
  estructura y tapan justo lo que uno quiere mirar. Por eso el conjunto
  de flechas se corre en bloque hasta quedar al lado del edificio, del
  lado opuesto a la lamina de armadura. Se conservan las posiciones
  relativas, asi que se sigue leyendo como un diagrama de cargas: la
  distribucion en altura y en planta es la misma, solo que al costado.

  Y aparecen junto con la deformada, no antes: primero se ve la
  estructura limpia, y al prender la deformada aparece lo que la esta
  empujando. Las dos cosas se controlan con `aplicarDeformada`.

  ----------------------------------------------------------------
  LA ARMADURA SIGUE A LA ESTRUCTURA (Semana 5)
  ----------------------------------------------------------------
  Las barras de las columnas y la jaula en sitio se ubican con
  VisorEstructura.PosicionActual, asi que siguen CUALQUIER deformada
  que este puesta (la sismica de aca, la del caso activo de Semana 4,
  la de un reanalisis o la de la carga movil) y no solo la sismica de
  este anexo. Cada vez que el visor redibuja (EventosVisor.Redibujado)
  las piezas se MUEVEN, no se vuelven a crear: en el LT2 con
  enfierrarTodas son 1 148 (800 barras de 40 columnas, y la jaula en
  sitio con 20 barras y 328 lados de estribo) y el editor redibuja en
  cada frame de arrastre. Respetan el
  filtro de piso con la misma regla que las barras
  (AjustesVista.ElementoEnCotaVisible).

  ----------------------------------------------------------------
  CARGA ASINCRONA
  ----------------------------------------------------------------
  El anexo se lee con LectorStreaming (sirve en Windows, Android y
  Web) y se dibuja cuando VisorEstructura.Listo: el modelo llega frames
  despues de Start, y "esperar un frame" ya no alcanza. Antes de
  dibujar se comprueba que el anexo sea de ESTE modelo (edificio y
  nodos); si no, no se dibuja nada y Aviso dice por que.

  Como usarlo:
    1. python semana03/exportar_unity.py <ed>
    2. Crea un GameObject vacio y llamalo "VisorSemana03".
    3. Arrastrale este script.
    4. Play. Los toggles del inspector prenden y apagan cada capa, y se
       aplican en caliente: OnValidate levanta una bandera y Update
       redibuja, que es como lo hace VisorEstructura.
*/

using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

// --- Contrato del JSON (los nombres calzan con exportar_unity.py) ---

[System.Serializable]
public class InfoSemana03
{
    public string descripcion;
    public string edificio;
    public string unidades;
    public List<string> parametros;
    public string nota;
}

[System.Serializable]
public class NivelSismo
{
    public int nodo_maestro;
    public float x;
    public float y;
    public float z;
    public float peso_kN;
    public float fraccion;
    public float F_kN;
}

[System.Serializable]
public class BloqueSismo
{
    public string patron;
    public float Cs;
    public float corte_basal_kN;
    public float fuerza_maxima_kN;
    public List<NivelSismo> niveles;
}

[System.Serializable]
public class PuntoSeccion
{
    public float y;
    public float z;
}

[System.Serializable]
public class PuntoXYZ
{
    public float x;
    public float y;
    public float z;
}

[System.Serializable]
public class BloqueArmadura
{
    public int columna_id;
    public float axial_G_kN;
    public float b;
    public float h;
    public float diametro_barra;
    public float diametro_estribo;
    public float espaciamiento_estribo;
    public float cuantia_pct;
    public string procedencia;
    public List<PuntoSeccion> barras;
    public List<PuntoSeccion> estribo_exterior;
    public List<PuntoSeccion> estribo_rombo;
    public PuntoXYZ nodo_inferior;
    public PuntoXYZ nodo_superior;
    public List<ColumnaRef> columnas;
}

[System.Serializable]
public class FlechaCarga
{
    public float x, y, z;         // punto de aplicacion (OpenSees)
    public float fx, fy, fz;      // vector fuerza (kN)
    public float kN;              // magnitud
}

[System.Serializable]
public class CasoCarga
{
    public string caso;
    public string descripcion;
    public float maxima_kN;
    public float total_kN;
    public List<FlechaCarga> flechas;
}

[System.Serializable]
public class ColumnaRef
{
    public int id, n1, n2;
    public float axial_G_kN;
}

[System.Serializable]
public class CasoDeformada
{
    public string caso;
    public float max_horizontal_mm;
    public List<DespNodo> desplazamientos;
}

[System.Serializable]
public class CajaEdificio
{
    public float x_min, x_max, y_min, y_max, z_min, z_max;
}

[System.Serializable]
public class AnexoSemana03
{
    public InfoSemana03 info;
    public CajaEdificio caja;
    public BloqueSismo sismo;
    public BloqueArmadura armadura;
    public List<CasoDeformada> deformadas;
    public List<CasoCarga> cargas;
}


public class VisorSemana03 : MonoBehaviour
{
    [Header("Archivo")]
    public string nombreArchivo = "semana03.json";

    [Header("Capas")]
    public bool mostrarCargas = true;
    public bool mostrarArmadura = true;

    [Tooltip("Enfierra TODAS las columnas, no solo la del detalle. Los " +
             "estribos solo se dibujan en la del detalle: en el LT2 (40 " +
             "columnas enfierradas en semana03.json) serian 13 120 objetos " +
             "y solo las barras ya son 800.")]
    public bool enfierrarTodas = true;

    [Header("Deformada")]
    [Tooltip("Prende la deformada del caso sismico en el VisorEstructura, " +
             "y con ella las cargas. Apagarlo devuelve la estructura sin " +
             "deformar y quita las flechas. El visor la escala con su " +
             "propio factorEscala (300 por defecto): en el LT2 EX son " +
             "17.2 mm reales y EY 16.6 mm (max_horizontal_mm de " +
             "semana03.json).")]
    public bool aplicarDeformada = true;

    [Tooltip("EX o EY.")]
    public string casoDeformada = "EX";

    [Header("Cargas")]
    [Tooltip("G, Q, EX, EY o COMBINACION. La combinacion usa los lambda " +
             "de parametros.json y viene ya sumada desde Python.")]
    public string casoCarga = "EX";

    [Tooltip("Corre las flechas en bloque hasta el costado del edificio. " +
             "Sobre su punto de aplicacion quedan dentro de la estructura " +
             "y tapan la vista; al lado se leen como un diagrama.")]
    public bool cargasAlCostado = true;

    [Tooltip("Las cargas solo se dibujan cuando la deformada esta puesta. " +
             "Asi la estructura se ve limpia primero, y al prender la " +
             "deformada aparece lo que la empuja.")]
    public bool cargasConLaDeformada = true;

    [Tooltip("Cuanto se separan las flechas del edificio, como fraccion " +
             "de su ancho en planta. Con 0.15 sobre un edificio de 50 m " +
             "quedan a unos 7 m del borde: al lado, no perdidas lejos.")]
    public float separacionCargas = 0.15f;

    [Tooltip("Largo en metros de la flecha mas grande del caso.")]
    public float largoFlechaMaxima = 6f;

    [Tooltip("Bajo este porcentaje de la fuerza mayor la flecha no se " +
             "dibuja. Evita 800 palitos invisibles en G o Q.")]
    [Range(0f, 50f)] public float umbralPorcentaje = 8f;

    public float grosorFlecha = 0.18f;
    public Color colorSismo = new Color(1f, 0.35f, 0.1f);

    [Header("Armadura")]
    [Tooltip("Dibuja la jaula dentro de la columna real. A escala del " +
             "edificio (50 x 29 m) queda del porte de un punto.")]
    public bool jaulaEnSitio = true;

    [Tooltip("Copia ampliada al costado del edificio, como lamina de " +
             "detalle: es la unica forma de ver de verdad las barras y " +
             "los estribos. Apagada por defecto porque a escala del " +
             "edificio parece una columna gigante flotando al lado.")]
    public bool jaulaDetalle = false;

    [Tooltip("Cuantas veces se amplia la jaula de la vista de detalle.")]
    public float escalaDetalle = 6f;

    [Tooltip("Las barras reales son de 16 mm: a escala del edificio no " +
             "se ven. Este factor las engorda solo para poder mirarlas.")]
    public float exageracionBarra = 6f;
    public Color colorBarra = new Color(0.1f, 0.1f, 0.12f);
    public Color colorEstribo = new Color(0.7f, 0.1f, 0.1f);

    public AnexoSemana03 Anexo { get; private set; }

    /// Vacio si el anexo calza con el modelo del visor (o todavia no se
    /// comprobo). Si no, por que no se dibuja: para el panel.
    public string Aviso { get; private set; } = "";

    /// true si el anexo es de este modelo: mismo edificio (cuando los dos
    /// lo dicen), deformadas con los mismos nodos y columnas que existen.
    public bool AnexoCalzaConElModelo { get; private set; }

    private readonly List<GameObject> creados = new List<GameObject>();
    private readonly Dictionary<Color, Material> materiales =
        new Dictionary<Color, Material>();

    private bool necesitaRedibujar = false;
    private bool deformadaPuesta = false;

    private VisorEstructura visor;
    private bool leyendo = false;     // corrutina de lectura en curso
    private bool preparado = false;   // anexo leido y visor listo (o sin visor)
    private bool avisoDado = false;

    /// Un trozo de armadura que va pegado a una columna: el segmento
    /// entre Lerp(pie, cabeza, t1) + off1 y Lerp(pie, cabeza, t2) + off2.
    /// Una barra es t1 = 0, t2 = 1 con el mismo off; un lado de estribo
    /// es t1 = t2 con off1 y off2 en dos vertices del poligono. Asi un
    /// solo "Colocar" sirve para las dos cosas y para cualquier deformada.
    class PiezaColumna
    {
        public Transform tr;
        public int n1 = -1, n2 = -1;          // nodos del modelo; -1 = coordenadas fijas
        public int elemento = -1;             // la columna; si el editor la borra, la pieza se apaga
        public Vector3 pieFijo, cabezaFija;   // si no hay nodos (sin visor)
        public float zInf, zSup;              // cotas OpenSees, para el filtro de piso
        public float t1, t2;
        public Vector3 off1, off2;
        public float grosor;
    }
    private readonly List<PiezaColumna> piezas = new List<PiezaColumna>();

    void OnEnable()
    {
        EventosVisor.Redibujado += AlRedibujarVisor;
    }

    void OnDisable()
    {
        EventosVisor.Redibujado -= AlRedibujarVisor;
    }

    void Start()
    {
        // Si otro script ya llamo a Redibujar (en su propio Start), la
        // lectura ya arranco: no se lee ni se dibuja dos veces.
        if (Anexo == null && !leyendo) StartCoroutine(Preparar());
    }

    /// Lee el anexo, espera al modelo del visor, comprueba que calcen y
    /// dibuja. Antes se esperaba UN frame: con la lectura asincrona el
    /// modelo puede tardar mas, y la armadura salia sin columnas.
    IEnumerator Preparar()
    {
        leyendo = true;
        yield return Leer();
        leyendo = false;
        if (Anexo == null) yield break;

        yield return EsperarAlVisor();
        Comprobar();
        preparado = true;
        Redibujar();
    }

    IEnumerator Leer()
    {
        string texto = null, error = null;
        yield return LectorStreaming.Leer(nombreArchivo, t => texto = t, e => error = e);
        if (texto == null)
        {
            Debug.LogError("VisorSemana03: " + error + ". Corre primero: "
                           + "python semana03/exportar_unity.py <ed> (deja la copia "
                           + "en StreamingAssets)");
            yield break;
        }

        AnexoSemana03 leido = null;
        try { leido = JsonUtility.FromJson<AnexoSemana03>(texto); }
        catch (System.Exception ex)
        {
            Debug.LogError("VisorSemana03: " + nombreArchivo + " no se pudo interpretar: "
                           + ex.Message);
        }
        if (leido == null)
        {
            Debug.LogError("VisorSemana03: no pude leer " + nombreArchivo);
            yield break;
        }
        Anexo = leido;
    }

    IEnumerator EsperarAlVisor()
    {
        if (visor == null) visor = FindAnyObjectByType<VisorEstructura>();
        if (visor == null)
        {
            Debug.LogWarning("VisorSemana03: no hay VisorEstructura en la escena. "
                             + "Dibujo las cargas y la jaula con las coordenadas del "
                             + "anexo, sin deformada ni armadura de todas las columnas.");
            yield break;
        }

        float desde = Time.realtimeSinceStartup;
        bool avisado = false;
        while (visor != null && !visor.Listo)
        {
            if (!avisado && Time.realtimeSinceStartup - desde > 10f)
            {
                avisado = true;
                Debug.LogWarning("VisorSemana03: llevo 10 s esperando a que "
                                 + "VisorEstructura cargue su modelo (su error, si lo "
                                 + "hay, esta en la consola). Dibujo cuando este listo.");
            }
            yield return null;
        }
    }

    /// El anexo de Semana 3 es de UN modelo: sus deformadas y sus columnas
    /// van por id de nodo. Dibujado sobre otro edificio no da error: da
    /// una deformada "razonable" y barras en columnas que no son. Se
    /// comprueba por dato, no por nombre de archivo.
    void Comprobar()
    {
        AnexoCalzaConElModelo = false;
        Aviso = "";
        if (visor == null || visor.Modelo == null || visor.Modelo.nodos == null) return;
        ModeloEstructural m = visor.Modelo;
        var motivos = new List<string>();

        string edAnexo = Anexo.info != null ? Anexo.info.edificio : "";
        string edModelo = m.info != null ? m.info.edificio : "";
        if (!string.IsNullOrEmpty(edAnexo) && !string.IsNullOrEmpty(edModelo)
            && edAnexo != edModelo)
            motivos.Add($"el anexo es de '{edAnexo}' y el modelo de '{edModelo}'");

        if (Anexo.deformadas != null)
        {
            foreach (CasoDeformada cd in Anexo.deformadas)
            {
                if (cd == null || cd.desplazamientos == null) continue;
                int ajenos = 0;
                foreach (DespNodo d in cd.desplazamientos)
                    if (m.NodoPorId(d.id) == null) ajenos++;
                if (ajenos > 0 || cd.desplazamientos.Count != m.nodos.Count)
                    motivos.Add($"la deformada {cd.caso} trae {cd.desplazamientos.Count} "
                                + $"nodos ({ajenos} que el modelo no tiene) y el modelo "
                                + $"tiene {m.nodos.Count}");
            }
        }

        BloqueArmadura a = Anexo.armadura;
        if (a != null && a.columnas != null)
        {
            int sinNodo = 0;
            foreach (ColumnaRef c in a.columnas)
                if (m.NodoPorId(c.n1) == null || m.NodoPorId(c.n2) == null) sinNodo++;
            if (sinNodo > 0)
                motivos.Add($"{sinNodo} de {a.columnas.Count} columnas enfierradas "
                            + "apuntan a nodos que el modelo no tiene");
        }

        AnexoCalzaConElModelo = motivos.Count == 0;
        if (!AnexoCalzaConElModelo)
            Aviso = "El anexo de Semana 3 es de otro modelo: " + string.Join("; ", motivos)
                    + ". Vuelve a exportar: python semana03/exportar_unity.py <ed>";
    }

    // Los toggles se aplican en caliente, con el mismo mecanismo que usa
    // VisorEstructura: OnValidate no puede destruir objetos, asi que solo
    // levanta la bandera y Update redibuja.
    void OnValidate()
    {
        if (Application.isPlaying && Anexo != null) necesitaRedibujar = true;
    }

    void Update()
    {
        if (necesitaRedibujar) { necesitaRedibujar = false; Redibujar(); }
    }

    /// El visor rehizo sus barras (otra deformada, otra escala, otro
    /// piso, un nodo arrastrado): la armadura se MUEVE a las posiciones
    /// nuevas. No llama a Redibujar del visor (lazo infinito, CONTRATO
    /// seccion 2.1) ni crea objetos.
    void AlRedibujarVisor()
    {
        if (piezas.Count > 0) ColocarPiezas();
    }

    /// Pone o quita la deformada en el VisorEstructura, segun el toggle.
    /// Devuelve si quedo puesta: de eso depende que se dibujen las cargas.
    public bool SincronizarDeformada()
    {
        if (visor == null) visor = FindAnyObjectByType<VisorEstructura>();
        if (visor == null)
        {
            Debug.LogWarning("VisorSemana03: no hay VisorEstructura en la "
                             + "escena, asi que no hay deformada que aplicar.");
            return false;
        }
        // Sin modelo todavia no hay a quien aplicarsela; Preparar vuelve
        // a pasar por aca cuando este listo.
        if (!visor.Listo) return false;

        if (!aplicarDeformada)
        {
            // Solo se limpia lo que puso ESTE script. La deformada de
            // gravedad la pone el panel de QA con los ux/uy/uz que el
            // JSON trae precalculados; si la borraramos aca, elegir
            // "Gravedad" en el panel la apagaria en el mismo frame.
            // LimpiarDeformada() ademas solo borra el estado, asi que
            // hay que pedir el redibujo.
            if (deformadaPuesta)
            {
                visor.LimpiarDeformada();
                visor.Redibujar();
            }
            return false;
        }

        if (!AnexoCalzaConElModelo) return false;
        if (Anexo == null || Anexo.deformadas == null) return false;
        CasoDeformada c = Anexo.deformadas.Find(d => d.caso == casoDeformada);
        if (c == null)
        {
            Debug.LogWarning($"VisorSemana03: no encontre el caso "
                             + $"'{casoDeformada}'. Usa EX o EY.");
            return false;
        }

        visor.mostrarDeformada = true;
        visor.AplicarDeformada(c.desplazamientos);   // ya redibuja
        Debug.Log($"VisorSemana03: deformada {c.caso} aplicada "
                  + $"({c.desplazamientos.Count} nodos, maximo real "
                  + $"{c.max_horizontal_mm:0.00} mm; el visor la amplifica "
                  + $"x{visor.factorEscala:0}).");
        return true;
    }

    /// Se puede llamar desde el inspector o desde otro script tras
    /// cambiar los toggles. Si el anexo o el modelo todavia no llegan,
    /// no dibuja: Preparar dibuja al terminar, con los toggles de ese
    /// momento.
    public void Redibujar()
    {
        Limpiar();
        if (Anexo == null)
        {
            // Con el objeto apagado StartCoroutine falla con un error; al
            // prenderlo, Start (o el siguiente Redibujar) lo lee.
            if (!leyendo && gameObject.activeInHierarchy) StartCoroutine(Preparar());
            return;
        }
        if (!preparado) return;
        Dibujar();
    }

    void Limpiar()
    {
        foreach (GameObject g in creados)
            if (g != null) DestroyImmediate(g);
        creados.Clear();
        piezas.Clear();
    }

    void Dibujar()
    {
        // Con visor, un anexo de otro modelo no se dibuja: ni flechas (son
        // de otro edificio) ni barras (irian a columnas que no son).
        if (visor != null && !AnexoCalzaConElModelo)
        {
            if (!avisoDado)
            {
                avisoDado = true;
                Debug.LogWarning("VisorSemana03: no dibujo nada. " + Aviso);
            }
            deformadaPuesta = SincronizarDeformada();   // con !calza solo suelta la suya
            return;
        }

        // Primero la deformada: mueve la estructura, y de si quedo puesta
        // depende que las cargas se dibujen.
        deformadaPuesta = SincronizarDeformada();

        if (mostrarCargas && Anexo.cargas != null
            && (deformadaPuesta || !cargasConLaDeformada))
            DibujarCargas();

        if (mostrarArmadura && Anexo.armadura != null)
        {
            if (jaulaEnSitio) DibujarArmadura(Anexo.armadura, 1f, Vector3.zero);
            if (jaulaDetalle)
                DibujarArmadura(Anexo.armadura, escalaDetalle, OffsetDetalle());
            if (enfierrarTodas) DibujarBarrasDeTodas();
        }
    }

    // ----------------------------------------------------------------
    // SISMO
    // ----------------------------------------------------------------
    /// Cuanto hay que correr el conjunto de flechas para que quede al
    /// costado del edificio, del lado contrario a la lamina de armadura.
    ///
    /// Se ancla al borde IZQUIERDO del propio conjunto y no al centro del
    /// edificio: asi la separacion es la misma se dibujen cinco flechas
    /// -- las de un caso sismico, en los nodos maestros -- o las
    /// quinientas de G, repartidas por toda la planta.
    Vector3 OffsetCargas(List<FlechaCarga> visibles)
    {
        if (!cargasAlCostado || Anexo.caja == null || visibles.Count == 0)
            return Vector3.zero;

        float borde = float.MaxValue;
        foreach (FlechaCarga f in visibles) borde = Mathf.Min(borde, f.x);

        CajaEdificio c = Anexo.caja;
        // El +largoFlechaMaxima deja sitio para la COLA: en un caso
        // sismico la flecha empuja en +x y su cola sale por la izquierda.
        float destino = c.x_max + separacionCargas * (c.x_max - c.x_min)
                      + largoFlechaMaxima;
        // Ejes.AUnity manda: OpenSees x -> Unity x.
        return new Vector3(destino - borde, 0f, 0f);
    }

    void DibujarCargas()
    {
        CasoCarga c = Anexo.cargas.Find(x => x.caso == casoCarga);
        if (c == null)
        {
            Debug.LogWarning($"VisorSemana03: no existe el caso de carga "
                             + $"'{casoCarga}'. Usa G, Q, EX, EY o COMBINACION.");
            return;
        }
        if (c.flechas == null || c.maxima_kN <= 0f) return;

        // G y Q traen ~500 flechas, casi todas chicas. Dibujarlas todas
        // llena la pantalla de palitos y no se entiende nada.
        float umbral = c.maxima_kN * umbralPorcentaje / 100f;
        List<FlechaCarga> visibles = new List<FlechaCarga>();
        foreach (FlechaCarga f in c.flechas)
            if (f.kN >= umbral) visibles.Add(f);
        if (visibles.Count == 0) return;

        Vector3 offset = OffsetCargas(visibles);

        Transform padre = new GameObject("Cargas_" + c.caso).transform;
        padre.SetParent(transform, false);
        creados.Add(padre.gameObject);

        foreach (FlechaCarga f in visibles)
        {
            Vector3 punta = Ejes.AUnity(f.x, f.y, f.z) + offset;
            // AUnity es lineal, asi que sirve igual para el vector fuerza.
            Vector3 dir = Ejes.AUnity(f.fx, f.fy, f.fz);
            if (dir.sqrMagnitude < 1e-12f) continue;
            dir.Normalize();

            float largo = largoFlechaMaxima * f.kN / c.maxima_kN;
            Vector3 cola = punta - dir * largo;
            Vector3 cuello = punta - dir * largo * 0.32f;

            GameObject cuerpo = Cilindro(cola, cuello, grosorFlecha);
            cuerpo.name = $"{c.caso}_{f.kN:0.#}kN";
            cuerpo.transform.SetParent(padre, true);
            Pintar(cuerpo, colorSismo);
            creados.Add(cuerpo);

            GameObject cabeza = Cono(cuello, punta, grosorFlecha * 2.4f);
            cabeza.name = cuerpo.name + "_punta";
            cabeza.transform.SetParent(padre, true);
            Pintar(cabeza, colorSismo);
            creados.Add(cabeza);
        }

        Debug.Log($"VisorSemana03: caso {c.caso} ({c.descripcion}) - "
                  + $"{visibles.Count} de {c.flechas.Count} flechas sobre el "
                  + $"{umbralPorcentaje:0}% de {c.maxima_kN:0.0} kN, "
                  + (cargasAlCostado
                     ? $"corridas {offset.x:0.0} m al costado. "
                     : "sobre su punto de aplicacion. ")
                  + $"Total del caso: {c.total_kN:0.0} kN.");
    }

    /// Barras de las columnas enfierradas, pegadas a sus nodos: siguen la
    /// deformada que tenga puesta el visor, sea cual sea.
    /// Los estribos NO se dibujan aca: en el LT2 serian 13 120 objetos.
    void DibujarBarrasDeTodas()
    {
        BloqueArmadura a = Anexo.armadura;
        if (a.columnas == null || a.columnas.Count == 0 || a.barras == null) return;

        if (visor == null) visor = FindAnyObjectByType<VisorEstructura>();
        if (visor == null || visor.Modelo == null)
        {
            Debug.LogWarning("VisorSemana03: sin VisorEstructura no se donde "
                             + "estan las columnas; no puedo enfierrarlas.");
            return;
        }

        Transform padre = new GameObject("Armadura_todas").transform;
        padre.SetParent(transform, false);
        creados.Add(padre.gameObject);

        float grosor = a.diametro_barra * exageracionBarra;
        int hechas = 0, visibles = 0;
        foreach (ColumnaRef col in a.columnas)
        {
            Nodo na = visor.Modelo.NodoPorId(col.n1);
            Nodo nb = visor.Modelo.NodoPorId(col.n2);
            if (na == null || nb == null) continue;

            foreach (PuntoSeccion p in a.barras)
            {
                Vector3 off = new Vector3(p.y, 0f, p.z);
                GameObject barra = Cilindro(Vector3.zero, Vector3.up, grosor);
                barra.name = $"col{col.id}_barra";
                barra.transform.SetParent(padre, true);
                Pintar(barra, colorBarra);
                creados.Add(barra);
                AgregarPieza(barra, col.id, na, nb, 0f, 1f, off, off, grosor);
            }
            hechas++;
            if (AjustesVista.ElementoEnCotaVisible(na.z, nb.z)) visibles++;
        }

        bool deformada = visor.mostrarDeformada && visor.HayDeformada;
        Debug.Log($"VisorSemana03: {hechas} columnas enfierradas "
                  + $"({hechas * a.barras.Count} barras"
                  + (deformada ? ", sobre la deformada que tiene puesta el visor" : "")
                  + (AjustesVista.HayFiltroDePiso ? $", {visibles} en el piso visible" : "")
                  + "). Los estribos van solo en la vista de detalle.");
    }

    // ----------------------------------------------------------------
    // PIEZAS QUE SIGUEN A SU COLUMNA
    // ----------------------------------------------------------------
    void AgregarPieza(GameObject go, int idElemento, Nodo na, Nodo nb, float t1, float t2,
                      Vector3 off1, Vector3 off2, float grosor)
    {
        var p = new PiezaColumna
        {
            tr = go.transform, elemento = idElemento,
            n1 = na.id, n2 = nb.id, zInf = na.z, zSup = nb.z,
            t1 = t1, t2 = t2, off1 = off1, off2 = off2, grosor = grosor
        };
        piezas.Add(p);
        Colocar(p);
    }

    void AgregarPiezaFija(GameObject go, Vector3 pie, Vector3 cabeza, float zInf, float zSup,
                          float t1, float t2, Vector3 off1, Vector3 off2, float grosor)
    {
        var p = new PiezaColumna
        {
            tr = go.transform, pieFijo = pie, cabezaFija = cabeza, zInf = zInf, zSup = zSup,
            t1 = t1, t2 = t2, off1 = off1, off2 = off2, grosor = grosor
        };
        piezas.Add(p);
        Colocar(p);
    }

    void ColocarPiezas()
    {
        for (int i = 0; i < piezas.Count; i++) Colocar(piezas[i]);
    }

    /// Ubica una pieza donde esta dibujada su columna AHORA, o la apaga si
    /// su columna no esta en el piso visible o ya no existe (se borro en
    /// el editor).
    void Colocar(PiezaColumna p)
    {
        if (p.tr == null) return;
        GameObject go = p.tr.gameObject;

        Vector3 pie, cabeza;
        float zInf = p.zInf, zSup = p.zSup;
        if (p.n1 >= 0)
        {
            ModeloEstructural m = visor != null ? visor.Modelo : null;
            Nodo na = m != null ? m.NodoPorId(p.n1) : null;
            Nodo nb = m != null ? m.NodoPorId(p.n2) : null;
            // Borrar la columna en el editor (la M1 de la Semana 5 borra la
            // 69) deja sus nodos: sin mirar el elemento, las barras
            // quedarian flotando donde ya no hay hormigon.
            bool columnaBorrada = p.elemento >= 0 && m != null && m.ElementoPorId(p.elemento) == null;
            if (na == null || nb == null || columnaBorrada)
            {
                if (go.activeSelf) go.SetActive(false);
                return;
            }
            pie = visor.PosicionActual(na);
            cabeza = visor.PosicionActual(nb);
            zInf = na.z;
            zSup = nb.z;
        }
        else
        {
            pie = p.pieFijo;
            cabeza = p.cabezaFija;
        }

        if (!AjustesVista.ElementoEnCotaVisible(zInf, zSup))
        {
            if (go.activeSelf) go.SetActive(false);
            return;
        }
        UbicarCilindro(p.tr, Vector3.Lerp(pie, cabeza, p.t1) + p.off1,
                       Vector3.Lerp(pie, cabeza, p.t2) + p.off2, p.grosor);
        if (!go.activeSelf) go.SetActive(true);
    }

    /// Los dos nodos de la columna del detalle en el modelo del visor,
    /// el de abajo primero. false si no hay visor, si la columna no esta
    /// o si sus nodos no estan donde dice el anexo (tolerancia de cota
    /// de AjustesVista: los dos JSON salen del mismo modelo con los
    /// mismos decimales).
    bool NodosDeLaColumnaDelDetalle(BloqueArmadura a, out Nodo pie, out Nodo cabeza)
    {
        pie = cabeza = null;
        if (visor == null || visor.Modelo == null || a.nodo_inferior == null) return false;

        int n1 = -1, n2 = -1;
        ColumnaRef r = a.columnas != null ? a.columnas.Find(c => c.id == a.columna_id) : null;
        if (r != null) { n1 = r.n1; n2 = r.n2; }
        else
        {
            Elemento e = visor.Modelo.ElementoPorId(a.columna_id);
            if (e != null) { n1 = e.n1; n2 = e.n2; }
        }
        Nodo na = visor.Modelo.NodoPorId(n1), nb = visor.Modelo.NodoPorId(n2);
        if (na == null || nb == null) return false;
        if (na.z > nb.z) { Nodo t = na; na = nb; nb = t; }

        float tol = AjustesVista.TOLERANCIA_COTA;
        if (Mathf.Abs(na.x - a.nodo_inferior.x) > tol || Mathf.Abs(na.y - a.nodo_inferior.y) > tol
            || Mathf.Abs(na.z - a.nodo_inferior.z) > tol)
            return false;

        pie = na;
        cabeza = nb;
        return true;
    }

    // ----------------------------------------------------------------
    // ARMADURA
    // ----------------------------------------------------------------
    /// La lamina de detalle se pone junto al edificio, apoyada en el
    /// suelo, separada una vez su ancho para que no se encime.
    Vector3 OffsetDetalle()
    {
        if (Anexo.caja == null) return new Vector3(-20f, 0f, 0f);
        CajaEdificio c = Anexo.caja;
        BloqueArmadura a = Anexo.armadura;
        // Ejes.AUnity manda: OpenSees x -> Unity x, OpenSees z -> Unity y.
        // La jaula queda al costado del edificio (x por debajo de x_min),
        // apoyada en el suelo y centrada en la profundidad de la planta.
        return new Vector3(c.x_min - (c.x_max - c.x_min) * 0.35f
                                   - a.nodo_inferior.x,
                           c.z_min - a.nodo_inferior.z,
                           (c.y_min + c.y_max) * 0.5f - a.nodo_inferior.y);
    }

    /// La jaula con sus estribos. En sitio (escala 1) cada barra y cada
    /// lado de estribo es una pieza pegada a la columna, asi que sigue la
    /// deformada; la lamina de detalle es un dibujo fijo al costado.
    void DibujarArmadura(BloqueArmadura a, float escala, Vector3 offset)
    {
        if (a.barras == null || a.nodo_inferior == null || a.nodo_superior == null)
            return;

        bool enSitio = escala <= 1f && offset == Vector3.zero;
        Nodo nPie = null, nCabeza = null;
        bool conNodos = enSitio && NodosDeLaColumnaDelDetalle(a, out nPie, out nCabeza);

        // La geometria sin deformar, en la que se cuentan los estribos.
        Vector3 pie = Ejes.AUnity(a.nodo_inferior.x, a.nodo_inferior.y,
                                  a.nodo_inferior.z) + offset;
        Vector3 cabeza = pie + Vector3.up
                       * (a.nodo_superior.z - a.nodo_inferior.z) * escala;

        string nombre = escala > 1f ? "Armadura_DETALLE"
                                    : $"Armadura_columna_{a.columna_id}";
        Transform padre = new GameObject(nombre).transform;
        padre.SetParent(transform, false);
        creados.Add(padre.gameObject);

        // La seccion vive en el plano horizontal: su eje y va a X de
        // Unity y su eje z va a Z de Unity, porque la columna sube en Y.
        // En la vista de detalle la jaula ya viene ampliada, asi que la
        // barra solo se escala: queda al 4 % del ancho, igual que 16 mm
        // en 400 mm reales. Multiplicar ademas por exageracionBarra la
        // dejaba al 24 % y la jaula se veia como un bloque macizo.
        float exagera = escala > 1f ? escala : exageracionBarra;
        float grosorBarra = a.diametro_barra * exagera;
        foreach (PuntoSeccion p in a.barras)
        {
            Vector3 off = new Vector3(p.y, 0f, p.z) * escala;
            GameObject barra = Cilindro(pie + off, cabeza + off, grosorBarra);
            barra.name = $"barra_{p.y:0.000}_{p.z:0.000}";
            barra.transform.SetParent(padre, true);
            Pintar(barra, colorBarra);
            creados.Add(barra);
            if (enSitio) Pegar(barra, conNodos, nPie, nCabeza, pie, cabeza, a, 0f, 1f, off, off, grosorBarra);
        }

        float grosorEstribo = a.diametro_estribo * exagera;
        float altura = Vector3.Distance(pie, cabeza);
        int cuantos = Mathf.Max(
            1, Mathf.RoundToInt(altura / (a.espaciamiento_estribo * escala)));
        for (int i = 0; i <= cuantos; i++)
        {
            float t = (float)i / cuantos;
            Poligono(a.estribo_exterior, t, pie, cabeza, grosorEstribo, escala, padre,
                     $"estribo_ext_{i}", enSitio, conNodos, nPie, nCabeza, a);
            Poligono(a.estribo_rombo, t, pie, cabeza, grosorEstribo, escala, padre,
                     $"estribo_rombo_{i}", enSitio, conNodos, nPie, nCabeza, a);
        }

        Debug.Log($"VisorSemana03: {(escala > 1f ? "DETALLE x" + escala : "en sitio")} "
                  + $"columna {a.columna_id} "
                  + $"({a.axial_G_kN:0} kN en G) con {a.barras.Count} barras "
                  + $"phi{a.diametro_barra * 1000f:0}, cuantia {a.cuantia_pct:0.00} %. "
                  + (enSitio && !conNodos ? "(Sin su columna en el modelo: queda fija, "
                                            + "no sigue la deformada.) " : "")
                  + a.procedencia);
    }

    /// Registra un trozo de la jaula en sitio como pieza: pegada a los
    /// nodos si estan en el modelo, fija en las coordenadas del anexo si no.
    void Pegar(GameObject go, bool conNodos, Nodo nPie, Nodo nCabeza, Vector3 pie,
               Vector3 cabeza, BloqueArmadura a, float t1, float t2, Vector3 off1,
               Vector3 off2, float grosor)
    {
        if (conNodos)
            AgregarPieza(go, a.columna_id, nPie, nCabeza, t1, t2, off1, off2, grosor);
        else
            AgregarPiezaFija(go, pie, cabeza, a.nodo_inferior.z, a.nodo_superior.z,
                             t1, t2, off1, off2, grosor);
    }

    /// Dibuja un poligono cerrado de la seccion como aro de cilindros, a
    /// la altura relativa t de la jaula.
    void Poligono(List<PuntoSeccion> puntos, float t, Vector3 pie, Vector3 cabeza,
                  float grosor, float escala, Transform padre, string nombre,
                  bool enSitio, bool conNodos, Nodo nPie, Nodo nCabeza, BloqueArmadura a)
    {
        if (puntos == null || puntos.Count < 2) return;
        Vector3 centro = Vector3.Lerp(pie, cabeza, t);
        for (int i = 0; i < puntos.Count; i++)
        {
            PuntoSeccion p = puntos[i];
            PuntoSeccion q = puntos[(i + 1) % puntos.Count];
            Vector3 offP = new Vector3(p.y, 0f, p.z) * escala;
            Vector3 offQ = new Vector3(q.y, 0f, q.z) * escala;
            GameObject lado = Cilindro(centro + offP, centro + offQ, grosor);
            lado.name = nombre + "_" + i;
            lado.transform.SetParent(padre, true);
            Pintar(lado, colorEstribo);
            creados.Add(lado);
            if (enSitio) Pegar(lado, conNodos, nPie, nCabeza, pie, cabeza, a, t, t, offP, offQ, grosor);
        }
    }

    // ----------------------------------------------------------------
    private static Mesh mallaCono;

    /// Unity no trae primitiva de cono, y una caja como punta hacia que
    /// las flechas parecieran martillos. Se genera una vez y se comparte.
    static Mesh MallaCono(int lados = 16)
    {
        if (mallaCono != null) return mallaCono;

        var vertices = new List<Vector3>();
        var triangulos = new List<int>();
        vertices.Add(new Vector3(0f, 1f, 0f));           // 0: punta
        vertices.Add(Vector3.zero);                      // 1: centro base
        for (int i = 0; i < lados; i++)
        {
            float t = 2f * Mathf.PI * i / lados;
            vertices.Add(new Vector3(Mathf.Cos(t), 0f, Mathf.Sin(t)));
        }
        for (int i = 0; i < lados; i++)
        {
            int a = 2 + i, b = 2 + (i + 1) % lados;
            triangulos.Add(0); triangulos.Add(b); triangulos.Add(a);   // manto
            triangulos.Add(1); triangulos.Add(a); triangulos.Add(b);   // tapa
        }

        mallaCono = new Mesh { name = "ConoFlecha" };
        mallaCono.SetVertices(vertices);
        mallaCono.SetTriangles(triangulos, 0);
        mallaCono.RecalculateNormals();
        return mallaCono;
    }

    GameObject Cono(Vector3 baseP, Vector3 punta, float radio)
    {
        GameObject cono = new GameObject("cono");
        cono.AddComponent<MeshFilter>().sharedMesh = MallaCono();
        cono.AddComponent<MeshRenderer>();

        Vector3 direccion = punta - baseP;
        float largo = direccion.magnitude;
        cono.transform.position = baseP;
        cono.transform.localScale = new Vector3(radio, largo, radio);
        if (largo > 1e-6f) cono.transform.up = direccion.normalized;
        return cono;
    }

    GameObject Cilindro(Vector3 desde, Vector3 hasta, float grosor)
    {
        GameObject cil = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        Collider col = cil.GetComponent<Collider>();
        if (col != null) DestroyImmediate(col);   // no estorbar al editor
        UbicarCilindro(cil.transform, desde, hasta, grosor);
        return cil;
    }

    /// El cilindro de Unity mide 2 de alto y apunta en Y. Se usa al crear
    /// y al mover una pieza: una sola definicion de "cilindro de A a B".
    /// La escala es la local: los padres de este script quedan con escala
    /// 1 (se crean con SetParent(transform, false) bajo un objeto sin escalar).
    static void UbicarCilindro(Transform t, Vector3 desde, Vector3 hasta, float grosor)
    {
        t.position = (desde + hasta) / 2f;
        Vector3 direccion = hasta - desde;
        float largo = direccion.magnitude;
        t.localScale = new Vector3(grosor, largo / 2f, grosor);
        if (largo > 1e-6f) t.up = direccion.normalized;
    }

    void Pintar(GameObject go, Color color)
    {
        Material mat;
        if (!materiales.TryGetValue(color, out mat))
        {
            // El mismo shader que usa el visor: con URP, Shader.Find
            // ("Standard") devuelve null y todo sale magenta.
            mat = new Material(VisorEstructura.ShaderCompatible());
            mat.color = color;
            if (mat.HasProperty("_BaseColor")) mat.SetColor("_BaseColor", color);
            materiales[color] = mat;
        }
        Renderer r = go.GetComponent<Renderer>();
        r.sharedMaterial = mat;
        // Mil barras de 1 cm y cientos de flechas proyectando sombra no
        // aportan lectura y cuestan en la vista realista (y en el movil).
        r.shadowCastingMode = ShadowCastingMode.Off;
    }
}
