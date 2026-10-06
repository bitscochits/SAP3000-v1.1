/*
================================================================
  CapturaSemana04.cs
================================================================
  Saca capturas de la Semana 4 sin intervencion: para revisar el visor
  A LA VISTA -- un diagrama puede compilar, leer bien el JSON y aun
  asi dibujarse del lado equivocado -- y para el informe.

      build/LaboratorioEstructural.exe -capturarS4 <carpeta>
            -screen-width 1920 -screen-height 1080 -screen-fullscreen 0

  Sin ese argumento no hace nada: ni siquiera crea su objeto. Es una
  herramienta de verificacion, no parte del visor.

  Cada escena se arma con la MISMA API que usan los botones del panel
  (SeleccionarElemento, ElegirCaso, EnfocarElemento), asi que lo que
  se captura es lo que ve quien hace la demo. Junto a cada imagen deja
  el texto del panel de Semana 4, para cruzarlo con
  semana04/trazabilidad.py.

  Toca dos campos privados por reflexion -- el scroll del panel de
  VisorQA y el angulo de la camara -- solo para que la captura muestre
  la parte del panel que importa desde un angulo que se lea. No cambia
  nada del calculo. Si un campo cambio de nombre o de tipo, la foto sale
  igual pero registro.txt dice "AVISO reflexion": antes callaba y la
  captura mostraba otra parte del panel sin que nadie lo notara.

  Desde la Semana 5 el panel va en pestanas: antes de cada foto se fija
  la que tiene lo que la foto muestra (Elemento para una barra con su
  P-M, Caso para los diagramas y la deformada, Capas para las capas QA).
  Con la pestana equivocada el scroll no apunta a nada.
================================================================
*/

using System.Collections;
using System.IO;
using System.Reflection;
using System.Text;
using UnityEngine;

public class CapturaSemana04 : MonoBehaviour
{
    private string carpeta;
    private readonly StringBuilder registro = new StringBuilder();

    // La pestana que se fijo para la foto que viene; Foto comprueba que
    // siga siendo esa al disparar.
    private VisorQA qa;
    private string pestanaEsperada;
    private float scrollEsperado;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Arrancar()
    {
        string[] args = System.Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
        {
            if (args[i] != "-capturarS4") continue;
            var go = new GameObject("CapturaSemana04");
            go.AddComponent<CapturaSemana04>().carpeta = args[i + 1];
            return;
        }
    }

