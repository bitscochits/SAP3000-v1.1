/*
================================================================
  VisorSemana04.Mapa.cs   (parte de VisorSemana04)
================================================================
  El mapa demanda/capacidad: pinta cada barra del edificio con el
  color de su u en el caso activo, y en el panel pone la leyenda con
  "NO PASA n/m" y la lista de criticos con un boton "Ir".

  Contesta "cuanta capacidad tiene?" para TODO el edificio de una vez.
  Hasta la Semana 4 habia que ir barra por barra abriendo la ventana
  P-M para encontrar las que no pasan.

  ----------------------------------------------------------------
  REGLA QUE NO SE ROMPE: aca no se calcula capacidad
  ----------------------------------------------------------------
  u = M / Mn(P) y PASA los escribe Python (semana04/exportar_unity.py,
  'pasa': u <= 1.0; u = 9999 cuando P cae fuera de la curva). Aca solo
  se LEEN u y pasa, se elige un color con PanelUI.ColorDemandaCapacidad
  (la misma definicion que usan la leyenda y el inspector) y se ordena
  la lista. Contar y ordenar no es calcular estructura.

  ----------------------------------------------------------------
  COLORES (PanelUI.ColorDemandaCapacidad)
  ----------------------------------------------------------------
      verde    pasa y u < 0.7
      amarillo pasa y u >= 0.7     (umbral de LECTURA, no de diseno)
      rojo     NO PASA (pasa = false del JSON)
      morado   u = 9999: P fuera de la curva, u no definido
      gris     sin fierro: la barra no tiene curva P-M

  ----------------------------------------------------------------
  PROTOCOLO DE MATERIALES (semana05/CONTRATO.md, seccion 8)
  ----------------------------------------------------------------
  Dos scripts cambian el sharedMaterial de la estructura: AmbienteVisor
  (vista realista o tecnica) y este mapa. Para que no se pisen:

  1. El mapa NO escucha Redibujado. Escucha MaterialesCambiados, que
     llega DESPUES de que AmbienteVisor puso la vista en los renderers
     nuevos (EventosVisor.AvisarRedibujado avisa en ese orden).
  2. Al activarse y en cada MaterialesCambiados: guarda como "base" el
     sharedMaterial que tiene cada renderer -- SALVO que sea uno de los
     materiales del mapa -- y pinta encima. Por esa excepcion recibir
     el aviso dos veces no corrompe la base: la segunda vez el renderer
     ya tiene un material del mapa y la base queda como estaba.
  3. Al apagarse devuelve la base a los renderers que siguen vivos y
     que siguen con un material del mapa (si otro los pinto despues,
     manda el otro).
  4. Al cambiar el caso activo (o volver a registrarse uno con el mismo
     nombre: versionCasos) no hay aviso de materiales: LateUpdate lo
     nota y repinta.
  5. Un material por color, cacheado; nunca renderer.material (crea
     una copia por objeto).

  Prioridad visual: mapa D/C > realista > tecnica.

  Si el anexo no calza con el modelo del visor (otro edificio, o el
  modelo se edito despues de exportar), el mapa NO pinta: los mismos
  ids serian otras barras, o esfuerzos de una geometria que ya no es.

  ----------------------------------------------------------------
  PANEL (seccion "Mapa demanda / capacidad" de la pestana Caso)
  ----------------------------------------------------------------
  - "NO PASA n/m" con VisorSemana04.ContarDemandas, la misma funcion de
    la cabecera de VisorQA: los dos numeros no pueden diferir.
  - Leyenda con cuantas demandas caen en cada color (de todo el anexo;
    el filtro de piso solo cambia lo que se pinta).
  - "Ver el caso con mas NO PASA": elige el caso con mas pasa = false
    (con empate, el primero del anexo). Es la foto de la demo.
  - Criticos del caso activo ordenados por u, cada uno con "Ir", que
    selecciona la barra por VisorQA y centra la camara con
    EventosVisor.PedirCentrar (IrA, en Panel.cs: lo comparten los
    botones de demo).
================================================================
*/

using System.Collections.Generic;
using UnityEngine;

public partial class VisorSemana04
{
    // Cuantos criticos se listan antes de "ver todos". Diez caben en el
    // panel sin scroll largo y cubren los NO PASA del LT2 (el peor caso
    // del anexo tiene 4).
    const int MAPA_CRITICOS_CORTA = 10;

