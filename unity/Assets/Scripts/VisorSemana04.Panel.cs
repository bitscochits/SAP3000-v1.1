/*
================================================================
  VisorSemana04.Panel.cs   (parte de VisorSemana04)
================================================================
  El texto que se suma al panel de VisorQA al seleccionar una barra, y
  los controles de la pestana "Caso" de ese panel.

  El texto contesta lo que pide la semana para la barra seleccionada:
  ID, nodos, seccion, material, ejes locales (esos ya los escribe
  VisorQA), restricciones, N, Vy, Vz, T, My, Mz del caso activo,
  demanda-capacidad y la cadena de trazabilidad.

  EL TEXTO NO SE TOCA: DescribirElemento va a registro.txt de las
  capturas y se cruza con semana04/trazabilidad.py. La Semana 5 cambio
  solo los CONTROLES.

  FORMATO INVARIANTE: en un Windows en espanol, 0.5 saldria "0,5" y
  los numeros no se podrian comparar a simple vista con los que
  imprime semana04/trazabilidad.py, que usa punto.

  ACCIONES DIFERIDAS: cambiar de caso dispara la deformada y el redibujo
  de VisorQA. Hacerlo dentro de OnGUI cambia la cantidad de controles
  entre el evento de Layout y el de Repaint, y IMGUI lo reclama. Por eso
  los botones anotan la accion y se ejecuta en LateUpdate.

  CONTROLES (Semana 5): la misma informacion de antes, en grillas y
  secciones plegables con los estilos escalados de PanelUI.
    - Caso activo: casos base en grilla de 4, combinaciones de 2 (el
      activo lleva "> "), y los controles de superposicion de
      VisorSemana04.Superposicion.cs (Hook_DibujarSuperposicion). Los
      casos tipo "superposicion" (E1..E3, LIBRE) los dibuja ese hook.
    - Diagramas: magnitudes en grilla de 4 x 2, alcance, escala, leyenda.
    - Curva P-M: el toggle de la ventana flotante (PM.cs).
    - Mapa demanda / capacidad (Mapa.cs).
    - Botones de demo.
  Los textos de los botones son los que citan los guiones de la demo
  ("Diagramas de esfuerzos", "todas las visibles", "Columna demo").
================================================================
*/

using System.Globalization;
using System.Text;
using UnityEngine;

public partial class VisorSemana04
{
    private System.Action accionPendiente;

    void Diferir(System.Action accion) { accionPendiente += accion; }

    void LateUpdate()
    {
        if (accionPendiente != null)
        {
            System.Action a = accionPendiente;
            accionPendiente = null;
            a();
        }
        // Despues de las acciones: si una cambio el caso activo, el mapa
        // D/C se repinta en este mismo frame.
        Mapa_Actualizar();
    }

    static string F(float v, string formato)
    {
        return v.ToString(formato, CultureInfo.InvariantCulture);
    }

    static string Cientifico(float v)
    {
        return v.ToString("0.000e+00", CultureInfo.InvariantCulture);
    }

    static string TextoRestr(int[] r)
    {
        if (r == null || r.Length < 6) return "[- - - - - -]";
        return $"[{r[0]} {r[1]} {r[2]} {r[3]} {r[4]} {r[5]}]";
    }

    /// Cuales de N, Vy, Vz, T, My, Mz mandan en cada tipo de barra. En un
    /// muro, el momento de su plano lo dice el JSON (el de inercia mayor)
    /// y el corte que lo acompana: Vz con My, Vy con Mz.
    static bool[] Relevantes(ElementoS4 e)
    {
        string t = e.tipo ?? "";
        if (e.es_brazo_rigido) return new[] { false, false, false, false, false, false };
        if (t.StartsWith("viga")) return new[] { false, true, true, false, true, true };
        if (t == "muro")
            return e.momento_en_el_plano == "My"
                ? new[] { true, false, true, false, true, false }
                : new[] { true, true, false, false, false, true };
        return new[] { true, false, false, false, true, true };
    }

