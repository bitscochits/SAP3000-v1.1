/*
================================================================
  VisorCargaMovil.cs
================================================================
  Una carga puntual P que recorre un eje de vigas del edificio. Lee
  StreamingAssets/carga_movil.json (lo escribe
  python semana05/carga_movil.py lt2) y MUESTRA la posicion que el
  usuario elige: la deformada de todo el edificio, la flecha de la
  carga, el recorrido resaltado y, en el panel, el reparto de la viga
  cargada, la conservacion (Suma Rz contra P) y la respuesta.

  ----------------------------------------------------------------
  POR QUE ASI
  ----------------------------------------------------------------
  - CERO calculo aca (regla de oro, semana05/CONTRATO.md decision 2).
    Cada posicion es una corrida de OpenSees hecha en Python con
    eleLoad -beamPoint. Unity elige un INDICE y una escala grafica;
    todo numero del panel viene escrito en el JSON.
  - Salta entre posiciones, NO interpola: el diagrama de momento tiene
    un quiebre bajo la carga, y promediar dos posiciones vecinas lo
    aplana (Python lo mide: bloque "por que no interpolar" de
    semana05/carga_movil.py y semana05/CARGA_MOVIL.md).
  - La escala de la deformada es UNA para todo el recorrido
    (info.escala_deformada): con una escala por posicion la animacion
    "respiraria" sin que cambie nada.
  - La viga cargada no se dibuja recta: Python exporta su elastica
    (decimos de L mas el punto de la carga, verificada contra la viga
    partida) y aca solo se escala, igual que Ejes.PosicionDeformada.

  ----------------------------------------------------------------
  CONTRATO (semana05/CONTRATO.md 2.2, 2.3, 5 y 8)
  ----------------------------------------------------------------
  - Se crea solo (RuntimeInitializeOnLoadMethod AfterSceneLoad) si la
    escena tiene un VisorEstructura.
  - IPanelIncrustable "Carga movil": VisorQA le pone PanelPropio = false
    y lo dibuja como pestana; sin VisorQA dibuja su propia ventana.
  - Deformada con la API del contrato: mostrarDeformada, factorEscala,
    AplicarDeformada. La quita SOLO si la puso este script, y se suelta
    (sin borrar nada) si otra fuente puso otra: la ultima manda.
  - ModeloEditado: los numeros son del modelo original; se apaga con
    aviso.
  - Las clases del JSON llevan sufijo Movil, un campo por linea y sin
    metodos: semana05/carga_movil.py [j] las lee como texto y compara
    en las dos direcciones (JsonUtility ignora sin avisar lo que no
    calza).
================================================================
*/

using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using UnityEngine.Rendering;

// ================================================================
// CLASES DEL JSON (carga_movil.json)
// ================================================================
[Serializable]
public class AnexoCargaMovil
{
    public InfoMovil info;
    public float P_kN;
    public string _P_kN_por_que;
    public RecorridoMovil recorrido;
    public List<PosicionMovil> posiciones;
}

[Serializable]
public class InfoMovil
{
    public string edificio;
    public string descripcion;
    public string unidades;
    public string generado_por;
    public string comando;
    public string[] convencion;
    public int n_posiciones;
    public float escala_deformada;
    public string _escala_por_que;
    public float max_desplazamiento_recorrido_mm;
    public float uz_bajo_carga_min_mm;
    public int indice_uz_bajo_carga_min;
    public int apoyos_z;
    public float cota_redondeo_kN;
    public List<VerificacionMovil> verificaciones;
}

[Serializable]
public class VerificacionMovil
{
    public string nombre;
    public string detalle;
    public string criterio;
    public bool cumple;
}

[Serializable]
public class RecorridoMovil
{
    public int[] elementos;
    public int[] nodos;
    public float[] largos_m;
    public float largo_m;
    public float z;
    public string eje;
    public float coord;
    public int divisiones;
    public string descripcion;
    public string _por_que;
}

[Serializable]
public class PosicionMovil
{
    public int indice;
    public int elemento;
    public float xL;
    public float a_m;
    public float L_m;
    public float s_m;
    public float x;
    public float y;
    public float z;
    public float Px_local_kN;
    public float Py_local_kN;
    public float Pz_local_kN;
    public float max_desplazamiento_mm;
    public int nodo_max_desplazamiento;
    public float uz_min_mm;
    public int nodo_uz_min;
    public float[] u_carga_m;
    public float uz_bajo_carga_mm;
    public float M_bajo_carga_kNm;
    public List<PuntoElasticaMovil> elastica;
    public List<DespNodo> desplazamientos;
    public List<ReacNodo> reacciones;
    public EquilibrioCaso equilibrio;
    public RepartoMovil reparto;
    public ConservacionMovil conservacion;
}

[Serializable]
public class PuntoElasticaMovil
{
    public float xL;
    public float x;
    public float y;
    public float z;
    public float ux;
    public float uy;
    public float uz;
}

