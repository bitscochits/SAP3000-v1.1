/*
================================================================
  VisorSemana04.Hooks.cs   (parte de VisorSemana04)
================================================================
  Los puntos de enganche entre las partes de VisorSemana04 que en la
  Semana 5 escriben paquetes distintos:

    VisorSemana04.cs               U3  carga, casos, RegistrarCasoExterno
    VisorSemana04.Diagramas.cs     U3  diagramas de esfuerzos
    VisorSemana04.Superposicion.cs U3  sliders de lambda -> /combinar
    VisorSemana04.Panel.cs         U2b controles del panel
    VisorSemana04.PM.cs            U2b curva P-M
    VisorSemana04.Mapa.cs          U2b mapa demanda/capacidad
    VisorSemana04.Hooks.cs         W1  este archivo

  ----------------------------------------------------------------
  POR QUE UN ARCHIVO DE HOOKS
  ----------------------------------------------------------------
  Un 'partial void' declarado aca y sin implementar compila igual: el
  compilador borra la llamada. Asi Panel.cs puede llamar a
  Hook_DibujarSuperposicion() aunque Superposicion.cs todavia no
  exista, y cada paquete compila solo. Cuando U3 implementa el hook,
  la llamada aparece sin tocar el archivo de U2b.

  Y los miembros que dos paquetes comparten (versionCasos,
  RegistrarCasoExterno) viven en UN archivo que no es de ninguno de los
  dos: si cada uno los declarara en el suyo, al juntar las ramas habria
  dos definiciones y no compilaria.

  REGLA DE NOMBRES en los partial: los miembros privados llevan el
  prefijo de su archivo (Sup_, Mapa_, Pnl_, PM_), para que dos
  archivos no declaren sin querer el mismo nombre.
================================================================
*/

public partial class VisorSemana04
{
    /// Sube cada vez que cambian los CASOS que se pueden dibujar (se
    /// registra o reemplaza uno externo, como LIBRE). Quien cachea algo
    /// que depende de un caso -- la textura de la P-M, la firma de los
    /// diagramas, el mapa D/C -- la incluye en su firma: con el mismo
    /// nombre de caso, los numeros pueden ser otros.
    /// Solo lo modifica RegistrarCasoExterno (su implementacion, U3).
    [System.NonSerialized]
    public int versionCasos = 0;

    /// Los controles de superposicion (sliders de lambda, E1..E3, boton
    /// "Combinar en Python"). Lo implementa U3 en
    /// VisorSemana04.Superposicion.cs; lo llama U2b desde
    /// DibujarControles, UNA vez, dentro de la seccion de casos.
    partial void Hook_DibujarSuperposicion();

    /// La curva P-M de la barra seleccionada dibujada DENTRO del panel
    /// (no en la ventana flotante). La implementa U2b en PM.cs.
    partial void Hook_DibujarPMEnLinea();

    /// Lo llama VisorQA (U2a) en la pestana Elemento, dentro de su area y
    /// su scroll. Solo GUILayout. Mientras U2b no implemente el hook, no
    /// dibuja nada (la ventana flotante sigue funcionando).
    public void DibujarPMEnLinea()
    {
        Hook_DibujarPMEnLinea();
    }

    /// Cuantas demandas trae un caso, cuantas NO PASAN (pasa == false del
    /// JSON) y cuantas de esas son "P fuera de la curva" (u = 9999). Solo
    /// cuenta lo que escribio Python; no revisa nada. La cabecera del
    /// panel (U2a) y la leyenda del mapa D/C (U2b) usan esta, para que
    /// "NO PASA n/m" sea el mismo numero en los dos lugares.
    public static void ContarDemandas(CasoS4 caso, out int noPasan, out int fueraDeCurva, out int total)
    {
        noPasan = 0;
        fueraDeCurva = 0;
        total = 0;
        if (caso == null || caso.demandas == null) return;
        foreach (DemandaS4 d in caso.demandas)
        {
            total++;
            if (!d.pasa) noPasan++;
            if (d.u >= PanelUI.U_FUERA_DE_CURVA) fueraDeCurva++;
        }
    }

    /// La implementacion de RegistrarCasoExterno. La escribe U3 en
    /// VisorSemana04.cs (ahi estan los indices privados casoPorNombre,
    /// esfuerzos y demandas).
    partial void Hook_RegistrarCasoExterno(CasoS4 caso);

    /// Agrega un caso que no vino en semana04.json -- la combinacion LIBRE
    /// que devuelve POST /combinar -- o reemplaza el que tenga el mismo
    /// nombre. Despues de llamarlo, ElegirCaso(caso.nombre) lo muestra en
    /// el panel, los diagramas, la deformada y la P-M.
    ///
    /// El caso tiene que venir COMPLETO de Python, con la forma de
    /// CasoS4 (desplazamientos de todos los nodos, esfuerzos de todas las
    /// barras con sus estaciones, demandas de las que tienen fierro): aca
    /// no se completa ni se combina nada.
    ///
    /// Mientras U3 no implemente el hook, no hace nada.
    public void RegistrarCasoExterno(CasoS4 caso)
    {
        if (caso == null || string.IsNullOrEmpty(caso.nombre)) return;
        Hook_RegistrarCasoExterno(caso);
    }
}
