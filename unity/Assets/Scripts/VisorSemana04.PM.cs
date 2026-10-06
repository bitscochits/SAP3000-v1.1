/*
================================================================
  VisorSemana04.PM.cs   (parte de VisorSemana04)
================================================================
  La curva P-M de la barra seleccionada y sus puntos de demanda, con
  el caso activo identificado.

  La curva y los puntos vienen del JSON: la curva de
  capacidad.interaccion() sobre la seccion de fibras, y cada punto de
  demanda_capacidad.demanda() sobre los 12 de localForce. Aca solo se
  pintan.

  ----------------------------------------------------------------
  DOS LUGARES, UN SOLO DIBUJO (Semana 5)
  ----------------------------------------------------------------
  PM_Contenido dibuja el grafico y su lectura dentro de un Rect, y lo
  usan los dos:
    - EN LINEA: la pestana Elemento de VisorQA llama a
      DibujarPMEnLinea() (Hooks.cs), que llega a Hook_DibujarPMEnLinea.
      Es donde se lee la barra: al lado de su texto.
    - VENTANA FLOTANTE, opcional (toggle en la pestana Caso): se abre a
      la derecha del panel y sirve para seguir el punto de demanda
      mientras se cambia de caso desde la pestana Caso. Mientras la
      pestana Elemento la muestra en linea, la ventana se oculta: dos
      copias del mismo grafico solo tapan el modelo.
  Si fueran dos codigos, un arreglo en uno dejaria al otro mintiendo.

  POR QUE UNA TEXTURA: IMGUI no dibuja lineas. Un Texture2D se pinta
  pixel a pixel y se regenera solo cuando cambia su FIRMA, no en cada
  frame. La firma es barra | caso activo | versionCasos | tamano:
  LIBRE se vuelve a combinar con el MISMO nombre y otros numeros, y sin
  versionCasos la curva seguiria mostrando el punto viejo (auditoria de
  superposicion, "trampas de redibujo"). El tamano de la textura sigue
  la escala de PanelUI para que las lineas no salgan borrosas en una
  pantalla de dpi alto.

  EJES: M horizontal desde cero (la curva es de magnitudes) y P
  vertical con la compresion hacia arriba, como en el curso. Los
  limites incluyen TODAS las demandas de la barra, para que un punto
  fuera de la curva se vea fuera y no cortado en el borde.
================================================================
*/

using UnityEngine;

public partial class VisorSemana04
{
    // El grafico a escala 1 de PanelUI (pantalla de 96 dpi), en pixeles.
    const int ANCHO_PM = 440;
    const int ALTO_PM = 300;

    public Color colorCurva = new Color(0.10f, 0.35f, 0.85f);
    public Color colorCurvaMax = new Color(0.65f, 0.75f, 0.95f);
    public Color colorDemanda = new Color(0.55f, 0.55f, 0.55f);
    public Color colorDemandaActiva = new Color(0.90f, 0.10f, 0.10f);

    private Rect ventanaPM;
    private bool ventanaIniciada = false;
    private Texture2D texturaPM;
    private string texturaPMFirma = null;
    private GUIStyle estiloSobreBlanco;

    // Limites del grafico en unidades del modelo (kN y kN*m).
    private float mMax = 1f, pMin = -1f, pMax = 1f;

    // Pixeles de la textura actual: ANCHO_PM x ALTO_PM por la escala.
    private int PM_ancho = ANCHO_PM, PM_alto = ALTO_PM;

    // Escala con que se ubico la ventana; si cambia se vuelve a ubicar.
    private float PM_escalaVentana = -1f;

    // Estilos propios, derivados de PanelUI (ver PM_PrepararEstilos).
    private GUIStyle PM_estiloVentana, PM_estiloTitulo, PM_estiloPasa, PM_estiloNoPasa;
    private GUIStyle PM_tenueDeLosEstilos;

    // Ultimo frame en que la pestana Elemento dibujo la curva en linea.
    private int PM_frameEnLinea = -10;
    // La ventana se decide en el Layout y vale para el resto del frame:
    // si apareciera entre el Layout y el Repaint, IMGUI lo reclama.
    private bool PM_ventanaEnLayout = false;
    // Ancho que le dio el panel al grafico en linea en el ultimo Repaint.
    private float PM_anchoEnLinea = -1f;