[Serializable]
public class RepartoMovil
{
    public int nodo_i;
    public int nodo_j;
    public string llega_a_i;
    public string llega_a_j;
    public float V_i_kN;
    public float V_j_kN;
    public float porcentaje_i;
    public float porcentaje_j;
    public float palanca_i_kN;
    public float palanca_j_kN;
    public float empotrado_V_i_kN;
    public float empotrado_V_j_kN;
    public float empotrado_My_i_kNm;
    public float empotrado_My_j_kNm;
    public float My_i_kNm;
    public float My_j_kNm;
    public float momentos_sobre_L_kN;
    public float[] f;
    public string explicacion;
}

[Serializable]
public class ConservacionMovil
{
    public float P_kN;
    public float suma_Rz_kN;
    public float error_kN;
    public float cota_kN;
    public int apoyos_z;
    public float suma_Rx_kN;
    public float suma_Ry_kN;
    public float cota_horizontal_kN;
    public int apoyos_xy;
    public float error_en_memoria_kN;
    public float suma_V_mas_Pz_kN;
    public float cierre_cociente;
    public string cierre_componente;
    public bool cumple;
}


// ================================================================
// EL VISOR
// ================================================================
public class VisorCargaMovil : MonoBehaviour, IPanelIncrustable
{
    public const string ARCHIVO = "carga_movil.json";

    [Header("Dibujo (solo grafico)")]
    [Tooltip("Largo de la flecha de P, en m de escena. No es proporcional a P: hay una sola carga.")]
    public float largoFlecha = 2.5f;
    public float grosorFlecha = 0.16f;
    [Tooltip("Diametro del resaltado de las vigas del recorrido (las barras del visor miden 0.05).")]
    public float grosorRecorrido = 0.12f;
    public float grosorElastica = 0.16f;
    public Color colorFlecha = new Color(0.95f, 0.20f, 0.15f);
    public Color colorRecorrido = new Color(1.00f, 0.74f, 0.25f);
    public Color colorElastica = new Color(1.00f, 0.45f, 0.10f);

    [Header("Animacion")]
    [Tooltip("Segundos que se queda en cada posicion con Play. Cada paso redibuja el edificio.")]
    [Range(0.1f, 3f)]
    public float segundosPorPaso = 0.6f;

    // ------------------------------------------------------------
    // IPanelIncrustable
    // ------------------------------------------------------------
    public string TituloPestana { get { return "Carga movil"; } }

    private bool panelPropio = true;
    public bool PanelPropio
    {
        get { return panelPropio; }
        set { panelPropio = value; }
    }

    // ------------------------------------------------------------
    // Estado (solo lectura desde afuera: la captura de la Semana 5)
    // ------------------------------------------------------------
    /// El JSON leido; null mientras no llega o si no se pudo leer.
    public AnexoCargaMovil Anexo { get; private set; }
    public bool Activo { get { return activo; } }
    public int Indice { get { return indice; } }
    public int CantidadPosiciones
    {
        get { return Anexo != null && Anexo.posiciones != null ? Anexo.posiciones.Count : 0; }
    }
    /// Por que no se puede mostrar, o que paso; null si no hay nada que decir.
    public string Aviso { get; private set; }

    private VisorEstructura visor;
    private bool activo = false;
    private int indice = 0;
    private bool reproduciendo = false;
    private float acumulado = 0f;
    private bool deformadaPuesta = false;
    private float factorPrevio = 300f;
    private bool modeloEditado = false;
    private bool yaCentrado = false;

    // Lo que pide el panel se aplica en Update: AplicarDeformada redibuja
    // cientos de objetos, y hacerlo dentro de OnGUI descuadra IMGUI.
    private bool pedidoActivar = false;
    private bool pedidoApagar = false;
    private bool pedidoCentrar = false;
    private bool pedidoSoltar = false;
    private int indicePedido = -1;
    private float escalaPedida = -1f;

    private GameObject dibujo;
    private readonly Dictionary<Color, Material> materiales = new Dictionary<Color, Material>();
    private static Mesh mallaCono;
    private Vector2 scrollPanel;
    private GUIStyle estiloCasilla;
    private GUIStyle baseCasilla;

    // Lo que cambia CUANTOS controles tiene el panel se lee solo en el
    // evento Layout: IMGUI arma el layout ahi y lo reusa en los demas
    // eventos del mismo cuadro. ModeloEditado puede llegar en medio (desde
    // el boton del OnGUI de otro panel) y un aviso o un apagado entre el
    // Layout y el click daria "Getting control N's position in a group
    // with only N controls".
    private bool activoEnLayout = false;
    private string avisoEnLayout = null;

    // ============================================================
    // ARRANQUE
    // ============================================================
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Arrancar()
    {
        if (FindAnyObjectByType<VisorEstructura>() == null) return;
        if (FindAnyObjectByType<VisorCargaMovil>() != null) return;
        new GameObject("VisorCargaMovil").AddComponent<VisorCargaMovil>();
    }

