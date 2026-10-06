/*
================================================================
  CamaraOrbital.cs
================================================================
  Camara que orbita alrededor del modelo, con zoom y paneo.
  Sin esto la camara de Unity queda fija donde la dejaste y no se
  puede inspeccionar nada durante el Play.

  CONTROLES (mouse)
    Click izquierdo + arrastrar ..... orbitar
    Click derecho / medio + arrastrar  panear
    Rueda ........................... zoom
    F ............................... encuadrar todo el modelo
    (el click izquierdo sobre un objeto lo SELECCIONA; solo orbita
     si arrastras, para que ambas cosas convivan)

  CONTROLES (tactil: telefono, tablet, pantalla tactil)
    Un dedo arrastrado .............. orbitar
    Dos dedos, pinza ................ zoom
    Dos dedos, arrastrados juntos ... panear
    (un toque sin arrastrar selecciona, igual que el click)

  QUE ESCUCHA (semana05/CONTRATO.md)
    EventosVisor.ModeloCargado  -> EncuadrarTodo: el modelo llega por
                                   UnityWebRequest frames despues de
                                   Start, y antes no hay que encuadrar.
    EventosVisor.PedirCentrar   -> centra en un punto ("Ir a ID", lista
                                   de criticos, carga movil).

  USO
    1. Selecciona la 'Main Camera' de la escena.
    2. Add Component -> CamaraOrbital.
    3. Arrastra el objeto 'Visor' al campo 'visor' (opcional: si no,
       lo busca).

  OJO: los campos privados 'pitch' y 'yaw' los lee y escribe
  CapturaSemana04 por reflexion. No renombrarlos ni cambiarles el tipo.
================================================================
*/

using UnityEngine;

[RequireComponent(typeof(Camera))]
public class CamaraOrbital : MonoBehaviour
{
    [Header("Objetivo")]
    public Vector3 centro = Vector3.zero;
    public float distancia = 14f;

    [Tooltip("Opcional: para encuadrar el modelo automaticamente al cargar.")]
    public VisorEstructura visor;

    [Header("Sensibilidad")]
    public float velocidadOrbita = 4f;
    public float velocidadPaneo = 0.012f;
    public float velocidadZoom = 4f;
    [Tooltip("Grados que gira la camara al recorrer con un dedo el lado "
           + "corto de la pantalla.")]
    public float gradosPorPantallaTactil = 180f;

    [Header("Limites")]
    public float distanciaMin = 1.5f;
    public float distanciaMax = 300f;

    // Angulos en grados: yaw alrededor del eje vertical, pitch sobre el horizonte.
    // CapturaSemana04 los fija por reflexion: nombre y tipo quedan.
    private float yaw = 45f;
    private float pitch = 22f;

    // Tope del pitch. 89.9 y no 85: VistaPlanta mira a 89.9 y, con un
    // tope menor, el primer arrastre despues de la planta saltaba 5 grados.
    const float PITCH_MAXIMO = 89.9f;

    // Un arrastre corto se interpreta como click (seleccion), no como orbita.
    private Vector3 posMouseAlPresionar;
    private bool arrastrando = false;

    /// El umbral de antes, en pixeles. Queda por compatibilidad; el que
    /// se usa es PanelUI.UmbralArrastre(), que crece con el dpi (en un
    /// telefono de 400 dpi un dedo quieto se mueve mas de 5 px).
    public const float UMBRAL_ARRASTRE = 5f;   // pixeles

    /// Lo enciende EditorEstructura mientras arrastras un nodo, para que
    /// el mismo boton izquierdo no orbite la camara al mismo tiempo.
    public bool bloqueada = false;

    /// true si el ultimo click (o toque) fue un arrastre real y por lo
    /// tanto NO debe tratarse como seleccion. Lo consultan VisorQA y
    /// EditorEstructura al soltar.
    public bool HuboArrastre { get; private set; }

    // El arrastre empezo sobre la interfaz (la barra de scroll del panel,
    // la ventana P-M, el panel del editor): la camara se queda quieta
    // hasta que se suelte, aunque el cursor salga del panel.
    private bool arrastreSobreUI;
    private VisorQA qa;

    // --- Estado del gesto tactil ---
    // Un gesto va desde que el primer dedo toca hasta que se levanta el
    // ultimo. Si en algun momento hubo dos dedos, el dedo que queda al
    // final NO orbita: al soltar una pinza nunca se levantan los dos en
    // el mismo frame, y la vista se iba de lado.
    private int dedosAntes = 0;
    private bool gestoSobreUI;
    private bool gestoConDosDedos;
    private Vector2 toqueInicial;
    private int dedoA = -1, dedoB = -1;
    private Vector2 medioAntes;
    private float separacionAntes;