    // Textos de la lectura, rehechos solo si cambia su firma.
    private string PM_firmaTextos = null;
    private string PM_textoFicha = "";
    private string PM_textoVeredicto = "";
    private bool PM_veredictoPasa = true;
    private string PM_textoNotas = "";
    private readonly GUIContent PM_contenido = new GUIContent();

    const string PM_LEYENDA = "azul: Mn nominal   celeste: M max del M-phi\n"
                            + "gris: los otros casos   rojo: el caso activo";

    // ============================================================
    // QUE BARRA TIENE CURVA
    // ============================================================

    /// La familia P-M de una barra, o null si no tiene fierro (o el indice
    /// no esta en el anexo). Una sola definicion para la P-M, el mapa D/C
    /// y el resumen del panel.
    FamiliaPM PM_FamiliaDe(ElementoS4 e)
    {
        if (e == null || Anexo == null || Anexo.familias == null) return null;
        if (e.familia < 0 || e.familia >= Anexo.familias.Count) return null;
        return Anexo.familias[e.familia];
    }

    /// Hay ventana si hay algo que mostrar (una barra seleccionada con
    /// familia P-M), el toggle esta prendido y la pestana Elemento no la
    /// esta mostrando en linea (en este frame o el anterior: el orden de
    /// los OnGUI de VisorQA y de este script no esta garantizado).
    /// Tambien lo usa MouseSobreVentana (VisorSemana04.cs).
    bool VentanaPMVisible()
    {
        if (!mostrarPM || Seleccionado < 0) return false;
        if (PM_FamiliaDe(ElementoPorId(Seleccionado)) == null) return false;
        return Time.frameCount - PM_frameEnLinea > 1;
    }

    // ============================================================
    // EN LINEA (pestana Elemento de VisorQA)
    // ============================================================
    partial void Hook_DibujarPMEnLinea()
    {
        PanelUI.Preparar();
        ElementoS4 e = ElementoPorId(Seleccionado);
        FamiliaPM fam = PM_FamiliaDe(e);
        if (fam == null)
        {
            GUILayout.Label(Seleccionado < 0
                ? "(sin barra seleccionada)"
                : $"(el elemento {Seleccionado} no tiene curva P-M: sin enfierradura)", PanelUI.Tenue);
            return;
        }
        PM_frameEnLinea = Time.frameCount;

        // El layout da el ancho recien en el Repaint; el alto se pide con
        // el ancho del Repaint anterior. Dentro de un mismo frame es el
        // mismo en el Layout y en el Repaint, asi que IMGUI no reclama.
        float ancho = PM_anchoEnLinea > 0f ? PM_anchoEnLinea : PanelUI.Px(360f);
        float alto = PM_Contenido(new Rect(0f, 0f, ancho, 0f), e, fam, false);
        Rect r = GUILayoutUtility.GetRect(GUIContent.none, GUIStyle.none,
                                          GUILayout.ExpandWidth(true), GUILayout.Height(alto));
        if (Event.current.type != EventType.Repaint) return;
        PM_anchoEnLinea = r.width;
        PM_Contenido(r, e, fam, true);
    }

    // ============================================================
    // VENTANA FLOTANTE (opcional)
    // ============================================================
    void OnGUI()
    {
        if (Event.current.type == EventType.Layout) PM_ventanaEnLayout = VentanaPMVisible();
        if (!PM_ventanaEnLayout) return;
        ElementoS4 e = ElementoPorId(Seleccionado);
        FamiliaPM fam = PM_FamiliaDe(e);
        if (fam == null) return;

        PanelUI.Preparar();
        PM_PrepararEstilos();
        PM_UbicarVentana(e, fam);
        GUI.color = Color.white;
        // Sin titulo de la skin: el de GUI.skin.window no escala su letra
        // ni su barra. El titulo lo dibuja DibujarVentanaPM.
        ventanaPM = GUI.Window(4404, ventanaPM, DibujarVentanaPM, GUIContent.none,
                               PM_estiloVentana ?? GUI.skin.window);
    }