    // ============================================================
    // TEXTO DEL PANEL
    // ============================================================
    public string DescribirElemento(int id)
    {
        var sb = new StringBuilder();
        sb.AppendLine("=========== SEMANA 4 ===========");
        if (!string.IsNullOrEmpty(Aviso)) sb.AppendLine("AVISO: " + Aviso);
        if (Anexo == null) return sb.ToString();

        ElementoS4 e = ElementoPorId(id);
        if (e == null)
        {
            sb.AppendLine($"(el elemento {id} no esta en el anexo)");
            return sb.ToString();
        }

        sb.AppendLine("--- material ---");
        sb.AppendLine(e.material);
        if (e.fpc_MPa > 0f) sb.AppendLine($"f'c    {F(e.fpc_MPa, "0.0")} MPa");
        sb.AppendLine($"E      {F(e.E_kPa / 1000f, "0")} MPa    G  {F(e.G_kPa / 1000f, "0")} MPa");
        sb.AppendLine($"nu     {F(e.poisson, "0.00")}     gamma  {F(e.gamma, "0.0")} kN/m3");

        sb.AppendLine("--- seccion ---");
        sb.AppendLine($"{e.seccion}   b {F(e.b, "0.00")} m   h {F(e.h, "0.00")} m   L {F(e.L, "0.000")} m");
        sb.AppendLine($"A  {F(e.A, "0.0000")} m2    J  {Cientifico(e.J)} m4");
        // En vigas y columnas Iz = b*h^3/12; en un muro la que importa es
        // la de su plano, y cual es lo dice el JSON.
        string rotuloI = e.tipo == "muro" && !string.IsNullOrEmpty(e.momento_en_el_plano)
            ? $"(la del plano: I{(e.momento_en_el_plano == "My" ? "y" : "z")}, momento {e.momento_en_el_plano})"
            : "(Iz = b*h^3/12)";
        sb.AppendLine($"Iy {Cientifico(e.Iy)} m4   Iz {Cientifico(e.Iz)} m4 {rotuloI}");

        sb.AppendLine("--- condiciones  [ux uy uz rx ry rz] ---");
        sb.AppendLine($"nodo {e.n1}  {TextoRestr(e.restr_n1)}"
                      + (e.diafragma_n1 >= 0 ? $"  diafragma, maestro {e.diafragma_n1}" : ""));
        sb.AppendLine($"nodo {e.n2}  {TextoRestr(e.restr_n2)}"
                      + (e.diafragma_n2 >= 0 ? $"  diafragma, maestro {e.diafragma_n2}" : ""));
        if (e.es_brazo_rigido)
            sb.AppendLine("brazo rigido: artificio numerico del muro; no se disena con esto");
        if (!string.IsNullOrEmpty(e.condiciones)) sb.AppendLine(e.condiciones);

        EsfuerzosS4 s = EsfuerzosDe(id);
        CasoS4 caso = CasoActivo();
        sb.AppendLine($"--- esfuerzos, caso activo {casoActivo} ---");
        if (caso != null) sb.AppendLine(caso.descripcion);
        if (s == null || s.f == null || s.f.Length < 12)
        {
            sb.AppendLine("(sin esfuerzos en este caso)");
        }
        else
        {
            // Internos, convencion de cara positiva: los extremos de las
            // estaciones del JSON. N positivo es traccion.
            string[] nombres = { "N", "Vy", "Vz", "T", "My", "Mz" };
            string[] unidades = { "kN", "kN", "kN", "kN*m", "kN*m", "kN*m" };
            bool[] manda = Relevantes(e);
            sb.AppendLine("               extremo i     extremo j");
            for (int k = 0; k < 6; k++)
            {
                float[] v = Magnitud(s, nombres[k]);
                float vi = (v != null && v.Length > 0) ? v[0] : 0f;
                float vj = (v != null && v.Length > 0) ? v[v.Length - 1] : 0f;
                sb.AppendLine($"{(manda[k] ? "*" : " ")} {nombres[k],-2} {unidades[k],-4}  "
                              + $"{F(vi, "0.00"),12}  {F(vj, "0.00"),12}");
            }
            sb.AppendLine($"(ejes locales; * = los que mandan en {e.tipo})");
            Extremo(sb, s, "My");
            Extremo(sb, s, "Mz");
            // La carga que recibe OpenSees en esta barra y en este caso.
            if (s.w != null && s.w.Length == 3
                && (s.w[0] != 0f || s.w[1] != 0f || s.w[2] != 0f))
                sb.AppendLine($"carga repartida (beamUniform)  wx {F(s.w[0], "0.000")}  "
                              + $"wy {F(s.w[1], "0.000")}  wz {F(s.w[2], "0.000")} kN/m");
            else
                sb.AppendLine("carga repartida: ninguna en este caso");
        }

        sb.AppendLine("--- demanda / capacidad ---");
        FamiliaPM fam = (e.familia >= 0 && Anexo.familias != null && e.familia < Anexo.familias.Count)
                        ? Anexo.familias[e.familia] : null;
        if (fam == null)
        {
            sb.AppendLine("(sin enfierradura: no tiene curva P-M)");
        }
        else
        {
            DemandaS4 d = DemandaDe(id, casoActivo);
            sb.AppendLine($"familia {fam.indice}: {fam.clave}");
            if (d != null)
            {
                string cual = e.tipo == "muro" ? $" (|{e.momento_en_el_plano}|, en su plano)" : "";
                sb.AppendLine($"P {F(d.P, "0.0")} kN   M {F(d.M, "0.0")} kN*m{cual}   extremo {d.extremo}");
                sb.AppendLine(d.u >= 9999f
                    ? TextoFueraDeCurva(d, fam)
                    : $"Mn {F(d.Mn, "0.0")} kN*m   u {F(d.u, "0.000")}   {(d.pasa ? "PASA" : "NO PASA")}");
            }
        }

        sb.AppendLine("--- trazabilidad ---");
        sb.AppendLine("OpenSees    " + e.tag_opensees);
        GameObject go = visor != null ? visor.ObjetoDeElemento(id) : null;
        DatoElemento dato = go != null ? go.GetComponent<DatoElemento>() : null;
        if (go == null)
        {
            sb.AppendLine($"Unity       (la barra no esta dibujada: capa apagada) se espera \"{e.objeto_unity}\"");
        }
        else
        {
            // Se comprueba AHORA, sobre el objeto real de la escena: que se
            // llame como dice el JSON y que su DatoElemento tenga ese id.
            bool calza = go.name == e.objeto_unity && dato != null && dato.idElemento == id;
            sb.AppendLine($"Unity       GameObject \"{go.name}\"  DatoElemento.idElemento = "
                          + $"{(dato != null ? dato.idElemento.ToString() : "-")}  {(calza ? "OK" : "NO CALZA")}");
        }
        sb.AppendLine($"Resultados  semana04.json casos[{casoActivo}].esfuerzos[id={id}].f");
        sb.AppendLine($"            {e.resultados}");
        if (s != null && s.f != null && s.f.Length == 12)
        {
            sb.AppendLine("            f_i " + Vector6(s.f, 0));
            sb.AppendLine("            f_j " + Vector6(s.f, 6));
        }
        sb.AppendLine(fam != null
            ? $"Seccion     \"{e.seccion}\" -> familia P-M {fam.indice} ({fam.clave})"
            : $"Seccion     \"{e.seccion}\" (sin familia P-M)");
        sb.AppendLine(AnexoCalzaConElModelo
            ? "Modelo      nodos y seccion del anexo calzan con el modelo del visor: OK"
            : "Modelo      el anexo NO calza con el modelo del visor");
        return sb.ToString();
    }