    /// Si el cursor (o el dedo: Unity simula el mouse con el primer
    /// toque) esta sobre algun panel. Lo sabe VisorQA, que es quien los
    /// dibuja; aca solo se pregunta.
    bool SobreUI()
    {
        if (qa == null) qa = FindAnyObjectByType<VisorQA>();
        return qa != null && qa.MouseSobreUI();
    }

    void OnEnable()
    {
        EventosVisor.ModeloCargado += AlCargarModelo;
        EventosVisor.PedirCentrar += AlPedirCentrar;
    }

    void OnDisable()
    {
        EventosVisor.ModeloCargado -= AlCargarModelo;
        EventosVisor.PedirCentrar -= AlPedirCentrar;
    }

    void Start()
    {
        // Si el visor ya cargo (llegamos tarde al evento), se encuadra
        // ahora; si no, lo hara AlCargarModelo. La F manual siempre queda.
        if (visor == null) visor = FindAnyObjectByType<VisorEstructura>();
        if (visor != null && visor.Listo) EncuadrarTodo();
        Aplicar();
    }

    void AlCargarModelo()
    {
        EncuadrarTodo();
        Aplicar();
    }

    /// Centra en 'punto' (coordenadas Unity). Con tamano > 0 acerca o
    /// aleja para que algo de 'tamano' metros quepa con aire alrededor;
    /// con tamano <= 0 deja el zoom como esta.
    void AlPedirCentrar(Vector3 punto, float tamano)
    {
        centro = punto;
        if (tamano > 0f)
            distancia = Mathf.Clamp(DistanciaParaVer(tamano * 0.5f) * 2f,
                                    distanciaMin, distanciaMax);
        Aplicar();
    }

    void LateUpdate()
    {
        if (bloqueada)
        {
            Aplicar();
            return;
        }

        // Con dedos en la pantalla manda el tactil. Unity ademas simula
        // el mouse con el primer dedo: si tambien corriera la rama del
        // mouse, un dedo orbitaria dos veces y la pinza panearia.
        if (Input.touchCount > 0 || dedosAntes > 0)
        {
            ManejarTactil();
            Aplicar();
            return;
        }

        // Un arrastre que NACE sobre la interfaz no es para la camara.
        bool algunBoton = Input.GetMouseButton(0) || Input.GetMouseButton(1)
                          || Input.GetMouseButton(2);
        if (Input.GetMouseButtonDown(0) || Input.GetMouseButtonDown(1)
            || Input.GetMouseButtonDown(2))
            arrastreSobreUI = SobreUI();
        if (!algunBoton) arrastreSobreUI = false;
        if (arrastreSobreUI)
        {
            Aplicar();
            return;
        }

        // --- Orbitar ---
        if (Input.GetMouseButtonDown(0))
        {
            posMouseAlPresionar = Input.mousePosition;
            arrastrando = false;
            HuboArrastre = false;
        }
        if (Input.GetMouseButton(0))
        {
            if (!arrastrando &&
                Vector3.Distance(Input.mousePosition, posMouseAlPresionar) > PanelUI.UmbralArrastre())
            {
                arrastrando = true;
                HuboArrastre = true;
            }
            if (arrastrando)
            {
                yaw += Input.GetAxis("Mouse X") * velocidadOrbita;
                pitch -= Input.GetAxis("Mouse Y") * velocidadOrbita;
                pitch = Mathf.Clamp(pitch, -PITCH_MAXIMO, PITCH_MAXIMO);
            }
        }
        if (Input.GetMouseButtonUp(0)) arrastrando = false;

        // --- Panear ---
        if (Input.GetMouseButton(1) || Input.GetMouseButton(2))
        {
            float f = distancia * velocidadPaneo;
            centro -= transform.right * Input.GetAxis("Mouse X") * f;
            centro -= transform.up * Input.GetAxis("Mouse Y") * f;
        }

        // --- Zoom ---
        // Con el cursor sobre el panel, la rueda es para su scroll.
        float rueda = SobreUI() ? 0f : Input.GetAxis("Mouse ScrollWheel");
        if (Mathf.Abs(rueda) > 0.0001f)
        {
            // Proporcional a la distancia: cerca avanza fino, lejos avanza rapido.
            distancia -= rueda * velocidadZoom * Mathf.Max(1f, distancia * 0.25f);
            distancia = Mathf.Clamp(distancia, distanciaMin, distanciaMax);
        }

        // La F no encuadra mientras se escribe en un campo de texto del
        // panel (un id, una coordenada del editor).
        if (Input.GetKeyDown(KeyCode.F) && GUIUtility.keyboardControl == 0) EncuadrarTodo();

        Aplicar();
    }