    /// La primera vez (y si cambia la escala) la ventana se abre a la
    /// DERECHA del panel de VisorQA, arriba: abajo al centro tapaba el
    /// edificio. Despues se respeta donde la deje el usuario, pero su
    /// tamano sigue al contenido y no se puede sacar de la pantalla.
    void PM_UbicarVentana(ElementoS4 e, FamiliaPM fam)
    {
        float s = PanelUI.Escala();
        float margen = PanelUI.Px(10f);
        float ancho = PanelUI.Px(ANCHO_PM) + 2f * margen;
        float alto = PM_ArribaVentana() + PM_Contenido(new Rect(0f, 0f, PanelUI.Px(ANCHO_PM), 0f), e, fam, false)
                     + margen;

        if (!ventanaIniciada || Mathf.Abs(s - PM_escalaVentana) > 0.001f)
        {
            float x = margen;
            if (qa != null) x = qa.RectPanel().xMax + margen;
            ventanaPM = new Rect(x, margen, ancho, alto);
            ventanaIniciada = true;
            PM_escalaVentana = s;
        }
        ventanaPM.width = Mathf.Min(ancho, Screen.width);
        ventanaPM.height = Mathf.Min(alto, Screen.height);
        ventanaPM.x = Mathf.Clamp(ventanaPM.x, 0f, Mathf.Max(0f, Screen.width - ventanaPM.width));
        ventanaPM.y = Mathf.Clamp(ventanaPM.y, 0f, Mathf.Max(0f, Screen.height - ventanaPM.height));
    }

    /// Alto de la barra de titulo de la ventana, mas un respiro.
    float PM_ArribaVentana() { return PanelUI.Px(30f); }

    void DibujarVentanaPM(int idVentana)
    {
        ElementoS4 e = ElementoPorId(Seleccionado);
        FamiliaPM fam = PM_FamiliaDe(e);
        if (fam == null) return;

        float barra = PM_ArribaVentana();
        GUI.Label(new Rect(0f, 0f, ventanaPM.width, barra - PanelUI.Px(4f)),
                  $"P-M  elemento {e.id} ({e.tipo})   caso activo: {casoActivo}",
                  PM_estiloTitulo ?? GUI.skin.label);
        float lado = barra - PanelUI.Px(8f);
        if (GUI.Button(new Rect(ventanaPM.width - lado - PanelUI.Px(2f), PanelUI.Px(2f), lado, lado),
                       "x", PanelUI.Boton ?? GUI.skin.button))
            mostrarPM = false;

        float margen = PanelUI.Px(10f);
        PM_Contenido(new Rect(margen, PM_ArribaVentana(), ventanaPM.width - 2f * margen,
                              ventanaPM.height - PM_ArribaVentana()), e, fam, true);

        GUI.DragWindow(new Rect(0f, 0f, 10000f, PM_ArribaVentana()));
    }

    // ============================================================
    // EL CONTENIDO: grafico arriba, lectura abajo
    // ============================================================

    /// Dibuja (si 'dibujar') el grafico y su lectura dentro de 'area' con
    /// GUI y Rect, sin GUILayout: sirve dentro de la ventana y dentro del
    /// panel. Devuelve el alto que ocupa para el ancho de 'area' (con
    /// dibujar = false solo mide).
    float PM_Contenido(Rect area, ElementoS4 e, FamiliaPM fam, bool dibujar)
    {
        PM_PrepararEstilos();
        PM_ArmarTextos(e, fam);
        float ancho = Mathf.Max(area.width, PanelUI.Px(120f));
        float y = area.y;

        // --- grafico, con la proporcion de la textura ---
        float altoGrafico = ancho * ALTO_PM / ANCHO_PM;
        Rect grafico = new Rect(area.x, y, ancho, altoGrafico);
        if (dibujar)
        {
            // Solo en el Repaint: el Layout y los clicks no pintan pixeles.
            if (Event.current.type == EventType.Repaint) ActualizarTexturaPM(e, fam);
            if (texturaPM != null) GUI.DrawTexture(grafico, texturaPM, ScaleMode.StretchToFill);
            PM_RotulosDeEjes(grafico);
        }
        y += altoGrafico + PanelUI.Px(4f);

        // --- lectura ---
        y += PM_Parrafo(area.x, y, ancho, PM_textoFicha, PanelUI.Texto, dibujar);
        y += PM_Parrafo(area.x, y, ancho, PM_textoVeredicto,
                        PM_veredictoPasa ? PM_estiloPasa : PM_estiloNoPasa, dibujar);
        if (!string.IsNullOrEmpty(PM_textoNotas))
            y += PM_Parrafo(area.x, y, ancho, PM_textoNotas, PanelUI.Texto, dibujar);
        y += PM_Parrafo(area.x, y, ancho, PM_LEYENDA, PanelUI.Tenue, dibujar);
        return y - area.y;
    }