    static void Extremo(StringBuilder sb, EsfuerzosS4 s, string m)
    {
        float[] v = Magnitud(s, m);
        if (v == null || s.x == null || v.Length != s.x.Length || v.Length == 0) return;
        int k = 0;
        for (int i = 1; i < v.Length; i++)
            if (Mathf.Abs(v[i]) > Mathf.Abs(v[k])) k = i;
        sb.AppendLine($"max |{m}| = {F(Mathf.Abs(v[k]), "0.00")} kN*m en x = {F(s.x[k], "0.00")} m"
                      + $"  ({v.Length} estaciones)");
    }

    static string Vector6(float[] f, int desde)
    {
        var sb = new StringBuilder("[");
        for (int k = 0; k < 6; k++)
            sb.Append((k > 0 ? "  " : "") + F(f[desde + k], "0.00"));
        return sb.Append("]").ToString();
    }

    // ============================================================
    // CONTROLES (pestana Caso de VisorQA, dentro de su scroll)
    // ============================================================

    // Lo que decide QUE controles hay se congela en el evento Layout y
    // vale para el resto de los eventos del frame. Si un control
    // apareciera entre el Layout y el Repaint (o el click), IMGUI tira
    // "Getting control N's position in a group with only N controls".
    // Por la misma razon los botones y toggles que agregan o quitan
    // controles cambian el estado con Diferir, no en el acto.
    private string Pnl_avisoEnLayout = "";
    private bool Pnl_hayAnexoEnLayout = false;
    private bool Pnl_diagramasEnLayout = false;
    private string Pnl_motivoSinDiagramaEnLayout = "";
    private string Pnl_avisoDeLecturaEnLayout = "";
    private bool Pnl_pedirClickEnLayout = false;

