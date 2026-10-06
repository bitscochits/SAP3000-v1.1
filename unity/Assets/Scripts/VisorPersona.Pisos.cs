/*
================================================================
  VisorPersona.Pisos.cs  --  subir y bajar de piso
================================================================
  Q / E, PgUp / PgDn o los botones del panel llevan al caminante al
  piso de abajo o de arriba, como en un ascensor (sube de a poco, en
  DURACION_PISO_S). Es solo dibujo y seleccion: el piso que sigue es el
  primero, en esa direccion, que tenga losa bajo la persona (una region
  tributaria que la contenga). Si ninguno la tiene, va al piso vecino y
  aparece en la region mas cercana a donde estaba, y el panel lo dice.
================================================================
*/

using System.Collections.Generic;
using UnityEngine;

public partial class VisorPersona
{
    const float DURACION_PISO_S = 0.7f;
    const float AVISO_PISO_S = 4f;

    float zDesde, tPiso = 1f;
    string avisoPiso = "", avisoMostrado = "";
    float tAvisoPiso = -100f;

    /// Cambia de piso; true si cambio. dir = +1 sube, -1 baja.
    bool CambiarPiso(int dir)
    {
        if (!puesta || !Listo()) return false;
        if (pisos.Count == 0) LeerPisos();
        if (pisos.Count == 0) return false;
        float zAntes = AlturaPersona(pisos[Mathf.Clamp(piso, 0, pisos.Count - 1)]);
        int destino = -1;
        for (int k = piso + dir; k >= 0 && k < pisos.Count; k += dir)
            if (HayLosaEn(pisos[k], x, y)) { destino = k; break; }
        if (destino < 0)
        {
            int k = piso + dir;
            if (k < 0 || k >= pisos.Count)
            {
                Avisar(dir > 0 ? "Ya esta en el piso mas alto." : "Ya esta en el piso mas bajo.");
                return false;
            }
            Vector2 c;
            if (!LosaMasCercana(pisos[k], x, y, out c)) return false;
            x = c.x; y = c.y;
            destino = k;
            Avisar("Justo " + (dir > 0 ? "arriba" : "abajo") + " no habia losa: aparece en la mas cercana.");
        }
        else Avisar("");
        zDesde = zAntes;
        piso = destino;
        tPiso = 0f;
        return true;
    }

    void Avisar(string texto) { avisoPiso = texto; tAvisoPiso = Time.unscaledTime; }

    /// Lo llama Update: avanza el ascensor y deja listo el aviso del panel
    /// (aca y no en OnGUI, para que el panel no cambie a mitad de evento).
    void AnimarPiso()
    {
        if (tPiso < 1f)
        {
            tPiso = Mathf.Min(1f, tPiso + Time.unscaledDeltaTime / DURACION_PISO_S);
            redibujar = true;
        }
        avisoMostrado = Time.unscaledTime - tAvisoPiso < AVISO_PISO_S ? avisoPiso : "";
    }

    /// Donde se dibuja la persona mientras sube o baja.
    float AlturaPersona(float z)
    {
        return tPiso >= 1f ? z : Mathf.Lerp(zDesde, z, Mathf.SmoothStep(0f, 1f, tPiso));
    }

    bool HayLosaEn(float z, float px, float py)
    {
        foreach (AreaTributaria a in visor.Modelo.areas_tributarias)
        {
            if (a == null || a.vertices == null || Mathf.Abs(a.z - z) > 0.02f) continue;
            foreach (List<VerticePlanta> pol in Poligonos(a))
                if (Adentro(pol, px, py)) return true;
        }
        return false;
    }

    /// El centro de la region de ese piso mas cercana al punto.
    bool LosaMasCercana(float z, float px, float py, out Vector2 c)
    {
        c = Vector2.zero;
        float mejor = float.MaxValue;
        foreach (AreaTributaria a in visor.Modelo.areas_tributarias)
        {
            if (a == null || a.vertices == null || Mathf.Abs(a.z - z) > 0.02f) continue;
            foreach (List<VerticePlanta> pol in Poligonos(a))
            {
                Vector2 k = Centro(pol);
                float d = (k - new Vector2(px, py)).sqrMagnitude;
                if (d < mejor && Adentro(pol, k.x, k.y)) { mejor = d; c = k; }
            }
        }
        return mejor < float.MaxValue;
    }

    void PanelPisos(GUIStyle boton)
    {
        GUILayout.BeginHorizontal();
        if (GUILayout.Button("Bajar piso (Q)", boton))
            diferida = () => { if (CambiarPiso(-1)) { Calcular(); PedirDeformadaPersona(); } };
        if (GUILayout.Button("Subir piso (E)", boton))
            diferida = () => { if (CambiarPiso(+1)) { Calcular(); PedirDeformadaPersona(); } };
        GUILayout.EndHorizontal();
        GUILayout.Label(avisoMostrado, PanelUI.Aviso ?? GUI.skin.label);
    }

    // Para CapturaPersona.
    public bool Captura_CambiarPiso(int dir)
    {
        if (!CambiarPiso(dir)) return false;
        Calcular();
        PedirDeformadaPersona();
        return true;
    }

    public string Captura_Piso { get { return pisos.Count > 0 ? (piso + 1) + " de " + pisos.Count + " (z = " + pisos[piso].ToString("0.00", System.Globalization.CultureInfo.InvariantCulture) + ")" : "?"; } }
}