    /// Un parrafo con ajuste de linea; devuelve su alto.
    float PM_Parrafo(float x, float y, float ancho, string texto, GUIStyle estilo, bool dibujar)
    {
        if (string.IsNullOrEmpty(texto)) return 0f;
        GUIStyle st = estilo ?? GUI.skin.label;
        PM_contenido.text = texto;
        float alto = st.CalcHeight(PM_contenido, ancho);
        if (dibujar) GUI.Label(new Rect(x, y, ancho, alto), PM_contenido, st);
        return alto;
    }

    void PM_RotulosDeEjes(Rect g)
    {
        GUIStyle st = estiloSobreBlanco ?? GUI.skin.label;
        float lh = st.lineHeight + PanelUI.Px(3f);
        float pad = PanelUI.Px(3f);
        GUI.Label(new Rect(g.x + pad, g.y + 1f, g.width * 0.7f, lh),
                  $"P = {F(pMax, "0")} kN  (compresion +)", st);
        GUI.Label(new Rect(g.x + pad, g.yMax - lh - 1f, g.width * 0.5f, lh),
                  $"P = {F(pMin, "0")} kN", st);
        PM_contenido.text = $"M = {F(mMax, "0")} kN*m";
        float w = st.CalcSize(PM_contenido).x;
        GUI.Label(new Rect(g.xMax - w - pad, g.yMax - lh - 1f, w, lh), PM_contenido, st);
    }

    /// Estilos propios escalados. Se rehacen cuando PanelUI rehace los
    /// suyos (cambio de escala): ahi Tenue es otro objeto. Son copias: los
    /// de PanelUI los comparten todos los paneles y no se modifican.
    void PM_PrepararEstilos()
    {
        GUIStyle tenue = PanelUI.Tenue;
        if (tenue == null || PanelUI.Caja == null || PanelUI.Seccion == null) return;
        if (estiloSobreBlanco != null && PM_tenueDeLosEstilos == tenue) return;
        PM_tenueDeLosEstilos = tenue;

        // Rotulos de los ejes, en negro sobre el fondo blanco del grafico.
        estiloSobreBlanco = new GUIStyle(GUI.skin.label);
        estiloSobreBlanco.fontSize = tenue.fontSize;
        estiloSobreBlanco.wordWrap = false;
        estiloSobreBlanco.normal.textColor = Color.black;

        // La ventana con el mismo fondo que el panel.
        PM_estiloVentana = new GUIStyle(PanelUI.Caja);
        PM_estiloVentana.padding = new RectOffset(0, 0, 0, 0);

        PM_estiloTitulo = new GUIStyle(PanelUI.Texto);
        PM_estiloTitulo.fontStyle = FontStyle.Bold;
        PM_estiloTitulo.wordWrap = false;
        PM_estiloTitulo.clipping = TextClipping.Clip;
        PM_estiloTitulo.alignment = TextAnchor.MiddleLeft;
        int p = Mathf.RoundToInt(PanelUI.Px(8f));
        PM_estiloTitulo.padding = new RectOffset(p, p, 0, 0);
        PM_estiloTitulo.normal.background = PanelUI.Seccion.normal.background;

        // El veredicto largo ("P fuera de la curva ...") tiene que poder
        // partir linea en un panel angosto; Pasa y NoPasa no la parten.
        PM_estiloPasa = new GUIStyle(PanelUI.Pasa);
        PM_estiloPasa.wordWrap = true;
        PM_estiloNoPasa = new GUIStyle(PanelUI.NoPasa);
        PM_estiloNoPasa.wordWrap = true;
    }