    // --- estado del mapa ---
    private bool Mapa_activo = false;
    private bool Mapa_suscrito = false;
    private string Mapa_motivo = "";
    private int Mapa_nPintadas = 0;

    // Lo que habia en cada renderer antes de pintar (protocolo, paso 2).
    private readonly Dictionary<Renderer, Material> Mapa_base =
        new Dictionary<Renderer, Material>();
    private readonly List<Renderer> Mapa_muertos = new List<Renderer>();

    // Materiales propios: por color para no crear uno por barra, y en un
    // conjunto para reconocerlos al guardar la base.
    private readonly Dictionary<Color, Material> Mapa_materiales =
        new Dictionary<Color, Material>();
    private readonly HashSet<Material> Mapa_propios = new HashSet<Material>();

    // Con que se pinto por ultima vez: si cambia, LateUpdate repinta.
    private string Mapa_casoPintado = null;
    private int Mapa_versionPintada = -1;
    private bool Mapa_calzabaAlPintar = false;

    // --- leyenda y lista, rehechas solo si cambia el caso ---
    private readonly List<DemandaS4> Mapa_criticos = new List<DemandaS4>();
    private CasoS4 Mapa_casoResumen = null;
    private int Mapa_versionResumen = -1;
    private AnexoSemana04 Mapa_anexoResumen = null;
    private int Mapa_holgados, Mapa_cerca, Mapa_rojos, Mapa_fuera, Mapa_noPasan, Mapa_total;
    private int Mapa_sinFamilia;
    private bool Mapa_verTodos = false;

    // ============================================================
    // API
    // ============================================================

    /// true si el mapa esta encendido (aunque no pueda pintar: ver el
    /// motivo en el panel).
    public bool MapaDCActivo { get { return Mapa_activo; } }

    /// Cuantas barras de la escena tienen hoy un color del mapa. Para el
    /// registro numerico de las capturas.
    public int MapaDCPintadas { get { return Mapa_nPintadas; } }

    /// Enciende o apaga el mapa. Encender guarda la base y pinta; apagar
    /// devuelve la base. Desde OnGUI, diferirlo (lo hace el toggle).
    public void MostrarMapaDC(bool activo)
    {
        if (activo == Mapa_activo) return;
        Mapa_activo = activo;
        if (activo)
        {
            Mapa_Suscribir();
            Mapa_Pintar();
        }
        else
        {
            Mapa_Restaurar();
            Mapa_Desuscribir();
            Mapa_motivo = "";
        }
    }

    /// El caso del anexo con mas demandas que NO PASAN (pasa = false del
    /// JSON); con empate, el primero en el anexo. null si no hay anexo.
    /// Para que la demo y las capturas muestren el mapa donde mas dice.
    public string CasoConMasNoPasa()
    {
        return Anexo != null ? Mapa_CasoConMasNoPasa(Anexo.casos) : null;
    }

    static string Mapa_CasoConMasNoPasa(List<CasoS4> casos)
    {
        if (casos == null) return null;
        string mejor = null;
        int mayor = -1;
        foreach (CasoS4 c in casos)
        {
            if (c == null) continue;
            int noPasan, fuera, total;
            ContarDemandas(c, out noPasan, out fuera, out total);
            if (noPasan > mayor) { mayor = noPasan; mejor = c.nombre; }
        }
        return mejor;
    }

    // ============================================================
    // EVENTOS
    // ============================================================

    // Se suscribe al ENCENDER y no en OnEnable: VisorSemana04 lo reparten
    // varios archivos y dos OnEnable en la misma clase no compilan (el
    // OnEnable es de VisorSemana04.cs). Al destruirse se da de baja en el
    // OnDestroy del final; y si igual llegara un aviso tardio, el propio
    // suscriptor se da de baja (un MonoBehaviour destruido compara a null).
    void Mapa_Suscribir()
    {
        if (Mapa_suscrito) return;
        EventosVisor.MaterialesCambiados += Mapa_AlCambiarMateriales;
        Mapa_suscrito = true;
    }

    void Mapa_Desuscribir()
    {
        if (!Mapa_suscrito) return;
        EventosVisor.MaterialesCambiados -= Mapa_AlCambiarMateriales;
        Mapa_suscrito = false;
    }

