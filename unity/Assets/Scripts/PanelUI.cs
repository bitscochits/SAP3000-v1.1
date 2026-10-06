/*
================================================================
  PanelUI.cs
================================================================
  Estilos IMGUI compartidos por todos los paneles del visor, escalados
  por la densidad de la pantalla. Una sola definicion de tamanos,
  colores y de los controles que se repiten (seccion plegable,
  insignia PASA / NO PASA, boton de opcion).

  ----------------------------------------------------------------
  POR QUE ASI
  ----------------------------------------------------------------
  - Escala por DPI y no GUI.matrix: GUI.matrix escala el dibujo pero
    no los Rect con que VisorQA, EditorEstructura y la camara
    preguntan "el mouse esta sobre el panel?". Con estilos escalados
    los rectangulos siguen en pixeles reales y esas preguntas no
    cambian. Todo largo en pixeles pasa por Px().
  - Estilos armados en codigo y no un GUISkin .asset: no hay que abrir
    Unity para cambiarlos y se ven igual en el editor y en la build.
  - Los GUIStyle copian de GUI.skin, que SOLO existe dentro de OnGUI.
    Por eso Preparar() va como primera linea de cada OnGUI que use
    estos estilos, y reconstruye solo si cambio la escala.

  ----------------------------------------------------------------
  USO
  ----------------------------------------------------------------
      void OnGUI()
      {
          PanelUI.Preparar();
          GUILayout.BeginArea(rect, PanelUI.Caja);
          GUILayout.Label("Caso activo", PanelUI.Titulo);
          if (PanelUI.Plegable("s4.diagramas", "Diagramas", true)) { ... }
          PanelUI.Insignia(demanda.pasa);
          GUILayout.EndArea();
      }

  Las claves de Plegable llevan el prefijo del paquete ("qa.", "s4.",
  "mapa.", "sup.", "editor.", "movil.") para que dos paneles no
  compartan sin querer el estado abierto/cerrado.
================================================================
*/

using System.Collections.Generic;
using UnityEngine;

public static class PanelUI
{
    // ============================================================
    // COLORES
    // ============================================================
    public static readonly Color ColorTexto = new Color(0.92f, 0.92f, 0.93f);
    public static readonly Color ColorTenue = new Color(0.66f, 0.67f, 0.70f);
    public static readonly Color ColorFondo = new Color(0.09f, 0.10f, 0.12f, 0.94f);
    public static readonly Color ColorSeccion = new Color(0.18f, 0.19f, 0.23f, 1f);
    public static readonly Color ColorBoton = new Color(0.24f, 0.25f, 0.29f, 1f);
    public static readonly Color ColorBotonEncima = new Color(0.31f, 0.32f, 0.37f, 1f);
    public static readonly Color ColorAcento = new Color(0.20f, 0.45f, 0.85f, 1f);
    public static readonly Color ColorAviso = new Color(1.00f, 0.74f, 0.25f);
    public static readonly Color ColorPasa = new Color(0.35f, 0.85f, 0.45f);
    public static readonly Color ColorNoPasa = new Color(1.00f, 0.40f, 0.35f);

    // --- Demanda / capacidad: los colores del mapa, su leyenda y el
    //     inspector. Una sola definicion para que el color de una barra
    //     en la escena y el de su insignia en el panel no difieran.
    public static readonly Color ColorDC_Holgado = new Color(0.20f, 0.72f, 0.32f);     // u < 0.7
    public static readonly Color ColorDC_Cerca = new Color(0.95f, 0.80f, 0.15f);       // 0.7 <= u, pasa
    public static readonly Color ColorDC_NoPasa = new Color(0.90f, 0.20f, 0.15f);      // pasa = false
    public static readonly Color ColorDC_FueraDeCurva = new Color(0.62f, 0.32f, 0.85f); // u = 9999
    public static readonly Color ColorDC_SinFamilia = new Color(0.55f, 0.55f, 0.58f);  // sin fierro