    /// Los textos de la lectura: dependen de la barra, del caso activo y
    /// de versionCasos, no del evento de OnGUI.
    void PM_ArmarTextos(ElementoS4 e, FamiliaPM fam)
    {
        string firma = e.id + "|" + casoActivo + "|" + versionCasos;
        if (firma == PM_firmaTextos) return;
        PM_firmaTextos = firma;

        PM_textoFicha = $"familia {fam.indice}: {fam.tipo} {fam.seccion}  "
                      + $"{F(fam.b, "0.00")} x {F(fam.h, "0.00")} m   "
                      + $"As {F(fam.As_cm2, "0.0")} cm2 ({F(fam.cuantia_pct, "0.00")} %)";

        DemandaS4 d = DemandaDe(e.id, casoActivo);
        if (d == null)
        {
            PM_textoFicha += $"\n{casoActivo}: sin demanda en este caso";
            PM_textoVeredicto = "";
            PM_veredictoPasa = true;
            PM_textoNotas = "";
            return;
        }
        PM_textoFicha += $"\n{casoActivo}:  P = {F(d.P, "0.0")} kN   M = {F(d.M, "0.0")} kN*m"
                       + $"   (extremo {d.extremo})";
        // El veredicto es 'pasa' del JSON; aca no se compara nada.
        PM_veredictoPasa = d.pasa;
        PM_textoVeredicto = d.u >= PanelUI.U_FUERA_DE_CURVA
            ? TextoFueraDeCurva(d, fam)
            : $"Mn(P) = {F(d.Mn, "0.0")} kN*m   u = M/Mn = {F(d.u, "0.000")}   "
              + (d.pasa ? "PASA" : "NO PASA");
        PM_textoNotas = fam.tipo == "muro"
            ? $"M = |{e.momento_en_el_plano}|, el de su plano.  Fuera de plano "
              + $"{F(d.M_fuera_plano, "0.0")} kN*m (no se compara)"
            : "";
        string nucleo = PanelUI.TextoNucleo(d);
        if (nucleo != "") PM_textoNotas += (PM_textoNotas == "" ? "" : "\n") + nucleo;
    }

    /// Un Mn = 0 no es "u infinito": es un P fuera del rango de la curva,
    /// y el caso real de este edificio son muros traccionados mas alla de
    /// su traccion pura bajo sismo. Se dice con palabras.
    static string TextoFueraDeCurva(DemandaS4 d, FamiliaPM fam)
    {
        float pmin = float.MaxValue, pmax = float.MinValue;
        if (fam.P != null)
            foreach (float p in fam.P) { pmin = Mathf.Min(pmin, p); pmax = Mathf.Max(pmax, p); }
        if (d.P < pmin)
            return $"P fuera de la curva: traccion {F(-d.P, "0")} kN mayor que la traccion "
                 + $"pura {F(-pmin, "0")} kN. NO PASA (u no definido)";
        if (d.P > pmax)
            return $"P fuera de la curva: compresion {F(d.P, "0")} kN mayor que la "
                 + $"compresion pura {F(pmax, "0")} kN. NO PASA (u no definido)";
        return "Mn = 0 a este P: NO PASA (u no definido)";
    }

    // ============================================================
    // LA TEXTURA
    // ============================================================
    void ActualizarTexturaPM(ElementoS4 e, FamiliaPM fam)
    {
        int ancho = Mathf.Clamp(Mathf.RoundToInt(PanelUI.Px(ANCHO_PM)), 220, 1600);
        int alto = Mathf.RoundToInt(ancho * (float)ALTO_PM / ANCHO_PM);
        string firma = e.id + "|" + casoActivo + "|" + versionCasos + "|" + ancho + "x" + alto;
        if (texturaPM != null && firma == texturaPMFirma) return;
        texturaPMFirma = firma;
        if (texturaPM == null || texturaPM.width != ancho || texturaPM.height != alto)
        {
            if (texturaPM != null) Destroy(texturaPM);
            texturaPM = new Texture2D(ancho, alto, TextureFormat.RGBA32, false);
            texturaPM.filterMode = FilterMode.Bilinear;
            texturaPM.wrapMode = TextureWrapMode.Clamp;
        }
        PM_ancho = ancho;
        PM_alto = alto;
        // Los grosores y radios se escalan con la textura.
        float k = ancho / (float)ANCHO_PM;
        int Gros(float g) { return Mathf.Max(1, Mathf.RoundToInt(g * k)); }

        mMax = 0f; pMin = 0f; pMax = 0f;
        int n = Mathf.Min(Largo(fam.P), Mathf.Min(Largo(fam.Mn), Largo(fam.Mmax)));
        for (int i = 0; i < n; i++)
        {
            mMax = Mathf.Max(mMax, Mathf.Max(fam.Mn[i], fam.Mmax[i]));
            pMin = Mathf.Min(pMin, fam.P[i]);
            pMax = Mathf.Max(pMax, fam.P[i]);
        }
        foreach (CasoS4 c in Anexo.casos)
        {
            if (c == null) continue;
            DemandaS4 dc = DemandaDe(e.id, c.nombre);
            if (dc == null) continue;
            mMax = Mathf.Max(mMax, dc.M);
            pMin = Mathf.Min(pMin, dc.P);
            pMax = Mathf.Max(pMax, dc.P);
        }
        mMax = Mathf.Max(mMax, 1f) * 1.08f;
        float rango = Mathf.Max(pMax - pMin, 1f);
        pMin -= 0.06f * rango;
        pMax += 0.06f * rango;

        var px = new Color32[PM_ancho * PM_alto];
        var fondo = new Color32(255, 255, 255, 255);
        for (int i = 0; i < px.Length; i++) px[i] = fondo;

        var grilla = new Color32(228, 228, 228, 255);
        for (int g = 1; g < 4; g++)
        {
            int xg = XPx(mMax * g / 4f);
            LineaPx(px, xg, 0, xg, PM_alto - 1, grilla, 1);
            int yg = YPx(pMin + (pMax - pMin) * g / 4f);
            LineaPx(px, 0, yg, PM_ancho - 1, yg, grilla, 1);
        }
        var eje = new Color32(80, 80, 80, 255);
        LineaPx(px, 0, YPx(0f), PM_ancho - 1, YPx(0f), eje, Gros(1f));
        LineaPx(px, XPx(0f), 0, XPx(0f), PM_alto - 1, eje, Gros(1f));

        Polilinea(px, fam.P, fam.Mmax, n, colorCurvaMax, Gros(1f));
        Polilinea(px, fam.P, fam.Mn, n, colorCurva, Gros(2f));

        // Los otros casos, incluidos los de la Semana 5 (E1..E3, LIBRE):
        // son puntos del anexo igual que G o S3.
        foreach (CasoS4 c in Anexo.casos)
        {
            if (c == null || c.nombre == casoActivo) continue;
            DemandaS4 dc = DemandaDe(e.id, c.nombre);
            if (dc != null) Punto(px, dc.M, dc.P, colorDemanda, Gros(2f));
        }
        DemandaS4 activa = DemandaDe(e.id, casoActivo);
        if (activa != null)
        {
            Punto(px, activa.M, activa.P, colorDemandaActiva, Gros(4f));
            Anillo(px, XPx(activa.M), YPx(activa.P), Gros(7f), new Color32(0, 0, 0, 255));
        }

        texturaPM.SetPixels32(px);
        texturaPM.Apply(false);
    }