    void OnEnable()
    {
        EventosVisor.Redibujado += AlRedibujar;
        EventosVisor.ModeloEditado += AlEditarModelo;
    }

    void OnDisable()
    {
        EventosVisor.Redibujado -= AlRedibujar;
        EventosVisor.ModeloEditado -= AlEditarModelo;
    }

    void OnDestroy()
    {
        BorrarDibujo();
        foreach (Material m in materiales.Values) if (m != null) Destroy(m);
        materiales.Clear();
    }

    IEnumerator Start()
    {
        visor = FindAnyObjectByType<VisorEstructura>();

        string texto = null, error = null;
        yield return LectorStreaming.Leer(ARCHIVO, t => texto = t, e => error = e);
        if (texto == null)
        {
            Aviso = "No encontre StreamingAssets/" + ARCHIVO + " (" + error + "). Generalo con "
                    + "'python semana05/carga_movil.py lt2' (escribe el JSON y su copia).";
            Debug.LogWarning("VisorCargaMovil: " + Aviso);
            yield break;
        }

        AnexoCargaMovil leido = null;
        try
        {
            leido = JsonUtility.FromJson<AnexoCargaMovil>(texto);
        }
        catch (Exception ex)
        {
            Aviso = ARCHIVO + " no se pudo interpretar: " + ex.Message;
            Debug.LogWarning("VisorCargaMovil: " + Aviso);
            yield break;
        }
        if (leido == null || leido.info == null || leido.recorrido == null
            || leido.recorrido.elementos == null || leido.posiciones == null
            || leido.posiciones.Count == 0)
        {
            Aviso = ARCHIVO + " no trae info, recorrido o posiciones: no es el formato de "
                    + "semana05/carga_movil.py.";
            Debug.LogWarning("VisorCargaMovil: " + Aviso);
            yield break;
        }

        // El modelo llega por su propia corrutina.
        while (visor != null && !visor.Listo) yield return null;
        if (visor == null || visor.Modelo == null)
        {
            Aviso = "No hay VisorEstructura con modelo en la escena: no hay donde dibujar.";
            yield break;
        }

        Anexo = leido;
        string motivo = ComprobarModelo();
        if (motivo != null) Aviso = motivo;
        Debug.Log($"VisorCargaMovil: {Anexo.posiciones.Count} posiciones de P = "
                  + $"{F(Anexo.P_kN, "0.##")} kN leidas de {ARCHIVO} ({Anexo.recorrido.descripcion})"
                  + (motivo != null ? ". NO se puede mostrar: " + motivo : "."));
    }

    /// null si el JSON es de este modelo; si no, por que no. Solo compara
    /// ids, nombres y coordenadas: no calcula nada.
    string ComprobarModelo()
    {
        ModeloEstructural M = visor.Modelo;
        string ed = Anexo.info.edificio;

        if (M.info != null && !string.IsNullOrEmpty(M.info.edificio) && M.info.edificio != ed)
            return $"La carga movil es del edificio '{ed}' y la escena muestra '{M.info.edificio}'. "
                   + $"Sincroniza con 'python comun/lanzar_unity.py sincronizar {ed}'.";

        VisorSemana04 s4 = FindAnyObjectByType<VisorSemana04>();
        if (s4 != null && s4.Anexo != null && s4.Anexo.info != null
            && !string.IsNullOrEmpty(s4.Anexo.info.edificio) && s4.Anexo.info.edificio != ed)
            return $"La carga movil es del edificio '{ed}' y el anexo de la Semana 4 es de "
                   + $"'{s4.Anexo.info.edificio}'.";

        foreach (int eid in Anexo.recorrido.elementos)
            if (M.ElementoPorId(eid) == null)
                return $"La viga {eid} del recorrido no esta en el modelo de la escena.";

        PosicionMovil p0 = Anexo.posiciones[0];
        if (p0.desplazamientos == null || p0.desplazamientos.Count != M.nodos.Count)
            return $"{ARCHIVO} trae {(p0.desplazamientos == null ? 0 : p0.desplazamientos.Count)} "
                   + $"desplazamientos y el modelo tiene {M.nodos.Count} nodos: es de otro modelo.";
        foreach (DespNodo d in p0.desplazamientos)
            if (M.NodoPorId(d.id) == null)
                return $"El nodo {d.id} de {ARCHIVO} no esta en el modelo de la escena.";

        // Un id igual no garantiza el mismo lugar: se compara la coordenada
        // del primer punto de la elastica con el nodo n1 de su viga.
        Elemento e0 = M.ElementoPorId(p0.elemento);
        Nodo n1 = e0 != null ? M.NodoPorId(e0.n1) : null;
        if (n1 != null && p0.elastica != null && p0.elastica.Count > 0)
        {
            PuntoElasticaMovil q = p0.elastica[0];
            if (Mathf.Abs(q.x - n1.x) > 0.01f || Mathf.Abs(q.y - n1.y) > 0.01f
                || Mathf.Abs(q.z - n1.z) > 0.01f)
                return $"La viga {p0.elemento} no esta donde dice {ARCHIVO}: es de otra geometria.";
        }
        return null;
    }