    public void DibujarControles()
    {
        // Idempotente: VisorQA ya lo llama al empezar su OnGUI. Si el que
        // llama no lo hizo, los estilos existen igual.
        PanelUI.Preparar();

        if (Event.current.type == EventType.Layout)
        {
            Pnl_avisoEnLayout = Aviso ?? "";
            Pnl_hayAnexoEnLayout = Anexo != null;
            Pnl_diagramasEnLayout = mostrarDiagramas;
            Pnl_motivoSinDiagramaEnLayout = MotivoSinDiagrama ?? "";
            Pnl_avisoDeLecturaEnLayout = AvisoDeLectura ?? "";
            Pnl_pedirClickEnLayout = soloSeleccionado && Seleccionado < 0;
        }

        if (Pnl_avisoEnLayout.Length > 0) GUILayout.Label("AVISO: " + Pnl_avisoEnLayout, PanelUI.Aviso);
        if (!Pnl_hayAnexoEnLayout || Anexo == null) return;

        // ---------- caso activo ----------
        if (PanelUI.Plegable("s4.casos", "Casos del anexo (Semana 4)", true))
        {
            CasoS4 activo = CasoActivo();
            GUILayout.Label("Caso activo: " + casoActivo
                            + (activo != null ? "  =  " + activo.descripcion : ""), PanelUI.Texto);
            if (Event.current.type == EventType.Layout) Pnl_ArmarGrillasDeCasos();
            Pnl_GrillaDeCasos("casos base", Pnl_nombresBase, Pnl_textosBase, 4);
            Pnl_GrillaDeCasos("combinaciones", Pnl_nombresComb, Pnl_textosComb, 2);
        }

        // Sliders de lambda, E1..E3 y "Combinar en Python" (U3). Una vez.
        Hook_DibujarSuperposicion();

        // ---------- diagramas ----------
        if (PanelUI.Plegable("s4.diagramas", "Diagramas", true))
        {
            bool diag = Pnl_Toggle(Pnl_diagramasEnLayout, "Diagramas de esfuerzos");
            if (diag != Pnl_diagramasEnLayout)
                Diferir(() => { mostrarDiagramas = diag; necesitaRedibujar = true; });
            if (Pnl_diagramasEnLayout) Pnl_ControlesDeDiagrama();
        }

        // ---------- curva P-M ----------
        if (PanelUI.Plegable("s4.pm", "Curva P-M", false))
        {
            // No agrega ni quita controles del panel: la ventana se decide
            // en su propio OnGUI (PM.cs).
            bool pm = Pnl_Toggle(mostrarPM, "Curva P-M de la seleccionada (ventana)");
            if (pm != mostrarPM) { mostrarPM = pm; texturaPMFirma = null; }
            GUILayout.Label("La pestana Elemento la dibuja dentro del panel; mientras se ve ahi, "
                            + "la ventana flotante se oculta. La ventana sirve para seguir el punto "
                            + "de demanda mientras se cambia de caso.", PanelUI.Tenue);
            GUILayout.Label(Pnl_ResumenFamilias(), PanelUI.Tenue);
        }

        // ---------- mapa demanda / capacidad ----------
        Mapa_DibujarControles();

        // ---------- demo ----------
        int col = Anexo.info != null ? Anexo.info.columna_demo : -1;
        int mur = Anexo.info != null ? Anexo.info.muro_demo : -1;
        if (col >= 0 || mur >= 0)
        {
            GUILayout.Space(PanelUI.Px(6f));
            GUILayout.BeginHorizontal();
            if (col >= 0 && GUILayout.Button($"Columna demo ({col})", PanelUI.Boton)) Diferir(() => IrA(col));
            if (mur >= 0 && GUILayout.Button($"Muro demo ({mur})", PanelUI.Boton)) Diferir(() => IrA(mur));
            GUILayout.EndHorizontal();
        }
    }

