/*
================================================================
  EditorEstructura.cs
================================================================
  Selecciona y EDITA el modelo dentro de Unity, y le pide al
  servidor que lo vuelva a resolver.

  Sigue la regla del CLAUDE.md: aca no se calcula nada estructural.
  Se editan DATOS (nodos, barras, secciones, restricciones) y el
  calculo vuelve a OpenSees por HTTP (AnalizadorEstructural).

  ----------------------------------------------------------------
  CONTROLES
    Click sobre un nodo o barra ..... seleccionar
    Arrastrar el nodo seleccionado .. moverlo en planta (X-Y)
    Shift + arrastrar ............... moverlo en altura (Z)
    Esc ............................. cancelar la barra nueva / deseleccionar
    Supr ............................ borrar lo seleccionado
    Enter ........................... recalcular en el servidor
  Supr, Enter y Esc NO actuan si el foco esta en un campo de texto
  (X/Y/Z, la URL, el "Ir a ID" de VisorQA): antes, borrar un caracter
  en X borraba el nodo.

  USO
    1. GameObject "Analizador" -> Add Component -> EditorEstructura
    2. Arrastra 'Visor' y 'Analizador' a sus campos (o se buscan solos).
    3. Play. Con VisorQA en la escena el panel es la pestana
       "Modificar"; sin VisorQA, un panel propio a la derecha.

  ----------------------------------------------------------------
  PESTANA "Modificar" (IPanelIncrustable, semana05/CONTRATO.md 8)
  ----------------------------------------------------------------
  VisorQA pone PanelPropio = false y llama a DibujarPanel() dentro de
  su pestana. Entonces:
    - OnGUI no dibuja nada y MouseSobrePanel() devuelve false;
    - la seleccion la manda VisorQA por EventosVisor.SeleccionCambio
      (una sola seleccion en toda la escena): este script deja de hacer
      su propio raycast y sigue esa;
    - el arrastre del nodo seleccionado y las teclas siguen aca.
  Lo que redibuja la escena (borrar, mover, cambiar seccion, mostrar un
  caso) no se hace dentro de OnGUI: se encola y corre en Update. Si se
  hiciera en el evento del click, IMGUI veria otra cantidad de controles
  entre Layout y Repaint.

  ----------------------------------------------------------------
  PARA AUTOMATIZAR (la M1 desde el exe, CapturaSemana05)
  ----------------------------------------------------------------
      editor.BorrarElementoPorId(69);   // inmediato; false si no existe
      analizador.Analizar(ok => ...);   // ver AnalizadorEstructural.cs
  BorrarElementoPorId hace lo mismo que el boton "Borrar barra": quita
  la barra y sus cargas distribuidas, avisa ModeloEditado y redibuja.

  ----------------------------------------------------------------
  INTEGRIDAD DEL MODELO
  Borrar cosas deja referencias huerfanas, y algunas son peligrosas
  porque NO fallan: si borras una barra y dejas su carga distribuida,
  OpenSees solo emite un warning por consola y DESCARTA la carga. El
  analisis "funciona" con menos carga de la que crees, y el equilibrio
  cierra igual porque la carga descartada nunca entro.
  Por eso al borrar se limpian tambien las cargas, los diafragmas y
  los brazos rigidos que apuntaban a lo borrado. El servidor ademas
  valida esto y lo rechaza con un mensaje explicito.

  Lo que NO se recalcula (no es calculo de Unity): el peso propio va
  horneado en las cargas del modelo exportado (w = A*gamma + q*A/L en
  las vigas y carga nodal en columnas y muros del LT2). Cambiar una
  seccion cambia la rigidez, no el peso; borrar una columna deja su
  carga nodal en los nodos. El panel lo dice.
================================================================
*/

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;
using UnityEngine.Rendering;

public class EditorEstructura : MonoBehaviour, IPanelIncrustable
{
    [Header("Referencias")]
    public VisorEstructura visor;
    public AnalizadorEstructural analizador;
    public CamaraOrbital camara;

    [Header("Apariencia")]
    // Ya no se usa. La escena lo guarda en amarillo (1, 0.85, 0.15), que
    // es el color del diafragma de VisorQA y casi el de la deformada: el
    // resaltado se confundia con ellos. Se deja el campo porque en la
    // Semana 5 no se borran miembros publicos (semana05/CONTRATO.md 2.5).
    [HideInInspector]
    public Color colorSeleccion = new Color(1f, 0.85f, 0.15f);

    [Tooltip("Color de la capa que envuelve al nodo o barra seleccionado. "
           + "No se usa amarillo: es el del diafragma y el de la deformada.")]
    public Color colorResaltado = new Color(0.15f, 0.85f, 1f);

    [Tooltip("Ancho del panel propio, en pixeles de diseno (se escala con PanelUI).")]
    public float anchoPanel = 310f;

    // El panel propio va a la DERECHA: VisorQA ocupa la izquierda.
    Rect RectPanel()
    {
        float ancho = PanelUI.Px(anchoPanel);
        float margen = PanelUI.Px(10f);
        return new Rect(Screen.width - ancho - margen, margen,
                        ancho, Screen.height - 2f * margen);
    }

    [Header("Edicion")]
    [Tooltip("Paso (m) con que avanza un nodo al arrastrarlo. Se aplica al "
           + "DESPLAZAMIENTO, no a la coordenada: un nodo en x = 7.77 "
           + "arrastrado queda en 8.02, 8.27... y la coordenada que no se "
           + "mueve no se toca. 0 = sin paso.")]
    public float pasoRejilla = 0.25f;

    // ------------------------------------------------------------
    // IPanelIncrustable
    // ------------------------------------------------------------
    public string TituloPestana { get { return "Modificar"; } }

    private bool panelPropio = true;
    public bool PanelPropio
    {
        get { return panelPropio; }
        set { panelPropio = value; }
    }

    // --- Seleccion ---
    private int nodoSel = -1;
    private int elemSel = -1;
    private int nodoAncla = -1;      // primer nodo al crear una barra

    /// Lo seleccionado en el editor (-1 = nada). Solo lectura.
    public int NodoSeleccionado { get { return nodoSel; } }
    public int ElementoSeleccionado { get { return elemSel; } }

    // --- Resaltado: una capa aparte que envuelve al objeto ---
    // No se toca el sharedMaterial del objeto: ese lo manejan AmbienteVisor
    // y el mapa D/C (protocolo de materiales, CONTRATO.md 8). La capa no
    // tiene collider, asi que no ataja clicks.
    private readonly List<GameObject> resaltes = new List<GameObject>();
    private Material matResaltado;
    private Color colorDelMaterial;

    // --- Arrastre de nodo ---
    private bool arrastrePendiente = false;   // se presiono sobre el nodo seleccionado
    private bool arrastrandoNodo = false;     // y el mouse ya supero el umbral
    private bool arrastreMovio = false;       // y el nodo cambio de lugar
    private bool bloqueeCamara = false;
    private bool soloAltura = false;
    private bool terminoGestoEsteFrame = false;
    private Plane planoArrastre;
    private Vector3 puntoInicial;
    private Vector2 mouseInicial;
    private float x0, y0, z0;
    private int frameFinArrastre = -10;

    /// true mientras se arrastra un nodo (ya supero el umbral) y durante
    /// el frame en que se suelta. Para VisorQA: ese MouseUp no es un click
    /// de seleccion. Con la camara bloqueada CamaraOrbital.HuboArrastre no
    /// se entera del gesto, y el raycast al soltar podia caer en el vacio y
    /// deseleccionar el nodo recien movido. Se compara por frame (y no con
    /// una bandera que se limpia en Update) para que de igual el orden en
    /// que Unity llama los Update de los dos scripts.
    public bool ArrastrandoNodo
    {
        get { return arrastrandoNodo || frameFinArrastre == Time.frameCount; }
    }