    // ============================================================
    // ACCIONES (publicas: fuera de OnGUI se pueden llamar directo)
    // ============================================================
    public void Activar()
    {
        if (activo || Anexo == null || visor == null || visor.Modelo == null) return;
        if (modeloEditado)
        {
            Aviso = "Se edito el modelo: la carga movil precalculada es del modelo original. "
                    + "Vuelve a cargar la escena para usarla.";
            return;
        }
        string motivo = ComprobarModelo();
        if (motivo != null) { Aviso = motivo; return; }

        Aviso = null;
        factorPrevio = visor.factorEscala;
        activo = true;
        AplicarPosicion(Anexo.info.escala_deformada > 0f ? Anexo.info.escala_deformada
                                                          : visor.factorEscala);
        if (!yaCentrado)
        {
            yaCentrado = true;
            Centrar();
        }
    }

    /// Quita lo que puso: su dibujo y, si sigue siendo suya, su deformada, y
    /// devuelve la escala que habia. La deformada de antes (G, sismo, caso
    /// activo) no se re-aplica sola: se pide de nuevo en su pestana
    /// (CONTRATO.md 2.3, nadie re-aplica la suya sin que el usuario la pida).
    public void Apagar()
    {
        if (!activo) return;
        activo = false;
        reproduciendo = false;
        BorrarDibujo();
        if (deformadaPuesta && visor != null)
        {
            deformadaPuesta = false;
            visor.LimpiarDeformada();
            visor.factorEscala = factorPrevio;
            visor.Redibujar();
        }
    }

    public void ElegirPosicion(int i)
    {
        if (Anexo == null) return;
        indice = Mathf.Clamp(i, 0, Anexo.posiciones.Count - 1);
        acumulado = 0f;
        if (activo) AplicarPosicion(visor.factorEscala);
    }

    void AplicarPosicion(float escala)
    {
        PosicionMovil p = Anexo.posiciones[indice];
        visor.mostrarDeformada = true;
        visor.factorEscala = escala;
        deformadaPuesta = true;
        visor.AplicarDeformada(p.desplazamientos);   // redibuja: AlRedibujar pone flecha y recorrido
    }

    void Centrar()
    {
        if (Anexo == null) return;
        // El punto del medio del recorrido, tal cual viene: no se promedia.
        PosicionMovil medio = Anexo.posiciones[Anexo.posiciones.Count / 2];
        EventosVisor.AvisarPedirCentrar(Ejes.AUnity(medio.x, medio.y, medio.z),
                                        Anexo.recorrido.largo_m);
    }

    // ============================================================
    // CICLO
    // ============================================================
    void Update()
    {
        if (Anexo == null || visor == null) return;

        if (pedidoSoltar)
        {
            // Otra fuente puso su deformada: ya no es nuestra, no se borra.
            pedidoSoltar = false;
            activo = false;
            reproduciendo = false;
            deformadaPuesta = false;
            BorrarDibujo();
            Aviso = "Otra pestana cambio la deformada del visor: la carga movil se apago. "
                    + "Activala de nuevo para volver.";
        }
        if (pedidoApagar) { pedidoApagar = false; Apagar(); }
        if (pedidoActivar) { pedidoActivar = false; Activar(); }
        if (indicePedido >= 0)
        {
            int i = indicePedido;
            indicePedido = -1;
            ElegirPosicion(i);
        }
        if (escalaPedida > 0f)
        {
            float e = escalaPedida;
            escalaPedida = -1f;
            if (activo) AplicarPosicion(e);
        }
        if (activo && reproduciendo)
        {
            acumulado += Time.deltaTime;
            if (acumulado >= segundosPorPaso)
                ElegirPosicion((indice + 1) % Anexo.posiciones.Count);
        }
        if (pedidoCentrar) { pedidoCentrar = false; Centrar(); }
    }

    /// Redibujado: los objetos del visor son nuevos. Se vuelve a dibujar
    /// encima (sin llamar a Redibujar: lazo infinito, CONTRATO.md 2.1).
    void AlRedibujar()
    {
        if (!activo || Anexo == null || visor == null || visor.Modelo == null) return;
        if (!MiDeformadaSigue())
        {
            BorrarDibujo();
            pedidoSoltar = true;
            return;
        }
        Dibujar();
    }

    void AlEditarModelo(string motivo)
    {
        modeloEditado = true;
        // El editor ya limpio la deformada: no se toca. Solo se devuelve la
        // escala grafica (el editor redibuja).
        if (activo && deformadaPuesta && visor != null) visor.factorEscala = factorPrevio;
        deformadaPuesta = false;
        activo = false;
        reproduciendo = false;
        BorrarDibujo();
        if (Anexo != null)
            Aviso = $"Se edito el modelo ({motivo}): la carga movil precalculada es del modelo "
                    + "original y se apago. Vuelve a cargar la escena para usarla.";
    }