    void Mapa_AlCambiarMateriales()
    {
        if (this == null)
        {
            EventosVisor.MaterialesCambiados -= Mapa_AlCambiarMateriales;
            return;
        }
        if (Mapa_activo) Mapa_Pintar();
    }

    /// Lo llama LateUpdate (Panel.cs) en cada frame. Barato: compara tres
    /// valores y sale.
    void Mapa_Actualizar()
    {
        if (!Mapa_activo) return;
        if (casoActivo != Mapa_casoPintado || versionCasos != Mapa_versionPintada
            || AnexoCalzaConElModelo != Mapa_calzabaAlPintar)
            Mapa_Pintar();
    }

    // ============================================================
    // PINTAR Y RESTAURAR
    // ============================================================
    void Mapa_Pintar()
    {
        Mapa_casoPintado = casoActivo;
        Mapa_versionPintada = versionCasos;
        Mapa_calzabaAlPintar = AnexoCalzaConElModelo;
        Mapa_PurgarMuertos();

        string motivo = Mapa_MotivoParaNoPintar();
        if (motivo != null)
        {
            // Se devuelve la base: dejar los colores de otro caso u otro
            // modelo seria peor que no mostrar nada. El mapa sigue
            // encendido y vuelve a pintar cuando se pueda.
            Mapa_Restaurar();
            Mapa_motivo = motivo;
            return;
        }
        Mapa_motivo = "";

        int pintadas = 0;
        foreach (KeyValuePair<int, GameObject> kv in visor.ObjetosDeElementos)
        {
            if (kv.Value == null) continue;
            Renderer r = kv.Value.GetComponent<Renderer>();
            if (r == null) continue;

            Material actual = r.sharedMaterial;
            if (actual == null || !Mapa_propios.Contains(actual)) Mapa_base[r] = actual;
            r.sharedMaterial = Mapa_MaterialDe(Mapa_ColorDe(kv.Key));
            pintadas++;
        }
        Mapa_nPintadas = pintadas;
    }

    /// null si se puede pintar; si no, por que, en una linea para el panel.
    string Mapa_MotivoParaNoPintar()
    {
        if (Anexo == null) return "no hay anexo de Semana 4";
        if (visor == null || visor.Modelo == null) return "el visor todavia no cargo el modelo";
        if (!AnexoCalzaConElModelo)
            return "el anexo no calza con el modelo del visor (otro edificio o modelo editado)";
        if (CasoActivo() == null) return $"el caso activo '{casoActivo}' no esta en el anexo";
        return null;
    }

    /// Devuelve la base a los renderers vivos que siguen con un color del
    /// mapa. Si otro script los pinto despues, se respeta lo suyo.
    void Mapa_Restaurar()
    {
        foreach (KeyValuePair<Renderer, Material> kv in Mapa_base)
        {
            Renderer r = kv.Key;
            if (r == null) continue;
            Material actual = r.sharedMaterial;
            if (actual != null && Mapa_propios.Contains(actual)) r.sharedMaterial = kv.Value;
        }
        Mapa_base.Clear();
        Mapa_nPintadas = 0;
    }

    /// Redibujar destruye los objetos: sus entradas ya no sirven.
    void Mapa_PurgarMuertos()
    {
        Mapa_muertos.Clear();
        foreach (Renderer r in Mapa_base.Keys)
            if (r == null) Mapa_muertos.Add(r);
        foreach (Renderer r in Mapa_muertos) Mapa_base.Remove(r);
        Mapa_muertos.Clear();
    }

    /// El color de una barra del modelo en el caso activo. Una barra que
    /// no esta en el anexo o no tiene demanda en este caso va en gris,
    /// como una sin fierro: no hay u que mostrar.
    Color Mapa_ColorDe(int id)
    {
        DemandaS4 d = PM_FamiliaDe(ElementoPorId(id)) != null ? DemandaDe(id, casoActivo) : null;
        return d == null
            ? PanelUI.ColorDemandaCapacidad(false, 0f, true)
            : PanelUI.ColorDemandaCapacidad(true, d.u, d.pasa);
    }

    Material Mapa_MaterialDe(Color color)
    {
        Material mat;
        if (Mapa_materiales.TryGetValue(color, out mat) && mat != null) return mat;
        // Lit como la estructura: el mapa se lee con luz y sombra, en la
        // vista realista y en la tecnica.
        mat = new Material(VisorEstructura.ShaderCompatible());
        mat.name = "MapaDC_" + ColorUtility.ToHtmlStringRGB(color);
        mat.color = color;
        if (mat.HasProperty("_BaseColor")) mat.SetColor("_BaseColor", color);
        if (mat.HasProperty("_Smoothness")) mat.SetFloat("_Smoothness", 0.15f);
        Mapa_materiales[color] = mat;
        Mapa_propios.Add(mat);
        return mat;
    }