    void Pnl_ControlesDeDiagrama()
    {
        // magnitudes: 8 en una grilla de 4 x 2
        int actual = System.Array.IndexOf(MAGNITUDES, magnitud);
        int elegida = GUILayout.SelectionGrid(actual, Pnl_TextosMagnitud(), 4, PanelUI.Boton);
        if (elegida != actual && elegida >= 0 && elegida < MAGNITUDES.Length)
        {
            string m = MAGNITUDES[elegida];
            Diferir(() => { magnitud = m; necesitaRedibujar = true; });
        }

        int alcance = soloSeleccionado ? 0 : 1;
        int nuevo = GUILayout.SelectionGrid(alcance, soloSeleccionado ? Pnl_ALCANCE_SOLA : Pnl_ALCANCE_TODAS,
                                            2, PanelUI.Boton);
        if (nuevo != alcance)
        {
            bool sola = nuevo == 0;
            Diferir(() => { soloSeleccionado = sola; necesitaRedibujar = true; });
        }

        // El slider cambia en el acto: solo mueve un numero y un texto, no
        // agrega controles, y diferirlo lo haria saltar al arrastrar.
        GUILayout.Label($"escala del diagrama x{F(multiplicadorEscala, "0.0")} (solo grafica)", PanelUI.Texto);
        float esc = GUILayout.HorizontalSlider(multiplicadorEscala, 0.1f, 5f);
        if (!Mathf.Approximately(esc, multiplicadorEscala))
        { multiplicadorEscala = esc; necesitaRedibujar = true; }

        GUILayout.Label(LeyendaDiagrama(), PanelUI.Tenue);
        // Por que no se ve nada: el visor no se queda mudo.
        if (Pnl_motivoSinDiagramaEnLayout.Length > 0)
            GUILayout.Label("sin diagrama: " + Pnl_motivoSinDiagramaEnLayout, PanelUI.Aviso);
        else if (Pnl_pedirClickEnLayout)
            GUILayout.Label("(click en una barra para ver su diagrama)", PanelUI.Tenue);
        // Y esto se dibujo, pero cuesta verlo.
        if (Pnl_avisoDeLecturaEnLayout.Length > 0)
            GUILayout.Label("ojo: " + Pnl_avisoDeLecturaEnLayout, PanelUI.Aviso);
    }

    // ------------------------------------------------------------
    // Grillas de casos. Los textos se arman solo cuando cambia el caso
    // activo o la lista de casos, y solo en el Layout: OnGUI llega varias
    // veces por frame y la grilla tiene que tener los mismos botones en
    // todos sus eventos.
    // ------------------------------------------------------------
    private readonly System.Collections.Generic.List<string> Pnl_nombresBase =
        new System.Collections.Generic.List<string>();
    private readonly System.Collections.Generic.List<string> Pnl_nombresComb =
        new System.Collections.Generic.List<string>();
    private string[] Pnl_textosBase = new string[0];
    private string[] Pnl_textosComb = new string[0];
    private string Pnl_casoGrillas = null;
    private int Pnl_versionGrillas = -1;
    private int Pnl_cuantosGrillas = -1;
    private AnexoSemana04 Pnl_anexoGrillas = null;

    private string[] Pnl_textosMagnitud = null;
    private string Pnl_magnitudTextos = null;

    static readonly string[] Pnl_ALCANCE_SOLA = { "> la seleccionada", "todas las visibles" };
    static readonly string[] Pnl_ALCANCE_TODAS = { "la seleccionada", "> todas las visibles" };