    /// true si lo que dibuja el visor sigue siendo la deformada de esta
    /// posicion. Compara el nodo que mas se mueve contra la misma cuenta
    /// que hace el visor (Ejes.PosicionDeformada), no calcula nada nuevo.
    bool MiDeformadaSigue()
    {
        if (!deformadaPuesta || !visor.mostrarDeformada || !visor.HayDeformada) return false;
        PosicionMovil p = Anexo.posiciones[indice];
        Nodo n = visor.Modelo.NodoPorId(p.nodo_max_desplazamiento);
        DespNodo d = null;
        if (p.desplazamientos != null)
            foreach (DespNodo x in p.desplazamientos)
                if (x.id == p.nodo_max_desplazamiento) { d = x; break; }
        if (n == null || d == null) return true;
        Vector3 esperada = Ejes.PosicionDeformada(n, d.ux, d.uy, d.uz, visor.factorEscala);
        return (visor.PosicionActual(n) - esperada).sqrMagnitude < 1e-8f;
    }

    // ============================================================
    // DIBUJO: flecha, recorrido y elastica de la viga cargada
    // ============================================================
    void Dibujar()
    {
        BorrarDibujo();
        dibujo = new GameObject("CargaMovil_Dibujo");
        dibujo.transform.SetParent(transform, false);

        ModeloEstructural M = visor.Modelo;
        PosicionMovil p = Anexo.posiciones[indice];
        bool conCurva = p.elastica != null && p.elastica.Count >= 2;
        // Solo grafico: la misma escala con que el visor dibuja la deformada.
        float escala = visor.mostrarDeformada ? visor.factorEscala : 0f;

        // Las vigas no cargadas del recorrido: rectas entre sus nodos, como
        // las dibuja el visor, un poco mas gruesas y de otro color.
        foreach (int eid in Anexo.recorrido.elementos)
        {
            if (eid == p.elemento && conCurva) continue;
            Elemento e = M.ElementoPorId(eid);
            if (e == null) continue;
            Nodo a = M.NodoPorId(e.n1);
            Nodo b = M.NodoPorId(e.n2);
            if (a == null || b == null) continue;
            Pieza(Cilindro(visor.PosicionActual(a), visor.PosicionActual(b), Envolvente(e, grosorRecorrido)),
                  colorRecorrido, "Recorrido_" + eid);
        }

        // La viga cargada: su elastica, que viene de Python.
        Elemento cargada = M.ElementoPorId(p.elemento);
        if (conCurva)
        {
            float grosor = Envolvente(cargada, grosorElastica);
            Vector3 previo = PuntoDibujado(p.elastica[0], escala);
            for (int k = 1; k < p.elastica.Count; k++)
            {
                Vector3 siguiente = PuntoDibujado(p.elastica[k], escala);
                Pieza(Cilindro(previo, siguiente, grosor), colorElastica,
                      "Elastica_" + p.elemento + "_" + k);
                previo = siguiente;
            }
        }

        // La flecha: punta en el punto cargado (desplazado con la misma
        // escala), apuntando como P, que es (0, 0, -1) en OpenSees. Con
        // perfiles, la punta se apoya sobre el resaltado de la viga y no
        // queda escondida dentro de la caja.
        Vector3 punta = (p.u_carga_m != null && p.u_carga_m.Length == 3)
            ? Ejes.AUnity(p.x + p.u_carga_m[0] * escala, p.y + p.u_carga_m[1] * escala,
                          p.z + p.u_carga_m[2] * escala)
            : Ejes.AUnity(p.x, p.y, p.z);
        punta += Vector3.up * 0.5f * (Envolvente(cargada, 0f));
        Vector3 hacia = Ejes.AUnity(0f, 0f, -1f);
        Vector3 cola = punta - hacia * largoFlecha;
        Vector3 cuello = punta - hacia * (largoFlecha * 0.32f);
        Pieza(Cilindro(cola, cuello, grosorFlecha), colorFlecha, "Flecha_P");
        Pieza(Cono(cuello, punta, grosorFlecha * 2.4f), colorFlecha, "Flecha_P_punta");
    }

    /// Diametro del resaltado de una viga. Con perfiles (vista realista) la
    /// viga es una caja de b x h: un cilindro de 12 cm quedaba ADENTRO y el
    /// recorrido no se veia. Se envuelve la seccion (su diagonal, con 8 % de
    /// aire). Es dibujo con el b y h del JSON; sin perfiles, 'minimo'.
    float Envolvente(Elemento e, float minimo)
    {
        if (e == null || visor == null || visor.Modelo == null || !visor.DibujaPerfiles) return minimo;
        Seccion s = visor.Modelo.SeccionPorNombre(e.seccion);
        if (s == null || !s.TienePerfil || e.EsMuro || e.EsBrazo) return minimo;
        return Mathf.Max(minimo, Mathf.Sqrt(s.b * s.b + s.h * s.h) * 1.08f);
    }

