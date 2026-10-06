/*
================================================================
  VisorPersona.cs   --   SQ4: la carga movil ES el usuario
================================================================
  Una persona parada en una losa. El usuario la mueve con las flechas
  (Q / E, PgUp / PgDn o los botones cambian de piso; VisorPersona.Pisos.cs)
  y en cada paso el visor:

    1. IDENTIFICA EL PANO Y LA REGION: el rectangulo de losa entre las
       cuatro vigas que la rodean, y dentro de el la region tributaria
       donde esta parada;
    2. RESALTA LAS VIGAS RECEPTORAS: las cuatro del pano, y mas fuerte
       la que se lleva su peso;
    3. MUESTRA LA CARGA ASIGNADA: cuanto le llega a cada viga.

  ----------------------------------------------------------------
  DE DONDE SALE EL REPARTO  (y por que no es calculo en C#)
  ----------------------------------------------------------------
  La regla es la del PROPIO modelo: la losa se reparte a las vigas
  por areas tributarias, y los poligonos de ese reparto los arma
  Python y viajan en data/unity/<ed>.json (areas_tributarias). Una
  carga puntual en la losa, con esa misma regla, va ENTERA a la viga
  duena de la region donde cae. Lo que hace este archivo es ubicar un
  punto dentro de un poligono que ya existe: es seleccion, no
  analisis. No hay ningun numero nuevo.

  La tabla del pano dice ademas cuanta area le toca a cada una de las
  cuatro vigas (tambien de los poligonos de Python): es el reparto que
  tendria el peso si la persona fuera una carga pareja sobre todo el
  pano, y sirve para ver que la regla puntual es una simplificacion.

  ----------------------------------------------------------------
  REANALISIS
  ----------------------------------------------------------------
  Moverse NO requiere reanalisis: es la regla de reparto aplicada a un
  punto, y el panel lo dice. El EFECTO de la persona sobre la
  estructura (la deformada y la flecha de la viga cargada) tampoco: lo
  muestra VisorPersona.Deformada.cs sumando casos unitarios que
  OpenSees resolvio en Python (semana05_lab/influencias_persona.py).
  Los momentos no se muestran.

  ----------------------------------------------------------------
  CONTRATO
  ----------------------------------------------------------------
  - Se crea solo (AfterSceneLoad) si la escena tiene un VisorEstructura,
    igual que VisorCargaMovil, y VisorQA lo encuentra como pestana
    (IPanelIncrustable "Persona").
  - NO toca los materiales de la estructura (CONTRATO.md 8: solo
    AmbienteVisor y el mapa D/C los cambian): dibuja sus propios
    objetos, con su propio material Unlit, como los diagramas.
  - Las flechas solo mueven a la persona si hay una puesta y ningun
    campo de texto tiene el foco.
================================================================
*/

using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

public partial class VisorPersona : MonoBehaviour, IPanelIncrustable
{
    // ============================================================
    // IPanelIncrustable
    // ============================================================
    public string TituloPestana { get { return "Persona"; } }
    public bool PanelPropio { get; set; } = true;

    [Tooltip("Peso del caminante, kN. Arranca en la P de la pestana Carga movil (100 kN) para que su "
             + "deformada se vea; una persona son 0.80 kN (boton Persona del panel).")]
    public float pesoKN = 100f;
    [Tooltip("Velocidad al caminar con las flechas, m/s.")]
    public float velocidad = 2.5f;

    // --- colores (overlay, no la estructura) ---
    static readonly Color COLOR_PERSONA = new Color(1.00f, 0.55f, 0.10f);
    static readonly Color COLOR_RECEPTORA = new Color(0.10f, 0.85f, 1.00f);
    static readonly Color COLOR_LLEVA = new Color(1.00f, 0.20f, 0.60f);
    static readonly Color COLOR_REGION = new Color(1.00f, 0.85f, 0.20f);
    static readonly Color COLOR_PANO = new Color(0.30f, 1.00f, 0.40f);

    // --- estado ---
    VisorEstructura visor;
    bool puesta = false;
    float x, y;                        // posicion en planta, ejes OpenSees
    int piso = 0;
    readonly List<float> pisos = new List<float>();
    Resultado ultimo;
    bool redibujar = false;
    bool modeloEditado = false;

