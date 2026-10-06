/*
================================================================
  AmbienteVisor.cs
================================================================
  El SUELO donde apoya el edificio y la VISTA REALISTA: cielo, luz,
  sombras, hormigon y tierra con textura. Mueve dibujo, no numeros:
  nada de lo que hace este archivo cambia un resultado.

  Se crea solo al cargar la escena (RuntimeInitializeOnLoadMethod) si
  hay un VisorEstructura: no hay que tocar SampleScene ni agregar
  componentes a mano. No expone API: todo entra por EventosVisor y
  AjustesVista (semana05/CONTRATO.md, seccion 2.2 y 8).

  ----------------------------------------------------------------
  LAS DOS VISTAS (AjustesVista.realista)
  ----------------------------------------------------------------
  Tecnica  = la de siempre: colores por tipo, el cielo y la luz de la
             escena. El suelo va en un color mate, sin textura.
  Realista = hormigon y acero con textura (descargada, CC0, o procedural
             si no esta; AmbienteVisor.Recursos.cs), suelo de pasto,
             excavacion de tierra, cielo mas azul (y la luz ambiente que
             sale de el), luz de dia suave con sombras blandas.
  El mapa D/C pinta ENCIMA de las dos (prioridad mapa > realista >
  tecnica): este script cambia sharedMaterial y SIEMPRE termina con
  EventosVisor.AvisarMaterialesCambiados(), que es cuando el mapa
  vuelve a pintar.

  ----------------------------------------------------------------
  EL SUELO
  ----------------------------------------------------------------
  - Va en info.cota_terreno, declarada en el perfil del edificio
    (edificios/lt2/perfiles/lt2_2024_22.json y
    edificios/ingenieria/perfiles/ingenieria_2017_67.json, 'terreno') y
    viaja en el JSON. Unity no la adivina: cada JSON tiene su datum.
  - Desde la Semana 5 los dos cuerpos la ponen DONDE ARRANCA LA
    ESTRUCTURA: el LT2 en -7.97 (16 apoyos, 8 columnas y 8 muros) e
    Ingenieria en su 0.00 local (29 apoyos, 10 columnas), que con el dz
    del calce es el mismo -7.97. Antes el LT2 declaraba -4.01.
  - Sin cota (-9999): el suelo va en el apoyo mas bajo, con un aviso en
    la consola. Es un respaldo de dibujo, no un dato.
  - SIN collider: VisorQA y EditorEstructura seleccionan con un
    Physics.Raycast que se queda con el PRIMER collider. Un suelo con
    collider se comeria el click a todo lo que esta bajo la cota.
  - Con HUECO donde hay estructura bajo la cota: un plano opaco taparia
    los apoyos, que es justo lo que responde "como esta apoyado". El
    hueco lleva paredes de tierra y un fondo, de una sola cara: desde
    afuera se ve la pared del frente del hoyo (detras del edificio) y la
    de adelante no tapa nada; desde abajo el suelo desaparece.
    Con la cota en el arranque NO HAY NADA bajo ella, asi que hoy la
    BASE sale sin hueco en los tres modelos (un solo cuadro de suelo).
  - TERRAZAS (AmbienteVisor.Terrazas.cs): cada nivel de info.terrenos
    sobre la base es una losa de pasto a su z con muros de tierra hasta
    la base; lo que baja bajo su cara se le recorta con la misma
    geometria del hueco (HuecoDelSuelo.CalcularTerraza). Hoy: la de
    Ingenieria, 3.96 local = -4.01 en el conjunto (segundo N.R.).
  - RELIEVE DEL SITIO (AmbienteVisor.Topografia.cs): el terreno natural
    alrededor del edificio, de StreamingAssets/topografia.json (lo arma
    edificios/conjunto/topografia.py). Con el a la vista se apaga el
    plano del suelo; las terrazas siguen.

  ----------------------------------------------------------------
  QUE NO HACE, A PROPOSITO
  ----------------------------------------------------------------
  - Niebla: con la de la escena apagada, el 'fog stripping' automatico
    de la build borra las variantes con niebla. Se veria en el editor y
    no en el exe.
  - Shaders nuevos ni keywords en materiales creados por codigo: solo el
    de VisorEstructura.ShaderCompatible() (URP Lit) sin keywords
    (_NORMALMAP, transparencia), que la build borra. Lo que si los usa
    (texturas con mapa normal, el cielo HDRI, el post-proceso realista)
    viene como ASSET en Resources/Ambiente, armado por
    Editor/RecursosRealistas.cs, y se copia (AmbienteVisor.Recursos.cs):
    asi la build incluye sus variantes. Sin esos assets, lo procedural.
  - Tocar el asset de URP o QualitySettings: en el editor el cambio
    quedaria guardado en disco.
================================================================
*/

using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using UnityEngine.Rendering;

// partial: las losas de dibujo van en AmbienteVisor.Losas.cs.
public partial class AmbienteVisor : MonoBehaviour
{
    // ============================================================
    // CONSTANTES (todas de dibujo)
    // ============================================================

    /// InfoModelo.cota_terreno vale -9999 cuando el JSON no la trae.
    const float SIN_COTA = -9000f;

    /// El suelo va 2 cm BAJO la cota: justo en la cota pelearia en
    /// profundidad con las esferas y barras que nacen ahi (z-fighting).
    const float BAJO_LA_COTA = 0.02f;

    /// Un nodo o una barra "esta en la cota" con esta tolerancia. Mas
    /// holgada que AjustesVista.TOLERANCIA_COTA (0.01) porque la cota
    /// viene de un perfil escrito a mano, no de las z de los nodos.
    const float TOL_EN_COTA = 0.05f;

    /// Tamano de celda del mapa del hueco (m). Las z y las x,y de los
    /// JSON traen 2 decimales, pero el hueco es dibujo: 0.5 m ya calza el
    /// borde con los muros a la vista, y con celdas mas chicas la malla
    /// crece al cuadrado.
    const double CELDA_MIN = 0.5;

    /// Medio lado del suelo (m). La camara se aleja hasta 300 m
    /// (CamaraOrbital.distanciaMax) y corta en 1000 m (far clip de la
    /// escena): 800 m de suelo cubren el encuadre sin llegar al corte.
    const float MEDIO_LADO_SUELO = 800f;

    // Metros por repeticion de cada textura. La del pasto es grande para
    // que el patron no se note desde la distancia de encuadre.
    const float REPETICION_PASTO = 12f;
    const float REPETICION_TIERRA = 3f;
    const float REPETICION_HORMIGON = 1.5f;

    // Las texturas (lado en pixeles). En movil y Web la mitad: se generan
    // en la CPU al primer uso y ocupan 4 bytes por pixel.
    static int LadoTextura { get { return EsPlataformaLiviana() ? 256 : 512; } }

    static bool EsPlataformaLiviana()
    {
        return Application.isMobilePlatform
               || Application.platform == RuntimePlatform.WebGLPlayer;
    }

    // ------------------------------------------------------------
    // Colores (sRGB). Los de hormigon quedan claros: el hormigon a la
    // vista refleja bastante, y las barras finas se leen mejor claras
    // sobre el pasto.
    //
    // La COLUMNA va con un tono salmon suave (pedido de la Semana 5): se
    // distingue de la viga y del muro, que siguen en gris hormigon, sin
    // dejar de leerse como hormigon. Sale de C_VIGA subiendo el rojo y
    // bajando el azul, con la misma luminancia (0.72 contra 0.73 de
    // antes: la pieza no se aclara ni se oscurece, solo se entibia) y con
    // saturacion 0.28, la mitad del salmon de libro (#FA8072, 0.54). La
    // textura de hormigon la multiplica, asi que en pantalla llega mas
    // apagado todavia. Las LOSAS no se tocan: su color es C_LOSA, en
    // AmbienteVisor.Losas.cs. La vista tecnica no cambia: ahi cada
    // renderer vuelve a su material registrado.
    static readonly Color C_COLUMNA = new Color(0.87f, 0.69f, 0.63f);
    static readonly Color C_VIGA = new Color(0.70f, 0.69f, 0.66f);
    static readonly Color C_MURO = new Color(0.78f, 0.77f, 0.73f);
    static readonly Color C_NODO = new Color(0.58f, 0.58f, 0.56f);
    // Acero con anticorrosivo: se distingue del hormigon igual que en la
    // vista tecnica (ahi es rojo), pero con un color que existe.
    static readonly Color C_METAL = new Color(0.50f, 0.31f, 0.27f);

    static readonly Color C_PASTO = Color.white;                 // la textura trae el color
    static readonly Color C_PARED_TIERRA = new Color(0.86f, 0.80f, 0.72f);
    static readonly Color C_FONDO = new Color(0.66f, 0.65f, 0.62f);

    // Vista tecnica: el suelo existe (para saber donde esta el terreno)
    // pero neutro y mate, para no competir con los colores por tipo.
    static readonly Color T_SUELO = new Color(0.78f, 0.80f, 0.76f);
    static readonly Color T_PARED = new Color(0.60f, 0.58f, 0.55f);
    static readonly Color T_FONDO = new Color(0.68f, 0.67f, 0.64f);

    // ============================================================
    // ESTADO
    // ============================================================
    private VisorEstructura visor;

    /// Material TECNICO de cada renderer de la estructura, registrado
    /// en Redibujado (el unico momento en que se sabe que lo es), con lo
    /// que hace falta para elegir su realista. Al cambiar de vista se
    /// aplica desde aca: nunca se lee el material actual, que puede ser
    /// del mapa D/C. El realista se busca al aplicar (no al registrar):
    /// en la vista tecnica no se generan texturas.
    private struct Registro
    {
        public Material tecnico;
        public string categoria;        // null = el tecnico tambien en la realista
        public Vector2Int repeticion;
    }
    private readonly Dictionary<Renderer, Registro> registro = new Dictionary<Renderer, Registro>();

    // Materiales propios, cacheados por clave (tipo y repeticion). Uno
    // por objeto dejaria cientos huerfanos y romperia el SRP Batcher.
    private readonly Dictionary<string, Material> materialesRealistas = new Dictionary<string, Material>();
    private readonly HashSet<Material> misMateriales = new HashSet<Material>();

    private Texture2D texHormigon, texEncofrado, texPasto, texTierra;
    private Material[] matSueloRealista, matSueloTecnico;

    private GameObject suelo;
    private string firmaSuelo;          // para no rehacer la malla si nada cambio

    // Lo que se aplico la ultima vez. Si alguien cambia AjustesVista sin
    // avisar VistaCambio, Update lo nota igual.
    private bool aplicadoRealista;
    private bool aplicadoSuelo;
    private bool hayAplicado = false;