    /// Desde que u se pinta amarillo. Es un umbral de LECTURA, no de
    /// diseno: el veredicto es 'pasa', que viene del JSON.
    public const float UMBRAL_DC_CERCA = 0.7f;

    /// El centinela de semana04/exportar_unity.py: P cae fuera de la
    /// curva y Mn = 0, asi que u no existe.
    public const float U_FUERA_DE_CURVA = 9999f;

    /// El color de una barra segun su demanda del JSON. No calcula nada:
    /// lee u y pasa tal como los escribio Python.
    public static Color ColorDemandaCapacidad(bool conFamilia, float u, bool pasa)
    {
        if (!conFamilia) return ColorDC_SinFamilia;
        if (u >= U_FUERA_DE_CURVA) return ColorDC_FueraDeCurva;
        if (!pasa) return ColorDC_NoPasa;
        if (u >= UMBRAL_DC_CERCA) return ColorDC_Cerca;
        return ColorDC_Holgado;
    }

    // ============================================================
    // ESCALA
    // ============================================================
    public static bool EsMovil { get { return Application.isMobilePlatform; } }

    const string CLAVE_ESCALA = "panel_escala";
    static float escalaUsuario = -1f;

    /// Multiplicador que elige el usuario (botones A- / A+). Se guarda
    /// en PlayerPrefs; si no se puede leer o escribir, queda en 1.
    public static float EscalaUsuario
    {
        get
        {
            if (escalaUsuario < 0f)
            {
                escalaUsuario = 1f;
                try { escalaUsuario = PlayerPrefs.GetFloat(CLAVE_ESCALA, 1f); }
                catch (System.Exception) { }
                escalaUsuario = Mathf.Clamp(escalaUsuario, 0.5f, 2.5f);
            }
            return escalaUsuario;
        }
        set
        {
            escalaUsuario = Mathf.Clamp(value, 0.5f, 2.5f);
            try { PlayerPrefs.SetFloat(CLAVE_ESCALA, escalaUsuario); }
            catch (System.Exception) { }
        }
    }

    /// Cuantos pixeles reales mide un "pixel de diseno" (el de un monitor
    /// de 96 dpi). Screen.dpi contra 96 en PC y 160 en movil (la
    /// densidad de referencia de Android); si la plataforma no informa
    /// el dpi (0), se usa el alto de pantalla contra 1080. Acotado a
    /// 0.8-3.5 para que un dpi informado mal no deje el panel ilegible.
    public static float Escala()
    {
        float dpi = Screen.dpi;
        float referencia = EsMovil ? 160f : 96f;
        float s = dpi > 1f ? dpi / referencia : Screen.height / 1080f;
        return Mathf.Clamp(s * EscalaUsuario, 0.8f, 3.5f);
    }

    /// Un largo de diseno en pixeles reales. Anchos de panel, alturas,
    /// espacios: todo lo que antes era un numero fijo.
    public static float Px(float v)
    {
        return v * (escalaEstilos > 0f ? escalaEstilos : Escala());
    }

    static int Fuente(float v) { return Mathf.Max(8, Mathf.RoundToInt(Px(v))); }

    /// Alto minimo de un boton: en movil, lo que pide un dedo.
    public static float AltoBoton { get { return Px(EsMovil ? 40f : 26f); } }

    /// Pixeles que tiene que moverse el puntero para que un click sea un
    /// arrastre. 5 px en un monitor comun; en un telefono de 400 dpi un
    /// dedo quieto se mueve mas que eso. La usan la camara y el editor.
    public static float UmbralArrastre()
    {
        return Mathf.Max(5f, 0.08f * Screen.dpi);
    }