    // Lo que se dibuja: se destruye y se rehace en cada paso.
    readonly List<GameObject> creados = new List<GameObject>();
    readonly Dictionary<Color, Material> materiales = new Dictionary<Color, Material>();

    // Una viga del piso, en planta.
    struct Viga
    {
        public int id; public string tipo;
        public float x1, y1, x2, y2;
        public bool enX;               // corre a lo largo de X
    }

    // Lo que se muestra.
    class Resultado
    {
        public float z;
        public int receptora = -1;     // la que se lleva el peso (regla tributaria)
        public float areaRegion;
        public List<VerticePlanta> region;
        public AreaTributaria tributaria;
        public int[] bordes = { -1, -1, -1, -1 };   // abajo (y-), arriba (y+), izq (x-), der (x+)
        public float x0, x1, y0, y1;                 // el pano
        public readonly Dictionary<int, float> areaEnPano = new Dictionary<int, float>();
    }

    // ============================================================
    // ARRANQUE
    // ============================================================
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Arrancar()
    {
        if (FindAnyObjectByType<VisorEstructura>() == null) return;
        if (FindAnyObjectByType<VisorPersona>() != null) return;
        new GameObject("VisorPersona").AddComponent<VisorPersona>();
    }

    void OnEnable()
    {
        EventosVisor.Redibujado += AlRedibujar;
        EventosVisor.ModeloEditado += AlEditarModelo;
    }

    void OnDisable()
    {
        SalirCabina();                          // VisorPersona.Cabina.cs: devuelve la camara
        EventosVisor.Redibujado -= AlRedibujar;
        EventosVisor.ModeloEditado -= AlEditarModelo;
        Limpiar();
    }

    // El visor destruye y rehace sus objetos; los de la persona no son
    // suyos, pero se rehacen igual para seguir la deformada si la hay.
    void AlRedibujar() { if (puesta) redibujar = true; }

    // Con el modelo editado las areas tributarias siguen siendo las del
    // modelo original: se sigue mostrando, pero se avisa.
    void AlEditarModelo(string que) { modeloEditado = true; SoltarDeformadaPersona(); }

    bool Listo()
    {
        if (visor == null) visor = FindAnyObjectByType<VisorEstructura>();
        return visor != null && visor.Modelo != null;
    }

    void LeerPisos()
    {
        pisos.Clear();
        if (!Listo() || visor.Modelo.areas_tributarias == null) return;
        foreach (AreaTributaria a in visor.Modelo.areas_tributarias)
        {
            if (a == null || a.vertices == null || a.vertices.Length < 3) continue;
            bool esta = false;
            foreach (float z in pisos) if (Mathf.Abs(z - a.z) < 0.02f) { esta = true; break; }
            if (!esta) pisos.Add(a.z);
        }
        pisos.Sort();
    }