    // El ambiente de la escena, para volver a la vista tecnica tal cual.
    // -1 = nunca aplicado, 0 = tecnico, 1 = realista.
    private int ambienteAplicado = -1;
    private bool ambienteGuardado = false;
    private Light sol;
    private float solIntensidad, solTemperatura, solFuerzaSombra;
    private Color solColor;
    private bool solUsaTemperatura;
    private LightShadows solSombras;
    private Quaternion solRotacion;
    private AmbientMode ambienteModo;
    private Color ambienteCielo, ambienteEcuador, ambienteSuelo;
    private Material cieloOriginal, cieloRealista;
    private Light solOriginalDeRender;

    /// Direccion del sol en la vista realista (Euler, grados). La de la
    /// escena (50, -30, 0) ilumina +X/-Z de Unity, pero la camara mira
    /// desde -X/-Z (VistaIso yaw 45, capturas yaw 35): la cara grande de
    /// los muros quedaba en sombra propia y se veia azul pizarra. Con yaw
    /// 65 el sol queda detras y a la izquierda de la camara: ilumina de
    /// frente las caras -X y de refilon las -Z, que siguen distinguiendose.
    static readonly Vector3 SOL_REALISTA = new Vector3(50f, 65f, 0f);

    // Luz ambiente de la realista, en tres tonos neutros (cielo, horizonte,
    // suelo). Con la del skybox azulado, lo que quedaba en sombra
    // salia azul; asi la sombra queda gris.
    static readonly Color AMB_CIELO = new Color(0.58f, 0.60f, 0.62f);
    static readonly Color AMB_ECUADOR = new Color(0.50f, 0.50f, 0.48f);
    static readonly Color AMB_SUELO = new Color(0.34f, 0.33f, 0.30f);

    // ============================================================
    // CREACION
    // ============================================================
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Crear()
    {
        // Solo donde hay algo que mirar: otras escenas quedan como estan.
        if (FindAnyObjectByType<VisorEstructura>() == null) return;
        if (FindAnyObjectByType<AmbienteVisor>() != null) return;
        new GameObject("AmbienteVisor").AddComponent<AmbienteVisor>();
    }

    void OnEnable()
    {
        EventosVisor.ModeloCargado += AlCargarModelo;
        EventosVisor.Redibujado += AlRedibujar;
        EventosVisor.VistaCambio += AlCambiarVista;
        EventosVisor.SeleccionCambio += AlCambiarSeleccionLosas;
    }

    void OnDisable()
    {
        EventosVisor.ModeloCargado -= AlCargarModelo;
        EventosVisor.Redibujado -= AlRedibujar;
        EventosVisor.VistaCambio -= AlCambiarVista;
        EventosVisor.SeleccionCambio -= AlCambiarSeleccionLosas;
    }

    void Start()
    {
        GuardarAmbienteOriginal();
        // El cielo y la luz no esperan al modelo: el primer cuadro ya
        // sale con la vista pedida.
        AplicarAmbiente(AjustesVista.realista);

        // Si el visor termino antes de que este script existiera (no pasa
        // con AfterSceneLoad, pero cuesta nada cubrirlo), se engancha aca.
        visor = FindAnyObjectByType<VisorEstructura>();
        if (visor != null && visor.Listo) AlCargarModelo();
    }

    void Update()
    {
        if (!hayAplicado)
        {
            // Sin modelo todavia (o si no llega): al menos el cielo y la luz.
            AplicarAmbiente(AjustesVista.realista);
            return;
        }
        if (AjustesVista.realista != aplicadoRealista || AjustesVista.suelo != aplicadoSuelo)
            Aplicar();
        // El mapa D/C y las capas que esconden las losas no avisan por
        // EventosVisor: se miran aca (barato, y solo toca algo si cambio).
        ActualizarVisibilidadLosas(false);
        bool mapa = MapaDCActivo();
        if (mapa != aplicadoMapa) AplicarMaterialesSuelo();
    }

    /// Con el mapa D/C prendido el suelo va neutro aunque la vista sea
    /// realista: 64 barras verdes sobre pasto verde no se distinguian.
    bool MapaDCActivo()
    {
        if (s4Losas == null && Time.unscaledTime >= proximaBusquedaLosas)
        {
            proximaBusquedaLosas = Time.unscaledTime + 1f;
            s4Losas = FindAnyObjectByType<VisorSemana04>();
        }
        return s4Losas != null && s4Losas.MapaDCActivo;
    }

    private bool aplicadoMapa = false;

    /// Solo los materiales del suelo (no avisa MaterialesCambiados: el suelo
    /// no es un renderer de la estructura y el mapa no lo pinta).
    void AplicarMaterialesSuelo()
    {
        aplicadoMapa = MapaDCActivo();
        Material[] mats = AjustesVista.realista && !aplicadoMapa ? MaterialesSueloRealista() : MaterialesSueloTecnico();
        // El suelo y sus hijos, las terrazas (AmbienteVisor.Terrazas.cs), y el
        // relieve del sitio (AmbienteVisor.Topografia.cs), con los mismos materiales.
        if (suelo != null)
            foreach (MeshRenderer mr in suelo.GetComponentsInChildren<MeshRenderer>(true)) mr.sharedMaterials = mats;
        if (relieve != null)
            foreach (MeshRenderer mr in relieve.GetComponentsInChildren<MeshRenderer>(true)) mr.sharedMaterials = mats;
    }

    void OnDestroy()
    {
        if (ambienteAplicado == 1) AplicarAmbiente(false);
        foreach (Material m in misMateriales) if (m != null) Destroy(m);
        if (cieloRealista != null) Destroy(cieloRealista);
        foreach (Texture2D t in new[] { texHormigon, texEncofrado, texPasto, texTierra })
            if (t != null) Destroy(t);
        if (suelo != null)
        {
            MeshFilter mf = suelo.GetComponent<MeshFilter>();
            if (mf != null && mf.sharedMesh != null) Destroy(mf.sharedMesh);
        }
        BorrarLosas(); BorrarTerrazas();     // y la malla de las terrazas (AmbienteVisor.Terrazas.cs)
        BorrarRelieve();                     // y la del relieve (AmbienteVisor.Topografia.cs)
    }

    // ============================================================
    // EVENTOS
    // ============================================================

    /// Primera carga: el suelo necesita el modelo. Los renderers ya se
    /// registraron en el Redibujado que la precede; aca solo se completan
    /// los que falten, sin pisar lo registrado (a esta altura el material
    /// puede ser ya el realista).
    void AlCargarModelo()
    {
        if (!BuscarVisor()) return;
        Registrar(false);
        ActualizarSueloSinCortar();
        ActualizarLosasSinCortar();
        PedirRelieveDelModelo();             // AmbienteVisor.Topografia.cs
        Aplicar();
    }

    /// Los GameObject de la estructura son NUEVOS y llevan el material
    /// tecnico (VisorEstructura.Pintar): es el momento de registrarlo.
    /// Antes que el mapa D/C, que escucha MaterialesCambiados.
    void AlRedibujar()
    {
        if (!BuscarVisor()) return;
        Registrar(true);
        ActualizarSueloSinCortar();
        ActualizarLosasSinCortar();
        Aplicar();
    }

    /// El suelo es lo unico de este script que recorre la geometria de un
    /// modelo que puede venir editado (U5) o de otro edificio. Si algo
    /// ahi falla, se avisa y se sigue: la vista y el aviso
    /// MaterialesCambiados de Aplicar() no pueden quedar sin llegar (el
    /// mapa D/C y la vista realista dependen de el).
    void ActualizarSueloSinCortar()
    {
        // las terrazas: AmbienteVisor.Terrazas.cs; el relieve: AmbienteVisor.Topografia.cs
        try { ActualizarSuelo(); ActualizarTerrazas(); ActualizarRelieve(); }
        catch (Exception ex) { Debug.LogException(ex); }
    }

    /// Realista/tecnica o suelo si/no. Aplica desde lo registrado. (El
    /// filtro de piso tambien avisa VistaCambio; ese lo redibuja el visor
    /// en su Update, y llega como Redibujado.)
    void AlCambiarVista()
    {
        if (!BuscarVisor()) return;
        Aplicar();
    }

    bool BuscarVisor()
    {
        if (visor == null) visor = FindAnyObjectByType<VisorEstructura>();
        return visor != null && visor.Modelo != null;
    }

    // ============================================================
    // REGISTRO DE MATERIALES
    // ============================================================
    void Registrar(bool desdeCero)
    {
        if (desdeCero) registro.Clear();
        else Podar();

        ModeloEstructural modelo = visor.Modelo;
        foreach (KeyValuePair<int, GameObject> kv in visor.ObjetosDeElementos)
        {
            Renderer r = RendererDe(kv.Value);
            if (r == null || registro.ContainsKey(r)) continue;
            Material tecnico = r.sharedMaterial;
            if (tecnico == null || misMateriales.Contains(tecnico)) continue;
            Elemento e = modelo.ElementoPorId(kv.Key);
            registro[r] = new Registro
            {
                tecnico = tecnico,
                categoria = CategoriaDeElemento(e),
                repeticion = Repeticion(r),
            };
        }
        foreach (KeyValuePair<int, GameObject> kv in visor.ObjetosDeNodos)
        {
            Renderer r = RendererDe(kv.Value);
            if (r == null || registro.ContainsKey(r)) continue;
            Material tecnico = r.sharedMaterial;
            if (tecnico == null || misMateriales.Contains(tecnico)) continue;
            Nodo n = modelo.NodoPorId(kv.Key);
            registro[r] = new Registro
            {
                tecnico = tecnico,
                categoria = CategoriaDeNodo(n),
                repeticion = Repeticion(r),
            };
        }
    }

    void Podar()
    {
        List<Renderer> muertos = null;
        foreach (Renderer r in registro.Keys)
            if (r == null) (muertos ?? (muertos = new List<Renderer>())).Add(r);
        if (muertos != null) foreach (Renderer r in muertos) registro.Remove(r);
    }

    static Renderer RendererDe(GameObject go)
    {
        return go != null ? go.GetComponent<Renderer>() : null;
    }

    /// null = se queda con el material tecnico tambien en la realista.
    string CategoriaDeElemento(Elemento e)
    {
        if (e == null) return null;
        // El brazo rigido es un artificio del modelo, pero lo que hay ahi
        // fisicamente es muro (VisorEstructura lo dibuja como linea fina): en
        // la realista va del color del muro. En magenta asomaba sobre las
        // losas como un cable suelto; en la tecnica sigue magenta.
        if (e.EsBrazo || e.tipo == "brazo" || e.tipo == "brazo_rigido") return "muro";
        // Con la deformada el visor pinta todo amarillo en la tecnica. En la
        // realista se conserva el hormigon (el amarillo con textura sobre el
        // pasto parecia musgo y tapaba el naranjo de la carga movil): la
        // posicion original la marca VisorEstructura con lineas oscuras.
        if (e.tipo == "columna") return "columna";
        if (e.tipo == "muro") return "muro";
        if (e.tipo == "pilar_metal" || e.tipo == "viga_metal" || e.tipo == "diagonal") return "metal";
        return "viga";
    }

