/*
================================================================
  EventosVisor.cs
================================================================
  Los avisos que se mandan entre los scripts del visor, y los ajustes
  de vista que comparten. Una sola clase estatica, sin escena.

  ----------------------------------------------------------------
  POR QUE EXISTE
  ----------------------------------------------------------------
  Hasta la Semana 4 cada script buscaba a los otros con
  FindAnyObjectByType y les llamaba metodos. Funciona con tres
  scripts; con diez, cada cambio obliga a editar el archivo del
  vecino, y en la Semana 5 los archivos los editan personas distintas
  a la vez. Con eventos, el que AVISA no sabe quien escucha: el
  ambiente, el mapa D/C o la carga movil se enganchan sin tocar el
  visor.

  El contrato completo (quien avisa, quien escucha, en que orden) esta
  en semana05/CONTRATO.md.

  ----------------------------------------------------------------
  REGLAS
  ----------------------------------------------------------------
  1. Quien se suscribe en OnEnable/Start se desuscribe en
     OnDisable/OnDestroy. Un MonoBehaviour destruido que sigue
     suscrito tira MissingReferenceException en el proximo aviso.
  2. Un suscriptor que falla NO corta a los demas: cada uno se llama
     dentro de su propio try/catch y el error va a la consola con el
     nombre del evento. Si no, un bug en el mapa D/C apagaria el suelo.
  3. Nada de calculo estructural en un suscriptor (regla de oro del
     CLAUDE.md): estos avisos mueven dibujo, no numeros.
================================================================
*/

using System;
using UnityEngine;

public static class EventosVisor
{
    // Valores de 'tipo' en SeleccionCambio. Constantes y no texto
    // suelto: un "Elemento" con mayuscula no calzaria con nadie.
    public const string TIPO_ELEMENTO = "elemento";
    public const string TIPO_NODO = "nodo";
    public const string TIPO_NINGUNO = "";

    // ------------------------------------------------------------
    // LOS EVENTOS
    // ------------------------------------------------------------

    /// VisorEstructura termino de leer el JSON del modelo y lo dibujo
    /// por primera vez. Se avisa una vez por carga.
    public static event Action ModeloCargado;

    /// VisorEstructura destruyo y volvio a crear los GameObject de la
    /// estructura (Redibujar). Los renderers de antes ya no existen.
    /// Despues de avisarlo, AvisarRedibujado avisa MaterialesCambiados.
    public static event Action Redibujado;

    /// Alguien cambio el modelo en memoria (mover, borrar o crear un
    /// nodo o una barra, cambiar una seccion o una restriccion). Los
    /// resultados precalculados (anexos de Semana 3 y 4, carga movil)
    /// ya no corresponden a esta geometria. 'motivo' es texto para el
    /// panel, p. ej. "borrar elemento 69".
    public static event Action<string> ModeloEditado;

    /// Pedido a la camara: centrar en 'centro' (coordenadas UNITY, ya
    /// pasadas por Ejes.AUnity) encuadrando algo de 'tamano' metros.
    /// tamano <= 0 = centrar sin cambiar el zoom.
    public static event Action<Vector3, float> PedirCentrar;

    /// Cambio la seleccion del panel. tipo = TIPO_ELEMENTO o TIPO_NODO
    /// con el id de OpenSees; TIPO_NINGUNO con id -1 al limpiar.
    public static event Action<string, int> SeleccionCambio;

    /// Cambio algun campo de AjustesVista (realista, suelo,
    /// cotaVisible). Quien lo cambia, lo avisa.
    public static event Action VistaCambio;

    /// Alguien cambio el sharedMaterial de los renderers de la
    /// estructura (AmbienteVisor, al aplicar la vista realista o la
    /// tecnica). Quien pinta ENCIMA (el mapa D/C) vuelve a pintar.
    public static event Action MaterialesCambiados;

    // ------------------------------------------------------------
    // AVISAR
    // ------------------------------------------------------------
    public static void AvisarModeloCargado() { Invocar(ModeloCargado, "ModeloCargado"); }

    /// Primero Redibujado y DESPUES MaterialesCambiados, siempre en ese
    /// orden. Asi el que registra el material tecnico de cada renderer
    /// nuevo (AmbienteVisor, en Redibujado) lo lee antes de que el mapa
    /// D/C pinte encima (en MaterialesCambiados), aunque AmbienteVisor
    /// no este en la escena.
    public static void AvisarRedibujado()
    {
        Invocar(Redibujado, "Redibujado");
        AvisarMaterialesCambiados();
    }

    public static void AvisarModeloEditado(string motivo)
    {
        Action<string> copia = ModeloEditado;
        if (copia == null) return;
        foreach (Delegate d in copia.GetInvocationList())
        {
            try { ((Action<string>)d)(motivo ?? ""); }
            catch (Exception ex) { Reportar("ModeloEditado", d, ex); }
        }
    }

    public static void AvisarPedirCentrar(Vector3 centro, float tamano)
    {
        Action<Vector3, float> copia = PedirCentrar;
        if (copia == null) return;
        foreach (Delegate d in copia.GetInvocationList())
        {
            try { ((Action<Vector3, float>)d)(centro, tamano); }
            catch (Exception ex) { Reportar("PedirCentrar", d, ex); }
        }
    }

    public static void AvisarSeleccionCambio(string tipo, int id)
    {
        Action<string, int> copia = SeleccionCambio;
        if (copia == null) return;
        foreach (Delegate d in copia.GetInvocationList())
        {
            try { ((Action<string, int>)d)(tipo ?? TIPO_NINGUNO, id); }
            catch (Exception ex) { Reportar("SeleccionCambio", d, ex); }
        }
    }