    // ============================================================
    // MOVERSE
    // ============================================================
    void Update()
    {
        if (!puesta || !Listo()) return;
        AnimarPiso();                           // VisorPersona.Pisos.cs: el ascensor entre pisos
        // Con el foco en un campo de texto las flechas son del campo.
        if (GUIUtility.keyboardControl != 0) { if (redibujar) Calcular(); AplicarDeformadaSiToca(); return; }
        if (Input.GetKeyDown(KeyCode.V)) { if (enCabina) SalirCabina(); else EntrarCabina(); }

        Vector2 mov = Vector2.zero;
        if (Input.GetKey(KeyCode.UpArrow)) mov.y += 1f;
        if (Input.GetKey(KeyCode.DownArrow)) mov.y -= 1f;
        if (Input.GetKey(KeyCode.RightArrow)) mov.x += 1f;
        if (Input.GetKey(KeyCode.LeftArrow)) mov.x -= 1f;
        bool cambio = false;
        if (enCabina) cambio = MoverEnCabina();     // VisorPersona.Cabina.cs: avanza y gira
        else if (mov != Vector2.zero)
        {
            // Relativo a la camara: "arriba" es alejarse de ella. En Unity
            // el plano es X-Z, que en OpenSees es X-Y (Ejes.AUnity).
            Camera cam = Camera.main;
            Vector3 f = cam != null ? cam.transform.forward : Vector3.forward;
            Vector3 r = cam != null ? cam.transform.right : Vector3.right;
            Vector2 fwd = new Vector2(f.x, f.z), der = new Vector2(r.x, r.z);
            if (fwd.sqrMagnitude < 1e-6f) fwd = new Vector2(0f, 1f);
            fwd.Normalize(); der.Normalize();
            Vector2 d = (fwd * mov.y + der * mov.x).normalized * velocidad * Time.unscaledDeltaTime;
            x += d.x; y += d.y;
            AlCaminar(d);                       // VisorPersona.Personaje.cs: el paso y el rumbo
            cambio = true;
        }
        if (Input.GetKeyDown(KeyCode.PageUp) || Input.GetKeyDown(KeyCode.E)) cambio |= CambiarPiso(+1);
        if (Input.GetKeyDown(KeyCode.PageDown) || Input.GetKeyDown(KeyCode.Q)) cambio |= CambiarPiso(-1);
        if (cambio || redibujar) Calcular();
        // La deformada se pide al MOVERSE, no al redibujar: aplicarla
        // redibuja, y pedirla en cada redibujo no pararia nunca.
        if (cambio) PedirDeformadaPersona();
        AplicarDeformadaSiToca();               // VisorPersona.Deformada.cs
    }

    /// Pone a la persona en el centro del piso elegido.
    void Poner()
    {
        LeerPisos();
        if (pisos.Count == 0) return;
        piso = Mathf.Clamp(piso, 0, pisos.Count - 1);
        // El centro de las regiones de ese piso: siempre cae sobre losa.
        float sx = 0f, sy = 0f; int n = 0;
        foreach (AreaTributaria a in visor.Modelo.areas_tributarias)
        {
            if (a == null || a.vertices == null || Mathf.Abs(a.z - pisos[piso]) > 0.02f) continue;
            foreach (VerticePlanta v in a.vertices) { sx += v.x; sy += v.y; n++; }
        }
        if (n == 0) return;
        x = sx / n; y = sy / n;
        puesta = true;
        PrepararInfluencias();
        Calcular();
        PedirDeformadaPersona();
    }

    void Quitar()
    {
        puesta = false;
        ultimo = null;
        SalirCabina();
        QuitarDeformadaPersona();
        Limpiar();
    }

    // ============================================================
    // IDENTIFICAR: region, pano y vigas
    // ============================================================
    void Calcular()
    {
        redibujar = false;
        if (!Listo() || pisos.Count == 0) return;
        var r = new Resultado { z = pisos[piso] };

        // --- 1. la region tributaria donde esta parada ---
        foreach (AreaTributaria a in visor.Modelo.areas_tributarias)
        {
            if (a == null || a.vertices == null || Mathf.Abs(a.z - r.z) > 0.02f) continue;
            foreach (List<VerticePlanta> pol in Poligonos(a))
            {
                if (!Adentro(pol, x, y)) continue;
                r.receptora = a.elemento;
                r.region = pol;
                r.areaRegion = Area(pol);
                r.tributaria = a;
                break;
            }
            if (r.receptora >= 0) break;
        }

        // --- 2. el pano: la viga mas cercana en cada direccion ---
        List<Viga> vigas = VigasDelPiso(r.z);
        float[] dist = { float.MaxValue, float.MaxValue, float.MaxValue, float.MaxValue };
        foreach (Viga v in vigas)
        {
            if (v.enX)
            {
                // corre en X: acota por abajo o por arriba si su tramo cubre x
                if (x < Mathf.Min(v.x1, v.x2) - 1e-3f || x > Mathf.Max(v.x1, v.x2) + 1e-3f) continue;
                float yv = 0.5f * (v.y1 + v.y2), d = y - yv;
                if (d >= 0f && d < dist[0]) { dist[0] = d; r.bordes[0] = v.id; r.y0 = yv; }
                if (d < 0f && -d < dist[1]) { dist[1] = -d; r.bordes[1] = v.id; r.y1 = yv; }
            }
            else
            {
                if (y < Mathf.Min(v.y1, v.y2) - 1e-3f || y > Mathf.Max(v.y1, v.y2) + 1e-3f) continue;
                float xv = 0.5f * (v.x1 + v.x2), d = x - xv;
                if (d >= 0f && d < dist[2]) { dist[2] = d; r.bordes[2] = v.id; r.x0 = xv; }
                if (d < 0f && -d < dist[3]) { dist[3] = -d; r.bordes[3] = v.id; r.x1 = xv; }
            }
        }

        // --- 3. cuanta area del pano le toca a cada viga (poligonos de Python) ---
        bool panoCerrado = r.bordes[0] >= 0 && r.bordes[1] >= 0 && r.bordes[2] >= 0 && r.bordes[3] >= 0;
        if (panoCerrado)
            foreach (AreaTributaria a in visor.Modelo.areas_tributarias)
            {
                if (a == null || a.vertices == null || Mathf.Abs(a.z - r.z) > 0.02f) continue;
                foreach (List<VerticePlanta> pol in Poligonos(a))
                {
                    Vector2 c = Centro(pol);
                    if (c.x < r.x0 || c.x > r.x1 || c.y < r.y0 || c.y > r.y1) continue;
                    float A;
                    r.areaEnPano.TryGetValue(a.elemento, out A);
                    r.areaEnPano[a.elemento] = A + Area(pol);
                }
            }

        ultimo = r;
        Dibujar(r, vigas);
    }