    /// Los apoyos (verdes) y los auxiliares (grises) conservan su color:
    /// son informacion estructural, no una pieza.
    static string CategoriaDeNodo(Nodo n)
    {
        if (n == null || n.auxiliar || n.fijo || TieneRestriccion(n)) return null;
        return "nodo";
    }

    static bool TieneRestriccion(Nodo n)
    {
        if (n.restricciones == null) return false;
        foreach (int r in n.restricciones) if (r != 0) return true;
        return false;
    }

    // ============================================================
    // APLICAR LA VISTA
    // ============================================================
    void Aplicar()
    {
        bool realista = AjustesVista.realista;
        foreach (KeyValuePair<Renderer, Registro> kv in registro)
        {
            if (kv.Key == null) continue;
            Registro reg = kv.Value;
            kv.Key.sharedMaterial = realista
                ? MaterialRealista(reg.categoria, reg.repeticion, reg.tecnico)
                : reg.tecnico;
        }

        AplicarAmbiente(realista);

        if (suelo != null) suelo.SetActive(AjustesVista.suelo);
        aplicadoRealista = realista;
        AplicarMaterialesSuelo();
        AplicarVisibilidadRelieve();
        aplicadoSuelo = AjustesVista.suelo;
        hayAplicado = true;
        ActualizarVisibilidadLosas(true);

        // Siempre, aunque nada haya cambiado: el mapa D/C re-guarda su
        // base y vuelve a pintar encima (CONTRATO.md, seccion 8).
        EventosVisor.AvisarMaterialesCambiados();
    }

    // ------------------------------------------------------------
    void GuardarAmbienteOriginal()
    {
        if (ambienteGuardado) return;
        ambienteGuardado = true;

        sol = RenderSettings.sun;
        if (sol == null)
        {
            // La escena no asigna Sun (m_Sun en null): la direccional mas
            // intensa es la que URP usa como luz principal.
            foreach (Light l in FindObjectsByType<Light>())
                if (l.type == LightType.Directional && (sol == null || l.intensity > sol.intensity))
                    sol = l;
        }
        if (sol != null)
        {
            solIntensidad = sol.intensity;
            solColor = sol.color;
            solUsaTemperatura = sol.useColorTemperature;
            solTemperatura = sol.colorTemperature;
            solSombras = sol.shadows;
            solFuerzaSombra = sol.shadowStrength;
            solRotacion = sol.transform.rotation;
        }
        ambienteModo = RenderSettings.ambientMode;
        ambienteCielo = RenderSettings.ambientSkyColor;
        ambienteEcuador = RenderSettings.ambientEquatorColor;
        ambienteSuelo = RenderSettings.ambientGroundColor;
        solOriginalDeRender = RenderSettings.sun;
        cieloOriginal = RenderSettings.skybox;
    }

    /// El cielo, la luz y la luz ambiente. Solo propiedades de tiempo de
    /// ejecucion (RenderSettings, Light): nada queda guardado en disco.
    /// Se aplica solo cuando cambia la vista: DynamicGI.UpdateEnvironment
    /// no es gratis y Redibujado llega seguido.
    void AplicarAmbiente(bool realista)
    {
        if (!ambienteGuardado) return;
        int pedido = realista ? 1 : 0;
        if (pedido == ambienteAplicado) return;
        // La primera vez en tecnica no hay nada que restaurar: la escena
        // ya esta como la dejo su autor.
        bool nadaQueRestaurar = ambienteAplicado == -1 && !realista;
        ambienteAplicado = pedido;
        if (nadaQueRestaurar) return;

        if (!realista)
        {
            if (sol != null)
            {
                sol.intensity = solIntensidad;
                sol.color = solColor;
                sol.useColorTemperature = solUsaTemperatura;
                sol.colorTemperature = solTemperatura;
                sol.shadows = solSombras;
                sol.shadowStrength = solFuerzaSombra;
                sol.transform.rotation = solRotacion;
            }
            RenderSettings.ambientMode = ambienteModo;
            RenderSettings.ambientSkyColor = ambienteCielo;
            RenderSettings.ambientEquatorColor = ambienteEcuador;
            RenderSettings.ambientGroundColor = ambienteSuelo;
            RenderSettings.sun = solOriginalDeRender;
            RenderSettings.skybox = cieloOriginal;
            AplicarVolumen(false);               // AmbienteVisor.Recursos.cs
            DynamicGI.UpdateEnvironment();
            return;
        }

        if (sol != null)
        {
            // Luz de dia algo mas calida y un poco menos fuerte que la de
            // la escena (intensidad 2 a 5000 K), con sombras blandas y
            // menos negras. La altura (50 grados) es la de la escena; el
            // rumbo se gira a SOL_REALISTA para iluminar las caras que ve la
            // camara. Se restaura en la tecnica (solRotacion).
            sol.transform.rotation = Quaternion.Euler(SOL_REALISTA);
            sol.intensity = solIntensidad * 0.85f;
            if (sol.useColorTemperature) sol.colorTemperature = 5600f;
            else sol.color = new Color(1f, 0.96f, 0.90f);
            sol.shadows = LightShadows.Soft;
            sol.shadowStrength = 0.75f;
            RenderSettings.sun = sol;
        }

        // Una COPIA del skybox: el de la escena es el Default-Skybox de
        // Unity, un recurso compartido que no conviene modificar. El
        // shader es el mismo (Skybox/Procedural): nada nuevo en la build.
        if (cieloOriginal != null)
        {
            if (cieloRealista == null)
            {
                cieloRealista = new Material(cieloOriginal) { name = "CieloRealista" };
                FijarSiExiste(cieloRealista, "_SkyTint", new Color(0.44f, 0.54f, 0.70f));
                FijarSiExiste(cieloRealista, "_AtmosphereThickness", 0.85f);
                FijarSiExiste(cieloRealista, "_Exposure", 1.15f);
                FijarSiExiste(cieloRealista, "_SunSize", 0.035f);
                // Bajo el horizonte el cielo pinta este color: el del pasto
                // visto de lejos, para que el borde del suelo no se note. Y
                // la luz ambiente que sube desde abajo sale verdosa, como el
                // rebote del pasto.
                FijarSiExiste(cieloRealista, "_GroundColor", new Color(0.36f, 0.40f, 0.30f));
            }
            RenderSettings.skybox = cieloRealista;
        }
        // El HDRI, si esta (AmbienteVisor.Recursos.cs), en vez del procedural.
        Material hdri = CieloReal();
        if (hdri != null) RenderSettings.skybox = hdri;
        AplicarVolumen(true);
        bool luzDelCielo = hdri != null;

        // La luz ambiente de la realista: tres tonos neutros (Trilight) en vez
        // del cielo azul. No se escribe la sonda a mano: si al arrancar
        // todavia no estaba calculada, guardarla y "restaurarla" dejaria la
        // vista tecnica a oscuras. Se pide recalcularla; si en alguna
        // plataforma no corre, queda la de la escena: nada se rompe.
        // Con el HDRI, la luz ambiente sale de el (la sonda se recalcula de
        // ese cielo); sin el, los tres tonos de siempre.
        RenderSettings.ambientMode = luzDelCielo ? AmbientMode.Skybox : AmbientMode.Trilight;
        RenderSettings.ambientIntensity = 1f;
        RenderSettings.ambientSkyColor = AMB_CIELO;
        RenderSettings.ambientEquatorColor = AMB_ECUADOR;
        RenderSettings.ambientGroundColor = AMB_SUELO;
        DynamicGI.UpdateEnvironment();
    }

    static void FijarSiExiste(Material m, string prop, Color c)
    {
        if (m.HasProperty(prop)) m.SetColor(prop, c);
    }

    static void FijarSiExiste(Material m, string prop, float v)
    {
        if (m.HasProperty(prop)) m.SetFloat(prop, v);
    }

    // ============================================================
    // MATERIALES Y TEXTURAS
    // ============================================================

    /// El material realista de un renderer. Se cachea por categoria y
    /// por REPETICION de la textura: los primitivos de Unity estiran el
    /// UV a todo el largo, y una columna de 4 m con la textura estirada se
    /// ve como vetas. La repeticion es un parametro del material, asi que
    /// va en la clave (redondeada: unas decenas de materiales, no uno por
    /// objeto).
    Material MaterialRealista(string categoria, Vector2Int rep, Material tecnico)
    {
        if (categoria == null) return tecnico;
        CrearTexturas();

        Color color;
        Texture2D tex = texHormigon;
        float suavidad = 0.12f, metalico = 0f;
        switch (categoria)
        {
            case "columna": color = C_COLUMNA; break;
            case "muro": color = C_MURO; tex = texEncofrado; suavidad = 0.08f; break;
            case "metal": color = C_METAL; suavidad = 0.35f; metalico = 0.25f; break;
            case "nodo": color = C_NODO; break;
            default: color = C_VIGA; break;
        }
        string clave = categoria + "|" + ColorUtility.ToHtmlStringRGB(color) + "|" + rep.x + "x" + rep.y;
        Material m;
        if (materialesRealistas.TryGetValue(clave, out m) && m != null) return m;

        // Con el recurso descargado (AmbienteVisor.Recursos.cs); si no, la procedural.
        m = NuevoMaterialReal("Realista_" + clave, ItemDe(categoria), color, suavidad, metalico,
                              new Vector2(rep.x, rep.y))
            ?? NuevoMaterial("Realista_" + clave, tex, color, suavidad, metalico, new Vector2(rep.x, rep.y));
        materialesRealistas[clave] = m;
        return m;
    }

    /// Cuantas veces se repite la textura en cada eje del UV del
    /// primitivo, segun su tamano real (lossyScale).
    ///   Cubo (muro, perfil): cada cara mapea su UV entero; con los dos
    ///     ejes mayores se cubren la cara grande del muro (largo x alto)
    ///     y la larga de la viga.
    ///   Cilindro (barra): la malla mide 2 de alto, v corre a lo largo.
    ///   Esfera (nodo): una vez.
    static Vector2Int Repeticion(Renderer r)
    {
        MeshFilter mf = r.GetComponent<MeshFilter>();
        string malla = mf != null && mf.sharedMesh != null ? mf.sharedMesh.name : "";
        Vector3 s = r.transform.lossyScale;
        if (malla.Contains("Cylinder"))
            return new Vector2Int(1, Veces(2f * Mathf.Abs(s.y)));
        if (malla.Contains("Cube"))
            return new Vector2Int(Veces(Mathf.Max(Mathf.Abs(s.x), Mathf.Abs(s.z))),
                                  Veces(Mathf.Max(Mathf.Abs(s.y), Mathf.Abs(s.z))));
        return new Vector2Int(1, 1);
    }