    void Pnl_ArmarGrillasDeCasos()
    {
        int cuantos = Anexo.casos != null ? Anexo.casos.Count : 0;
        if (casoActivo == Pnl_casoGrillas && versionCasos == Pnl_versionGrillas
            && cuantos == Pnl_cuantosGrillas && Anexo == Pnl_anexoGrillas)
            return;
        Pnl_casoGrillas = casoActivo;
        Pnl_versionGrillas = versionCasos;
        Pnl_cuantosGrillas = cuantos;
        Pnl_anexoGrillas = Anexo;

        Pnl_nombresBase.Clear();
        Pnl_nombresComb.Clear();
        if (Anexo.casos != null)
            foreach (CasoS4 c in Anexo.casos)
            {
                if (c == null || string.IsNullOrEmpty(c.nombre)) continue;
                // Las superposiciones (E1..E3, LIBRE) van con sus sliders,
                // en el hook de U3. Cualquier otro tipo, con los base.
                if (c.tipo == TIPO_SUPERPOSICION) continue;
                if (c.tipo == "combinacion") Pnl_nombresComb.Add(c.nombre);
                else Pnl_nombresBase.Add(c.nombre);
            }
        Pnl_textosBase = Pnl_ConMarca(Pnl_nombresBase);
        Pnl_textosComb = Pnl_ConMarca(Pnl_nombresComb);
    }

    string[] Pnl_ConMarca(System.Collections.Generic.List<string> nombres)
    {
        var textos = new string[nombres.Count];
        for (int i = 0; i < nombres.Count; i++)
            textos[i] = (nombres[i] == casoActivo ? "> " : "") + nombres[i];
        return textos;
    }

    /// Una grilla de botones de caso. El activo lleva "> " y el color de
    /// acento (el estado "on" de PanelUI.Boton); si el activo no esta en
    /// esta grilla (E1..E3, LIBRE), ninguno queda marcado.
    void Pnl_GrillaDeCasos(string titulo, System.Collections.Generic.List<string> nombres,
                           string[] textos, int columnas)
    {
        if (nombres.Count == 0 || textos.Length != nombres.Count) return;
        GUILayout.Label(titulo, PanelUI.Tenue);
        int actual = nombres.IndexOf(Pnl_casoGrillas);
        int elegido = GUILayout.SelectionGrid(actual, textos, Mathf.Min(columnas, textos.Length),
                                              PanelUI.Boton);
        if (elegido != actual && elegido >= 0 && elegido < nombres.Count)
        {
            string nombre = nombres[elegido];
            Diferir(() => ElegirCaso(nombre));
        }
    }

    string[] Pnl_TextosMagnitud()
    {
        if (Pnl_textosMagnitud != null && magnitud == Pnl_magnitudTextos) return Pnl_textosMagnitud;
        Pnl_magnitudTextos = magnitud;
        Pnl_textosMagnitud = new string[MAGNITUDES.Length];
        for (int i = 0; i < MAGNITUDES.Length; i++)
            Pnl_textosMagnitud[i] = (MAGNITUDES[i] == magnitud ? "> " : "") + MAGNITUDES[i];
        return Pnl_textosMagnitud;
    }

    private AnexoSemana04 Pnl_anexoFamilias = null;
    private string Pnl_textoFamilias = "";

    /// Cuantas barras tienen curva P-M: lo que el JSON trae, contado. Una
    /// vez por anexo, no en cada evento de OnGUI.
    string Pnl_ResumenFamilias()
    {
        if (Anexo == Pnl_anexoFamilias) return Pnl_textoFamilias;
        Pnl_anexoFamilias = Anexo;
        int conFamilia = 0, total = 0;
        if (Anexo != null && Anexo.elementos != null)
            foreach (ElementoS4 e in Anexo.elementos)
            {
                total++;
                if (PM_FamiliaDe(e) != null) conFamilia++;
            }
        int familias = Anexo != null && Anexo.familias != null ? Anexo.familias.Count : 0;
        Pnl_textoFamilias = $"{conFamilia} de {total} barras con fierro, {familias} curvas P-M "
                          + "distintas en el anexo";
        return Pnl_textoFamilias;
    }

    // ------------------------------------------------------------
    // Toggle con la letra escalada. PanelUI no trae uno: se copia el del
    // skin y se le pone la fuente de PanelUI.Texto. Se rehace cuando
    // PanelUI rehace sus estilos (cambio de escala): ahi Texto es otro
    // objeto.
    // ------------------------------------------------------------
    private GUIStyle Pnl_estiloToggle = null;
    private GUIStyle Pnl_textoDelToggle = null;