    // ============================================================
    // TACTIL
    // ============================================================
    void ManejarTactil()
    {
        int dedos = Input.touchCount;
        if (dedos == 0)
        {
            // Se levanto el ultimo dedo: termina el gesto. HuboArrastre
            // se queda como estaba hasta el proximo toque, que es lo que
            // lee VisorQA al soltar.
            dedosAntes = 0;
            gestoConDosDedos = false;
            gestoSobreUI = false;
            dedoA = dedoB = -1;
            return;
        }

        Touch t0 = Input.GetTouch(0);
        if (dedosAntes == 0)
        {
            // Empieza un gesto.
            gestoSobreUI = SobreUI();
            gestoConDosDedos = false;
            toqueInicial = t0.position;
            HuboArrastre = false;
            dedoA = dedoB = -1;
        }
        if (gestoSobreUI)
        {
            dedosAntes = dedos;
            return;
        }

        if (dedos == 1)
        {
            if (!HuboArrastre && (t0.position - toqueInicial).magnitude > PanelUI.UmbralArrastre())
                HuboArrastre = true;

            // deltaPosition es el movimiento de ESTE dedo desde el frame
            // anterior: no salta aunque antes hubiera otro dedo.
            if (HuboArrastre && !gestoConDosDedos && t0.phase == TouchPhase.Moved)
            {
                float lado = Mathf.Max(1f, Mathf.Min(Screen.width, Screen.height));
                float gradosPorPixel = gradosPorPantallaTactil / lado;
                yaw += t0.deltaPosition.x * gradosPorPixel;
                pitch -= t0.deltaPosition.y * gradosPorPixel;
                pitch = Mathf.Clamp(pitch, -PITCH_MAXIMO, PITCH_MAXIMO);
            }
        }
        else
        {
            gestoConDosDedos = true;
            HuboArrastre = true;

            Touch t1 = Input.GetTouch(1);
            Vector2 medio = (t0.position + t1.position) * 0.5f;
            float separacion = (t0.position - t1.position).magnitude;

            // Solo se mueve si son los MISMOS dos dedos del frame
            // anterior; si cambio el par (entro un tercero, salio uno),
            // se toma la referencia de nuevo en vez de saltar.
            if (t0.fingerId == dedoA && t1.fingerId == dedoB)
            {
                // Pinza: la distancia sigue a la separacion de los dedos.
                if (separacion > 1f && separacionAntes > 1f)
                    distancia = Mathf.Clamp(distancia * separacionAntes / separacion,
                                            distanciaMin, distanciaMax);

                // Paneo: el punto bajo los dedos se queda bajo los dedos.
                Vector2 d = medio - medioAntes;
                float m = MetrosPorPixel();
                centro -= transform.right * d.x * m;
                centro -= transform.up * d.y * m;
            }
            dedoA = t0.fingerId;
            dedoB = t1.fingerId;
            medioAntes = medio;
            separacionAntes = separacion;
        }
        dedosAntes = dedos;
    }

    /// Cuantos metros mide un pixel de pantalla a la distancia del
    /// centro. Con esto un paneo tactil mueve el modelo lo mismo que el
    /// dedo, se este cerca o lejos.
    float MetrosPorPixel()
    {
        Camera cam = GetComponent<Camera>();
        float alto = Mathf.Max(1f, Screen.height);
        if (cam != null && cam.orthographic) return 2f * cam.orthographicSize / alto;
        float fov = cam != null ? cam.fieldOfView : 60f;
        return 2f * distancia * Mathf.Tan(fov * 0.5f * Mathf.Deg2Rad) / alto;
    }

    /// Distancia a la que un radio 'radio' llena el campo de vision mas
    /// estrecho. En una pantalla vertical (telefono) el estrecho es el
    /// horizontal: con solo el vertical el edificio quedaba cortado a los
    /// lados.
    float DistanciaParaVer(float radio)
    {
        Camera cam = GetComponent<Camera>();
        float fov = cam != null ? cam.fieldOfView : 60f;
        float aspecto = cam != null && cam.aspect > 0f ? cam.aspect : 1f;
        float tanV = Mathf.Tan(fov * 0.5f * Mathf.Deg2Rad);
        float tan = Mathf.Min(tanV, tanV * aspecto);
        return radio / Mathf.Max(tan, 1e-3f);
    }