    // ============================================================
    // LEYENDA Y CRITICOS (datos)
    // ============================================================

    /// Conteos por color y lista ordenada del caso activo. Se rehace solo
    /// si cambia el caso (el objeto: registrar uno externo lo reemplaza),
    /// versionCasos o el anexo, y solo en el Layout (ver
    /// Mapa_DibujarControles).
    void Mapa_ArmarResumen()
    {
        CasoS4 caso = CasoActivo();
        if (caso == Mapa_casoResumen && versionCasos == Mapa_versionResumen
            && Anexo == Mapa_anexoResumen)
            return;
        Mapa_casoResumen = caso;
        Mapa_versionResumen = versionCasos;
        Mapa_anexoResumen = Anexo;

        // "NO PASA n/m" con la MISMA funcion que la cabecera del panel.
        ContarDemandas(caso, out Mapa_noPasan, out Mapa_fuera, out Mapa_total);
        Mapa_Clasificar(caso, out Mapa_holgados, out Mapa_cerca, out Mapa_rojos, out int moradas);

        Mapa_criticos.Clear();
        if (caso != null && caso.demandas != null)
            foreach (DemandaS4 d in caso.demandas)
                if (d != null) Mapa_criticos.Add(d);
        Mapa_criticos.Sort(Mapa_OrdenCriticos);

        Mapa_sinFamilia = 0;
        if (Anexo != null && Anexo.elementos != null)
            foreach (ElementoS4 e in Anexo.elementos)
                if (PM_FamiliaDe(e) == null) Mapa_sinFamilia++;

        // El peor caso, para el boton "ver": cambia solo si cambian los
        // casos (versionCasos o cuantos hay).
        int cuantos = Anexo != null && Anexo.casos != null ? Anexo.casos.Count : 0;
        if (cuantos != Mapa_cuantosPeor || versionCasos != Mapa_versionPeor || Anexo != Mapa_anexoPeor)
        {
            Mapa_cuantosPeor = cuantos;
            Mapa_versionPeor = versionCasos;
            Mapa_anexoPeor = Anexo;
            Mapa_peorCaso = CasoConMasNoPasa();
            int f, t;
            Mapa_peorNoPasan = 0;
            CasoS4 peor = null;
            if (Mapa_peorCaso != null && Anexo != null)
                peor = Anexo.casos.Find(c => c != null && c.nombre == Mapa_peorCaso);
            ContarDemandas(peor, out Mapa_peorNoPasan, out f, out t);
        }
    }

    /// Cuantas demandas caen en cada color del mapa. Se clasifica con el
    /// color que devuelve PanelUI.ColorDemandaCapacidad, no con otra copia
    /// de los umbrales: la leyenda cuenta lo mismo que se pinta.
    static void Mapa_Clasificar(CasoS4 caso, out int verdes, out int amarillas,
                                out int rojas, out int moradas)
    {
        verdes = amarillas = rojas = moradas = 0;
        if (caso == null || caso.demandas == null) return;
        foreach (DemandaS4 d in caso.demandas)
        {
            if (d == null) continue;
            Color c = PanelUI.ColorDemandaCapacidad(true, d.u, d.pasa);
            if (c == PanelUI.ColorDC_FueraDeCurva) moradas++;
            else if (c == PanelUI.ColorDC_NoPasa) rojas++;
            else if (c == PanelUI.ColorDC_Cerca) amarillas++;
            else verdes++;
        }
    }

    /// Primero las que NO PASAN, despues por u de mayor a menor (u = 9999,
    /// fuera de la curva, queda arriba), y a igual u por id, para que la
    /// lista no salte de un frame a otro.
    static int Mapa_OrdenCriticos(DemandaS4 a, DemandaS4 b)
    {
        int c = a.pasa.CompareTo(b.pasa);          // false antes que true
        if (c != 0) return c;
        c = b.u.CompareTo(a.u);
        if (c != 0) return c;
        return a.id.CompareTo(b.id);
    }

    // ============================================================
    // PANEL (dentro de DibujarControles, pestana Caso)
    // ============================================================