    static Vector3 PuntoDibujado(PuntoElasticaMovil q, float escala)
    {
        return Ejes.AUnity(q.x + q.ux * escala, q.y + q.uy * escala, q.z + q.uz * escala);
    }

    void BorrarDibujo()
    {
        if (dibujo != null) Destroy(dibujo);
        dibujo = null;
    }

    void Pieza(GameObject go, Color color, string nombre)
    {
        go.name = nombre;
        go.transform.SetParent(dibujo.transform, true);
        Material mat;
        if (!materiales.TryGetValue(color, out mat))
        {
            mat = new Material(VisorEstructura.ShaderCompatible());
            mat.color = color;
            if (mat.HasProperty("_BaseColor")) mat.SetColor("_BaseColor", color);
            materiales[color] = mat;
        }
        Renderer r = go.GetComponent<Renderer>();
        r.sharedMaterial = mat;
        r.shadowCastingMode = ShadowCastingMode.Off;
    }

    /// Sin collider: un click pasa a la barra de abajo (seleccion y editor).
    static GameObject Cilindro(Vector3 desde, Vector3 hasta, float grosor)
    {
        GameObject cil = GameObject.CreatePrimitive(PrimitiveType.Cylinder);
        Collider col = cil.GetComponent<Collider>();
        if (col != null) DestroyImmediate(col);
        cil.transform.position = (desde + hasta) / 2f;
        Vector3 direccion = hasta - desde;
        float largo = direccion.magnitude;
        cil.transform.localScale = new Vector3(grosor, largo / 2f, grosor);   // el cilindro de Unity mide 2
        if (largo > 1e-6f) cil.transform.up = direccion.normalized;
        return cil;
    }

    static GameObject Cono(Vector3 baseP, Vector3 punta, float radio)
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

    /// Cono de alto 1 y radio 1 con la base en el origen (el de VisorSemana03).
    static Mesh MallaCono()
    {
        if (mallaCono != null) return mallaCono;
        const int lados = 16;
        var vertices = new List<Vector3> { new Vector3(0f, 1f, 0f), Vector3.zero };
        var triangulos = new List<int>();
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
        mallaCono = new Mesh { name = "ConoCargaMovil" };
        mallaCono.SetVertices(vertices);
        mallaCono.SetTriangles(triangulos, 0);
        mallaCono.RecalculateNormals();
        return mallaCono;
    }

    // ============================================================
    // PANEL
    // ============================================================
    /// Ventana propia, solo sin VisorQA (abajo a la izquierda: el editor
    /// usa la derecha).
    void OnGUI()
    {
        if (!PanelPropio) return;
        if (Anexo == null && Aviso == null) return;
        PanelUI.Preparar();
        GUILayout.BeginArea(RectPanel(), PanelUI.Caja);
        scrollPanel = GUILayout.BeginScrollView(scrollPanel);
        DibujarCuerpo();
        GUILayout.EndScrollView();
        GUILayout.EndArea();
    }

    Rect RectPanel()
    {
        float margen = PanelUI.Px(10f);
        float ancho = Mathf.Min(PanelUI.Px(400f), Screen.width - 2f * margen);
        float alto = Mathf.Min(PanelUI.Px(620f), Screen.height - 2f * margen);
        return new Rect(margen, Screen.height - alto - margen, ancho, alto);
    }

    /// Para que la camara no gire al arrastrar sobre la ventana propia.
    /// Con PanelPropio == false el panel es de VisorQA: false.
    public bool MouseSobrePanel()
    {
        if (!PanelPropio || (Anexo == null && Aviso == null)) return false;
        Vector2 p = new Vector2(Input.mousePosition.x, Screen.height - Input.mousePosition.y);
        return RectPanel().Contains(p);
    }

    /// El contenido de la pestana "Carga movil". Solo GUILayout.
    public void DibujarPanel()
    {
        PanelUI.Preparar();   // no-op si VisorQA ya lo llamo en este OnGUI
        DibujarCuerpo();
    }