    IEnumerator Start()
    {
        Directory.CreateDirectory(carpeta);
        // Los visores cargan en su Start y esperan un frame: margen amplio.
        yield return new WaitForSeconds(5f);
        // Desde la Semana 5 la carga es asincrona (LectorStreaming): los 5 s
        // son un margen, no una garantia. Ademas se espera a que el modelo y
        // el anexo esten leidos, con tope de 30 s para que un archivo que
        // falta no cuelgue la captura (el chequeo de abajo escribe ERROR.txt).
        float tope = Time.realtimeSinceStartup + 30f;
        yield return new WaitUntil(() =>
        {
            VisorEstructura v = FindAnyObjectByType<VisorEstructura>();
            VisorSemana04 s = FindAnyObjectByType<VisorSemana04>();
            return Time.realtimeSinceStartup > tope
                || (v != null && v.Listo && s != null && s.Anexo != null);
        });

        qa = FindAnyObjectByType<VisorQA>();
        VisorSemana04 s4 = FindAnyObjectByType<VisorSemana04>();
        CamaraOrbital cam = FindAnyObjectByType<CamaraOrbital>();
        if (qa == null || s4 == null || cam == null || s4.Anexo == null)
        {
            File.WriteAllText(Path.Combine(carpeta, "ERROR.txt"),
                "falta VisorQA, VisorSemana04, CamaraOrbital o el anexo. Aviso: "
                + (s4 != null ? s4.Aviso : "(sin VisorSemana04)"));
            Application.Quit(2);
            yield break;
        }

        InfoSemana04 info = s4.Anexo.info;
        int col = info.columna_demo;
        int mur = info.muro_demo;
        registro.AppendLine("edificio " + info.edificio + "  caso por defecto " + info.caso_por_defecto);
        registro.AppendLine("aviso del anexo: '" + s4.Aviso + "'  calza con el modelo: " + s4.AnexoCalzaConElModelo);
        registro.AppendLine();

        Angulo(cam, 28f, 35f);
        // La lamina ampliada de la Semana 3 queda detras del panel: fuera.
        VisorSemana03 s3 = FindAnyObjectByType<VisorSemana03>();
        if (s3 != null && s3.jaulaDetalle) { s3.jaulaDetalle = false; s3.Redibujar(); }
        s4.mostrarDiagramas = true;
        s4.mostrarPM = true;
        s4.multiplicadorEscala = 1f;

        // 1. La columna demo: panel con material, esfuerzos, trazabilidad y P-M.
        //    Pestana Elemento al fondo: las ultimas secciones del inspector y
        //    la curva P-M dentro del panel (antes: el final del scroll unico).
        s4.ElegirCaso(info.caso_por_defecto);
        s4.magnitud = "My";
        s4.soloSeleccionado = true;
        qa.SeleccionarElemento(col);
        s4.EnfocarElemento(col);
        Pestana(VisorQA.PESTANA_ELEMENTO, 100000f);
        yield return Foto("01_columna_" + col + "_panel_y_PM", s4, col);

        // 2. Momento My de las vigas de un piso: el lado traccionado a la vista.
        //    ElegirPiso y no soloNivel a mano: copia la cota a AjustesVista en
        //    el acto, y el visor filtra el piso antes de la foto.
        s4.soloSeleccionado = false;
        s4.magnitud = "My";
        qa.ElegirPiso(2);
        s4.Redibujar();
        EncuadrarNivel(qa, cam);
        Pestana(VisorQA.PESTANA_CASO, 0f);
        yield return Foto("02_My_todas_piso_2", s4, -1);

        // 3. Una viga cargada con su parabola y sus etiquetas.
        int viga = VigaConParabola(s4, info.caso_por_defecto);
        if (viga >= 0)
        {
            s4.soloSeleccionado = true;
            qa.ElegirPiso(-1);
            qa.SeleccionarElemento(viga);
            s4.EnfocarElemento(viga);
            Angulo(cam, 12f, 20f);
            Pestana(VisorQA.PESTANA_CASO, 0f);
            yield return Foto("03_viga_" + viga + "_My_etiquetas", s4, viga);
            Angulo(cam, 28f, 35f);
        }

        // 4. Axial N en todo el edificio: traccion y compresion por color.
        s4.soloSeleccionado = false;
        s4.magnitud = "N";
        qa.ElegirPiso(-1);
        s4.Redibujar();
        cam.EncuadrarTodo();
        Pestana(VisorQA.PESTANA_CASO, 0f);
        yield return Foto("04_N_todas", s4, -1);

        // 4b. La carga repartida del mismo piso: la causa del diagrama.
        s4.magnitud = "wz";
        qa.ElegirPiso(2);
        s4.Redibujar();
        EncuadrarNivel(qa, cam);
        Pestana(VisorQA.PESTANA_CASO, 0f);
        yield return Foto("04b_wz_todas_piso_2", s4, -1);

        // 5. Corte Vz de un piso.
        s4.magnitud = "Vz";
        qa.ElegirPiso(2);
        s4.Redibujar();
        EncuadrarNivel(qa, cam);
        Pestana(VisorQA.PESTANA_CASO, 0f);
        yield return Foto("05_Vz_todas_piso_2", s4, -1);

        // 5b. Capas: areas tributarias y cargas G del mismo piso, sin diagramas.
        //     Pestana Capas: la leyenda de apoyos y el conteo de areas.
        s4.mostrarDiagramas = false;
        s4.mostrarPM = false;
        s4.Redibujar();
        qa.verAreasTributarias = true;
        Refrescar(qa);
        Pestana(VisorQA.PESTANA_CAPAS, 0f);
        if (s3 != null)
        {
            s3.mostrarCargas = true;
            s3.cargasConLaDeformada = false;
            s3.casoCarga = "G";
            s3.Redibujar();
        }
        yield return Foto("05b_capas_areas_y_cargas_G_piso_2", s4, -1);
        qa.verAreasTributarias = false;
        Refrescar(qa);
        if (s3 != null)
        {
            s3.cargasConLaDeformada = true;
            s3.casoCarga = "EX";
            s3.Redibujar();
        }
        s4.mostrarDiagramas = true;
        s4.mostrarPM = true;

        // 6. El muro demo con su P-M, en la combinacion con sismo en Y.
        s4.soloSeleccionado = true;
        s4.magnitud = EnSuPlano(s4, mur);
        qa.ElegirPiso(-1);
        s4.ElegirCaso("1.2G+1.0Q+1.4EY");
        qa.SeleccionarElemento(mur);
        s4.EnfocarElemento(mur);
        Pestana(VisorQA.PESTANA_ELEMENTO, 100000f);
        yield return Foto("06_muro_" + mur + "_" + s4.magnitud + "_PM_1.2G+1.0Q+1.4EY", s4, mur);

        // 7 y 8. Los dos casos que no pasan, si existen en este edificio.
        //     Como la 6: pestana Elemento al fondo, con su P-M.
        if (s4.ElementoPorId(80) != null && info.edificio == "ingenieria")
        {
            s4.magnitud = "My";
            s4.ElegirCaso(info.caso_por_defecto);
            qa.SeleccionarElemento(80);
            s4.EnfocarElemento(80);
            Pestana(VisorQA.PESTANA_ELEMENTO, 100000f);
            yield return Foto("07_columna_80_no_pasa", s4, 80);
        }
        if (s4.ElementoPorId(427) != null && info.edificio == "ingenieria")
        {
            s4.magnitud = EnSuPlano(s4, 427);
            s4.ElegirCaso("1.2G+1.0Q+1.4EX");
            qa.SeleccionarElemento(427);
            s4.EnfocarElemento(427);
            Pestana(VisorQA.PESTANA_ELEMENTO, 100000f);
            yield return Foto("08_muro_427_fuera_de_curva", s4, 427);
        }
        if (s4.ElementoPorId(508) != null && info.edificio == "ingenieria")
        {
            // Un muro corto traccionado por el sismo en Y: no pasa en flexion.
            s4.magnitud = EnSuPlano(s4, 508);
            s4.ElegirCaso("1.2G+1.0Q+1.4EY");
            qa.SeleccionarElemento(508);
            s4.EnfocarElemento(508);
            Pestana(VisorQA.PESTANA_ELEMENTO, 100000f);
            yield return Foto("08b_muro_508_no_pasa_1.2G+1.0Q+1.4EY", s4, 508);
        }

        // 9. Deformada de una combinacion.
        s4.mostrarPM = false;
        s4.mostrarDiagramas = false;
        s4.ElegirCaso("1.2G+1.0Q+1.4EY");
        s4.AplicarDeformadaDelCaso();
        s4.Redibujar();
        cam.EncuadrarTodo();
        Pestana(VisorQA.PESTANA_CASO, 0f);
        yield return Foto("09_deformada_1.2G+1.0Q+1.4EY", s4, -1);

        File.WriteAllText(Path.Combine(carpeta, "registro.txt"), registro.ToString());
        yield return new WaitForSeconds(0.5f);
        Application.Quit(0);
    }