    // ============================================================
    // ESTILOS
    // ============================================================
    public static GUIStyle Texto { get; private set; }
    public static GUIStyle Tenue { get; private set; }
    public static GUIStyle Titulo { get; private set; }
    public static GUIStyle Seccion { get; private set; }
    public static GUIStyle Boton { get; private set; }
    public static GUIStyle BotonActivo { get; private set; }
    public static GUIStyle Caja { get; private set; }
    public static GUIStyle Aviso { get; private set; }
    public static GUIStyle Pasa { get; private set; }
    public static GUIStyle NoPasa { get; private set; }

    /// Texto de ancho fijo para las tablas que se alinean con espacios
    /// (el bloque de esfuerzos de VisorSemana04.DescribirElemento). Si la
    /// plataforma no da una fuente monoespaciada, es igual a Texto.
    public static GUIStyle Mono { get; private set; }

    /// Casilla de verificacion (GUILayout.Toggle) a la escala del panel.
    /// La del GUI.skin por defecto es una imagen fija de unos 9 px: con la
    /// escala 1.25 la letra crecia y la casilla no, y prendida y apagada
    /// se distinguian apenas por un punto gris. Esta dibuja un cuadro de
    /// Px(18) con borde, relleno de acento y un visto blanco al prenderse.
    public static GUIStyle Casilla { get; private set; }

    static float escalaEstilos = -1f;
    static Texture2D texFondo, texSeccion, texBoton, texBotonEncima, texAcento;
    // Dependen de la escala (el cuadro mide Px(18)): se rehacen con ella.
    static Texture2D texCasillaNo, texCasillaNoEncima, texCasillaSi;
    static Font fuenteMono;
    static bool fuenteMonoBuscada = false;

    /// Primera linea de cada OnGUI que use estos estilos. Barato si no
    /// cambio nada.
    public static void Preparar()
    {
        float s = Escala();
        bool texturasVivas = texFondo != null && texSeccion != null && texBoton != null
                             && texBotonEncima != null && texAcento != null;
        bool casillaViva = texCasillaNo != null && texCasillaNoEncima != null && texCasillaSi != null;
        if (Texto != null && texturasVivas && casillaViva && Mathf.Abs(s - escalaEstilos) < 0.001f) return;
        escalaEstilos = s;

        if (!texturasVivas)
        {
            texFondo = Plana(ColorFondo);
            texSeccion = Plana(ColorSeccion);
            texBoton = Plana(ColorBoton);
            texBotonEncima = Plana(ColorBotonEncima);
            texAcento = Plana(ColorAcento);
        }

        Texto = new GUIStyle(GUI.skin.label);
        Texto.fontSize = Fuente(13f);
        Texto.wordWrap = true;
        Texto.richText = false;
        ColorDeTexto(Texto, ColorTexto);

        Tenue = new GUIStyle(Texto);
        Tenue.fontSize = Fuente(11f);
        ColorDeTexto(Tenue, ColorTenue);

        Titulo = new GUIStyle(Texto);
        Titulo.fontSize = Fuente(16f);
        Titulo.fontStyle = FontStyle.Bold;
        Titulo.wordWrap = false;

        Seccion = new GUIStyle(GUI.skin.button);
        Seccion.fontSize = Fuente(13f);
        Seccion.fontStyle = FontStyle.Bold;
        Seccion.alignment = TextAnchor.MiddleLeft;
        Seccion.padding = Margen(6f);
        Seccion.margin = new RectOffset(0, 0, Mathf.RoundToInt(Px(6f)), Mathf.RoundToInt(Px(2f)));
        Seccion.border = new RectOffset(0, 0, 0, 0);
        Fondos(Seccion, texSeccion, texBotonEncima, texSeccion);
        ColorDeTexto(Seccion, ColorTexto);

        Boton = new GUIStyle(GUI.skin.button);
        Boton.fontSize = Fuente(13f);
        // GUIStyle no tiene alto minimo: se fija. Los botones son de una
        // linea (wordWrap = false), asi que no se corta texto.
        Boton.fixedHeight = AltoBoton;
        Boton.padding = Margen(5f);
        Boton.border = new RectOffset(0, 0, 0, 0);
        Boton.wordWrap = false;
        Fondos(Boton, texBoton, texBotonEncima, texAcento);
        ColorDeTexto(Boton, ColorTexto);

        BotonActivo = new GUIStyle(Boton);
        BotonActivo.fontStyle = FontStyle.Bold;
        Fondos(BotonActivo, texAcento, texAcento, texAcento);
        ColorDeTexto(BotonActivo, Color.white);

        Caja = new GUIStyle(GUI.skin.box);
        Caja.padding = Margen(10f);
        Caja.border = new RectOffset(0, 0, 0, 0);
        Caja.normal.background = texFondo;

        Aviso = new GUIStyle(Texto);
        ColorDeTexto(Aviso, ColorAviso);

        Pasa = new GUIStyle(Texto);
        Pasa.fontStyle = FontStyle.Bold;
        Pasa.wordWrap = false;
        ColorDeTexto(Pasa, ColorPasa);

        NoPasa = new GUIStyle(Pasa);
        ColorDeTexto(NoPasa, ColorNoPasa);

        Mono = new GUIStyle(Texto);
        Mono.wordWrap = false;
        Font f = FuenteMono();
        if (f != null) { Mono.font = f; Mono.fontSize = Fuente(12f); }

        PrepararCasilla();
    }