    void Aplicar()
    {
        Quaternion rot = Quaternion.Euler(pitch, yaw, 0f);
        transform.rotation = rot;
        // Corrida de lado, no girada: 'centro' queda en el medio de lo que el
        // panel deja libre (y no detras del panel) y la orbita sigue siendo
        // alrededor de 'centro'. Como solo se mueve la camara, ScreenPointToRay
        // y los clicks siguen calzando.
        transform.position = centro - rot * Vector3.forward * distancia
                             - rot * Vector3.right * CorrimientoPorPanel();
    }

    private float proximaBusquedaQA = 0f;

    /// Metros que la camara se corre a la izquierda para que lo que mira
    /// quede en el centro del hueco a la derecha del panel. Antes F, C e
    /// "Ir a ID" centraban en la pantalla entera y lo mirado quedaba a
    /// 290 px del borde del panel (31 % del ancho a 1600 px); solo las
    /// capturas lo compensaban. Sin panel, o si el panel ocupa mas del 60 %
    /// del ancho (telefono vertical), no se corre.
    float CorrimientoPorPanel()
    {
        if (qa == null && Time.unscaledTime >= proximaBusquedaQA)
        {
            proximaBusquedaQA = Time.unscaledTime + 1f;
            qa = FindAnyObjectByType<VisorQA>();
        }
        if (qa == null || !qa.panelVisible) return 0f;
        float borde = qa.RectPanel().xMax;
        if (borde <= 0f || borde > 0.6f * Mathf.Max(1f, Screen.width)) return 0f;
        return 0.5f * borde * MetrosPorPixel();
    }

    /// Centra y aleja la camara para que quepa todo el modelo.
    public void EncuadrarTodo()
    {
        if (visor == null) visor = FindAnyObjectByType<VisorEstructura>();
        if (visor == null || visor.Modelo == null || visor.Modelo.nodos == null
            || visor.Modelo.nodos.Count == 0) return;

        Bounds b = new Bounds(Ejes.PosicionDe(visor.Modelo.nodos[0]), Vector3.zero);
        foreach (Nodo n in visor.Modelo.nodos) b.Encapsulate(Ejes.PosicionDe(n));

        centro = b.center;
        // Un poco de aire alrededor del modelo, con 60 grados de campo en
        // pantalla horizontal; en una vertical se aleja en la proporcion del
        // aspecto. Radio = el mayor entre la media diagonal en PLANTA y la
        // media altura: con la diagonal 3D y 2.6 (lo de antes) el LT2 usaba
        // el 57 % x 55 % de la zona libre. Con 2.2 la esquina cercana salia
        // cortada por la perspectiva; 2.6 sobre este radio lo deja entero.
        float radio = Mathf.Max(Mathf.Max(new Vector2(b.extents.x, b.extents.z).magnitude, b.extents.y), 1f);
        Camera cam = GetComponent<Camera>();
        float aspecto = cam != null && cam.aspect > 0f ? cam.aspect : 1f;
        distancia = Mathf.Clamp(radio * 2.6f * Mathf.Max(1f, 1f / aspecto),
                                distanciaMin, distanciaMax);
    }

    /// Encuadra un punto concreto sin cambiar el zoom (para "ir al nodo N").
    public void MirarA(Vector3 punto)
    {
        centro = punto;
    }

    // --- Vistas fijas (API de la Semana 5, semana05/CONTRATO.md) ---
    // Solo giran la camara; el centro y el zoom quedan. yaw 0 mira hacia
    // +Z de Unity, que es +Y de OpenSees: se ve el plano XZ del modelo.

    /// Desde arriba.
    public void VistaPlanta() { pitch = PITCH_MAXIMO; yaw = 0f; Aplicar(); }

    /// Elevacion del plano X-Z de OpenSees (mirando hacia +Y).
    public void VistaElevX() { pitch = 0f; yaw = 0f; Aplicar(); }

    /// Elevacion del plano Y-Z de OpenSees (mirando hacia +X).
    public void VistaElevY() { pitch = 0f; yaw = 90f; Aplicar(); }

    /// La vista con que arranca.
    public void VistaIso() { pitch = 22f; yaw = 45f; Aplicar(); }
}