    IEnumerator Foto(string nombre, VisorSemana04 s4, int id)
    {
        // El scroll se vuelve a fijar un frame despues de Pestana(). VisorQA
        // arma el inspector de la seleccion nueva en su Update, que corre
        // DESPUES de esta corrutina: en el OnGUI de ese mismo frame el panel
        // todavia tiene los bloques de antes y el ScrollView recorta el
        // scroll a lo que cabe. En la foto 01 no habia seleccion previa, el
        // contenido era corto y el scroll quedaba en 0: la foto "panel y P-M"
        // salia sin la P-M ni la trazabilidad (medido en la integracion S5).
        yield return null;
        if (qa != null) Scroll(qa, scrollEsperado);
        // Que se rehagan mallas, texturas y el OnGUI con el estado nuevo.
        yield return new WaitForSeconds(1.5f);
        string ruta = Path.Combine(carpeta, nombre + ".png");
        ScreenCapture.CaptureScreenshot(ruta);
        yield return new WaitForEndOfFrame();
        yield return new WaitForSeconds(1f);

        registro.AppendLine("=== " + nombre + " ===");
        // Solo si algo cambio la pestana entre Pestana() y la foto (un
        // click, un panel incrustable): en el caso normal registro.txt queda
        // linea por linea igual al de la Semana 4.
        if (qa != null && !string.IsNullOrEmpty(pestanaEsperada) && qa.Pestana != pestanaEsperada)
            registro.AppendLine("AVISO pestana: se fijo '" + pestanaEsperada + "' y la foto salio con '"
                                + qa.Pestana + "'");
        registro.AppendLine($"caso {s4.casoActivo}  magnitud {s4.magnitud}  "
                            + $"solo seleccionada {s4.soloSeleccionado}  seleccionado {s4.Seleccionado}");
        if (id >= 0) registro.AppendLine(s4.DescribirElemento(id));
        registro.AppendLine();
    }