    List<Viga> VigasDelPiso(float z)
    {
        var salida = new List<Viga>();
        ModeloEstructural mod = visor.Modelo;
        foreach (Elemento e in mod.elementos)
        {
            if (e == null || e.tipo == null || !e.tipo.StartsWith("viga")) continue;
            Nodo a = mod.NodoPorId(e.n1), b = mod.NodoPorId(e.n2);
            if (a == null || b == null) continue;
            if (Mathf.Abs(a.z - z) > 0.02f || Mathf.Abs(b.z - z) > 0.02f) continue;
            salida.Add(new Viga
            {
                id = e.id, tipo = e.tipo,
                x1 = a.x, y1 = a.y, x2 = b.x, y2 = b.y,
                enX = Mathf.Abs(b.x - a.x) >= Mathf.Abs(b.y - a.y),
            });
        }
        return salida;
    }

    /// Los poligonos de una entrada: vienen CONCATENADOS y 'tamanos' dice
    /// cuantos vertices tiene cada uno (AreaTributaria, ModeloEstructural).
    static IEnumerable<List<VerticePlanta>> Poligonos(AreaTributaria a)
    {
        if (a.tamanos == null || a.tamanos.Length == 0)
        {
            yield return new List<VerticePlanta>(a.vertices);
            yield break;
        }
        int i = 0;
        foreach (int n in a.tamanos)
        {
            if (n <= 0 || i + n > a.vertices.Length) yield break;
            var pol = new List<VerticePlanta>(n);
            for (int k = 0; k < n; k++) pol.Add(a.vertices[i + k]);
            i += n;
            yield return pol;
        }
    }

    /// Punto en poligono, por paridad de cruces.
    static bool Adentro(List<VerticePlanta> p, float px, float py)
    {
        bool dentro = false;
        for (int i = 0, j = p.Count - 1; i < p.Count; j = i++)
        {
            if (((p[i].y > py) != (p[j].y > py))
                && px < (p[j].x - p[i].x) * (py - p[i].y) / (p[j].y - p[i].y) + p[i].x)
                dentro = !dentro;
        }
        return dentro;
    }

    static float Area(List<VerticePlanta> p)
    {
        float s = 0f;
        for (int i = 0, j = p.Count - 1; i < p.Count; j = i++) s += p[j].x * p[i].y - p[i].x * p[j].y;
        return Mathf.Abs(s) * 0.5f;
    }

    static Vector2 Centro(List<VerticePlanta> p)
    {
        float sx = 0f, sy = 0f;
        foreach (VerticePlanta v in p) { sx += v.x; sy += v.y; }
        return new Vector2(sx / p.Count, sy / p.Count);
    }