    // El peor caso del anexo (boton "ver").
    private string Mapa_peorCaso = null;
    private int Mapa_peorNoPasan = 0;
    private int Mapa_cuantosPeor = -1, Mapa_versionPeor = -1;
    private AnexoSemana04 Mapa_anexoPeor = null;

    // Lo que decide que controles hay, congelado en el Layout (el mismo
    // cuidado que Panel.cs: IMGUI exige los mismos controles en todos los
    // eventos de un frame).
    private bool Mapa_activoEnLayout = false;
    private string Mapa_motivoEnLayout = "";
    private bool Mapa_verTodosEnLayout = false;
    private int Mapa_pintadasEnLayout = 0;
    private readonly HashSet<int> Mapa_ocultasEnLayout = new HashSet<int>();

    void Mapa_DibujarControles()
    {
        if (!PanelUI.Plegable("mapa.dc", "Mapa demanda / capacidad", true)) return;

        if (Event.current.type == EventType.Layout)
        {
            Mapa_ArmarResumen();
            Mapa_activoEnLayout = Mapa_activo;
            Mapa_motivoEnLayout = Mapa_motivo ?? "";
            Mapa_verTodosEnLayout = Mapa_verTodos;
            Mapa_pintadasEnLayout = Mapa_nPintadas;
            Mapa_ocultasEnLayout.Clear();
            int n = Mapa_verTodos ? Mapa_criticos.Count : Mathf.Min(MAPA_CRITICOS_CORTA, Mapa_criticos.Count);
            for (int i = 0; i < n; i++)
                if (visor == null || visor.ObjetoDeElemento(Mapa_criticos[i].id) == null)
                    Mapa_ocultasEnLayout.Add(Mapa_criticos[i].id);
        }

        bool quiere = Pnl_Toggle(Mapa_activoEnLayout, "Pintar el edificio por u (caso activo)");
        if (quiere != Mapa_activoEnLayout) Diferir(() => MostrarMapaDC(quiere));
        if (Mapa_activoEnLayout && Mapa_motivoEnLayout.Length > 0)
            GUILayout.Label("sin mapa: " + Mapa_motivoEnLayout, PanelUI.Aviso);

        // El mismo texto que la cabecera de VisorQA: un caso sin demandas
        // no es "NO PASA 0/0" en verde (pareceria que todo pasa).
        GUILayout.BeginHorizontal();
        PanelUI.Insignia(PanelUI.TextoDemanda(Mapa_noPasan, Mapa_fuera, Mapa_total),
                         Mapa_total == 0 ? PanelUI.Tenue : (Mapa_noPasan > 0 ? PanelUI.NoPasa : PanelUI.Pasa));
        GUILayout.Label("  en " + Mapa_NombreDe(Mapa_casoResumen), PanelUI.Tenue);
        GUILayout.EndHorizontal();

        string umbral = F(PanelUI.UMBRAL_DC_CERCA, "0.0");
        Mapa_FilaLeyenda(PanelUI.ColorDC_Holgado, $"pasa, u < {umbral}", Mapa_holgados);
        Mapa_FilaLeyenda(PanelUI.ColorDC_Cerca, $"pasa, u >= {umbral}", Mapa_cerca);
        Mapa_FilaLeyenda(PanelUI.ColorDC_NoPasa, "NO PASA (u > 1)", Mapa_rojos);
        Mapa_FilaLeyenda(PanelUI.ColorDC_FueraDeCurva, "P fuera de la curva: NO PASA", Mapa_fuera);
        Mapa_FilaLeyenda(PanelUI.ColorDC_SinFamilia, "sin fierro: no tiene curva P-M", Mapa_sinFamilia);
        GUILayout.Label("u = M / Mn(P) y PASA vienen del JSON (Python). Aca no se calcula nada. "
                        + "Los conteos son de todo el anexo; el filtro de piso solo cambia lo que "
                        + "se pinta.", PanelUI.Tenue);
        if (Mapa_activoEnLayout && Mapa_motivoEnLayout.Length == 0)
            GUILayout.Label($"en la escena: {Mapa_pintadasEnLayout} barras pintadas", PanelUI.Tenue);

        // El caso que mas dice el mapa, a un click (la captura de la demo).
        if (Mapa_peorCaso != null && Mapa_peorNoPasan > 0)
        {
            string peor = Mapa_peorCaso;
            if (GUILayout.Button($"Ver el caso con mas NO PASA: {peor} ({Mapa_peorNoPasan})", PanelUI.Boton))
                Diferir(() => ElegirCaso(peor));
        }

        if (!PanelUI.Plegable("mapa.criticos", "Criticos del caso activo", true)) return;
        if (Mapa_criticos.Count == 0)
        {
            GUILayout.Label("(este caso no trae demandas)", PanelUI.Tenue);
            return;
        }
        GUILayout.Label("primero los que no pasan, despues por u", PanelUI.Tenue);
        int cuantas = Mapa_verTodosEnLayout ? Mapa_criticos.Count
                                           : Mathf.Min(MAPA_CRITICOS_CORTA, Mapa_criticos.Count);
        for (int i = 0; i < cuantas; i++) Mapa_FilaCritico(Mapa_criticos[i]);
        if (Mapa_criticos.Count > MAPA_CRITICOS_CORTA)
        {
            string texto = Mapa_verTodosEnLayout ? $"ver solo los {MAPA_CRITICOS_CORTA} primeros"
                                                 : $"ver los {Mapa_criticos.Count}";
            if (GUILayout.Button(texto, PanelUI.Boton)) Diferir(() => Mapa_verTodos = !Mapa_verTodos);
        }
    }

