/*
================================================================
  IPanelIncrustable.cs
================================================================
  Un panel que se puede dibujar solo (su propia ventana IMGUI) o como
  una pestana del panel de VisorQA.

  ----------------------------------------------------------------
  POR QUE
  ----------------------------------------------------------------
  El editor tenia su panel a la derecha y VisorQA el suyo a la
  izquierda: dos paneles que tapan el modelo y repiten toggles. Con
  esta interfaz VisorQA busca, con FindObjectsByType, todo
  MonoBehaviour que la implemente, le pone PanelPropio = false y lo
  muestra como pestana. Sin VisorQA en la escena el componente sigue
  dibujando su propio panel, como antes.

  ----------------------------------------------------------------
  CONTRATO (semana05/CONTRATO.md, seccion g)
  ----------------------------------------------------------------
  - TituloPestana: texto corto y FIJO (el de la pestana). Sin tildes,
    como el resto del panel: "Modificar", "Carga movil".
  - PanelPropio: true por defecto. Si es false, el OnGUI propio del
    componente NO dibuja nada (return al principio) y su
    MouseSobrePanel, si tiene, devuelve false.
  - DibujarPanel(): SOLO GUILayout, sin BeginArea, sin ScrollView
    propio y sin GUI.Window: lo llama VisorQA dentro de su area y de
    su scroll. Cambios que redibujan la escena, diferidos a
    Update/LateUpdate (IMGUI reclama si cambia la cantidad de
    controles entre Layout y Repaint).
================================================================
*/

public interface IPanelIncrustable
{
    string TituloPestana { get; }

    bool PanelPropio { get; set; }

    void DibujarPanel();
}