    static int Veces(float metros)
    {
        return Mathf.Clamp(Mathf.RoundToInt(metros / REPETICION_HORMIGON), 1, 24);
    }

    Material NuevoMaterial(string nombre, Texture tex, Color color, float suavidad, float metalico, Vector2 repeticion)
    {
        Material m = new Material(VisorEstructura.ShaderCompatible()) { name = nombre };
        // URP Lit usa _BaseMap/_BaseColor/_Smoothness; si el proyecto
        // cayera al Standard, _MainTex/_Color/_Glossiness. Se ponen los
        // que existan: ninguno enciende un keyword.
        foreach (string p in new[] { "_BaseMap", "_MainTex" })
        {
            if (!m.HasProperty(p)) continue;
            m.SetTexture(p, tex);
            m.SetTextureScale(p, repeticion);
        }
        m.color = color;
        FijarSiExiste(m, "_BaseColor", color);
        FijarSiExiste(m, "_Smoothness", suavidad);
        FijarSiExiste(m, "_Glossiness", suavidad);
        FijarSiExiste(m, "_Metallic", metalico);
        misMateriales.Add(m);
        return m;
    }

    Material[] MaterialesSueloRealista()
    {
        if (matSueloRealista != null) return matSueloRealista;
        CrearTexturas();
        // Las UV del suelo ya vienen en metros / repeticion (ver la malla):
        // el material no escala.
        // Los recursos descargados cubren menos metros por imagen que la
        // procedural: se reescalan sobre las mismas UV (AmbienteVisor.Recursos.cs).
        matSueloRealista = new[]
        {
            NuevoMaterialReal("SueloPasto", "pasto", C_PASTO_REAL, 0.04f, 0f, Vector2.one * (REPETICION_PASTO / TILE_PASTO_M))
                ?? NuevoMaterial("SueloPasto", texPasto, C_PASTO, 0.04f, 0f, Vector2.one),
            NuevoMaterialReal("ExcavacionPared", "tierra", C_PARED_TIERRA, 0.03f, 0f, Vector2.one * (REPETICION_TIERRA / TILE_TIERRA_M))
                ?? NuevoMaterial("ExcavacionPared", texTierra, C_PARED_TIERRA, 0.03f, 0f, Vector2.one),
            NuevoMaterialReal("ExcavacionFondo", "hormigon_losa", C_FONDO, 0.06f, 0f, Vector2.one)
                ?? NuevoMaterial("ExcavacionFondo", texHormigon, C_FONDO, 0.06f, 0f, Vector2.one),
        };
        return matSueloRealista;
    }

    Material[] MaterialesSueloTecnico()
    {
        if (matSueloTecnico != null) return matSueloTecnico;
        matSueloTecnico = new[]
        {
            NuevoMaterial("SueloTecnico", null, T_SUELO, 0.02f, 0f, Vector2.one),
            NuevoMaterial("ParedTecnica", null, T_PARED, 0.02f, 0f, Vector2.one),
            NuevoMaterial("FondoTecnico", null, T_FONDO, 0.02f, 0f, Vector2.one),
        };
        return matSueloTecnico;
    }

    // ------------------------------------------------------------
    // Texturas procedurales. Sin assets descargados: se calculan con un
    // ruido PERIODICO (la red de valores se envuelve con el periodo), asi
    // la textura empalma consigo misma y no se ve la costura al repetir.
    // Semillas fijas: la misma imagen en cada corrida y en cada captura.
    // ------------------------------------------------------------
    void CrearTexturas()
    {
        if (texHormigon != null) return;
        var reloj = System.Diagnostics.Stopwatch.StartNew();
        int n = LadoTextura;
        texHormigon = Textura("Hormigon", n, PixelHormigon);
        texEncofrado = Textura("Encofrado", n, PixelEncofrado);
        texPasto = Textura("Pasto", n, PixelPasto);
        texTierra = Textura("Tierra", n / 2, PixelTierra);
        // Se genera en la CPU la primera vez que se pide la vista realista:
        // el tiempo queda en el log para ver cuanto cuesta en cada equipo.
        Debug.Log(string.Format(CultureInfo.InvariantCulture,
                                "AmbienteVisor: texturas procedurales de {0} px en {1} ms.",
                                n, reloj.ElapsedMilliseconds));
    }

    static Texture2D Textura(string nombre, int n, Func<int, int, int, Color> pixel)
    {
        Texture2D t = new Texture2D(n, n, TextureFormat.RGBA32, true, false)
        {
            name = nombre,
            wrapMode = TextureWrapMode.Repeat,
            filterMode = FilterMode.Trilinear,
            anisoLevel = 8,
        };
        Color32[] px = new Color32[n * n];
        for (int y = 0; y < n; y++)
            for (int x = 0; x < n; x++)
                px[y * n + x] = pixel(x, y, n);
        t.SetPixels32(px);
        // Mipmaps: sin ellos el pasto titila al alejarse. Se libera la
        // copia en CPU, que ya no hace falta.
        t.Apply(true, true);
        return t;
    }

    static Color PixelHormigon(int x, int y, int n)
    {
        float u = (float)x / n, v = (float)y / n;
        float g = 0.88f + 0.16f * (Fbm(u, v, 4, 5, 11) - 0.5f);           // tono general
        float mancha = Fbm(u, v, 2, 3, 23);
        g -= 0.10f * Mathf.InverseLerp(0.58f, 0.80f, mancha);                  // manchas de humedad
        g += 0.05f * (Hash(x, y, 5) - 0.5f);                                  // grano
        if (Hash(x, y, 7) < 0.012f) g -= 0.30f * Hash(x, y, 8);               // poros
        return new Color(g, g * 0.99f, g * 0.96f, 1f);
    }

    static Color PixelEncofrado(int x, int y, int n)
    {
        Color c = PixelHormigon(x, y, n);
        int alto = Mathf.Max(n / 4, 1);                   // 4 tablas por repeticion
        int tabla = y / alto;
        float f = 1f + 0.035f * (Hash(tabla, 0, 61) - 0.5f) * 2f;             // cada tabla su tono
        // Veta de la madera: ruido en u con v fijo por tabla, asi corre a
        // lo largo de la tabla y la textura sigue empalmando.
        f += 0.03f * (Fbm((float)x / n, (tabla + 0.5f) / 4f, 16, 2, 67) - 0.5f);
        int enTabla = y % alto;
        if (enTabla == 0) f *= 0.80f;                                          // junta entre tablas
        else if (enTabla == 1) f *= 1.03f;
        // Pasadas de los separadores del moldaje (unos 2.5 cm con 1.5 m
        // por repeticion): dos por tabla, en tablas alternas.
        int cy = alto / 2, cx1 = n / 4, cx2 = 3 * n / 4, radio = Mathf.Max(n / 128, 1);
        if (tabla % 2 == 0)
        {
            int dy = enTabla - cy;
            int dx = Mathf.Min(Mathf.Abs(x - cx1), Mathf.Abs(x - cx2));
            if (dx * dx + dy * dy <= radio * radio) f *= 0.55f;
        }
        return new Color(c.r * f, c.g * f, c.b * f, 1f);
    }

    static Color PixelPasto(int x, int y, int n)
    {
        float u = (float)x / n, v = (float)y / n;
        Color oscuro = new Color(0.22f, 0.32f, 0.13f);
        Color claro = new Color(0.40f, 0.50f, 0.21f);
        Color seco = new Color(0.55f, 0.52f, 0.31f);
        Color tierra = new Color(0.42f, 0.35f, 0.25f);

        float matas = Fbm(u, v, 32, 3, 37);
        float hoja = Hash(x, y, 43);
        Color c = Color.Lerp(oscuro, claro, Mathf.Clamp01(matas * 0.85f + hoja * 0.25f));
        float zonas = Fbm(u, v, 4, 4, 31);
        // Las zonas secas y las calvas son lo que el ojo reconoce al
        // repetirse la textura cada 12 m: van suaves.
        c = Color.Lerp(c, seco, 0.25f * Mathf.InverseLerp(0.55f, 0.78f, zonas));
        float calvas = Fbm(u, v, 8, 3, 41);
        c = Color.Lerp(c, tierra, 0.35f * Mathf.InverseLerp(0.70f, 0.88f, calvas));
        float grano = 0.9f + 0.2f * Hash(x, y, 47);
        return new Color(c.r * grano, c.g * grano, c.b * grano, 1f);
    }

    static Color PixelTierra(int x, int y, int n)
    {
        float u = (float)x / n, v = (float)y / n;
        float g = 0.82f + 0.30f * (Fbm(u, v, 8, 4, 51) - 0.5f);
        // Estratos: bandas horizontales onduladas, como un corte de
        // excavacion.
        g += 0.05f * Mathf.Sin((v * 6f + 0.35f * Fbm(u, v, 4, 2, 53)) * Mathf.PI * 2f);
        Color c = new Color(0.56f * g, 0.46f * g, 0.35f * g, 1f);
        if (Hash(x, y, 57) < 0.008f)                                           // piedrecillas
        {
            float p = 0.45f + 0.15f * Hash(x, y, 59);
            c = new Color(p, p * 0.92f, p * 0.82f, 1f);
        }
        return c;
    }

    static float Hash(int x, int y, int semilla)
    {
        unchecked
        {
            uint h = (uint)(x * 374761393 + y * 668265263 + semilla * 1442695041);
            h = (h ^ (h >> 13)) * 1274126177u;
            h ^= h >> 16;
            return (h & 0xFFFFFF) / 16777215f;
        }
    }

    /// Ruido de valores con la red envuelta cada 'periodo' celdas: u y v
    /// en [0, 1) empalman en los bordes.
    static float RuidoPeriodico(float u, float v, int periodo, int semilla)
    {
        float x = u * periodo, y = v * periodo;
        int x0 = Mathf.FloorToInt(x), y0 = Mathf.FloorToInt(y);
        float fx = x - x0, fy = y - y0;
        fx = fx * fx * (3f - 2f * fx);
        fy = fy * fy * (3f - 2f * fy);
        int xa = ((x0 % periodo) + periodo) % periodo, xb = (xa + 1) % periodo;
        int ya = ((y0 % periodo) + periodo) % periodo, yb = (ya + 1) % periodo;
        float a = Mathf.Lerp(Hash(xa, ya, semilla), Hash(xb, ya, semilla), fx);
        float b = Mathf.Lerp(Hash(xa, yb, semilla), Hash(xb, yb, semilla), fx);
        return Mathf.Lerp(a, b, fy);
    }