    static string Mapa_NombreDe(CasoS4 caso)
    {
        return caso != null ? caso.nombre : "(sin caso activo)";
    }

    void Mapa_FilaLeyenda(Color color, string texto, int cuantas)
    {
        GUILayout.BeginHorizontal();
        Mapa_Muestra(color);
        GUILayout.Label($"{cuantas,4}  {texto}", PanelUI.Texto);
        GUILayout.EndHorizontal();
    }

    void Mapa_FilaCritico(DemandaS4 d)
    {
        ElementoS4 e = ElementoPorId(d.id);
        bool fuera = d.u >= PanelUI.U_FUERA_DE_CURVA;
        GUILayout.BeginHorizontal();
        Mapa_Muestra(PanelUI.ColorDemandaCapacidad(true, d.u, d.pasa));
        GUILayout.Label($"{d.id,5} {(e != null ? e.tipo : "?"),-8} u {(fuera ? "  --- " : F(d.u, "0.000"))}",
                        PanelUI.Mono, GUILayout.ExpandWidth(false));
        if (fuera) PanelUI.Insignia("fuera de curva", PanelUI.NoPasa);
        else PanelUI.Insignia(d.pasa);
        if (Mapa_ocultasEnLayout.Contains(d.id))
            GUILayout.Label("(oculta)", PanelUI.Tenue, GUILayout.ExpandWidth(false));
        GUILayout.FlexibleSpace();
        int id = d.id;
        if (GUILayout.Button("Ir", PanelUI.Boton, GUILayout.Width(PanelUI.Px(44f))))
            Diferir(() => IrA(id));
        GUILayout.EndHorizontal();
    }

    /// Un cuadrado del color, del alto de una linea de texto.
    static void Mapa_Muestra(Color color)
    {
        Rect fila = GUILayoutUtility.GetRect(GUIContent.none, PanelUI.Texto,
                                             GUILayout.Width(PanelUI.Px(16f)));
        if (Event.current.type != EventType.Repaint) return;
        float lado = Mathf.Min(PanelUI.Px(12f), fila.height);
        Rect cuadro = new Rect(fila.x + (fila.width - lado) * 0.5f,
                               fila.y + (fila.height - lado) * 0.5f, lado, lado);
        Color antes = GUI.color;
        GUI.color = color;
        GUI.DrawTexture(cuadro, Texture2D.whiteTexture);
        GUI.color = antes;
    }

    // ============================================================
    // AL DESTRUIR
    // ============================================================

    // Los materiales del mapa son propios (uno por color) y Unity no los
    // libera solo. Antes de destruirlos se devuelve la base a las barras
    // que siguen pintadas, para que no queden con un material destruido.
    // Es el unico OnDestroy de VisorSemana04: un segundo en otro archivo
    // del partial no compila.
    void OnDestroy()
    {
        Mapa_Desuscribir();
        Mapa_Restaurar();
        foreach (Material m in Mapa_materiales.Values)
            if (m != null) Destroy(m);
        Mapa_materiales.Clear();
        Mapa_propios.Clear();
    }
}