    void DibujarCuerpo()
    {
        if (Event.current == null || Event.current.type == EventType.Layout)
        {
            activoEnLayout = activo;
            avisoEnLayout = Aviso;
        }

        GUILayout.Label("Carga movil", Est(PanelUI.Titulo));
        if (avisoEnLayout != null) GUILayout.Label(avisoEnLayout, Est(PanelUI.Aviso));
        if (Anexo == null)
        {
            if (avisoEnLayout == null) GUILayout.Label("Leyendo " + ARCHIVO + "...", Est(PanelUI.Tenue));
            return;
        }

        int n = Anexo.posiciones.Count;
        GUILayout.Label($"P = {F(Anexo.P_kN, "0.##")} kN hacia abajo, {n} posiciones. "
                        + Anexo.recorrido.descripcion, Est(PanelUI.Texto));
        GUILayout.Label("Cada posicion es una corrida de OpenSees (eleLoad -beamPoint) hecha en "
                        + "Python. Unity salta de una a otra: no interpola ni calcula.",
                        Est(PanelUI.Tenue));

        bool quiere = GUILayout.Toggle(activoEnLayout, "  Mostrar la carga movil", Casilla());
        if (quiere != activoEnLayout)
        {
            if (quiere) pedidoActivar = true;
            else pedidoApagar = true;
        }

        if (activoEnLayout)
        {
            DibujarControles(n);
            DibujarNumeros(Anexo.posiciones[indice]);
        }
        else
        {
            GUILayout.Label("Al activarla pone la deformada de la posicion elegida (escala x"
                            + F(Anexo.info.escala_deformada, "0") + ", fija para todo el recorrido), "
                            + "la flecha de P y el recorrido resaltado. Al apagarla los quita y "
                            + "devuelve la escala.", Est(PanelUI.Tenue));
        }

        if (PanelUI.Plegable("movil.verificaciones", "Verificaciones en Python", false))
        {
            if (Anexo.info.verificaciones != null)
                foreach (VerificacionMovil v in Anexo.info.verificaciones)
                {
                    GUILayout.BeginHorizontal();
                    PanelUI.Insignia(v.cumple);
                    GUILayout.Label(v.nombre, Est(PanelUI.Texto));
                    GUILayout.EndHorizontal();
                    GUILayout.Label(v.detalle + "  (" + v.criterio + ")", Est(PanelUI.Tenue));
                }
            GUILayout.Label(Anexo._P_kN_por_que, Est(PanelUI.Tenue));
            GUILayout.Label("Generado con: " + Anexo.info.comando, Est(PanelUI.Tenue));
        }
    }

    void DibujarControles(int n)
    {
        GUILayout.Label($"Posicion {indice + 1} de {n}", Est(PanelUI.Texto));
        // Solo lo que mueve el usuario (GUI.changed): el valor que devuelve
        // un slider sin tocarlo puede venir recortado a su rango. El
        // GUI.changed de antes se devuelve: es de VisorQA, que nos dibuja.
        bool cambioAntes = GUI.changed;
        GUI.changed = false;
        float v = GUILayout.HorizontalSlider(indice, 0f, n - 1);
        int elegido = Mathf.RoundToInt(v);
        if (GUI.changed && elegido != indice) indicePedido = elegido;

        GUILayout.BeginHorizontal();
        if (GUILayout.Button("|<", Bot(PanelUI.Boton))) indicePedido = 0;
        if (GUILayout.Button("<", Bot(PanelUI.Boton))) indicePedido = Mathf.Max(0, indice - 1);
        if (PanelUI.Opcion(reproduciendo, reproduciendo ? "Pausa" : "Play"))
        {
            reproduciendo = !reproduciendo;
            acumulado = 0f;
        }
        if (GUILayout.Button(">", Bot(PanelUI.Boton))) indicePedido = Mathf.Min(n - 1, indice + 1);
        if (GUILayout.Button(">|", Bot(PanelUI.Boton))) indicePedido = n - 1;
        GUILayout.EndHorizontal();

        GUILayout.Label($"Segundos por paso: {F(segundosPorPaso, "0.0")}", Est(PanelUI.Tenue));
        segundosPorPaso = GUILayout.HorizontalSlider(segundosPorPaso, 0.1f, 3f);

        float recomendada = Anexo.info.escala_deformada > 0f ? Anexo.info.escala_deformada : 1f;
        GUILayout.Label($"Escala grafica x{F(visor.factorEscala, "0")} (solo visual; la del recorrido "
                        + $"es x{F(recomendada, "0")})", Est(PanelUI.Tenue));
        bool cambioSlider = GUI.changed;
        GUI.changed = false;
        float nueva = GUILayout.HorizontalSlider(visor.factorEscala, 1f, 2f * recomendada);
        if (GUI.changed && Mathf.Abs(nueva - visor.factorEscala) >= 1f) escalaPedida = nueva;
        GUI.changed = cambioAntes || cambioSlider || GUI.changed;
        GUILayout.BeginHorizontal();
        if (GUILayout.Button("Escala del recorrido", Bot(PanelUI.Boton))) escalaPedida = recomendada;
        if (GUILayout.Button("Centrar camara", Bot(PanelUI.Boton))) pedidoCentrar = true;
        GUILayout.EndHorizontal();
    }