    static float Fbm(float u, float v, int periodo, int octavas, int semilla)
    {
        float suma = 0f, amp = 1f, total = 0f;
        for (int k = 0; k < octavas; k++)
        {
            suma += amp * RuidoPeriodico(u, v, periodo << k, semilla + 101 * k);
            total += amp;
            amp *= 0.5f;
        }
        return suma / total;
    }

    // ============================================================
    // EL SUELO
    // ============================================================

    /// Arma (o reusa) la malla del suelo. Solo depende de la cota y de la
    /// geometria ORIGINAL bajo la cota (no de la deformada): si la firma
    /// no cambio, no se rehace. Redibujado llega seguido (escala de la
    /// deformada, capas) y rehacer el hueco cada vez seria perder tiempo.
    void ActualizarSuelo()
    {
        ModeloEstructural modelo = visor.Modelo;
        if (modelo.nodos == null || modelo.nodos.Count == 0) return;

        string fuente;
        float cota = CotaDelTerreno(modelo, out fuente);

        List<double[]> estampas = new List<double[]>();
        List<double[]> techo = new List<double[]>();
        List<double[]> apoyos = new List<double[]>();
        double zFondo;
        ReunirGeometria(modelo, cota, estampas, techo, apoyos, out zFondo);

        string firma = Firma(cota, estampas, techo, apoyos);
        if (suelo != null && firma == firmaSuelo) return;

        if (fuente != null) Debug.LogWarning(fuente);

        // Donde se arma la malla: sobre las estampas si hay subterraneo;
        // si no, un solo cuadro sobre la planta del edificio.
        double minX = double.MaxValue, minY = double.MaxValue, maxX = double.MinValue, maxY = double.MinValue;
        foreach (Nodo n in modelo.nodos)
        {
            minX = Math.Min(minX, n.x); maxX = Math.Max(maxX, n.x);
            minY = Math.Min(minY, n.y); maxY = Math.Max(maxY, n.y);
        }

        HuecoDelSuelo.Resultado hueco = HuecoDelSuelo.Calcular(
            estampas, techo, apoyos, CeldaPara(minX, minY, maxX, maxY), minX, minY, maxX, maxY);

        float yS = cota - BAJO_LA_COTA;
        float yF = estampas.Count > 0 ? (float)zFondo - BAJO_LA_COTA : yS;
        Mesh malla = ConstruirMalla(hueco, yS, yF);

        if (suelo == null)
        {
            // Sin Collider a proposito (ver el encabezado): solo filtro y
            // renderer. Tampoco proyecta sombra; la recibe.
            suelo = new GameObject("Suelo");
            suelo.transform.SetParent(transform, false);
            suelo.AddComponent<MeshFilter>();
            MeshRenderer mr = suelo.AddComponent<MeshRenderer>();
            mr.shadowCastingMode = ShadowCastingMode.Off;
            mr.receiveShadows = true;
        }
        MeshFilter mf = suelo.GetComponent<MeshFilter>();
        if (mf.sharedMesh != null) Destroy(mf.sharedMesh);
        mf.sharedMesh = malla;
        // La firma se guarda recien con la malla puesta: si algo arriba
        // fallo, el proximo Redibujado lo vuelve a intentar.
        firmaSuelo = firma;

        // Con punto decimal (InvariantCulture, como los numeros del panel):
        // con la cultura de un Windows en espanol saldria "-4,01", y esta
        // linea se lee en el registro de la integracion.
        Debug.Log(string.Format(CultureInfo.InvariantCulture,
            "AmbienteVisor: suelo en z = {0:F2} m{1}; hueco del subterraneo {2:F0} m2 "
            + "sobre {3} estampas bajo la cota (fondo z = {4:F2}); {5} apoyos en terreno "
            + "fuera del hueco, {6} sobre muros del subterraneo.",
            cota, fuente == null ? " (info.cota_terreno)" : " (apoyo mas bajo)",
            hueco.areaHueco, estampas.Count, estampas.Count > 0 ? zFondo : cota,
            hueco.apoyosUsados, hueco.apoyosSobreSubterraneo));
    }

    /// info.cota_terreno si viene; si no, la z del apoyo mas bajo, y
    /// 'aviso' con el por que (null si vino).
    static float CotaDelTerreno(ModeloEstructural modelo, out string aviso)
    {
        aviso = null;
        if (modelo.info != null && modelo.info.cota_terreno > SIN_COTA)
            return modelo.info.cota_terreno;

        float z = float.MaxValue, zTodos = float.MaxValue;
        foreach (Nodo n in modelo.nodos)
        {
            zTodos = Mathf.Min(zTodos, n.z);
            if (!n.auxiliar && (n.fijo || TieneRestriccion(n))) z = Mathf.Min(z, n.z);
        }
        if (z == float.MaxValue) z = zTodos;
        aviso = string.Format(CultureInfo.InvariantCulture,
            "AmbienteVisor: el JSON no trae info.cota_terreno, asi que el suelo se "
            + "dibuja en el apoyo mas bajo (z = {0:F2} m). Es un respaldo de dibujo, NO "
            + "un dato: la cota del terreno se declara como supuesto en el perfil del "
            + "edificio y la exporta su exportar_unity.py (ver el 'terreno' de "
            + "edificios/lt2/perfiles/lt2_2024_22.json).", z);
        return z;
    }

    /// En planta (x, y OpenSees), con {x1, y1, x2, y2} por estampa:
    ///   estampas: lo que va BAJO la cota. Nodos, barras (su proyeccion) y
    ///     muros con su LARGO real, que es lo que cierra el perimetro del
    ///     subterraneo.
    ///   techo: las barras y nodos EN la cota, la planta del edificio a la
    ///     altura del terreno. El hueco no pasa de ella (mas el margen).
    ///   apoyos: los apoyos EN la cota, prueba de que ahi el terreno
    ///     sostiene; el hueco los respeta.
    static void ReunirGeometria(ModeloEstructural modelo, float cota, List<double[]> estampas,
                                List<double[]> techo, List<double[]> apoyos, out double zFondo)
    {
        double limite = cota - AjustesVista.TOLERANCIA_COTA;
        zFondo = cota;
        foreach (Nodo n in modelo.nodos)
        {
            if (n.z < limite)
            {
                estampas.Add(new double[] { n.x, n.y, n.x, n.y });
                zFondo = Math.Min(zFondo, n.z);
            }
            else if (Mathf.Abs(n.z - cota) <= TOL_EN_COTA)
            {
                techo.Add(new double[] { n.x, n.y, n.x, n.y });
                if (!n.auxiliar && (n.fijo || TieneRestriccion(n)))
                    apoyos.Add(new double[] { n.x, n.y });
            }
        }
        if (modelo.elementos == null) return;
        foreach (Elemento e in modelo.elementos)
        {
            Nodo a = modelo.NodoPorId(e.n1), b = modelo.NodoPorId(e.n2);
            if (a == null || b == null) continue;
            if (Mathf.Abs(a.z - cota) <= TOL_EN_COTA && Mathf.Abs(b.z - cota) <= TOL_EN_COTA)
            {
                techo.Add(new double[] { a.x, a.y, b.x, b.y });
                continue;
            }
            if (Mathf.Min(a.z, b.z) >= limite) continue;
            if (!e.EsMuro)
            {
                estampas.Add(new double[] { a.x, a.y, b.x, b.y });
                continue;
            }
            // El muro es UNA barra en su eje: en planta mide 'largo' a lo
            // largo de dir_largo (el mismo dato con que lo dibuja el visor).
            float largo = e.largo;
            if (largo < 0.01f)
            {
                Seccion s = modelo.SeccionPorNombre(e.seccion);
                if (s != null && s.TieneMuro) largo = s.largo;
            }
            double cx = 0.5 * (a.x + b.x), cy = 0.5 * (a.y + b.y);
            if (largo < 0.01f || e.dir_largo == null || e.dir_largo.Length < 2)
            {
                estampas.Add(new double[] { cx, cy, cx, cy });
                continue;
            }
            double dx = e.dir_largo[0], dy = e.dir_largo[1];
            double norma = Math.Sqrt(dx * dx + dy * dy);
            if (norma < 1e-6) { estampas.Add(new double[] { cx, cy, cx, cy }); continue; }
            double h = 0.5 * largo / norma;
            estampas.Add(new double[] { cx - dx * h, cy - dy * h, cx + dx * h, cy + dy * h });
        }
    }

    static string Firma(float cota, List<double[]> estampas, List<double[]> techo, List<double[]> apoyos)
    {
        double s = 0;
        foreach (double[] e in estampas) s += e[0] * 1.3 + e[1] * 1.7 + e[2] * 2.9 + e[3] * 3.1;
        foreach (double[] e in techo) s += e[0] * 4.1 + e[1] * 4.3 + e[2] * 4.7 + e[3] * 4.9;
        foreach (double[] p in apoyos) s += p[0] * 5.3 + p[1] * 7.1;
        return string.Format("{0:F3}|{1}|{2}|{3}|{4:F3}", cota, estampas.Count, techo.Count, apoyos.Count, s);
    }

    static double CeldaPara(double minX, double minY, double maxX, double maxY)
    {
        // A lo mas 300 celdas a lo largo del edificio (mas la holgura del
        // cierre). Con los tres edificios la celda queda en 0.5 m y la
        // malla bajo los 65 mil vertices del indice de 16 bits: 30 524 el
        // LT2, 42 900 el conjunto, 12 Ingenieria (sin hueco). Si otro
        // edificio pasa, ConstruirMalla usa indice de 32 bits.
        return Math.Max(CELDA_MIN, Math.Max(maxX - minX, maxY - minY) / 300.0);
    }