    public static void AvisarVistaCambio() { Invocar(VistaCambio, "VistaCambio"); }

    public static void AvisarMaterialesCambiados() { Invocar(MaterialesCambiados, "MaterialesCambiados"); }

    // ------------------------------------------------------------
    static void Invocar(Action evento, string nombre)
    {
        if (evento == null) return;
        foreach (Delegate d in evento.GetInvocationList())
        {
            try { ((Action)d)(); }
            catch (Exception ex) { Reportar(nombre, d, ex); }
        }
    }

    static void Reportar(string evento, Delegate d, Exception ex)
    {
        string quien = d.Target != null ? d.Target.GetType().Name : "(estatico)";
        Debug.LogError($"EventosVisor.{evento}: fallo el suscriptor {quien}.{d.Method.Name}: "
                       + ex.Message + "\n" + ex.StackTrace);
    }

    /// Con 'Enter Play Mode Options' sin recarga de dominio, los campos
    /// estaticos sobreviven entre dos Play: quedarian suscritos objetos
    /// de la sesion anterior, ya destruidos. Se limpia al arrancar.
    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.SubsystemRegistration)]
    static void Reiniciar()
    {
        ModeloCargado = null;
        Redibujado = null;
        ModeloEditado = null;
        PedirCentrar = null;
        SeleccionCambio = null;
        VistaCambio = null;
        MaterialesCambiados = null;
        AjustesVista.Reiniciar();
    }
}


/// <summary>
/// Como se esta mirando el modelo. Lo cambia el panel (VisorQA) y lo
/// leen VisorEstructura, AmbienteVisor y quien dibuje por piso. Quien
/// cambia un campo llama a EventosVisor.AvisarVistaCambio().
/// </summary>
public static class AjustesVista
{
    /// true: texturas de hormigon y suelo con tierra (AmbienteVisor).
    /// false: la vista tecnica de siempre, colores por tipo. Por defecto
    /// realista: lo pidio Pedro para la Semana 5. El mapa D/C y los
    /// diagramas se leen en las dos.
    public static bool realista = true;

    /// Dibujar el suelo en la cota del terreno (info.cota_terreno).
    public static bool suelo = true;

    /// Dibujar el relieve del sitio (StreamingAssets/topografia.json, de
    /// edificios/conjunto/topografia.py). Con el a la vista se apaga el
    /// plano del suelo, no sus terrazas.
    public static bool relieve = true;

    /// Lo que AmbienteVisor sabe del relieve, para el panel: de donde
    /// salio, o por que no hay. Lo escribe AmbienteVisor; solo se lee.
    public static string relieveEstado = "";

    /// Dibujar las losas por piso en la vista realista (AmbienteVisor). Es
    /// DIBUJO de los poligonos de areas_tributarias del JSON, no un dato
    /// nuevo: sin collider, y se esconden solas con la deformada, la carga
    /// movil, los diagramas o el mapa D/C, que no siguen.
    public static bool losas = true;

    /// Filtro de piso: NaN = todos los pisos. Si no, la cota z (OpenSees,
    /// metros) del unico piso que se dibuja. Se compara con
    /// EnCotaVisible, que tiene la tolerancia.
    public static float cotaVisible = float.NaN;

    /// Tolerancia de cota: la misma 0.01 m con que VisorQA arma la lista
    /// de cotas del modelo (VisorQA.CotasDelModelo). En lt2, ingenieria y
    /// conjunto las z de los nodos traen 2 decimales y los pisos estan a
    /// 3.96 m uno de otro (medido en data/unity/*.json): 0.01 separa
    /// pisos sin confundirlos y absorbe el redondeo del float32.
    public const float TOLERANCIA_COTA = 0.01f;

    public static bool HayFiltroDePiso { get { return !float.IsNaN(cotaVisible); } }

    /// true si un punto a cota z (OpenSees) pasa el filtro de piso.
    public static bool EnCotaVisible(float z)
    {
        return float.IsNaN(cotaVisible) || Mathf.Abs(z - cotaVisible) < TOLERANCIA_COTA;
    }

    /// true si una barra con nodos a cotas zA y zB pertenece al piso
    /// visible. Regla: "el piso de la cota z" es la losa a esa cota (vigas
    /// con los dos nodos ahi) mas lo que NACE de ella (columnas y muros
    /// cuyo nodo INFERIOR esta ahi): la cota MENOR de la barra.
    ///
    /// Por que la menor y no la mayor: (1) es la regla que ya usaban los
    /// diagramas de la Semana 4 (VisorSemana04.Diagramas.cs, filtro con
    /// Mathf.Min(a.z, b.z)), y las capturas de piso de CapturaSemana04
    /// salieron con ella; (2) ninguna cota queda sin barras: con la mayor,
    /// la mas baja no tiene ninguna (-7.97 del LT2 y del conjunto, 0.00 de
    /// Ingenieria: 0 barras; con la menor 16, 45 y 29, contado en
    /// data/unity/*.json) y se veria el "filtrar no muestra NADA" que ya
    /// costo tiempo en VisorQA.
    ///
    /// Una sola definicion para el visor, los diagramas, el mapa D/C y
    /// las capas QA: si cada uno filtrara a su manera, un diagrama
    /// quedaria flotando sobre una barra oculta.
    public static bool ElementoEnCotaVisible(float zA, float zB)
    {
        return EnCotaVisible(Mathf.Min(zA, zB));
    }

    internal static void Reiniciar()
    {
        realista = true;
        suelo = true;
        losas = true;
        cotaVisible = float.NaN;
    }
}