    // ============================================================
    // DIBUJAR (objetos propios; la estructura no se toca)
    // ============================================================
    void Dibujar(Resultado r, List<Viga> vigas)
    {
        Limpiar();
        float z = r.z;
        // Con la deformada puesta, la persona baja con el punto que carga
        // (dibujado, con la misma escala que el edificio). Al cambiar de
        // piso sube o baja de a poco (AlturaPersona).
        float dz = DescensoDibujado() + AlturaPersona(z) - z;

        // el AT-ST (VisorPersona.Personaje.cs) o, sin el, una capsula de 1.70 m
        if (!DibujarPersonaje(z + dz))
        {
            GameObject p = GameObject.CreatePrimitive(PrimitiveType.Capsule);
            Destroy(p.GetComponent<Collider>());
            p.name = "SQ4_Persona";
            p.transform.position = Ejes.AUnity(x, y, z + dz + 0.85f);
            p.transform.localScale = new Vector3(0.45f, 0.85f, 0.45f);
            p.GetComponent<Renderer>().sharedMaterial = MaterialDe(COLOR_PERSONA);
            creados.Add(p);
        }

        // la flecha de su peso, hasta la losa
        Linea(Ejes.AUnity(x, y, z + dz + 2.6f), Ejes.AUnity(x, y, z + dz + 0.02f), COLOR_PERSONA, 0.06f);
        // y por donde llega a la viga: hasta el punto cargado (o el nodo del muro)
        Vector3 cargado;
        if (PuntoDeCarga(out cargado))
            Linea(Ejes.AUnity(x, y, z + dz + 0.02f), cargado, COLOR_LLEVA, 0.05f);

        // la region tributaria donde esta parada
        if (r.region != null) Contorno(r.region, z + 0.03f, COLOR_REGION, 0.07f);

        // el pano
        if (r.bordes[0] >= 0 && r.bordes[1] >= 0 && r.bordes[2] >= 0 && r.bordes[3] >= 0)
        {
            var pano = new List<VerticePlanta>
            {
                new VerticePlanta { x = r.x0, y = r.y0 }, new VerticePlanta { x = r.x1, y = r.y0 },
                new VerticePlanta { x = r.x1, y = r.y1 }, new VerticePlanta { x = r.x0, y = r.y1 },
            };
            Contorno(pano, z + 0.02f, COLOR_PANO, 0.04f);
        }

        // las vigas del pano, en su posicion actual (sigue la deformada)
        bool dibujada = false;
        var bordes = new HashSet<int>(r.bordes);
        foreach (Viga v in vigas)
        {
            if (!bordes.Contains(v.id) && v.id != r.receptora) continue;
            bool lleva = v.id == r.receptora;
            dibujada |= lleva;
            Resaltar(v.id, lleva);
        }
        // La que recibe puede no ser una viga del pano: medido en el
        // conjunto, 92 de las 883 regiones tributarias son de MUROS (la
        // losa les descarga directo). Se resalta igual.
        if (r.receptora >= 0 && !dibujada) Resaltar(r.receptora, true);

        DibujarMomentos();                      // VisorPersona.Momentos.cs
    }

    void Resaltar(int id, bool lleva)
    {
        Elemento e = visor.Modelo.ElementoPorId(id);
        if (e == null) return;
        Nodo a = visor.Modelo.NodoPorId(e.n1), b = visor.Modelo.NodoPorId(e.n2);
        if (a == null || b == null) return;
        Vector3 alto = Vector3.up * (lleva ? 0.55f : 0.45f);
        // La que lleva el peso, con su elastica si la deformada esta puesta.
        if (lleva && DibujarElastica(id, alto, 0.22f)) return;
        Linea(visor.PosicionActual(a) + alto, visor.PosicionActual(b) + alto,
              lleva ? COLOR_LLEVA : COLOR_RECEPTORA, lleva ? 0.22f : 0.12f);
    }