    /// El cuadro va a la izquierda de una imagen de (lado + 1) x AltoBoton:
    /// el borde izquierdo de 9 cortes (lado) no se estira y la ultima
    /// columna, transparente, se estira bajo el texto. Con fixedHeight =
    /// alto de la imagen, tampoco se estira en vertical.
    static void PrepararCasilla()
    {
        foreach (Texture2D t in new[] { texCasillaNo, texCasillaNoEncima, texCasillaSi })
            if (t != null) Object.Destroy(t);
        int lado = Mathf.Max(10, Mathf.RoundToInt(Px(18f)));
        int alto = Mathf.Max(lado, Mathf.RoundToInt(AltoBoton));
        int borde = Mathf.Max(1, Mathf.RoundToInt(Px(1.5f)));
        texCasillaNo = TexturaCasilla(lado, alto, borde, ColorTenue, ColorBoton, false);
        texCasillaNoEncima = TexturaCasilla(lado, alto, borde, ColorTexto, ColorBotonEncima, false);
        texCasillaSi = TexturaCasilla(lado, alto, borde, ColorAcento, ColorAcento, true);

        Casilla = new GUIStyle(GUI.skin.toggle);
        Casilla.fontSize = Texto.fontSize;
        Casilla.wordWrap = false;
        Casilla.alignment = TextAnchor.MiddleLeft;
        Casilla.fixedHeight = alto;
        Casilla.border = new RectOffset(lado, 0, 0, 0);
        Casilla.overflow = new RectOffset(0, 0, 0, 0);
        Casilla.padding = new RectOffset(lado + Mathf.RoundToInt(Px(8f)), Mathf.RoundToInt(Px(4f)), 0, 0);
        Casilla.margin = new RectOffset(0, Mathf.RoundToInt(Px(6f)), Mathf.RoundToInt(Px(1f)), Mathf.RoundToInt(Px(1f)));
        Casilla.contentOffset = Vector2.zero;
        Casilla.normal.background = texCasillaNo;
        Casilla.focused.background = texCasillaNo;
        Casilla.hover.background = texCasillaNoEncima;
        Casilla.active.background = texCasillaNoEncima;
        Casilla.onNormal.background = texCasillaSi;
        Casilla.onFocused.background = texCasillaSi;
        Casilla.onHover.background = texCasillaSi;
        Casilla.onActive.background = texCasillaSi;
        ColorDeTexto(Casilla, ColorTexto);
        Casilla.onFocused.textColor = ColorTexto;
    }