    // --- Estado ---
    private bool modificado = false;
    private string ultimoMotivo = "";
    private int versionEdicion = 0;
    private string mensaje = "";
    private float mensajeHasta = 0f;
    private Vector2 scrollPanel;
    private string rutaGuardado = "";

    // Campos de texto del panel (se editan como string para poder
    // escribir "-" o "0." sin que el parseo los borre a mitad).
    private string campoX = "", campoY = "", campoZ = "";
    private int nodoEnCampos = -1;
    const string PREFIJO_CAMPO = "editor.";

    // Acciones pedidas desde el panel; corren en Update.
    private readonly List<Action> pendientes = new List<Action>();

    // Foco de teclado: ver ManejarTeclas.
    private bool focoEnMisCampos = false;
    private int frameDibujado = -10;
    private bool soltarFoco = false;

    // Lista de secciones para "Cambiar seccion" (cache).
    private bool soloFamilia = true;
    private string claveSecciones = "";
    private List<string> seccionesCache = new List<string>();
    private bool familiaUtil = false;

    // Estilos propios que PanelUI no trae (campo, casilla, error).
    private GUIStyle baseEstilos, estiloCampo, estiloCasilla, estiloError;

    private VisorQA qa;
    private float proximaBusquedaQA = 0f;

    static readonly string[] GDL = { "ux", "uy", "uz", "rx", "ry", "rz" };

    // ============================================================
    // CICLO DE VIDA
    // ============================================================
    void Start()
    {
        AsegurarReferencias();
        if (visor == null)
            Debug.LogError("EditorEstructura necesita un VisorEstructura en la escena.");
    }

    void AsegurarReferencias()
    {
        if (visor == null) visor = FindAnyObjectByType<VisorEstructura>();
        if (analizador == null) analizador = FindAnyObjectByType<AnalizadorEstructural>();
        if (camara == null) camara = FindAnyObjectByType<CamaraOrbital>();
    }

    void OnEnable()
    {
        EventosVisor.SeleccionCambio += AlCambiarSeleccion;
        EventosVisor.Redibujado += AlRedibujar;
    }

    void OnDisable()
    {
        EventosVisor.SeleccionCambio -= AlCambiarSeleccion;
        EventosVisor.Redibujado -= AlRedibujar;
        // Un arrastre cortado a la mitad no puede dejar la camara bloqueada.
        arrastrePendiente = false;
        arrastrandoNodo = false;
        SoltarCamara();
        QuitarResaltado();
    }

    void OnDestroy()
    {
        if (matResaltado != null) Destroy(matResaltado);
    }

    // La seleccion de VisorQA. Se aplica en Update: el aviso puede llegar
    // desde el OnGUI de VisorQA (un boton "Ir a ID"), y cambiar lo que
    // dibuja este panel en medio de ese evento descuadra IMGUI.
    void AlCambiarSeleccion(string tipo, int id)
    {
        pendientes.Add(() =>
        {
            if (tipo == EventosVisor.TIPO_NODO) SeleccionarNodo(id);
            else if (tipo == EventosVisor.TIPO_ELEMENTO) SeleccionarElemento(id);
            else Deseleccionar();
        });
    }

    // Redibujar destruye los objetos: la capa de resaltado se rehace sobre
    // los nuevos (sigue a la deformada, al filtro de piso y al arrastre).
    // No se llama a Redibujar aca (CONTRATO.md 2.1).
    void AlRedibujar()
    {
        AplicarResaltado();
    }

    // ============================================================
    // ENTRADA
    // ============================================================
    void Update()
    {
        terminoGestoEsteFrame = false;
        if (visor == null || visor.Modelo == null) return;

        EjecutarPendientes();
        ValidarSeleccion();
        ManejarArrastre();
        if (PanelPropio) ManejarClick();
        ManejarTeclas();
    }

    void EjecutarPendientes()
    {
        if (pendientes.Count == 0) return;
        Action[] copia = pendientes.ToArray();
        pendientes.Clear();
        foreach (Action a in copia)
        {
            try { a(); }
            catch (Exception ex)
            {
                Debug.LogException(ex);
                Avisar("Error: " + ex.Message);
            }
        }
    }

    // Lo borrado por otro camino (o por este, en otro orden) no puede
    // quedar seleccionado.
    void ValidarSeleccion()
    {
        ModeloEstructural M = visor.Modelo;
        if (nodoSel >= 0 && M.NodoPorId(nodoSel) == null) Deseleccionar();
        if (elemSel >= 0 && M.ElementoPorId(elemSel) == null) Deseleccionar();
        if (nodoAncla >= 0 && M.NodoPorId(nodoAncla) == null) nodoAncla = -1;
    }

    /// Publico para que VisorQA tampoco deje pasar los clicks que caen
    /// sobre este panel. Con PanelPropio == false no hay panel propio:
    /// devuelve false (el panel es de VisorQA).
    public bool MouseSobrePanel()
    {
        if (!PanelPropio) return false;
        // El origen de GUI esta arriba-izquierda y el de mousePosition
        // abajo-izquierda: hay que invertir la Y antes de comparar.
        Vector2 p = new Vector2(Input.mousePosition.x,
                                Screen.height - Input.mousePosition.y);
        return RectPanel().Contains(p);
    }

    // El propio panel o cualquiera de VisorQA. OJO: MouseSobrePanel NO
    // pregunta a VisorQA, porque VisorQA.MouseSobreUI pregunta a este
    // (serian llamadas en circulo).
    bool MouseSobreAlgunaUI()
    {
        if (MouseSobrePanel()) return true;
        if (qa == null && Time.realtimeSinceStartup >= proximaBusquedaQA)
        {
            qa = FindAnyObjectByType<VisorQA>();
            proximaBusquedaQA = Time.realtimeSinceStartup + 1f;
        }
        return qa != null && qa.MouseSobreUI();
    }

    void ManejarClick()
    {
        if (arrastrePendiente || terminoGestoEsteFrame) return;
        if (!Input.GetMouseButtonUp(0)) return;
        if (MouseSobreAlgunaUI()) return;
        // Si el usuario estaba orbitando, el click no es una seleccion.
        if (camara != null && camara.HuboArrastre) return;
        Camera cam = Camera.main;
        if (cam == null) return;

        RaycastHit hit;
        if (!Physics.Raycast(cam.ScreenPointToRay(Input.mousePosition), out hit))
        {
            Deseleccionar();
            return;
        }

        DatoNodo dn = hit.collider.GetComponentInParent<DatoNodo>();
        if (dn != null) { SeleccionarNodo(dn.idNodo); return; }

        DatoElemento de = hit.collider.GetComponentInParent<DatoElemento>();
        if (de != null) { SeleccionarElemento(de.idElemento); return; }

        Deseleccionar();
    }

    // ------------------------------------------------------------
    // ARRASTRE
    // Antes, presionar sobre el nodo seleccionado (sin moverlo) lo
    // redondeaba a la rejilla de 0.25 m en x, y y z: las cotas del LT2
    // (-4.01, -0.05, 3.91, 7.87, 11.83) no son multiplos de 0.25, asi que
    // un click sacaba el nodo del plano del diafragma y el servidor
    // respondia HTTP 400. Ahora:
    //   1. la camara se bloquea al presionar (no orbita), pero el nodo
    //      no se mueve hasta superar PanelUI.UmbralArrastre();
    //   2. el paso de la rejilla se aplica al DESPLAZAMIENTO desde donde
    //      estaba, y solo en las coordenadas que se mueven: en planta z
    //      no se toca nunca; en altura (Shift) x e y no se tocan.
    // ------------------------------------------------------------
    void ManejarArrastre()
    {
        Camera cam = Camera.main;
        if (cam == null) return;

        if (Input.GetMouseButtonDown(0) && nodoSel >= 0 && !arrastrePendiente
            && !MouseSobreAlgunaUI())
            EmpezarArrastre(cam);

        if (!arrastrePendiente) return;

        // Soltado (o perdido fuera de la ventana): termina el gesto.
        if (!Input.GetMouseButton(0))
        {
            TerminarArrastre();
            return;
        }

        if (!arrastrandoNodo
            && Vector2.Distance((Vector2)Input.mousePosition, mouseInicial) > PanelUI.UmbralArrastre())
            arrastrandoNodo = true;

        if (arrastrandoNodo) MoverNodoArrastrado(cam);
    }