    void DibujarNumeros(PosicionMovil p)
    {
        RepartoMovil r = p.reparto;
        ConservacionMovil c = p.conservacion;

        if (PanelUI.Plegable("movil.donde", "Donde esta la carga", true))
        {
            PanelUI.Fila("Recorrido", $"s = {F(p.s_m, "0.00")} de {F(Anexo.recorrido.largo_m, "0.00")} m");
            PanelUI.Fila("Viga", $"{p.elemento}, xL = {F(p.xL, "0.00")} (a = {F(p.a_m, "0.00")} de "
                                 + $"L = {F(p.L_m, "0.00")} m)");
            PanelUI.Fila("Punto", $"({F(p.x, "0.00")}, {F(p.y, "0.00")}, {F(p.z, "0.00")}) m");
        }

        if (r != null && PanelUI.Plegable("movil.reparto", "Reparto a los extremos de la viga", true))
        {
            PanelUI.Fila($"V_i nodo {r.nodo_i}", $"{F(r.V_i_kN, "0.00")} kN ({F(r.porcentaje_i, "0.0")} %)");
            PanelUI.Fila($"V_j nodo {r.nodo_j}", $"{F(r.V_j_kN, "0.00")} kN ({F(r.porcentaje_j, "0.0")} %)");
            PanelUI.Fila("Palanca", $"{F(r.palanca_i_kN, "0.00")} / {F(r.palanca_j_kN, "0.00")} kN "
                                    + "(simplemente apoyada)");
            PanelUI.Fila("Empotrada", $"{F(r.empotrado_V_i_kN, "0.00")} / {F(r.empotrado_V_j_kN, "0.00")} kN "
                                      + "(fuerzas nodales equivalentes)");
            PanelUI.Fila("(My_i+My_j)/L", $"{F(r.momentos_sobre_L_kN, "0.00")} kN");
            PanelUI.Fila($"Llega a {r.nodo_i}", r.llega_a_i);
            PanelUI.Fila($"Llega a {r.nodo_j}", r.llega_a_j);
            GUILayout.Label(r.explicacion, Est(PanelUI.Tenue));
        }

        if (c != null && PanelUI.Plegable("movil.conservacion", "Conservacion (regla de calcular.equilibrio)", true))
        {
            GUILayout.BeginHorizontal();
            PanelUI.Insignia(c.cumple);
            GUILayout.Label($"Suma Rz = {F(c.suma_Rz_kN, "0.0000")} kN contra P = {F(c.P_kN, "0.####")} kN",
                            Est(PanelUI.Texto));
            GUILayout.EndHorizontal();
            PanelUI.Fila("Error", $"{F(c.error_kN, "0.0E+00")} kN (cota {F(c.cota_kN, "0.0E+00")}, "
                                  + $"{c.apoyos_z} apoyos)");
            PanelUI.Fila("Suma Rx, Ry", $"{F(c.suma_Rx_kN, "0.0000")} / {F(c.suma_Ry_kN, "0.0000")} kN "
                                        + $"(cota {F(c.cota_horizontal_kN, "0.0E+00")})");
            PanelUI.Fila("Vz_i+Vz_j+Pz", $"{F(c.suma_V_mas_Pz_kN, "0.0E+00")} kN");
            PanelUI.Fila("Cierre en L", $"{F(c.cierre_cociente, "0.000")} de la cota ({c.cierre_componente})");
        }

        if (PanelUI.Plegable("movil.respuesta", "Respuesta", true))
        {
            PanelUI.Fila("UZ max", $"{F(p.uz_min_mm, "0.000")} mm en el nodo {p.nodo_uz_min}");
            PanelUI.Fila("|u| max", $"{F(p.max_desplazamiento_mm, "0.000")} mm en el nodo "
                                    + $"{p.nodo_max_desplazamiento}");
            PanelUI.Fila("Bajo la carga", $"uz = {F(p.uz_bajo_carga_mm, "0.000")} mm");
            PanelUI.Fila("M bajo la carga", $"My = {F(p.M_bajo_carga_kNm, "0.00")} kN*m");
        }
    }

    GUIStyle Casilla()
    {
        if (PanelUI.Texto == null) return GUI.skin.toggle;
        if (estiloCasilla != null && ReferenceEquals(baseCasilla, PanelUI.Texto)) return estiloCasilla;
        baseCasilla = PanelUI.Texto;   // Preparar crea estilos nuevos al cambiar la escala
        estiloCasilla = new GUIStyle(PanelUI.Casilla ?? GUI.skin.toggle);   // casilla escalada
        estiloCasilla.fontSize = baseCasilla.fontSize;
        estiloCasilla.normal.textColor = PanelUI.ColorTexto;
        estiloCasilla.onNormal.textColor = PanelUI.ColorTexto;
        estiloCasilla.hover.textColor = PanelUI.ColorTexto;
        estiloCasilla.onHover.textColor = PanelUI.ColorTexto;
        return estiloCasilla;
    }

    static GUIStyle Est(GUIStyle s) { return s ?? GUI.skin.label; }
    static GUIStyle Bot(GUIStyle s) { return s ?? GUI.skin.button; }

    static string F(float v, string formato)
    {
        return v.ToString(formato, CultureInfo.InvariantCulture);
    }
}