    /// "la viga 331" o "el muro 200012": el panel nombra lo que es.
    string Nombre(int id)
    {
        Elemento e = Listo() ? visor.Modelo.ElementoPorId(id) : null;
        if (e == null) return "el elemento " + id;
        if (e.tipo == "muro") return "el muro " + id;
        if (e.tipo == "brazo" || e.tipo == "brazo_rigido") return "el brazo rigido " + id;
        if (e.tipo == "columna" || e.tipo == "pilar_metal") return "la columna " + id;
        if (e.tipo == "diagonal") return "la diagonal " + id;
        return "la viga " + id;
    }

    void Linea(Vector3 a, Vector3 b, Color c, float grosor)
    {
        GameObject go = new GameObject("SQ4_Linea");
        LineRenderer lr = go.AddComponent<LineRenderer>();
        lr.positionCount = 2;
        lr.SetPosition(0, a); lr.SetPosition(1, b);
        lr.startWidth = lr.endWidth = grosor;
        lr.sharedMaterial = MaterialDe(c);
        lr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        creados.Add(go);
    }

    void Contorno(List<VerticePlanta> pol, float z, Color c, float grosor)
    {
        GameObject go = new GameObject("SQ4_Contorno");
        LineRenderer lr = go.AddComponent<LineRenderer>();
        lr.loop = true;
        lr.positionCount = pol.Count;
        for (int k = 0; k < pol.Count; k++) lr.SetPosition(k, Ejes.AUnity(pol[k].x, pol[k].y, z));
        lr.startWidth = lr.endWidth = grosor;
        lr.sharedMaterial = MaterialDe(c);
        lr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        creados.Add(go);
    }

    Material MaterialDe(Color color)
    {
        Material m;
        if (materiales.TryGetValue(color, out m)) return m;
        // El mismo shader que los diagramas: el Unlit de URP, que la build
        // incluye siempre (ConstruirApp).
        Shader sh = Shader.Find("Universal Render Pipeline/Unlit");
        if (sh == null) sh = VisorEstructura.ShaderCompatible();
        m = new Material(sh) { color = color };
        if (m.HasProperty("_BaseColor")) m.SetColor("_BaseColor", color);
        materiales[color] = m;
        return m;
    }

    void Limpiar()
    {
        foreach (GameObject g in creados) if (g != null) Destroy(g);
        creados.Clear();
    }

    // ============================================================
    // PANEL
    // ============================================================
    void OnGUI()
    {
        HudCabina();                            // VisorPersona.Cabina.cs
        if (!PanelPropio) return;
        PanelUI.Preparar();
        GUILayout.BeginArea(new Rect(Screen.width - PanelUI.Px(380f), PanelUI.Px(10f),
                                     PanelUI.Px(370f), Screen.height - PanelUI.Px(20f)),
                            GUI.skin.box);
        DibujarPanel();
        GUILayout.EndArea();
    }