    /// La viga cuyo momento mas se curva por su propia carga: su diagrama es
    /// una parabola que se lee sola. Solo elige que mostrar.
    static int VigaConParabola(VisorSemana04 s4, string caso)
    {
        int mejor = -1;
        float mayor = 0f;
        foreach (ElementoS4 e in s4.Anexo.elementos)
        {
            if (e.tipo == null || !e.tipo.StartsWith("viga") || !e.cargada) continue;
            CasoS4 c = s4.Anexo.casos.Find(x => x.nombre == caso);
            if (c == null) return -1;
            EsfuerzosS4 s = c.esfuerzos.Find(x => x.id == e.id);
            if (s == null || s.My == null || s.My.Length < 3) continue;
            float medio = Mathf.Abs(s.My[s.My.Length / 2] - 0.5f * (s.My[0] + s.My[s.My.Length - 1]));
            if (medio > mayor) { mayor = medio; mejor = e.id; }
        }
        return mejor;
    }

    /// Centra la camara en los nodos del piso filtrado, para que sus
    /// diagramas se lean. Solo elige el encuadre.
    static void EncuadrarNivel(VisorQA qa, CamaraOrbital cam)
    {
        VisorEstructura v = FindAnyObjectByType<VisorEstructura>();
        if (v == null || v.Modelo == null || v.Modelo.nodos == null) { cam.EncuadrarTodo(); return; }
        bool hay = false;
        Bounds b = default;
        foreach (Nodo n in v.Modelo.nodos)
        {
            if (!qa.NivelVisible((float)n.z)) continue;
            Vector3 p = Ejes.PosicionDe(n);
            if (!hay) { b = new Bounds(p, Vector3.zero); hay = true; }
            else b.Encapsulate(p);
        }
        if (!hay) { cam.EncuadrarTodo(); return; }
        cam.centro = b.center;
        cam.distancia = Mathf.Clamp(b.extents.magnitude * 1.5f, 10f, 150f);
    }

    /// El momento del plano del muro, tal como lo trae el JSON.
    static string EnSuPlano(VisorSemana04 s4, int id)
    {
        ElementoS4 e = s4.ElementoPorId(id);
        return e != null && e.momento_en_el_plano == "My" ? "My" : "Mz";
    }

    /// Fija la pestana del panel y despues su scroll. En ese orden:
    /// ElegirPestana vuelve el scroll arriba, asi que al reves el scroll se
    /// perderia.
    void Pestana(string titulo, float scrollY)
    {
        // En el inspector la trazabilidad viene plegada; la foto de la
        // Semana 4 la mostraba al fondo del panel, junto a la P-M. La
        // captura cierra la app al terminar: no deja el plegable cambiado.
        if (titulo == VisorQA.PESTANA_ELEMENTO) PanelUI.FijarPlegable("qa.s4.trazabilidad", true);
        qa.ElegirPestana(titulo);
        pestanaEsperada = titulo;
        scrollEsperado = scrollY;
        Scroll(qa, scrollY);
    }

    /// Pide a VisorQA que rehaga sus capas en el proximo frame.
    void Refrescar(VisorQA qa)
    {
        FieldInfo f = typeof(VisorQA).GetField("refrescar", BindingFlags.NonPublic | BindingFlags.Instance);
        Fijar(f, qa, true, "VisorQA.refrescar (bool)");
    }

    void Scroll(VisorQA qa, float y)
    {
        FieldInfo f = typeof(VisorQA).GetField("scroll", BindingFlags.NonPublic | BindingFlags.Instance);
        Fijar(f, qa, new Vector2(0f, y), "VisorQA.scroll (Vector2)");
    }

    void Angulo(CamaraOrbital cam, float pitch, float yaw)
    {
        const BindingFlags B = BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance;
        FieldInfo fp = typeof(CamaraOrbital).GetField("pitch", B);
        FieldInfo fy = typeof(CamaraOrbital).GetField("yaw", B);
        Fijar(fp, cam, pitch, "CamaraOrbital.pitch (float)");
        Fijar(fy, cam, yaw, "CamaraOrbital.yaw (float)");
    }

    /// Asigna un campo leido por reflexion. Si no existe o cambio de tipo
    /// lo deja escrito en registro.txt (y en el log) en vez de callar: la
    /// foto saldria desde otro angulo u otra parte del panel y nadie lo
    /// sabria.
    void Fijar(FieldInfo f, object objeto, object valor, string campo)
    {
        if (f == null)
        {
            Avisar("AVISO reflexion: no existe el campo " + campo);
            return;
        }
        if (!f.FieldType.IsInstanceOfType(valor))
        {
            Avisar("AVISO reflexion: " + campo + " ahora es " + f.FieldType.Name);
            return;
        }
        try
        {
            f.SetValue(objeto, valor);
        }
        catch (System.Exception ex)
        {
            Avisar("AVISO reflexion: no pude asignar " + campo + ": " + ex.Message);
        }
    }

    void Avisar(string texto)
    {
        registro.AppendLine(texto);
        Debug.LogWarning("CapturaSemana04: " + texto);
    }
}