    static Texture2D TexturaCasilla(int lado, int alto, int borde, Color colorBorde, Color relleno, bool visto)
    {
        Texture2D t = new Texture2D(lado + 1, alto, TextureFormat.RGBA32, false);
        t.hideFlags = HideFlags.HideAndDontSave;
        t.filterMode = FilterMode.Point;
        t.wrapMode = TextureWrapMode.Clamp;
        Color transparente = new Color(0f, 0f, 0f, 0f);
        int y0 = (alto - lado) / 2;
        // El visto: dos trazos, de (0.22, 0.50) a (0.42, 0.28) y de ahi a
        // (0.78, 0.72), en fraccion del lado (y hacia arriba, como la textura).
        float grosor = Mathf.Max(1.2f, lado * 0.09f);
        Vector2 p1 = new Vector2(0.22f, 0.50f) * lado, p2 = new Vector2(0.42f, 0.28f) * lado,
                p3 = new Vector2(0.78f, 0.72f) * lado;
        for (int y = 0; y < alto; y++)
            for (int x = 0; x <= lado; x++)
            {
                Color c = transparente;
                int yy = y - y0;
                if (x < lado && yy >= 0 && yy < lado)
                {
                    bool enBorde = x < borde || yy < borde || x >= lado - borde || yy >= lado - borde;
                    c = enBorde ? colorBorde : relleno;
                    if (visto && !enBorde)
                    {
                        Vector2 p = new Vector2(x + 0.5f, yy + 0.5f);
                        float d = Mathf.Min(DistanciaASegmento(p, p1, p2), DistanciaASegmento(p, p2, p3));
                        if (d <= grosor) c = Color.white;
                    }
                }
                t.SetPixel(x, y, c);
            }
        t.Apply();
        return t;
    }

    static float DistanciaASegmento(Vector2 p, Vector2 a, Vector2 b)
    {
        Vector2 ab = b - a;
        float k = Mathf.Clamp01(Vector2.Dot(p - a, ab) / Mathf.Max(ab.sqrMagnitude, 1e-6f));
        return Vector2.Distance(p, a + ab * k);
    }

    static Texture2D Plana(Color c)
    {
        Texture2D t = new Texture2D(1, 1, TextureFormat.RGBA32, false);
        t.hideFlags = HideFlags.HideAndDontSave;
        t.SetPixel(0, 0, c);
        t.Apply();
        return t;
    }

    static RectOffset Margen(float v)
    {
        int p = Mathf.RoundToInt(Px(v));
        return new RectOffset(p, p, p, p);
    }

    static void ColorDeTexto(GUIStyle s, Color c)
    {
        s.normal.textColor = c;
        s.hover.textColor = c;
        s.active.textColor = c;
        s.focused.textColor = c;
        s.onNormal.textColor = c;
        s.onHover.textColor = c;
        s.onActive.textColor = c;
    }

    static void Fondos(GUIStyle s, Texture2D normal, Texture2D encima, Texture2D presionado)
    {
        s.normal.background = normal;
        s.focused.background = normal;
        s.hover.background = encima;
        s.active.background = presionado;
        s.onNormal.background = presionado;
        s.onHover.background = presionado;
        s.onActive.background = presionado;
    }

    /// Consolas en Windows, la que haya en otras plataformas. En Web no
    /// hay fuentes del sistema: Mono queda igual a Texto.
    static Font FuenteMono()
    {
        if (fuenteMonoBuscada) return fuenteMono;
        fuenteMonoBuscada = true;
#if !UNITY_WEBGL
        try
        {
            fuenteMono = Font.CreateDynamicFontFromOSFont(
                new[] { "Consolas", "Courier New", "Droid Sans Mono", "DejaVu Sans Mono", "Menlo" },
                12);
        }
        catch (System.Exception)
        {
            fuenteMono = null;
        }
#endif
        return fuenteMono;
    }