    // ------------------------------------------------------------
    /// La malla, con tres submallas: 0 suelo, 1 paredes de la
    /// excavacion, 2 fondo. En coordenadas UNITY: x = x, z = y OpenSees.
    ///
    /// El borde del hueco sale por 'marching squares' sobre las muestras
    /// del mapa: cada celda se recorta por los puntos medios de sus lados,
    /// asi el borde va en diagonales y no en escalones de 0.5 m.
    static Mesh ConstruirMalla(HuecoDelSuelo.Resultado h, float yS, float yF)
    {
        List<Vector3> v = new List<Vector3>();
        List<Vector3> nor = new List<Vector3>();
        List<Vector2> uv = new List<Vector2>();
        List<int> triSuelo = new List<int>(), triPared = new List<int>(), triFondo = new List<int>();
        Dictionary<long, int> idSuelo = new Dictionary<long, int>();
        Dictionary<long, int> idFondo = new Dictionary<long, int>();

        int nx = h.nx, ny = h.ny;
        double c = h.celda;
        long ancho = 2L * ny + 3;

        // Vertice del suelo o del fondo en coordenadas DOBLES de la red
        // (esquinas pares, puntos medios impares): se comparten entre
        // celdas vecinas y la malla no tiene grietas.
        Func<int, int, bool, int> vertice = (i2, j2, arriba) =>
        {
            Dictionary<long, int> dic = arriba ? idSuelo : idFondo;
            long clave = i2 * ancho + j2;
            int id;
            if (dic.TryGetValue(clave, out id)) return id;
            float x = (float)(h.x0 + i2 * 0.5 * c), z = (float)(h.y0 + j2 * 0.5 * c);
            id = v.Count;
            v.Add(new Vector3(x, arriba ? yS : yF, z));
            nor.Add(Vector3.up);
            float rep = arriba ? REPETICION_PASTO : REPETICION_TIERRA;
            uv.Add(new Vector2(x / rep, z / rep));
            dic[clave] = id;
            return id;
        };

        int[] ci = { 0, 2, 2, 0 };     // esquinas de la celda en dobles: c0 c1 c2 c3
        int[] cj = { 0, 0, 2, 2 };
        int[] ei = { 1, 2, 1, 0 };     // punto medio del lado k (entre ck y ck+1)
        int[] ej = { 0, 1, 2, 1 };
        List<int> poli = new List<int>(6);
        List<bool> esMedio = new List<bool>(6);
        bool hayFondo = yF < yS - 1e-3f;

        for (int j = 0; j < ny; j++)
        {
            for (int i = 0; i < nx; i++)
            {
                bool[] s = { h.Suelo(i, j), h.Suelo(i + 1, j), h.Suelo(i + 1, j + 1), h.Suelo(i, j + 1) };
                bool todas = s[0] && s[1] && s[2] && s[3];
                bool ninguna = !s[0] && !s[1] && !s[2] && !s[3];

                for (int pasada = 0; pasada < 2; pasada++)
                {
                    bool arriba = pasada == 0;
                    if (arriba && ninguna) continue;
                    if (!arriba && (todas || !hayFondo)) continue;

                    poli.Clear(); esMedio.Clear();
                    for (int k = 0; k < 4; k++)
                    {
                        int k1 = (k + 1) % 4;
                        if (s[k] == arriba)
                        {
                            poli.Add(vertice(2 * i + ci[k], 2 * j + cj[k], arriba));
                            esMedio.Add(false);
                        }
                        if (s[k] != s[k1])
                        {
                            poli.Add(vertice(2 * i + ei[k], 2 * j + ej[k], arriba));
                            esMedio.Add(true);
                        }
                    }
                    if (poli.Count < 3) continue;
                    List<int> tri = arriba ? triSuelo : triFondo;
                    for (int k = 1; k + 1 < poli.Count; k++)
                        Triangulo(tri, v, poli[0], poli[k], poli[k + 1], Vector3.up);

                    // Paredes: cada par de puntos medios seguidos en el
                    // poligono del SUELO es un tramo del borde del hueco.
                    if (!arriba || !hayFondo || todas) continue;
                    Vector3 centro = Vector3.zero;
                    int nSuelo = 0;
                    for (int k = 0; k < 4; k++)
                    {
                        if (!s[k]) continue;
                        centro += new Vector3((float)(h.x0 + (i + ci[k] / 2) * c), 0f, (float)(h.y0 + (j + cj[k] / 2) * c));
                        nSuelo++;
                    }
                    centro /= Mathf.Max(nSuelo, 1);
                    for (int k = 0; k < poli.Count; k++)
                    {
                        int k1 = (k + 1) % poli.Count;
                        if (esMedio[k] && esMedio[k1])
                            Pared(v, nor, uv, triPared, v[poli[k]], v[poli[k1]], centro, yS, yF);
                    }
                }
            }
        }

        // El marco hasta MEDIO_LADO_SUELO: cuatro franjas de trapecios que
        // usan los MISMOS vertices del borde de la red (sin uniones en T).
        float gx0 = (float)h.x0, gz0 = (float)h.y0;
        float gx1 = (float)(h.x0 + nx * c), gz1 = (float)(h.y0 + ny * c);
        float cx = 0.5f * (gx0 + gx1), cz = 0.5f * (gz0 + gz1);
        float L = Mathf.Max(MEDIO_LADO_SUELO, 0.5f * Mathf.Max(gx1 - gx0, gz1 - gz0) + 100f);
        float ox0 = cx - L, ox1 = cx + L, oz0 = cz - L, oz1 = cz + L;
        Func<float, float, int> exterior = (x, z) =>
        {
            int id = v.Count;
            v.Add(new Vector3(x, yS, z));
            nor.Add(Vector3.up);
            uv.Add(new Vector2(x / REPETICION_PASTO, z / REPETICION_PASTO));
            return id;
        };
        for (int i = 0; i < nx; i++)
        {
            float t0 = (float)i / nx, t1 = (float)(i + 1) / nx;
            // abajo (z menor) y arriba (z mayor)
            Cuadro(triSuelo, v, vertice(2 * i, 0, true), vertice(2 * i + 2, 0, true),
                   exterior(Mathf.Lerp(ox0, ox1, t1), oz0), exterior(Mathf.Lerp(ox0, ox1, t0), oz0));
            Cuadro(triSuelo, v, vertice(2 * i, 2 * ny, true), vertice(2 * i + 2, 2 * ny, true),
                   exterior(Mathf.Lerp(ox0, ox1, t1), oz1), exterior(Mathf.Lerp(ox0, ox1, t0), oz1));
        }
        for (int j = 0; j < ny; j++)
        {
            float t0 = (float)j / ny, t1 = (float)(j + 1) / ny;
            Cuadro(triSuelo, v, vertice(0, 2 * j, true), vertice(0, 2 * j + 2, true),
                   exterior(ox0, Mathf.Lerp(oz0, oz1, t1)), exterior(ox0, Mathf.Lerp(oz0, oz1, t0)));
            Cuadro(triSuelo, v, vertice(2 * nx, 2 * j, true), vertice(2 * nx, 2 * j + 2, true),
                   exterior(ox1, Mathf.Lerp(oz0, oz1, t1)), exterior(ox1, Mathf.Lerp(oz0, oz1, t0)));
        }

        Mesh m = new Mesh { name = "SueloAmbiente" };
        if (v.Count > 65000) m.indexFormat = IndexFormat.UInt32;
        m.SetVertices(v);
        m.SetNormals(nor);
        m.SetUVs(0, uv);
        m.subMeshCount = 3;
        m.SetTriangles(triSuelo, 0);
        m.SetTriangles(triPared, 1);
        m.SetTriangles(triFondo, 2);
        m.RecalculateTangents();             // para el mapa normal (AmbienteVisor.Recursos.cs)
        m.RecalculateBounds();
        return m;
    }

    /// Agrega el triangulo con la cara VISIBLE hacia 'normal'. En Unity la
    /// cara de frente es la que ve los vertices en sentido horario, que es
    /// cuando Cross(b - a, c - a) apunta al observador.
    static void Triangulo(List<int> tri, List<Vector3> v, int a, int b, int c, Vector3 normal)
    {
        Vector3 n = Vector3.Cross(v[b] - v[a], v[c] - v[a]);
        if (n.sqrMagnitude < 1e-12f) return;
        tri.Add(a);
        if (Vector3.Dot(n, normal) >= 0f) { tri.Add(b); tri.Add(c); }
        else { tri.Add(c); tri.Add(b); }
    }

    static void Cuadro(List<int> tri, List<Vector3> v, int a, int b, int c, int d)
    {
        Triangulo(tri, v, a, b, c, Vector3.up);
        Triangulo(tri, v, a, c, d, Vector3.up);
    }

    /// Un tramo de pared de la excavacion, de la cota al fondo, mirando
    /// HACIA EL HUECO (lejos del suelo de esa celda). Una sola cara: la
    /// pared del lado de la camara no tapa el subterraneo.
    static void Pared(List<Vector3> v, List<Vector3> nor, List<Vector2> uv, List<int> tri,
                      Vector3 p, Vector3 q, Vector3 centroSuelo, float yS, float yF)
    {
        Vector3 d = q - p;
        d.y = 0f;
        if (d.sqrMagnitude < 1e-8f) return;
        Vector3 n = new Vector3(d.z, 0f, -d.x).normalized;
        Vector3 medio = 0.5f * (p + q);
        medio.y = 0f;
        if (Vector3.Dot(n, centroSuelo - medio) > 0f) n = -n;

        // u a lo largo de la pared: la proyeccion sobre su direccion.
        Vector3 dir = d.normalized;
        int i0 = v.Count;
        Vector3[] esquinas =
        {
            new Vector3(p.x, yS, p.z), new Vector3(q.x, yS, q.z),
            new Vector3(q.x, yF, q.z), new Vector3(p.x, yF, p.z),
        };
        foreach (Vector3 e in esquinas)
        {
            v.Add(e);
            nor.Add(n);
            float u = (e.x * dir.x + e.z * dir.z) / REPETICION_TIERRA;
            uv.Add(new Vector2(u, e.y / REPETICION_TIERRA));
        }
        Triangulo(tri, v, i0, i0 + 1, i0 + 2, n);
        Triangulo(tri, v, i0, i0 + 2, i0 + 3, n);
    }
}


/// <summary>
/// DONDE va el hueco del suelo: geometria pura en planta (x, y OpenSees,
/// metros), sin tipos de Unity, para poder probarla fuera del editor.
///
/// EN LA BASE HOY NO SE USA: la cota va donde arranca la estructura, no
/// hay nada bajo ella y Calcular() devuelve por su primera rama un solo
/// cuadro de suelo. LO USAN LAS TERRAZAS (desde el 18-09):
/// CalcularTerraza(), al final, recorta la de Ingenieria (3.96 local =
/// -4.01, el segundo N.R.) alrededor de lo que baja a la base, con estas
/// mismas estampas, cierre, techo y apoyos. Todos los numeros de abajo
/// son de cuando el LT2 declaraba -4.01 (el mismo nivel que la terraza),
/// y siguen siendo la medida con la que se eligieron las constantes.
///
/// EL PROBLEMA
/// Bajo la cota hay pocos puntos sueltos: en el LT2, 16 apoyos y 8 muros
/// cortos en un rectangulo de 31 x 16 m, con tramos de fachada de 10 y
/// 12.5 m sin nada. La planta del subterraneo no viene en el JSON: hay que
/// deducirla sin tapar el terreno que SI sostiene al edificio (en el
/// conjunto hay apoyos en terreno en -4.01 a 4.8 m de un muro del
/// subterraneo).
///
/// COMO
/// 1. Estampas: nodos, barras y muros (con su largo) bajo la cota.
/// 2. CIERRE morfologico de radio R_CIERRE: se engorda R y se adelgaza
///    R - MARGEN. Rellena los tramos entre estampas y deja el borde
///    MARGEN afuera. Un rectangulo vuelve rectangulo (con esquinas de
///    radio MARGEN). Los huecos encerrados se rellenan antes de adelgazar.
/// 3. El cierre tambien rellena las esquinas ENTRANTES (hasta unos
///    0.41 R en diagonal), y eso cavaria terreno abierto. Lo acota el
///    TECHO: la planta del edificio en la cota (sus vigas y nodos ahi),
///    cerrada con R_TECHO. Lo rellenado no pasa de ella mas MARGEN.
/// 4. Los APOYOS EN TERRENO (en la cota) mandan cerca de ellos: lo
///    rellenado es hueco solo si el apoyo mas cercano esta al menos
///    VENTAJA_TERRENO mas lejos que la estampa mas cercana. Los apoyos a
///    menos de APOYO_SOBRE_MURO de una estampa se ignoran: estan sobre un
///    muro del subterraneo, no sobre tierra.
/// A MARGEN de una estampa siempre hay hueco: nada bajo la cota queda
/// tapado.
///
/// Las distancias son euclidianas exactas sobre la red (Felzenszwalb y
/// Huttenlocher), en tiempo lineal. Los numeros de los comentarios salen
/// de correr esta clase, copiada tal cual, sobre data/unity/lt2.json y
/// conjunto.json.
/// </summary>
public static class HuecoDelSuelo
{
    // ---- INICIO GEOMETRIA PURA ----