    void EmpezarArrastre(Camera cam)
    {
        Ray r = cam.ScreenPointToRay(Input.mousePosition);
        RaycastHit hit;
        if (!Physics.Raycast(r, out hit)) return;
        DatoNodo dn = hit.collider.GetComponentInParent<DatoNodo>();
        if (dn == null || dn.idNodo != nodoSel) return;
        Nodo n = visor.Modelo.NodoPorId(nodoSel);
        if (n == null) return;

        // El plano pasa por la posicion SIN deformar; como se usa la
        // diferencia entre dos puntos del plano, da igual que el nodo
        // este dibujado deformado.
        Vector3 pos = Ejes.PosicionDe(n);
        soloAltura = ShiftPresionado();
        if (soloAltura)
        {
            // Plano vertical de cara a la camara: el mouse sube y baja el nodo.
            Vector3 frente = cam.transform.forward;
            frente.y = 0f;
            if (frente.sqrMagnitude < 1e-6f) { frente = cam.transform.up; frente.y = 0f; }
            if (frente.sqrMagnitude < 1e-6f) frente = Vector3.forward;
            planoArrastre = new Plane(-frente.normalized, pos);
        }
        else
        {
            planoArrastre = new Plane(Vector3.up, pos);
        }

        float d;
        if (!planoArrastre.Raycast(r, out d)) return;

        puntoInicial = r.GetPoint(d);
        mouseInicial = Input.mousePosition;
        x0 = n.x; y0 = n.y; z0 = n.z;
        arrastrePendiente = true;
        arrastrandoNodo = false;
        arrastreMovio = false;
        if (camara != null) { camara.bloqueada = true; bloqueeCamara = true; }
    }

    void MoverNodoArrastrado(Camera cam)
    {
        Nodo n = visor.Modelo.NodoPorId(nodoSel);
        if (n == null) { TerminarArrastre(); return; }

        Ray r = cam.ScreenPointToRay(Input.mousePosition);
        float d;
        if (!planoArrastre.Raycast(r, out d)) return;

        // Unity(x, z_opensees, y_opensees): la Y de Unity es la Z de OpenSees.
        Vector3 delta = r.GetPoint(d) - puntoInicial;
        float nx = x0, ny = y0, nz = z0;
        if (soloAltura) nz = z0 + Paso(delta.y);
        else { nx = x0 + Paso(delta.x); ny = y0 + Paso(delta.z); }

        // Sin cambio real (medio paso de rejilla) no se marca ni se redibuja.
        if (nx == n.x && ny == n.y && nz == n.z) return;

        n.x = nx; n.y = ny; n.z = nz;
        if (!arrastreMovio)
        {
            arrastreMovio = true;
            MarcarModificado($"mover nodo {n.id}");
        }
        SincronizarCampos(n);
        visor.Redibujar();
    }

    void TerminarArrastre()
    {
        bool movio = arrastreMovio;
        if (arrastrandoNodo) frameFinArrastre = Time.frameCount;
        arrastrePendiente = false;
        arrastrandoNodo = false;
        arrastreMovio = false;
        SoltarCamara();
        // El MouseUp de este gesto no es un click de seleccion.
        terminoGestoEsteFrame = true;

        if (movio)
        {
            Nodo n = visor.Modelo.NodoPorId(nodoSel);
            if (n != null)
                Avisar($"Nodo {n.id} movido a ({F(n.x, "0.###")}, {F(n.y, "0.###")}, "
                       + $"{F(n.z, "0.###")}). Enter para recalcular.");
        }
    }

    void SoltarCamara()
    {
        if (bloqueeCamara && camara != null) camara.bloqueada = false;
        bloqueeCamara = false;
    }

    bool ShiftPresionado()
    {
        return Input.GetKey(KeyCode.LeftShift) || Input.GetKey(KeyCode.RightShift);
    }

    // El paso de la rejilla aplicado a un DESPLAZAMIENTO.
    float Paso(float desplazamiento)
    {
        if (pasoRejilla <= 0f) return desplazamiento;
        return Mathf.Round(desplazamiento / pasoRejilla) * pasoRejilla;
    }

    // Para un nodo NUEVO (no tiene una coordenada que conservar).
    float Rejilla(float v)
    {
        if (pasoRejilla <= 0f) return v;
        return Mathf.Round(v / pasoRejilla) * pasoRejilla;
    }

    // ------------------------------------------------------------
    // TECLAS
    // Con el foco en un campo de texto de IMGUI, las teclas son del
    // campo. GUIUtility.keyboardControl != 0 lo dice para TODOS los
    // paneles (el de VisorQA incluido).
    // ------------------------------------------------------------
    void ManejarTeclas()
    {
        if (GUIUtility.keyboardControl != 0)
        {
            // Foco huerfano: el campo era de este panel y la pestana ya no
            // se dibuja (el usuario cambio de pestana con el foco en X).
            // Sin esto, Supr y Enter quedarian muertos hasta hacer click
            // en la escena. Se suelta en el proximo OnGUI.
            if (focoEnMisCampos && Time.frameCount - frameDibujado > 2)
            {
                soltarFoco = true;
                focoEnMisCampos = false;
            }
            return;
        }
        if (arrastrePendiente) return;

        if (Input.GetKeyDown(KeyCode.Escape))
        {
            if (nodoAncla >= 0) { nodoAncla = -1; Avisar("Barra nueva cancelada."); }
            // En la pestana la seleccion es de VisorQA: Esc aca solo cancela
            // lo propio del editor.
            else if (PanelPropio) Deseleccionar();
        }
        if (Input.GetKeyDown(KeyCode.Delete)) BorrarSeleccion();
        if (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.KeypadEnter))
            Recalcular();
    }

    // ============================================================
    // SELECCION
    // ============================================================
    void SeleccionarNodo(int id)
    {
        Nodo n = visor != null && visor.Modelo != null ? visor.Modelo.NodoPorId(id) : null;
        if (n == null) { Deseleccionar(); return; }
        nodoSel = id; elemSel = -1;
        SincronizarCampos(n);
        AplicarResaltado();
    }

    void SeleccionarElemento(int id)
    {
        Elemento e = visor != null && visor.Modelo != null ? visor.Modelo.ElementoPorId(id) : null;
        if (e == null) { Deseleccionar(); return; }
        elemSel = id; nodoSel = -1;
        AplicarResaltado();
    }

    void Deseleccionar()
    {
        if (arrastrePendiente) TerminarArrastre();
        nodoSel = -1; elemSel = -1; nodoAncla = -1;
        QuitarResaltado();
    }

    void AplicarResaltado()
    {
        QuitarResaltado();
        if (visor == null || !PanelPropio) return;   // con VisorQA resalta VisorQA (uno solo, cian)
        GameObject go = nodoSel >= 0 ? visor.ObjetoDeNodo(nodoSel)
                      : elemSel >= 0 ? visor.ObjetoDeElemento(elemSel) : null;
        if (go == null) return;   // capa apagada o fuera del filtro de piso

        MeshFilter mf = go.GetComponent<MeshFilter>();
        if (mf == null || mf.sharedMesh == null) return;

        GameObject capa = new GameObject("ResalteEditor");
        capa.transform.SetPositionAndRotation(go.transform.position, go.transform.rotation);
        capa.transform.localScale = EscalaDeResalte(mf.sharedMesh, go.transform.lossyScale);
        capa.AddComponent<MeshFilter>().sharedMesh = mf.sharedMesh;
        MeshRenderer mr = capa.AddComponent<MeshRenderer>();
        mr.sharedMaterial = MaterialDeResalte();
        mr.shadowCastingMode = ShadowCastingMode.Off;
        mr.receiveShadows = false;
        resaltes.Add(capa);
    }