    static int Largo(float[] v) { return v == null ? 0 : v.Length; }

    int XPx(float m)
    {
        return Mathf.Clamp(Mathf.RoundToInt(m / mMax * (PM_ancho - 1)), 0, PM_ancho - 1);
    }

    int YPx(float p)
    {
        return Mathf.Clamp(Mathf.RoundToInt((p - pMin) / (pMax - pMin) * (PM_alto - 1)),
                           0, PM_alto - 1);
    }

    void Polilinea(Color32[] px, float[] P, float[] M, int n, Color color, int grosor)
    {
        Color32 c = color;
        for (int i = 1; i < n; i++)
            LineaPx(px, XPx(M[i - 1]), YPx(P[i - 1]), XPx(M[i]), YPx(P[i]), c, grosor);
    }

    void Punto(Color32[] px, float m, float p, Color color, int radio)
    {
        Color32 c = color;
        int x = XPx(m), y = YPx(p);
        for (int j = -radio; j <= radio; j++)
            for (int i = -radio; i <= radio; i++)
                Pixel(px, x + i, y + j, c);
    }

    void Anillo(Color32[] px, int x, int y, int r, Color32 c)
    {
        for (int k = -r; k <= r; k++)
        {
            Pixel(px, x + k, y - r, c); Pixel(px, x + k, y + r, c);
            Pixel(px, x - r, y + k, c); Pixel(px, x + r, y + k, c);
        }
    }

    /// Bresenham con pincel cuadrado para el grosor.
    void LineaPx(Color32[] px, int x0, int y0, int x1, int y1, Color32 c, int grosor)
    {
        int dx = Mathf.Abs(x1 - x0), dy = -Mathf.Abs(y1 - y0);
        int sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1;
        int err = dx + dy;
        int r = grosor / 2;
        while (true)
        {
            for (int j = -r; j <= r; j++)
                for (int i = -r; i <= r; i++)
                    Pixel(px, x0 + i, y0 + j, c);
            if (x0 == x1 && y0 == y1) break;
            int e2 = 2 * err;
            if (e2 >= dy) { err += dy; x0 += sx; }
            if (e2 <= dx) { err += dx; y0 += sy; }
        }
    }

    void Pixel(Color32[] px, int x, int y, Color32 c)
    {
        if (x < 0 || y < 0 || x >= PM_ancho || y >= PM_alto) return;
        px[y * PM_ancho + x] = c;
    }
}