    /// 25 m. El cierre deja una muesca de R - sqrt(R^2 - (g/2)^2) en un
    /// tramo de largo g sin estampas. En el LT2 los tramos de fachada son
    /// de 10 m (pilares de x 22.35 a 32.35) y 12.49 m (x = 11.30, entre
    /// los muros de y 9.84..12.76 y 25.25..28.17): con R = 15 el borde
    /// quedaba 0.24 m ADENTRO de la fachada norte y 0.50 m adentro de la
    /// oeste (el suelo tapaba el perimetro); con R = 25 no queda adentro
    /// en ningun tramo (de 0 a 0.6 m afuera entre estampas, 1 m en ellas;
    /// medido con celda de 0.5 m). Las esquinas entrantes que eso rellena
    /// las acota el techo: en el conjunto, en la esquina del muro x = 7.77
    /// con la fachada norte del LT2, la excavacion llegaba (en y = 68) a
    /// 7.05 m del muro; con el techo, a 1.05.
    public const double R_CIERRE = 25.0;

    /// 1 m de excavacion alrededor de lo estampado: el pie del muro y el
    /// apoyo se ven enteros desde arriba, no pegados a la tierra.
    public const double MARGEN = 1.0;

    /// 4 m: cierra la planta en la cota aunque falte una viga de borde
    /// en un vano de hasta 8 m, y rellena poco las esquinas entrantes
    /// (0.41 x 4 = 1.7 m en diagonal).
    public const double R_TECHO = 4.0;

    /// Cuanto mas lejos que la estampa tiene que estar el apoyo en terreno
    /// para que la celda sea hueco. Con 3 m, los cuatro apoyos en terreno
    /// del conjunto entre el muro x = 18.22 y el eje x = 28.02 quedan con
    /// tierra alrededor (el hueco termina en x = 19.22, a MARGEN del muro).
    public const double VENTAJA_TERRENO = 3.0;

    /// Un apoyo en la cota a menos de esto de una estampa esta SOBRE el
    /// subterraneo (en el conjunto hay apoyos en -4.01 a 0.2 m de muros
    /// que bajan a -7.97): no prueba que haya tierra alrededor.
    public const double APOYO_SOBRE_MURO = MARGEN + 0.5;

    public class Resultado
    {
        public double x0, y0, celda;
        public int nx, ny;              // celdas; muestras (nx+1) x (ny+1)
        public bool[] suelo;            // true = suelo en la muestra (i, j)
        public double areaHueco;        // m2 de muestras sin suelo
        public int apoyosUsados, apoyosSobreSubterraneo;

        public bool Suelo(int i, int j) { return suelo[j * (nx + 1) + i]; }
    }

    /// estampas y techo: {x1, y1, x2, y2} (un punto repite las
    /// coordenadas). apoyos: {x, y}. min/max: la planta del edificio, para
    /// el cuadro cuando no hay nada bajo la cota.
    public static Resultado Calcular(List<double[]> estampas, List<double[]> techo,
                                     List<double[]> apoyos, double celda,
                                     double minX, double minY, double maxX, double maxY)
    {
        Resultado r = new Resultado { celda = celda };
        if (estampas == null || estampas.Count == 0)
        {
            // Sin nada bajo la cota: un solo cuadro sobre la planta.
            r.x0 = minX - 10.0; r.y0 = minY - 10.0;
            r.nx = 1; r.ny = 1;
            r.celda = Math.Max(maxX - minX, maxY - minY) + 20.0;
            r.suelo = new[] { true, true, true, true };
            return r;
        }
        techo = techo ?? new List<double[]>();
        apoyos = apoyos ?? new List<double[]>();

        // La red cubre las estampas con holgura para el engorde (el relleno
        // de encerrados parte del borde, que tiene que quedar afuera) y el
        // techo con holgura para el suyo.
        double x0 = double.MaxValue, y0 = double.MaxValue, x1 = double.MinValue, y1 = double.MinValue;
        Extender(estampas, R_CIERRE + MARGEN + 3.0, ref x0, ref y0, ref x1, ref y1);
        Extender(techo, R_TECHO + MARGEN + 3.0, ref x0, ref y0, ref x1, ref y1);
        r.x0 = x0; r.y0 = y0;
        r.nx = (int)Math.Ceiling((x1 - x0) / celda);
        r.ny = (int)Math.Ceiling((y1 - y0) / celda);
        int w = r.nx + 1, h = r.ny + 1;

        // 1 y 2. Estampas, cierre.
        double[] dEstampa = Distancias(Estampar(estampas, r, w, h), w, h, celda);
        double[] dFuera = DistanciaAFueraDelCierre(dEstampa, R_CIERRE, w, h, celda);

        // 3. Techo (si no hay nada en la cota, no acota).
        double[] dFueraTecho = null;
        if (techo.Count > 0)
            dFueraTecho = DistanciaAFueraDelCierre(
                Distancias(Estampar(techo, r, w, h), w, h, celda), R_TECHO, w, h, celda);

        // 4. Apoyos en terreno.
        bool[] marcaApoyo = new bool[w * h];
        foreach (double[] p in apoyos)
        {
            int i = (int)Math.Round((p[0] - r.x0) / celda);
            int j = (int)Math.Round((p[1] - r.y0) / celda);
            if (i < 0 || i >= w || j < 0 || j >= h) continue;   // lejos: no influye
            if (dEstampa[j * w + i] < APOYO_SOBRE_MURO) { r.apoyosSobreSubterraneo++; continue; }
            marcaApoyo[j * w + i] = true;
            r.apoyosUsados++;
        }
        double[] dApoyo = r.apoyosUsados > 0 ? Distancias(marcaApoyo, w, h, celda) : null;

        r.suelo = new bool[w * h];
        int huecos = 0;
        for (int k = 0; k < r.suelo.Length; k++)
        {
            bool rellenado = dFuera[k] > R_CIERRE - MARGEN
                             && (dFueraTecho == null || dFueraTecho[k] > R_TECHO - MARGEN)
                             && (dApoyo == null || dApoyo[k] >= dEstampa[k] + VENTAJA_TERRENO);
            bool hueco = dEstampa[k] <= MARGEN || rellenado;
            r.suelo[k] = !hueco;
            if (hueco) huecos++;
        }
        r.areaHueco = huecos * celda * celda;
        return r;
    }

    static void Extender(List<double[]> segs, double holgura,
                         ref double x0, ref double y0, ref double x1, ref double y1)
    {
        foreach (double[] e in segs)
        {
            x0 = Math.Min(x0, Math.Min(e[0], e[2]) - holgura); x1 = Math.Max(x1, Math.Max(e[0], e[2]) + holgura);
            y0 = Math.Min(y0, Math.Min(e[1], e[3]) - holgura); y1 = Math.Max(y1, Math.Max(e[1], e[3]) + holgura);
        }
    }

    /// Marca las muestras que tocan cada segmento (paso de media celda).
    static bool[] Estampar(List<double[]> segs, Resultado r, int w, int h)
    {
        bool[] marca = new bool[w * h];
        foreach (double[] e in segs)
        {
            double dx = e[2] - e[0], dy = e[3] - e[1];
            int pasos = Math.Max(1, (int)Math.Ceiling(Math.Sqrt(dx * dx + dy * dy) / (0.5 * r.celda)));
            for (int k = 0; k <= pasos; k++)
            {
                double t = (double)k / pasos;
                int i = (int)Math.Round((e[0] + t * dx - r.x0) / r.celda);
                int j = (int)Math.Round((e[1] + t * dy - r.y0) / r.celda);
                if (i >= 0 && i < w && j >= 0 && j < h) marca[j * w + i] = true;
            }
        }
        return marca;
    }

    /// Engorda a 'radio' lo marcado (dMarca <= radio), rellena lo
    /// encerrado y devuelve la distancia de cada muestra a lo que quedo
    /// AFUERA. "dentro del cierre con margen m" = resultado > radio - m.
    static double[] DistanciaAFueraDelCierre(double[] dMarca, double radio, int w, int h, double celda)
    {
        bool[] gordo = new bool[w * h];
        for (int k = 0; k < gordo.Length; k++) gordo[k] = dMarca[k] <= radio;
        RellenarEncerrados(gordo, w, h);
        for (int k = 0; k < gordo.Length; k++) gordo[k] = !gordo[k];
        return Distancias(gordo, w, h, celda);
    }

    /// Distancia euclidiana (m) de cada muestra a la marcada mas cercana.
    /// Sin marcas, todo queda en ~1e10.
    static double[] Distancias(bool[] marcado, int w, int h, double celda)
    {
        const double INF = 1e20;
        int n = Math.Max(w, h);
        double[] f = new double[w * h];
        for (int k = 0; k < f.Length; k++) f[k] = marcado[k] ? 0.0 : INF;
        double[] col = new double[n], d = new double[n], z = new double[n + 1];
        int[] v = new int[n];
        for (int x = 0; x < w; x++)
        {
            for (int y = 0; y < h; y++) col[y] = f[y * w + x];
            Transformada1D(col, h, d, v, z);
            for (int y = 0; y < h; y++) f[y * w + x] = d[y];
        }
        for (int y = 0; y < h; y++)
        {
            for (int x = 0; x < w; x++) col[x] = f[y * w + x];
            Transformada1D(col, w, d, v, z);
            for (int x = 0; x < w; x++) f[y * w + x] = d[x];
        }
        for (int k = 0; k < f.Length; k++) f[k] = Math.Sqrt(f[k]) * celda;
        return f;
    }