    // Un poco mas grande que el objeto, SUMANDO grosor y no multiplicando:
    // un muro de 7.95 m por 1.2 invadiria a los vecinos.
    static Vector3 EscalaDeResalte(Mesh malla, Vector3 s)
    {
        string nombre = malla.name ?? "";
        if (nombre.Contains("Sphere"))
            return s + Vector3.one * Mathf.Max(0.08f, 0.35f * s.x);
        if (nombre.Contains("Cylinder"))   // mide 2 de alto en Y: el largo no se toca
            return new Vector3(s.x + Mathf.Max(0.04f, 0.8f * s.x), s.y,
                               s.z + Mathf.Max(0.04f, 0.8f * s.z));
        return s + Vector3.one * 0.06f;
    }

    Material MaterialDeResalte()
    {
        if (matResaltado != null && colorDelMaterial == colorResaltado) return matResaltado;
        if (matResaltado != null) Destroy(matResaltado);
        matResaltado = new Material(VisorEstructura.ShaderCompatible());
        matResaltado.color = colorResaltado;
        if (matResaltado.HasProperty("_BaseColor")) matResaltado.SetColor("_BaseColor", colorResaltado);
        colorDelMaterial = colorResaltado;
        return matResaltado;
    }

    void QuitarResaltado()
    {
        foreach (GameObject g in resaltes) if (g != null) Destroy(g);
        resaltes.Clear();
    }

    void SincronizarCampos(Nodo n)
    {
        nodoEnCampos = n.id;
        campoX = F(n.x, "0.###");
        campoY = F(n.y, "0.###");
        campoZ = F(n.z, "0.###");
    }

    // ============================================================
    // EDICION DEL MODELO
    // ============================================================
    void MarcarModificado(string motivo)
    {
        modificado = true;
        ultimoMotivo = motivo;
        versionEdicion++;
        if (visor != null)
        {
            // La deformada dibujada ya no corresponde a esta geometria.
            visor.LimpiarDeformada();
            // Indices por id: CONTRATO.md 2.1, despues de toda edicion.
            if (visor.Modelo != null) visor.Modelo.InvalidarIndice();
        }
        // Anexos S3/S4, carga movil y cabecera de VisorQA se enteran aca.
        EventosVisor.AvisarModeloEditado(motivo);
    }

    void Avisar(string txt)
    {
        mensaje = txt;
        mensajeHasta = Time.time + 6f;
        Debug.Log("[editor] " + txt);
    }

    int ProximoIdNodo()
    {
        int m = 0;
        foreach (Nodo n in visor.Modelo.nodos) if (n.id > m) m = n.id;
        return m + 1;
    }

    int ProximoIdElemento()
    {
        int m = 0;
        foreach (Elemento e in visor.Modelo.elementos) if (e.id > m) m = e.id;
        return m + 1;
    }

    void CrearNodo()
    {
        ModeloEstructural M = visor.Modelo;
        // Lo pone en el centro de la vista, a cota 0.
        Vector3 c = camara != null ? camara.centro : Vector3.zero;
        Nodo n = new Nodo {
            id = ProximoIdNodo(),
            x = Rejilla(c.x), y = Rejilla(c.z), z = 0f,
            fijo = false, restricciones = new int[6]
        };
        M.nodos.Add(n);
        MarcarModificado($"crear nodo {n.id}");
        visor.Redibujar();
        SeleccionarNodo(n.id);
        Avisar($"Nodo {n.id} creado. Arrastralo o edita sus coordenadas.");
    }

    void CrearBarra(int n1, int n2, string seccion, string tipo)
    {
        if (n1 == n2) { Avisar("Una barra necesita dos nodos distintos."); return; }

        foreach (Elemento e in visor.Modelo.elementos)
        {
            if ((e.n1 == n1 && e.n2 == n2) || (e.n1 == n2 && e.n2 == n1))
            {
                Avisar($"Ya existe la barra {e.id} entre esos nodos.");
                return;
            }
        }

        Elemento nuevo = new Elemento {
            id = ProximoIdElemento(), n1 = n1, n2 = n2,
            seccion = seccion, tipo = tipo, vecxz = new float[0]
        };
        visor.Modelo.elementos.Add(nuevo);
        MarcarModificado($"crear barra {nuevo.id}");
        visor.Redibujar();
        SeleccionarElemento(nuevo.id);
        Avisar($"Barra {nuevo.id} creada ({n1} -> {n2}). Sin carga asignada: ni peso propio ni losa.");
    }

    void BorrarSeleccion()
    {
        if (elemSel >= 0) BorrarElemento(elemSel);
        else if (nodoSel >= 0) BorrarNodo(nodoSel);
    }

    /// Borra la barra 'id' como el boton "Borrar barra" (con sus cargas
    /// distribuidas), avisa ModeloEditado y redibuja. Inmediato: para la
    /// automatizacion de la M1 (borrar la columna 69 del LT2 desde el exe).
    /// false si no hay modelo o no existe esa barra.
    public bool BorrarElementoPorId(int id)
    {
        AsegurarReferencias();
        if (visor == null || visor.Modelo == null || visor.Modelo.elementos == null) return false;
        if (visor.Modelo.ElementoPorId(id) == null)
        {
            Avisar($"No existe la barra {id}.");
            return false;
        }
        BorrarElemento(id);
        return true;
    }

    void BorrarElemento(int id)
    {
        ModeloEstructural M = visor.Modelo;
        Elemento e = M.ElementoPorId(id);
        if (e == null) { Avisar($"No existe la barra {id}."); return; }
        bool vertical = EsVertical(e);

        M.elementos.RemoveAll(x => x.id == id);
        int cargas = QuitarCargasDeElemento(id);
        if (elemSel == id) Deseleccionar();
        MarcarModificado($"borrar elemento {id}");
        visor.Redibujar();
        Avisar($"Barra {id} borrada" +
               (cargas > 0 ? $" (y {cargas} carga(s) distribuida(s) que la referenciaban)." : ".") +
               (vertical ? " Las cargas nodales de sus nodos (peso propio de columnas y muros "
                           + "en el LT2) quedan aplicadas." : ""));
    }

    void BorrarNodo(int id)
    {
        ModeloEstructural M = visor.Modelo;

        // Las barras que llegaban al nodo dejarian de tener extremo.
        List<int> huerfanas = new List<int>();
        foreach (Elemento e in M.elementos)
            if (e.n1 == id || e.n2 == id) huerfanas.Add(e.id);

        int cargas = 0;
        foreach (int idEl in huerfanas)
        {
            M.elementos.RemoveAll(e => e.id == idEl);
            cargas += QuitarCargasDeElemento(idEl);
            if (elemSel == idEl) Deseleccionar();
        }

        M.nodos.RemoveAll(n => n.id == id);
        cargas += QuitarCargasDeNodo(id);
        LimpiarReferenciasANodo(id);

        if (nodoSel == id) Deseleccionar();
        if (nodoAncla == id) nodoAncla = -1;
        MarcarModificado($"borrar nodo {id}");
        visor.Redibujar();
        Avisar($"Nodo {id} borrado" +
               (huerfanas.Count > 0 ? $", con {huerfanas.Count} barra(s)" : "") +
               (cargas > 0 ? $" y {cargas} carga(s)." : "."));
    }