    public void DibujarPanel()
    {
        PanelUI.Preparar();
        GUIStyle texto = PanelUI.Texto ?? GUI.skin.label;
        GUIStyle tenue = PanelUI.Tenue ?? GUI.skin.label;
        GUIStyle aviso = PanelUI.Aviso ?? GUI.skin.label;
        GUIStyle boton = PanelUI.Boton ?? GUI.skin.button;

        GUILayout.Label("SQ4: la carga movil es una persona", texto);
        GUILayout.Label("Ponla en una losa y muevela con las FLECHAS (relativas a la camara). "
                        + "Q / E (o PgUp / PgDn, o los botones) cambian de piso.", tenue);

        if (!Listo()) { GUILayout.Label("Esperando el modelo...", aviso); return; }

        // Mismos controles en Layout y Repaint: los botones se dibujan
        // siempre y la accion se difiere a Update (regla de IMGUI).
        if (GUILayout.Button(puesta ? "Volver al centro del piso" : "Poner persona", boton))
            diferida = Poner;
        GUI.enabled = puesta;
        if (GUILayout.Button("Quitar persona", boton)) diferida = Quitar;
        PanelPisos(boton);                                  // VisorPersona.Pisos.cs
        PanelCabina(boton);                                 // VisorPersona.Cabina.cs
        GUI.enabled = true;

        GUILayout.Label($"Peso: {F(pesoKN, "0.00")} kN  ({F(pesoKN / 9.80665f * 1000f, "0")} kg)", texto);
        PanelPeso(boton);                                   // VisorPersona.Deformada.cs
        PanelDeformada(texto, tenue, aviso, boton);
        PanelMomentos(texto, tenue, aviso, boton);          // VisorPersona.Momentos.cs

        if (modeloEditado)
            GUILayout.Label("El modelo se edito: las areas tributarias son las del modelo "
                            + "original.", aviso);

        if (!puesta || ultimo == null) return;
        Resultado r = ultimo;
        GUILayout.Space(PanelUI.Px(6f));
        GUILayout.Label($"Piso z = {F(r.z, "0.00")} m ({piso + 1} de {pisos.Count})   "
                        + $"posicion ({F(x, "0.00")}, {F(y, "0.00")})", texto);

        // 1. pano y region
        bool cerrado = r.bordes[0] >= 0 && r.bordes[1] >= 0 && r.bordes[2] >= 0 && r.bordes[3] >= 0;
        GUILayout.Label(cerrado
            ? $"PANO: {F(r.x1 - r.x0, "0.00")} x {F(r.y1 - r.y0, "0.00")} m, entre las vigas "
              + $"{r.bordes[2]} (izq), {r.bordes[3]} (der), {r.bordes[0]} (abajo) y {r.bordes[1]} (arriba)"
            : "PANO: no esta cerrado por cuatro vigas (borde o voladizo)", texto);
        if (r.receptora < 0)
        {
            GUILayout.Label("REGION: fuera de toda area tributaria (no hay losa aca, o es un "
                            + "vacio). Su peso no le llega a ninguna viga.", aviso);
            return;
        }
        GUILayout.Label($"REGION: la tributaria de {Nombre(r.receptora)}, {F(r.areaRegion, "0.00")} m2 "
                        + "(amarilla en la escena)", texto);

        // 2 y 3. vigas y carga
        GUILayout.Label($"CARGA ASIGNADA, con la regla del modelo: {F(pesoKN, "0.00")} kN enteros a "
                        + $"{Nombre(r.receptora)} (magenta). Las otras vigas del pano (celeste) no reciben "
                        + "nada de un punto: la regla tributaria es por region, y cada punto de losa "
                        + "es de UN solo elemento (medido: 0 traslapes en 49 940 puntos del conjunto).", texto);
        if (r.tributaria != null && r.tributaria.w > 0f)
            GUILayout.Label($"Para comparar: ese elemento ya recibe {F(r.tributaria.w, "0.00")} kN/m de losa "
                            + $"en G ({F(r.tributaria.carga_total, "0.0")} kN en su region), o sea la "
                            + $"persona es el {F(100f * pesoKN / Mathf.Max(r.tributaria.carga_total, 1e-6f), "0.0")} % "
                            + "de esa carga.", tenue);

        if (r.areaEnPano.Count > 0)
        {
            float total = 0f;
            foreach (float a in r.areaEnPano.Values) total += a;
            GUILayout.Label("Si el peso se repartiera parejo en el pano (misma regla, por area):", tenue);
            foreach (KeyValuePair<int, float> kv in r.areaEnPano)
                GUILayout.Label($"   viga {kv.Key}: {F(100f * kv.Value / total, "0")} % del pano -> "
                                + $"{F(pesoKN * kv.Value / total, "0.000")} kN", tenue);
        }

        GUILayout.Space(PanelUI.Px(6f));
        GUILayout.Label("REANALISIS: no hace falta. El reparto es la regla tributaria aplicada a un "
                        + "punto, y la deformada (arriba) suma casos unitarios que OpenSees ya "
                        + "resolvio en Python: el modelo es lineal.", tenue);
    }

    // Las acciones de los botones corren en LateUpdate, fuera de OnGUI.
    System.Action diferida;
    void LateUpdate()
    {
        CamaraDeCabina();                       // VisorPersona.Cabina.cs
        if (diferida == null) return;
        System.Action a = diferida;
        diferida = null;
        a();
    }

    static string F(float v, string formato)
    {
        return v.ToString(formato, CultureInfo.InvariantCulture);
    }
}