    // ============================================================
    // CONTROLES
    // ============================================================
    static readonly Dictionary<string, bool> abiertos = new Dictionary<string, bool>();
    static readonly Dictionary<string, bool> pendientes = new Dictionary<string, bool>();

    /// Encabezado de seccion que se abre y cierra. Devuelve si esta
    /// abierta; el contenido se dibuja solo si devuelve true.
    ///
    /// El click no cambia el estado en el mismo evento: se aplica en el
    /// proximo Layout. Si cambiara al soltar el mouse, los controles de
    /// abajo aparecerian (o desaparecerian) entre el Layout y el
    /// MouseUp, e IMGUI tira "Getting control N's position in a group
    /// with only N controls".
    public static bool Plegable(string clave, string titulo, bool abiertoPorDefecto)
    {
        bool abiertoAhora = PlegableSinMarca(clave, titulo, abiertoPorDefecto);
        Marcar(clave);
        return abiertoAhora;
    }

    static bool PlegableSinMarca(string clave, string titulo, bool abiertoPorDefecto)
    {
        bool abierto;
        if (!abiertos.TryGetValue(clave, out abierto)) abierto = abiertoPorDefecto;

        bool nuevo;
        if (Event.current != null && Event.current.type == EventType.Layout
            && pendientes.TryGetValue(clave, out nuevo))
        {
            abierto = nuevo;
            pendientes.Remove(clave);
        }
        abiertos[clave] = abierto;

        if (GUILayout.Button((abierto ? "-  " : "+  ") + titulo, Seccion ?? GUI.skin.button))
            pendientes[clave] = !abierto;
        return abierto;
    }

    // Donde quedo dibujado cada encabezado (y cada Marcar), en pixeles del
    // CONTENIDO del scroll que lo contiene (GUILayout mide dentro del
    // scroll sin el corrimiento). Solo lo leen las capturas: con esto
    // CapturaSemana05 lleva el scroll a lo que tiene que salir en la foto
    // en vez de a un numero medido a mano.
    static readonly Dictionary<string, float> posiciones = new Dictionary<string, float>();

    /// Anota la y del ultimo control dibujado con esta clave. Solo en
    /// Repaint, que es cuando GetLastRect es valido.
    public static void Marcar(string clave)
    {
        if (Event.current != null && Event.current.type == EventType.Repaint)
            posiciones[clave] = GUILayoutUtility.GetLastRect().y;
    }

    /// La y anotada por Marcar o por Plegable; -1 si no se ha dibujado.
    public static float PosicionDe(string clave)
    {
        float y;
        return posiciones.TryGetValue(clave, out y) ? y : -1f;
    }

    public static void OlvidarPosiciones() { posiciones.Clear(); }

    /// Fuerza el estado de una seccion (lo usan las capturas automaticas
    /// para abrir lo que tiene que salir en la foto).
    public static void FijarPlegable(string clave, bool abierto)
    {
        abiertos[clave] = abierto;
        pendientes.Remove(clave);
    }

    /// "PASA" en verde o "NO PASA" en rojo, del ancho del texto.
    public static void Insignia(bool pasa)
    {
        GUILayout.Label(pasa ? "PASA" : "NO PASA", (pasa ? Pasa : NoPasa) ?? GUI.skin.label,
                        GUILayout.ExpandWidth(false));
    }

    /// Una insignia con otro texto y estilo ("P fuera de la curva" con
    /// Aviso, por ejemplo).
    public static void Insignia(string texto, GUIStyle estilo)
    {
        GUILayout.Label(texto, estilo ?? GUI.skin.label, GUILayout.ExpandWidth(false));
    }