    bool Pnl_Toggle(bool valor, string texto)
    {
        GUIStyle baseTexto = PanelUI.Texto;
        if (baseTexto != null && (Pnl_estiloToggle == null || Pnl_textoDelToggle != baseTexto))
        {
            Pnl_estiloToggle = new GUIStyle(PanelUI.Casilla ?? GUI.skin.toggle);   // casilla escalada
            Pnl_estiloToggle.fontSize = baseTexto.fontSize;
            Pnl_estiloToggle.wordWrap = false;
            Color c = PanelUI.ColorTexto;
            Pnl_estiloToggle.normal.textColor = c;
            Pnl_estiloToggle.hover.textColor = c;
            Pnl_estiloToggle.active.textColor = c;
            Pnl_estiloToggle.onNormal.textColor = c;
            Pnl_estiloToggle.onHover.textColor = c;
            Pnl_estiloToggle.onActive.textColor = c;
            Pnl_textoDelToggle = baseTexto;
        }
        return GUILayout.Toggle(valor, texto, Pnl_estiloToggle ?? GUI.skin.toggle);
    }

    string LeyendaDiagrama()
    {
        string lado;
        switch (magnitud)
        {
            case "My": lado = "del lado traccionado: +My hacia +z local"; break;
            case "Mz": lado = "del lado traccionado: -Mz hacia +y local"; break;
            case "N": lado = "en z local; azul traccion, rojo compresion"; break;
            case "wy":
            case "wz":
                lado = "en " + (magnitud == "wy" ? "y" : "z") + " local, hacia donde "
                     + "empuja: es la carga repartida que recibe OpenSees, no un esfuerzo";
                break;
            default: lado = "en " + (magnitud == "Vy" ? "y" : "z") + " local"; break;
        }
        string largo = F(largoDiagramaMaximo * multiplicadorEscala, "0.0");
        string u = UnidadDe(magnitud);
        string escala = "";
        if (mayorBarrasDibujado > 0f)
            escala += $"\n{largo} m = {F(mayorBarrasDibujado, "0.0")} {u} en vigas y columnas";
        if (mayorMurosDibujado > 0f)
            escala += $"\n{largo} m = {F(mayorMurosDibujado, "0.0")} {u} en muros (escala aparte)";
        return $"{magnitud} dibujado {lado}\nazul = {magnitud} > 0, rojo = {magnitud} < 0{escala}";
    }

    /// Selecciona la barra y le pide a la camara que la encuadre. Lo usan
    /// los botones de demo y la lista de criticos del mapa D/C.
    ///
    /// La seleccion va por VisorQA (la describe en la pestana Elemento y
    /// avisa SeleccionCambio, la unica fuente de seleccion). La camara va
    /// por EventosVisor.PedirCentrar con el centro en coordenadas Unity y
    /// donde la barra esta DIBUJADA ahora (con la deformada, si esta
    /// puesta). Sin VisorQA en la escena, se selecciona aca y la camara
    /// se mueve igual.
    void IrA(int id)
    {
        if (qa != null) qa.SeleccionarElemento(id);
        else Seleccionar(id);

        if (visor == null || visor.Modelo == null) return;
        Elemento e = visor.Modelo.ElementoPorId(id);
        if (e == null) return;
        Nodo a = visor.Modelo.NodoPorId(e.n1);
        Nodo b = visor.Modelo.NodoPorId(e.n2);
        if (a == null || b == null) return;

        Vector3 pa = visor.PosicionActual(a), pb = visor.PosicionActual(b);
        // Lo que hay que encuadrar: la barra, o el ancho del muro si es mas
        // largo que alto; nunca menos de 3 m (igual que "Centrar" de VisorQA).
        ElementoS4 s = ElementoPorId(id);
        float tamano = Mathf.Max(Vector3.Distance(pa, pb), s != null ? Mathf.Max(s.b, s.h) : 0f, 3f);
        EventosVisor.AvisarPedirCentrar((pa + pb) * 0.5f, tamano);
    }
}