    /// La envolvente inferior de parabolas (Felzenszwalb y Huttenlocher
    /// 2012): distancia al cuadrado en 1D, en celdas.
    static void Transformada1D(double[] f, int n, double[] d, int[] v, double[] z)
    {
        const double INF = 1e20;
        int k = 0;
        v[0] = 0; z[0] = -INF; z[1] = INF;
        for (int q = 1; q < n; q++)
        {
            double s = ((f[q] + (double)q * q) - (f[v[k]] + (double)v[k] * v[k])) / (2.0 * q - 2.0 * v[k]);
            while (s <= z[k])
            {
                k--;
                s = ((f[q] + (double)q * q) - (f[v[k]] + (double)v[k] * v[k])) / (2.0 * q - 2.0 * v[k]);
            }
            k++;
            v[k] = q; z[k] = s; z[k + 1] = INF;
        }
        k = 0;
        for (int q = 0; q < n; q++)
        {
            while (z[k + 1] < q) k++;
            double dq = q - v[k];
            d[q] = dq * dq + f[v[k]];
        }
    }

    /// Marca como 'true' lo que no se alcanza desde el borde de la red
    /// caminando por 'false' (4 vecinos): los huecos encerrados.
    static void RellenarEncerrados(bool[] lleno, int w, int h)
    {
        bool[] visto = new bool[w * h];
        Stack<int> pila = new Stack<int>();
        for (int x = 0; x < w; x++) { Sembrar(x, 0); Sembrar(x, h - 1); }
        for (int y = 0; y < h; y++) { Sembrar(0, y); Sembrar(w - 1, y); }
        while (pila.Count > 0)
        {
            int k = pila.Pop();
            int x = k % w, y = k / w;
            if (x > 0) Sembrar(x - 1, y);
            if (x < w - 1) Sembrar(x + 1, y);
            if (y > 0) Sembrar(x, y - 1);
            if (y < h - 1) Sembrar(x, y + 1);
        }
        for (int k = 0; k < lleno.Length; k++) if (!lleno[k] && !visto[k]) lleno[k] = true;

        void Sembrar(int x, int y)
        {
            int k = y * w + x;
            if (lleno[k] || visto[k]) return;
            visto[k] = true;
            pila.Push(k);
        }
    }

    // ------------------------------------------------------------
    // LA TERRAZA (la dibuja AmbienteVisor.Terrazas.cs). Va al final de
    // la clase a proposito: los documentos citan lineas (CLAUDE.md 6).
    // ------------------------------------------------------------

    /// 0.35 m del eje en planta de lo que baja a la base. Ahi la terraza
    /// se recorta SIEMPRE, para que la pieza no quede enterrada (media
    /// columna de 0.50 son 0.25 m; medio muro de 0.30, 0.15). Y un apoyo de
    /// la terraza a menos de esto de una estampa esta SOBRE esa pieza, no
    /// sobre tierra: no reclama tierra alrededor. Medido en Ingenieria: los
    /// 6 apoyos del recinto de muros del suroeste estan a 0.00-0.25 m del
    /// eje de un muro que baja a la base (encima de el); el que sigue,
    /// (23.02, 64.10), a 0.60 m del muro y = 64.70, y ese queda en tierra.
    public const double HOLGURA_TERRAZA = 0.35;

    /// La terraza de un nivel sobre la red: 'suelo' = la muestra cae en la
    /// region (algun poligono de 'region', x, y OpenSees) y ahi no se
    /// recorta. Con las mismas entradas que Calcular() --estampas: lo que
    /// queda bajo la cara de la terraza; techo: lo que esta en su cara;
    /// apoyos: los apoyos en su cara-- se recorta:
    ///   - a HOLGURA_TERRAZA de una estampa, siempre;
    ///   - a MARGEN de una estampa, salvo donde un apoyo de la terraza esta
    ///     mas cerca que la estampa (ese punto es del apoyo, que queda con
    ///     tierra debajo);
    ///   - lo rellenado del cierre, igual que en Calcular(): un recinto de
    ///     muros que baja a la base se ve entero, como un pozo.
    /// Dos diferencias con Calcular(), por lo mismo: el apoyo que no cuenta
    /// es el que esta SOBRE la estructura (HOLGURA_TERRAZA, medido exacto
    /// sobre el segmento y no sobre la red), no el que esta a menos de
    /// APOYO_SOBRE_MURO (1.5 m); y el anillo de MARGEN cede al apoyo mas
    /// cercano. Con las reglas de Calcular(), el apoyo (23.02, 64.10) de
    /// Ingenieria quedaba colgando sobre el hueco a 0.45 m de la cara de un
    /// muro, y la esquina entre los muros x = 18.22 e y = 64.70 se cavaba.
    public static Resultado CalcularTerraza(List<List<double[]>> region, List<double[]> estampas,
                                            List<double[]> techo, List<double[]> apoyos, double celda)
    {
        Resultado r = new Resultado { celda = celda };
        estampas = estampas ?? new List<double[]>();
        techo = techo ?? new List<double[]>();
        apoyos = apoyos ?? new List<double[]>();

        // La red: la region con dos celdas de holgura (su borde queda
        // adentro de la red y lleva pared), y lo demas con la del cierre.
        double x0 = double.MaxValue, y0 = double.MaxValue, x1 = double.MinValue, y1 = double.MinValue;
        foreach (List<double[]> poli in region)
            foreach (double[] p in poli)
            {
                x0 = Math.Min(x0, p[0] - 2.0 * celda); x1 = Math.Max(x1, p[0] + 2.0 * celda);
                y0 = Math.Min(y0, p[1] - 2.0 * celda); y1 = Math.Max(y1, p[1] + 2.0 * celda);
            }
        if (x0 > x1)
        {
            r.nx = 1; r.ny = 1; r.suelo = new bool[4];
            return r;
        }
        Extender(estampas, R_CIERRE + MARGEN + 3.0, ref x0, ref y0, ref x1, ref y1);
        Extender(techo, R_TECHO + MARGEN + 3.0, ref x0, ref y0, ref x1, ref y1);
        r.x0 = x0; r.y0 = y0;
        r.nx = (int)Math.Ceiling((x1 - x0) / celda);
        r.ny = (int)Math.Ceiling((y1 - y0) / celda);
        int w = r.nx + 1, h = r.ny + 1;
        r.suelo = new bool[w * h];

        double[] dEstampa = null, dFuera = null, dFueraTecho = null, dApoyo = null;
        if (estampas.Count > 0)
        {
            dEstampa = Distancias(Estampar(estampas, r, w, h), w, h, celda);
            dFuera = DistanciaAFueraDelCierre(dEstampa, R_CIERRE, w, h, celda);
            if (techo.Count > 0)
                dFueraTecho = DistanciaAFueraDelCierre(
                    Distancias(Estampar(techo, r, w, h), w, h, celda), R_TECHO, w, h, celda);
        }

        bool[] marcaApoyo = new bool[w * h];
        foreach (double[] p in apoyos)
        {
            if (!EnRegion(p[0], p[1], region)) continue;         // de otra terraza
            if (DistanciaASegmentos(p[0], p[1], estampas) < HOLGURA_TERRAZA)
            {
                r.apoyosSobreSubterraneo++;                     // sobre la estructura
                continue;
            }
            int i = (int)Math.Round((p[0] - r.x0) / celda);
            int j = (int)Math.Round((p[1] - r.y0) / celda);
            if (i < 0 || i >= w || j < 0 || j >= h) continue;
            marcaApoyo[j * w + i] = true;
            r.apoyosUsados++;                                   // sobre tierra
        }
        if (r.apoyosUsados > 0) dApoyo = Distancias(marcaApoyo, w, h, celda);

        int huecos = 0;
        for (int j = 0; j < h; j++)
        {
            for (int i = 0; i < w; i++)
            {
                if (!EnRegion(r.x0 + i * celda, r.y0 + j * celda, region)) continue;
                int k = j * w + i;
                bool hueco = false;
                if (dEstampa != null)
                {
                    double dA = dApoyo != null ? dApoyo[k] : double.MaxValue;
                    bool rellenado = dFuera[k] > R_CIERRE - MARGEN
                                     && (dFueraTecho == null || dFueraTecho[k] > R_TECHO - MARGEN)
                                     && dA >= dEstampa[k] + VENTAJA_TERRENO;
                    hueco = dEstampa[k] <= HOLGURA_TERRAZA
                            || (dEstampa[k] <= MARGEN && dEstampa[k] < dA)
                            || rellenado;
                }
                r.suelo[k] = !hueco;
                if (hueco) huecos++;
            }
        }
        r.areaHueco = huecos * celda * celda;
        return r;
    }

    /// Si (x, y) cae en algun poligono (borde incluido, a 1e-6 m).
    public static bool EnRegion(double x, double y, List<List<double[]>> region)
    {
        foreach (List<double[]> poli in region)
        {
            bool dentro = false;
            for (int k = 0, n = poli.Count; k < n; k++)
            {
                double[] a = poli[(k + n - 1) % n], b = poli[k];
                double lx = b[0] - a[0], ly = b[1] - a[1];
                if (Math.Abs(lx * (y - a[1]) - ly * (x - a[0])) <= 1e-6 * Math.Max(Math.Sqrt(lx * lx + ly * ly), 1.0)
                    && x >= Math.Min(a[0], b[0]) - 1e-6 && x <= Math.Max(a[0], b[0]) + 1e-6
                    && y >= Math.Min(a[1], b[1]) - 1e-6 && y <= Math.Max(a[1], b[1]) + 1e-6)
                    return true;
                if ((a[1] > y) != (b[1] > y) && x < a[0] + (y - a[1]) * lx / ly) dentro = !dentro;
            }
            if (dentro) return true;
        }
        return false;
    }

    /// Distancia (m) de (x, y) al segmento {x1, y1, x2, y2} mas cercano.
    static double DistanciaASegmentos(double x, double y, List<double[]> segs)
    {
        double mejor = double.MaxValue;
        foreach (double[] s in segs)
        {
            double lx = s[2] - s[0], ly = s[3] - s[1], l2 = lx * lx + ly * ly;
            double u = l2 < 1e-12 ? 0.0 : Math.Max(0.0, Math.Min(1.0, ((x - s[0]) * lx + (y - s[1]) * ly) / l2));
            double dx = x - s[0] - u * lx, dy = y - s[1] - u * ly;
            mejor = Math.Min(mejor, Math.Sqrt(dx * dx + dy * dy));
        }
        return mejor;
    }

    // ---- FIN GEOMETRIA PURA ----
}