    /// El resumen de demanda/capacidad de un caso, igual en la cabecera, la
    /// leyenda del mapa D/C y la superposicion. Con todo pasando dice
    /// "PASAN m/m": "NO PASA 0/69" en verde se leia, rapido, al reves.
    /// No calcula: cuenta lo que ya trae el JSON (VisorSemana04.ContarDemandas).
    public static string TextoDemanda(int noPasan, int fuera, int total)
    {
        if (total == 0) return "sin demandas en este caso";
        if (noPasan == 0) return $"PASAN {total}/{total}";
        return $"NO PASA {noPasan}/{total}" + (fuera > 0 ? $" ({fuera} fuera de curva)" : "");
    }

    /// Texto de un plano DXF listo para MOSTRAR: %%C (y %%c) es el codigo
    /// de AutoCAD del simbolo de diametro, y " | malla -" la columna vacia
    /// de una pieza sin malla. El texto del JSON y el de DescribirElemento
    /// (que va a registro.txt) quedan tal cual.
    public static string TextoPlano(string texto)
    {
        if (string.IsNullOrEmpty(texto)) return texto ?? "";
        return texto.Replace("%%C", "\u00D8").Replace("%%c", "\u00D8").Replace(" | malla -", "");
    }

    /// Boton de una opcion entre varias. El activo lleva el acento y el
    /// "> " delante, que es como lo nombran los guiones de la demo.
    public static bool Opcion(bool activo, string texto, params GUILayoutOption[] opciones)
    {
        GUIStyle estilo = activo ? BotonActivo : Boton;
        return GUILayout.Button((activo ? "> " : "") + texto, estilo ?? GUI.skin.button, opciones);
    }

    /// Una fila "etiqueta   valor" con la etiqueta en gris y de ancho fijo.
    public static void Fila(string etiqueta, string valor)
    {
        GUILayout.BeginHorizontal();
        GUILayout.Label(etiqueta, Tenue ?? GUI.skin.label, GUILayout.Width(Px(120f)));
        GUILayout.Label(valor, Texto ?? GUI.skin.label);
        GUILayout.EndHorizontal();
    }

    /// <summary>
    /// De que NUCLEO es esta pata, cuando lo es.
    ///
    /// Lo calcula Python (comun/nucleos.py) y viaja en la fila de
    /// demanda; aca solo se redacta. NO cambia el veredicto: un muro
    /// que es pata de un nucleo se sigue revisando contra SU curva,
    /// que es como revisan los "piers" los programas comerciales y lo
    /// que corresponde, porque el ala traccionada tiene que llevar su
    /// traccion con su propio fierro.
    ///
    /// Lo que dice es de DONDE viene el axial que lo saca de la curva.
    /// Un nucleo resiste el volcamiento como un PAR de axiales entre
    /// sus patas: si el grupo entero esta comprimido, la traccion de
    /// esta pata es ese par interno y no una carga que el grupo tenga
    /// que tomar. Medido en el conjunto: de las 119 filas que no
    /// pasan, 92 son patas de un grupo COMPRIMIDO, 11 de un grupo
    /// traccionado dentro de su As*fy y NINGUNA de un grupo
    /// sobrepasado.
    /// </summary>
    public static string TextoNucleo(DemandaS4 d)
    {
        if (d == null || d.nucleo_patas <= 0) return "";
        string donde = $"Pata de un nucleo de {d.nucleo_patas} muros: el grupo ";
        float traccion = -d.nucleo_P;
        if (d.nucleo_estado == "comprimido")
            return donde + $"esta COMPRIMIDO ({d.nucleo_P:0} kN), asi que la traccion de "
                 + "esta pata es el par interno del nucleo, no carga del grupo.";
        if (d.nucleo_estado == "traccion_dentro")
            return donde + $"tracciona {traccion:0} kN, DENTRO de lo que toma su propio "
                 + $"fierro ({d.nucleo_Asfy:0} kN).";
        return donde + $"tracciona {traccion:0} kN, POR SOBRE lo que toma su fierro "
             + $"({d.nucleo_Asfy:0} kN): esta si es del grupo.";
    }

}