    int QuitarCargasDeElemento(int idEl)
    {
        int n = 0;
        if (visor.Modelo.casos_de_carga == null) return 0;
        foreach (CasoDeCarga c in visor.Modelo.casos_de_carga)
        {
            if (c.cargas_distribuidas == null) continue;
            n += c.cargas_distribuidas.RemoveAll(x => x.elemento == idEl);
        }
        return n;
    }

    int QuitarCargasDeNodo(int idNodo)
    {
        int n = 0;
        if (visor.Modelo.casos_de_carga == null) return 0;
        foreach (CasoDeCarga c in visor.Modelo.casos_de_carga)
        {
            if (c.cargas_nodales == null) continue;
            n += c.cargas_nodales.RemoveAll(x => x.nodo == idNodo);
        }
        return n;
    }

    // Diafragmas y brazos rigidos tambien apuntan a nodos por id.
    void LimpiarReferenciasANodo(int idNodo)
    {
        ModeloEstructural M = visor.Modelo;

        if (M.brazos_rigidos != null)
            M.brazos_rigidos.RemoveAll(b => b.maestro == idNodo || b.esclavo == idNodo);

        if (M.diafragmas == null) return;
        M.diafragmas.RemoveAll(d => d.nodo_maestro == idNodo);
        foreach (Diafragma d in M.diafragmas)
        {
            if (d.nodos == null) continue;
            List<int> quedan = new List<int>();
            foreach (int nid in d.nodos) if (nid != idNodo) quedan.Add(nid);
            d.nodos = quedan.ToArray();
        }
    }

