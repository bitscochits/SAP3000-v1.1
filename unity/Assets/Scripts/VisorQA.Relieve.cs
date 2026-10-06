/*
================================================================
  VisorQA.Relieve.cs
================================================================
  La casilla "Relieve del sitio" de Capas > Vista, debajo de la del
  suelo. Va en su propio archivo (VisorQA es partial) para no correr las
  lineas de VisorQA.cs que citan los informes: VisorQA.cs solo la llama
  al final de una linea que ya existia.

  Siempre dibuja los mismos dos controles (la casilla y su nota), tenga
  o no relieve el modelo: cambiar la cantidad de controles a mitad de un
  evento de IMGUI hace saltar "Getting control N's position".
  El cambio se difiere a Update, como el resto del panel.
================================================================
*/

using UnityEngine;

public partial class VisorQA
{
    void CasillaRelieve()
    {
        bool relieve = GUILayout.Toggle(AjustesVista.relieve,
            "Relieve del sitio (Google Earth + Copernicus 30 m)", estToggle);
        if (relieve != AjustesVista.relieve)
            Diferir(() => { AjustesVista.relieve = relieve; EventosVisor.AvisarVistaCambio(); });
        GUILayout.Label(string.IsNullOrEmpty(AjustesVista.relieveEstado)
            ? "Relieve del sitio: todavia no se carga el modelo."
            : AjustesVista.relieveEstado, PanelUI.Tenue);
    }
}