    void AplicarCoordenadas()
    {
        Nodo n = visor.Modelo.NodoPorId(nodoEnCampos);
        if (n == null) return;

        float x, y, z;
        bool ok = float.TryParse(campoX, NumberStyles.Float, CultureInfo.InvariantCulture, out x)
                & float.TryParse(campoY, NumberStyles.Float, CultureInfo.InvariantCulture, out y)
                & float.TryParse(campoZ, NumberStyles.Float, CultureInfo.InvariantCulture, out z);
        if (!ok) { Avisar("Coordenadas invalidas. Usa punto decimal."); return; }
        if (x == n.x && y == n.y && z == n.z) { Avisar($"Nodo {n.id}: sin cambios."); return; }

        n.x = x; n.y = y; n.z = z;
        MarcarModificado($"coordenadas del nodo {n.id}");
        visor.Redibujar();
        Avisar($"Nodo {n.id} en ({F(x, "0.###")}, {F(y, "0.###")}, {F(z, "0.###")}). Enter para recalcular.");
    }

    void CambiarRestricciones(int idNodo, int[] r)
    {
        Nodo n = visor.Modelo.NodoPorId(idNodo);
        if (n == null || r == null || r.Length != 6) return;
        n.restricciones = (int[])r.Clone();
        // 'fijo' manda solo si 'restricciones' viene vacio (servidor): se
        // deja coherente para quien lo lea (VisorQA, el dibujo del apoyo).
        n.fijo = Array.TrueForAll(r, v => v == 1);
        MarcarModificado($"restricciones del nodo {idNodo}");
        visor.Redibujar();
        Avisar($"Nodo {idNodo}: {DescribirRestricciones(r)}. Enter para recalcular.");
    }

    void CambiarSeccion(int idElemento, string seccion)
    {
        Elemento e = visor.Modelo.ElementoPorId(idElemento);
        if (e == null || e.seccion == seccion) return;
        string antes = e.seccion;
        e.seccion = seccion;
        MarcarModificado($"seccion del elemento {idElemento}: {antes} -> {seccion}");
        // Antes no se redibujaba: el muro o el perfil seguian con el tamano viejo.
        visor.Redibujar();
        Avisar($"Barra {idElemento}: {antes} -> {seccion}. El peso propio va horneado "
               + "en las cargas: no cambia.");
    }

    void Recalcular()
    {
        AsegurarReferencias();
        if (analizador == null)
        {
            Avisar("No hay AnalizadorEstructural en la escena.");
            return;
        }
        if (analizador.Ocupado) { Avisar("Ya hay un analisis en curso."); return; }

        int version = versionEdicion;
        bool salio = analizador.Analizar(ok =>
        {
            // Solo si nadie edito mientras el servidor resolvia.
            if (ok && version == versionEdicion) modificado = false;
        });
        if (salio) Avisar("Modelo enviado al servidor.");
    }

    void GuardarJSON()
    {
        string ruta = Path.Combine(Application.persistentDataPath, "modelo_editado.json");
        try
        {
            File.WriteAllText(ruta, JsonUtility.ToJson(visor.Modelo, true));
            rutaGuardado = ruta;
            Debug.Log("Modelo guardado en: " + ruta);
            Avisar("Modelo guardado.");
        }
        catch (Exception ex)
        {
            Avisar("No pude guardar " + ruta + ": " + ex.Message);
        }
    }

    // ============================================================
    // CONSULTAS DE DATOS (sin calculo: etiquetas y listas)
    // ============================================================
    bool EsVertical(Elemento e)
    {
        if (e.tipo == "columna" || e.tipo == "muro") return true;
        Nodo a = visor.Modelo.NodoPorId(e.n1), b = visor.Modelo.NodoPorId(e.n2);
        if (a == null || b == null) return false;
        return Mathf.Abs(b.z - a.z) > Mathf.Max(Mathf.Abs(b.x - a.x), Mathf.Abs(b.y - a.y));
    }

    // Etiqueta sugerida. El servidor igual decide por la GEOMETRIA,
    // no por esta etiqueta; si no calzan, avisa en 'avisos'.
    string TipoSegunGeometria(int a, int b)
    {
        Nodo na = visor.Modelo.NodoPorId(a);
        Nodo nb = visor.Modelo.NodoPorId(b);
        if (na == null || nb == null) return "viga_x";

        float dx = Mathf.Abs(nb.x - na.x);
        float dy = Mathf.Abs(nb.y - na.y);
        float dz = Mathf.Abs(nb.z - na.z);

        if (dz > dx && dz > dy) return "columna";
        return dx >= dy ? "viga_x" : "viga_y";
    }

    // viga_x y viga_y son la misma familia para elegir seccion.
    static string Familia(string tipo)
    {
        if (string.IsNullOrEmpty(tipo)) return "";
        if (tipo.StartsWith("viga")) return "vigas";
        if (tipo == "columna") return "columnas";
        if (tipo == "muro") return "muros";
        return tipo;
    }

    // Las secciones que ya usa alguna barra de la misma familia (en el
    // orden del modelo), mas la actual. 13 botones del LT2 o 47 del
    // conjunto en una fila no se leian. Si la familia tiene una sola
    // seccion (las columnas del LT2), se muestran todas.
    List<string> SeccionesPara(ModeloEstructural M, string tipo, string actual)
    {
        string clave = $"{tipo}|{actual}|{soloFamilia}|{versionEdicion}|{M.elementos.Count}";
        if (clave == claveSecciones) return seccionesCache;
        claveSecciones = clave;

        List<string> todas = new List<string>();
        if (M.secciones != null) foreach (Seccion s in M.secciones) todas.Add(s.nombre);

        string familia = Familia(tipo);
        HashSet<string> usadas = new HashSet<string>();
        foreach (Elemento e in M.elementos)
            if (Familia(e.tipo) == familia && !string.IsNullOrEmpty(e.seccion)) usadas.Add(e.seccion);
        if (!string.IsNullOrEmpty(actual)) usadas.Add(actual);

        List<string> deFamilia = new List<string>();
        foreach (string s in todas) if (usadas.Contains(s)) deFamilia.Add(s);

        familiaUtil = deFamilia.Count > 1 && deFamilia.Count < todas.Count;
        seccionesCache = (soloFamilia && familiaUtil) ? deFamilia : todas;
        return seccionesCache;
    }

    static int[] RestriccionesDe(Nodo n)
    {
        // Vacio o ausente -> manda 'fijo' (ModeloEstructural.cs, servidor).
        if (n.restricciones == null || n.restricciones.Length != 6)
            return n.fijo ? new int[] { 1, 1, 1, 1, 1, 1 } : new int[6];
        return (int[])n.restricciones.Clone();
    }

    static string DescribirRestricciones(int[] r)
    {
        if (Array.TrueForAll(r, v => v == 1)) return "empotrado";
        if (Array.TrueForAll(r, v => v == 0)) return "libre";
        List<string> fijos = new List<string>();
        for (int i = 0; i < 6; i++) if (r[i] == 1) fijos.Add(GDL[i]);
        return "fijos: " + string.Join(" ", fijos.ToArray());
    }

    static string F(float v, string formato)
    {
        return v.ToString(formato, CultureInfo.InvariantCulture);
    }

    static string Mm(float metros)
    {
        return F(metros * 1000f, "0.####");
    }

    // ============================================================
    // PANEL
    // ============================================================
    void OnGUI()
    {
        Event ev = Event.current;
        if (soltarFoco) { GUIUtility.keyboardControl = 0; soltarFoco = false; }
        if (ev != null && GUIUtility.keyboardControl != 0)
        {
            // Click en la escena: el campo de texto suelta el foco (IMGUI no
            // lo suelta solo), y Supr/Enter vuelven a ser del editor.
            if (ev.type == EventType.MouseDown && !MouseSobreAlgunaUI())
                GUIUtility.keyboardControl = 0;
            else if (ev.type == EventType.KeyDown && ev.keyCode == KeyCode.Escape)
                GUIUtility.keyboardControl = 0;
        }

        // En la pestana de VisorQA no se dibuja nada propio.
        if (!PanelPropio) return;
        if (visor == null || visor.Modelo == null) return;

        PanelUI.Preparar();
        GUILayout.BeginArea(RectPanel(), PanelUI.Caja);
        scrollPanel = GUILayout.BeginScrollView(scrollPanel);
        DibujarCuerpo();
        GUILayout.EndScrollView();
        GUILayout.EndArea();
    }

    /// El contenido de la pestana "Modificar". Solo GUILayout, sin area ni
    /// scroll propios: lo pone VisorQA.
    public void DibujarPanel()
    {
        PanelUI.Preparar();   // no-op si VisorQA ya lo llamo en este OnGUI
        if (visor == null || visor.Modelo == null)
        {
            GUILayout.Label("Sin modelo cargado.", Est(PanelUI.Tenue));
            return;
        }
        DibujarCuerpo();
    }

    static GUIStyle Est(GUIStyle s) { return s ?? GUI.skin.label; }
    static GUIStyle Bot(GUIStyle s) { return s ?? GUI.skin.button; }

    void AsegurarEstilos()
    {
        if (PanelUI.Texto == null) return;
        if (ReferenceEquals(baseEstilos, PanelUI.Texto) && estiloCampo != null) return;
        baseEstilos = PanelUI.Texto;   // PanelUI.Preparar crea estilos nuevos al cambiar la escala

        estiloCampo = new GUIStyle(GUI.skin.textField);
        estiloCampo.fontSize = baseEstilos.fontSize;

        estiloCasilla = new GUIStyle(PanelUI.Casilla ?? GUI.skin.toggle);   // casilla escalada
        estiloCasilla.fontSize = baseEstilos.fontSize;
        estiloCasilla.normal.textColor = PanelUI.ColorTexto;
        estiloCasilla.onNormal.textColor = PanelUI.ColorTexto;
        estiloCasilla.hover.textColor = PanelUI.ColorTexto;
        estiloCasilla.onHover.textColor = PanelUI.ColorTexto;

        // PanelUI.NoPasa no parte lineas: un error largo se saldria del panel.
        estiloError = new GUIStyle(baseEstilos);
        estiloError.normal.textColor = PanelUI.ColorNoPasa;
        estiloError.hover.textColor = PanelUI.ColorNoPasa;
    }

    void DibujarCuerpo()
    {
        AsegurarEstilos();
        ModeloEstructural M = visor.Modelo;
        Event ev = Event.current;
        if (ev != null && ev.type == EventType.Repaint)
        {
            frameDibujado = Time.frameCount;
            focoEnMisCampos = GUI.GetNameOfFocusedControl().StartsWith(PREFIJO_CAMPO);
        }

        GUILayout.Label("MODIFICAR EL MODELO", Est(PanelUI.Titulo));
        GUILayout.Label($"{M.nodos.Count} nodos   {M.elementos.Count} barras   "
                        + $"{(M.secciones != null ? M.secciones.Count : 0)} secciones",
                        Est(PanelUI.Tenue));
        // Dentro del panel de VisorQA la cabecera ya dice que el modelo se
        // edito (y si lo que se ve es el reanalisis): repetirlo aca eran tres
        // avisos naranjos iguales. Solo con panel propio.
        if (modificado && PanelPropio)
            GUILayout.Label("Modificado (" + ultimoMotivo + "): los resultados precalculados "
                            + "ya no corresponden. Enter para recalcular.", Est(PanelUI.Aviso));
        if (Time.time < mensajeHasta && mensaje.Length > 0)
            GUILayout.Label(mensaje, Est(PanelUI.Texto));

        if (PanelUI.Plegable("editor.reanalisis", "Reanalisis en el servidor", true))
            DibujarReanalisis();

        if (PanelUI.Plegable("editor.seleccion", "Seleccion", true))
        {
            Nodo n = nodoSel >= 0 ? M.NodoPorId(nodoSel) : null;
            Elemento e = elemSel >= 0 ? M.ElementoPorId(elemSel) : null;
            if (n != null) PanelNodo(M, n);
            else if (e != null) PanelElemento(M, e);
            else GUILayout.Label("Nada seleccionado. Haz click en un nodo o una barra.",
                                 Est(PanelUI.Tenue));
        }

        if (PanelUI.Plegable("editor.crear", "Crear y guardar", false))
        {
            GUILayout.BeginHorizontal();
            if (GUILayout.Button("Nodo nuevo", Bot(PanelUI.Boton))) pendientes.Add(CrearNodo);
            if (GUILayout.Button("Guardar JSON", Bot(PanelUI.Boton))) pendientes.Add(GuardarJSON);
            GUILayout.EndHorizontal();
            if (rutaGuardado.Length > 0)
                GUILayout.Label("Guardado en: " + rutaGuardado, Est(PanelUI.Tenue));
        }

        // Capas y deformada son de VisorQA; aca solo si no hay VisorQA.
        if (PanelPropio && PanelUI.Plegable("editor.capas", "Capas", false))
            PanelCapas();

        if (PanelUI.Plegable("editor.controles", "Controles", false))
        {
            GUILayout.Label("Click en un nodo o barra: seleccionar\n"
                          + "Arrastrar el nodo seleccionado: mover en planta"
                          + (pasoRejilla > 0f ? $" (paso {F(pasoRejilla, "0.###")} m)" : "") + "\n"
                          + "Shift + arrastrar: mover en altura\n"
                          + "Esc: cancelar barra nueva / deseleccionar\n"
                          + "Supr: borrar lo seleccionado   Enter: recalcular\n"
                          + "Supr y Enter no actuan con el foco en un campo de texto.",
                          Est(PanelUI.Tenue));
        }
    }

    void DibujarReanalisis()
    {
        if (analizador == null)
        {
            GUILayout.Label("No hay AnalizadorEstructural en la escena.", Est(PanelUI.Aviso));
            return;
        }
        AnalizadorEstructural A = analizador;
        bool libre = !A.Ocupado;

        GUILayout.Label("Servidor (URL de /analizar)", Est(PanelUI.Tenue));
        GUI.enabled = libre;
        GUI.SetNextControlName(PREFIJO_CAMPO + "url");
        A.urlServidor = GUILayout.TextField(A.urlServidor ?? "", estiloCampo ?? GUI.skin.textField);
        GUILayout.BeginHorizontal();
        GUI.enabled = !A.ProbandoServidor;
        if (GUILayout.Button("Probar conexion", Bot(PanelUI.Boton))) pendientes.Add(A.ProbarServidor);   // diferido: la corrutina llena EstadoPing antes de su yield y el Label de abajo saldria en el MouseUp sin estar en el Layout
        GUI.enabled = libre;
        if (GUILayout.Button("localhost", Bot(PanelUI.Boton)))
        {
            A.urlServidor = AnalizadorEstructural.URL_POR_DEFECTO;
            GUIUtility.keyboardControl = 0;
        }
        GUILayout.EndHorizontal();
        GUI.enabled = true;
        if (!string.IsNullOrEmpty(A.EstadoPing))
            GUILayout.Label(A.EstadoPing, Est(PanelUI.Tenue));

        GUI.enabled = libre;
        if (GUILayout.Button(libre ? "Recalcular en el servidor  (Enter)" : "Analizando...",
                             Bot(PanelUI.BotonActivo)))
            pendientes.Add(Recalcular);
        GUI.enabled = true;

        GUILayout.Label(A.Estado ?? "", Est(PanelUI.Texto));
        if (!string.IsNullOrEmpty(A.UltimoError))
            GUILayout.Label(A.UltimoError, estiloError ?? GUI.skin.label);
        if (A.Avisos != null && A.Avisos.Count > 0)
            GUILayout.Label($"{A.Avisos.Count} aviso(s) del servidor (etiqueta 'tipo' que no "
                            + "calza con la geometria; detalle en la consola).", Est(PanelUI.Tenue));

        List<string> casos = A.CasosDisponibles();
        if (casos.Count == 0) return;

        if (A.Desactualizado)
            GUILayout.Label("Estos resultados son del modelo ANTES de la ultima edicion.",
                            Est(PanelUI.Aviso));

        GUILayout.Label("Caso mostrado (deformada y valores de la seleccion):", Est(PanelUI.Tenue));
        PanelUI.Marcar("editor.caso_mostrado");   // CapturaSemana05 lleva el scroll hasta aca
        // Con el modelo editado, dibujar un caso viejo pondria desplazamientos
        // de otra geometria sobre la nueva.
        GUI.enabled = libre && !A.Desactualizado;
        GUILayout.BeginHorizontal();
        int enFila = 0;
        foreach (string c in casos)
        {
            if (enFila == 4) { GUILayout.EndHorizontal(); GUILayout.BeginHorizontal(); enFila = 0; }
            string nombre = c;
            if (PanelUI.Opcion(c == A.casoActivo, c))
                pendientes.Add(() => A.MostrarCaso(nombre));
            enFila++;
        }
        GUILayout.EndHorizontal();
        GUI.enabled = true;
        GUILayout.Label("Q, EX y EY salen del modelo del visor; pueden no coincidir con "
                        + "los del anexo de la Semana 4.", Est(PanelUI.Tenue));

        CasoResultado cr = A.CasoMostrado;
        if (cr != null)
        {
            PanelUI.Fila("Max. componente", Mm(cr.max_desplazamiento) + " mm");
            if (AnalizadorEstructural.TieneEquilibrio(cr))
            {
                GUILayout.Label(AnalizadorEstructural.TablaEquilibrio(cr), Est(PanelUI.Mono));
                GUILayout.Label(AnalizadorEstructural.NotaEquilibrio(cr), Est(PanelUI.Tenue));
            }
            else
            {
                GUILayout.Label(AnalizadorEstructural.NotaEquilibrio(cr), Est(PanelUI.Aviso));
            }
        }

        if (!string.IsNullOrEmpty(A.ExcelReanalisis))
        {
            if (GUILayout.Button("Abrir Excel de este reanalisis", Bot(PanelUI.Boton)))
            {
                string error;
                if (!LectorStreaming.AbrirArchivo(A.ExcelReanalisis, out error)) Avisar(error);
            }
            GUILayout.Label(A.ExcelReanalisis, Est(PanelUI.Tenue));
        }
        if (!string.IsNullOrEmpty(A.ExcelError))
            GUILayout.Label("Sin Excel: " + A.ExcelError, Est(PanelUI.Tenue));
    }

    void PanelCapas()
    {
        bool nN = GUILayout.Toggle(visor.verNodos, "Nodos", estiloCasilla ?? GUI.skin.toggle);
        bool nA = GUILayout.Toggle(visor.verNodosAuxiliares, "Nodos auxiliares", estiloCasilla ?? GUI.skin.toggle);
        bool nC = GUILayout.Toggle(visor.verColumnas, "Columnas", estiloCasilla ?? GUI.skin.toggle);
        bool nV = GUILayout.Toggle(visor.verVigas, "Vigas", estiloCasilla ?? GUI.skin.toggle);
        bool nM = GUILayout.Toggle(visor.verMuros, "Muros", estiloCasilla ?? GUI.skin.toggle);
        bool nB = GUILayout.Toggle(visor.verBrazos, "Brazos", estiloCasilla ?? GUI.skin.toggle);

        GUI.enabled = visor.HayDeformada;
        bool nD = GUILayout.Toggle(visor.mostrarDeformada,
                                   "Deformada  x" + F(visor.factorEscala, "0"),
                                   estiloCasilla ?? GUI.skin.toggle);
        GUI.enabled = true;
        // Sin desplazamientos el toggle no puede hacer nada: se dice por que.
        if (!visor.HayDeformada)
            GUILayout.Label("Sin deformada: editaste el modelo o no hay analisis. Enter para recalcular.",
                            Est(PanelUI.Tenue));

        if (nN != visor.verNodos || nA != visor.verNodosAuxiliares || nC != visor.verColumnas
            || nV != visor.verVigas || nM != visor.verMuros || nB != visor.verBrazos
            || nD != visor.mostrarDeformada)
        {
            pendientes.Add(() =>
            {
                visor.verNodos = nN; visor.verNodosAuxiliares = nA; visor.verColumnas = nC;
                visor.verVigas = nV; visor.verMuros = nM; visor.verBrazos = nB;
                visor.mostrarDeformada = nD;
                visor.Redibujar();
            });
        }
    }

    void PanelNodo(ModeloEstructural M, Nodo n)
    {
        GUILayout.Label($"Nodo {n.id}", Est(PanelUI.Texto));

        // Resultado del ultimo analisis, si lo hay. Arriba, antes de los
        // campos para editar: es lo que se busca al seleccionar un nodo
        // despues de recalcular (quedaba bajo X/Y/Z y las restricciones).
        if (analizador != null)
        {
            DespNodo d = analizador.DesplazamientoDe(n.id);
            if (d != null)
            {
                GUILayout.Label($"Caso {analizador.casoActivo}"
                                + (analizador.Desactualizado ? " (modelo antes de editar)" : "") + ":",
                                Est(PanelUI.Tenue));
                GUILayout.Label($"UX {Mm(d.ux)} mm\n"
                              + $"UY {Mm(d.uy)} mm\n"
                              + $"UZ {Mm(d.uz)} mm", Est(PanelUI.Texto));
            }
        }

        if (nodoEnCampos != n.id) SincronizarCampos(n);

        // Enter con el foco en X, Y o Z = aplicar (y soltar el foco, para
        // que el siguiente Enter recalcule). Se mira ANTES de dibujar los
        // campos, que podrian consumir el evento.
        Event ev = Event.current;
        if (ev != null && ev.type == EventType.KeyDown
            && (ev.keyCode == KeyCode.Return || ev.keyCode == KeyCode.KeypadEnter)
            && GUI.GetNameOfFocusedControl().StartsWith(PREFIJO_CAMPO + "coord"))
        {
            pendientes.Add(AplicarCoordenadas);
            GUIUtility.keyboardControl = 0;
            ev.Use();
        }

        GUILayout.BeginHorizontal();
        GUIStyle campo = estiloCampo ?? GUI.skin.textField;
        float anchoEtiqueta = PanelUI.Px(14f);
        GUILayout.Label("X", Est(PanelUI.Tenue), GUILayout.Width(anchoEtiqueta));
        GUI.SetNextControlName(PREFIJO_CAMPO + "coordX");
        campoX = GUILayout.TextField(campoX, campo);
        GUILayout.Label("Y", Est(PanelUI.Tenue), GUILayout.Width(anchoEtiqueta));
        GUI.SetNextControlName(PREFIJO_CAMPO + "coordY");
        campoY = GUILayout.TextField(campoY, campo);
        GUILayout.Label("Z", Est(PanelUI.Tenue), GUILayout.Width(anchoEtiqueta));
        GUI.SetNextControlName(PREFIJO_CAMPO + "coordZ");
        campoZ = GUILayout.TextField(campoZ, campo);
        GUILayout.EndHorizontal();
        if (GUILayout.Button("Aplicar coordenadas", Bot(PanelUI.Boton))) pendientes.Add(AplicarCoordenadas);

        // --- Restricciones: una casilla por GDL. Antes era 'Empotrado (los
        //     6 GDL)', que al tocarlo pisaba un vector parcial [0 0 1 1 1 0]
        //     (el de los maestros de diafragma del LT2) con todo 1 o todo 0.
        GUILayout.Label("Restricciones (marcado = fijo): " + DescribirRestricciones(RestriccionesDe(n)),
                        Est(PanelUI.Tenue));
        int[] r = RestriccionesDe(n);
        int[] nuevo = (int[])r.Clone();
        GUIStyle casilla = estiloCasilla ?? GUI.skin.toggle;
        for (int fila = 0; fila < 2; fila++)
        {
            GUILayout.BeginHorizontal();
            for (int i = fila * 3; i < fila * 3 + 3; i++)
                nuevo[i] = GUILayout.Toggle(r[i] == 1, GDL[i], casilla) ? 1 : 0;
            GUILayout.EndHorizontal();
        }
        GUILayout.BeginHorizontal();
        if (GUILayout.Button("Empotrar", Bot(PanelUI.Boton))) nuevo = new int[] { 1, 1, 1, 1, 1, 1 };
        if (GUILayout.Button("Liberar", Bot(PanelUI.Boton))) nuevo = new int[6];
        GUILayout.EndHorizontal();
        bool cambio = false;
        for (int i = 0; i < 6; i++) if (nuevo[i] != r[i]) cambio = true;
        if (cambio)
        {
            int id = n.id;
            int[] valores = nuevo;
            pendientes.Add(() => CambiarRestricciones(id, valores));
        }

        // --- Barra nueva desde este nodo ---
        if (nodoAncla < 0)
        {
            if (GUILayout.Button("Empezar barra desde aqui", Bot(PanelUI.Boton))) nodoAncla = n.id;
        }
        else if (nodoAncla == n.id)
        {
            GUILayout.Label("Ahora selecciona el otro nodo.", Est(PanelUI.Texto));
            if (GUILayout.Button("Cancelar", Bot(PanelUI.Boton))) nodoAncla = -1;
        }
        else
        {
            int a = nodoAncla, b = n.id;
            string tipo = TipoSegunGeometria(a, b);
            GUILayout.Label($"Unir {a} con {b} ({tipo}). Seccion:", Est(PanelUI.Texto));
            string elegida = GrillaSecciones(M, tipo, null);
            if (elegida != null)
                pendientes.Add(() => { CrearBarra(a, b, elegida, tipo); nodoAncla = -1; });
            if (GUILayout.Button("Cancelar", Bot(PanelUI.Boton))) nodoAncla = -1;
        }

        if (GUILayout.Button("Borrar nodo  (Supr)", Bot(PanelUI.Boton)))
        {
            int id = n.id;
            pendientes.Add(() => BorrarNodo(id));
        }
    }

    // Grilla de secciones de 3 columnas (2 si los nombres son largos).
    // Devuelve la elegida en este evento, o null.
    string GrillaSecciones(ModeloEstructural M, string tipo, string actual)
    {
        List<string> nombres = SeccionesPara(M, tipo, actual);
        if (nombres.Count == 0)
        {
            GUILayout.Label("El modelo no trae secciones.", Est(PanelUI.Tenue));
            return null;
        }
        if (familiaUtil || !soloFamilia)
        {
            bool nuevo = GUILayout.Toggle(soloFamilia, "Solo las de " + Familia(tipo),
                                          estiloCasilla ?? GUI.skin.toggle);
            if (nuevo != soloFamilia) pendientes.Add(() => soloFamilia = nuevo);
        }

        int largo = 0;
        foreach (string s in nombres) largo = Mathf.Max(largo, s.Length);
        int columnas = largo > 12 ? 2 : 3;
        int indice = actual != null ? nombres.IndexOf(actual) : -1;
        int elegido = GUILayout.SelectionGrid(indice, nombres.ToArray(), columnas, Bot(PanelUI.Boton));
        return (elegido >= 0 && elegido != indice) ? nombres[elegido] : null;
    }

    void PanelElemento(ModeloEstructural M, Elemento e)
    {
        GUILayout.Label($"Barra {e.id}   nodos {e.n1} -> {e.n2}", Est(PanelUI.Texto));
        GUILayout.Label($"tipo: {e.tipo}   seccion: {e.seccion}", Est(PanelUI.Tenue));

        // Esfuerzos del ultimo analisis, en EJES LOCALES.
        if (analizador != null)
        {
            FuerzaElemento f = analizador.FuerzaDe(e.id);
            if (f != null && f.f != null && f.f.Length >= 12)
            {
                GUILayout.Label($"Esfuerzos, caso {analizador.casoActivo} (ejes locales, localForce)"
                                + (analizador.Desactualizado ? ", modelo antes de editar" : "") + ":",
                                Est(PanelUI.Tenue));
                GUILayout.Label($"N  {F(f.N_i, "0.###")} kN\n"
                              + $"Vz {F(f.Vz_i, "0.###")} kN\n"
                              + $"My {F(f.My_i, "0.###")} / {F(f.My_j, "0.###")} kN*m",
                              Est(PanelUI.Texto));
            }
        }

        if (M.secciones != null && M.secciones.Count > 1
            && PanelUI.Plegable("editor.secciones", "Cambiar seccion", false))
        {
            string elegida = GrillaSecciones(M, e.tipo, e.seccion);
            if (elegida != null)
            {
                int id = e.id;
                pendientes.Add(() => CambiarSeccion(id, elegida));
            }
            GUILayout.Label("El peso propio va horneado en las cargas (w = A*gamma + q*A/L en "
                            + "las vigas, carga nodal en columnas y muros): cambiar la seccion "
                            + "cambia la rigidez, no el peso.", Est(PanelUI.Tenue));
        }

        if (GUILayout.Button("Borrar barra  (Supr)", Bot(PanelUI.Boton)))
        {
            int id = e.id;
            pendientes.Add(() => BorrarElemento(id));
        }
        if (EsVertical(e))
            GUILayout.Label("Al borrarla, las cargas nodales de sus nodos (peso propio de "
                            + "columnas y muros en el LT2) quedan aplicadas: Unity no recalcula cargas.",
                            Est(PanelUI.Tenue));
    }
}
