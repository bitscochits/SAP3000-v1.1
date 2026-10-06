/*
================================================================
  VisorPersona.Personaje.cs  --  quien camina: un AT-ST
================================================================
  Dibuja al caminante de la pestana Persona como un AT-ST que da pasos
  y mira hacia donde va. Es solo dibujo: el peso y donde cae los
  decide el resto de VisorPersona.

  - La malla la prepara python semana05_lab/personaje_atst.py en
    Resources/Personaje/atst.json: cuerpo y dos piernas, en ejes de
    Unity, con el pivote de cada pierna en su cadera. Aca solo se
    arman los Mesh (una vez) y se giran las piernas.
  - El paso sigue a lo CAMINADO, no al tiempo: quieto no se mueve, y
    un ciclo de piernas son LARGO_PASO_M.
  - Modelo: "AT-ST" de Tom Meyer, CC BY 3.0, via Poly Pizza. La
    licencia pide nombrarlo: el panel muestra info.atribucion.
  - Si el recurso no esta, se dibuja la capsula de siempre.
================================================================
*/

using System;
using UnityEngine;

// Clases de atst.json; personaje_atst.py las compara con el JSON.
[Serializable]
public class PersonajeJson
{
    public InfoPersonaje info;
    public PiezaPersonaje[] piezas;
}

[Serializable]
public class InfoPersonaje
{
    public string nombre, atribucion, generado_por, _por_que;
    public float alto_m;
    public float[] color;
}

[Serializable]
public class PiezaPersonaje
{
    public string nombre;
    public float[] pivote;
    public float[] vertices;
    public int n_piezas_obj;
}

public partial class VisorPersona
{
    const string RECURSO_PERSONAJE = "Personaje/atst";
    const float AMPLITUD_PASO_GRADOS = 20f;
    const float LARGO_PASO_M = 1.8f;

    bool dibujarAtst = true;
    PersonajeJson personaje;
    bool personajeLeido;
    Mesh[] mallasPersonaje;
    Material materialPersonaje;
    float fasePaso, rumboGrados;

    bool CargarPersonaje()
    {
        if (personajeLeido) return personaje != null;
        personajeLeido = true;
        TextAsset t = Resources.Load<TextAsset>(RECURSO_PERSONAJE);
        if (t == null) return false;
        PersonajeJson p;
        try { p = JsonUtility.FromJson<PersonajeJson>(t.text); }
        catch (Exception ex) { Debug.LogWarning("VisorPersona: atst.json no se pudo leer: " + ex.Message); return false; }
        if (p == null || p.piezas == null || p.piezas.Length == 0) return false;
        mallasPersonaje = new Mesh[p.piezas.Length];
        for (int k = 0; k < p.piezas.Length; k++)
        {
            float[] v = p.piezas[k].vertices;
            int n = v.Length / 3;
            var vs = new Vector3[n];
            var ts = new int[n];
            for (int i = 0; i < n; i++)
            {
                vs[i] = new Vector3(v[3 * i], v[3 * i + 1], v[3 * i + 2]);
                ts[i] = i;
            }
            var m = new Mesh { name = "ATST_" + p.piezas[k].nombre };
            if (n > 65000) m.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
            m.vertices = vs;
            m.triangles = ts;
            m.RecalculateNormals();
            m.RecalculateBounds();
            mallasPersonaje[k] = m;
        }
        Color c = p.info != null && p.info.color != null && p.info.color.Length >= 3
            ? new Color(p.info.color[0], p.info.color[1], p.info.color[2]) : Color.gray;
        materialPersonaje = new Material(VisorEstructura.ShaderCompatible()) { color = c };
        if (materialPersonaje.HasProperty("_BaseColor")) materialPersonaje.SetColor("_BaseColor", c);
        personaje = p;
        return true;
    }

    /// Lo llama Update al caminar: d es lo avanzado en planta (m, ejes OpenSees).
    void AlCaminar(Vector2 d)
    {
        if (d.sqrMagnitude < 1e-12f) return;
        fasePaso = Mathf.Repeat(fasePaso + d.magnitude / LARGO_PASO_M * 2f * Mathf.PI, 2f * Mathf.PI);
        // Unity (x, z) = OpenSees (x, y): rumbo 0 mira a +y de OpenSees.
        // En la cabina el rumbo lo giran A/D: retroceder no lo da vuelta.
        if (!enCabina) rumboGrados = Mathf.Atan2(d.x, d.y) * Mathf.Rad2Deg;
    }

    /// El AT-ST parado en (x, y, zPiso). false si no hay recurso o se apago.
    bool DibujarPersonaje(float zPiso)
    {
        if (!dibujarAtst || !CargarPersonaje()) return false;
        var raiz = new GameObject("SQ4_ATST");
        raiz.transform.position = Ejes.AUnity(x, y, zPiso);
        raiz.transform.rotation = Quaternion.Euler(0f, rumboGrados, 0f);
        float ang = AMPLITUD_PASO_GRADOS * Mathf.Sin(fasePaso);
        for (int k = 0; k < personaje.piezas.Length; k++)
        {
            PiezaPersonaje pz = personaje.piezas[k];
            // Desde la cabina no se dibuja la cabina: taparia la vista.
            if (enCabina && pz.nombre == "cuerpo") continue;
            var go = new GameObject(pz.nombre);
            go.transform.SetParent(raiz.transform, false);
            if (pz.pivote != null && pz.pivote.Length == 3)
                go.transform.localPosition = new Vector3(pz.pivote[0], pz.pivote[1], pz.pivote[2]);
            // Las piernas van en contrafase; la cabina sube un poco a mitad de paso.
            if (pz.nombre == "pierna_izq") go.transform.localRotation = Quaternion.Euler(ang, 0f, 0f);
            else if (pz.nombre == "pierna_der") go.transform.localRotation = Quaternion.Euler(-ang, 0f, 0f);
            else go.transform.localPosition += Vector3.up * 0.04f * Mathf.Abs(Mathf.Cos(fasePaso));
            go.AddComponent<MeshFilter>().sharedMesh = mallasPersonaje[k];
            go.AddComponent<MeshRenderer>().sharedMaterial = materialPersonaje;
        }
        creados.Add(raiz);
        return true;
    }

    void PanelPersonaje(GUIStyle tenue)
    {
        bool quiere = GUILayout.Toggle(dibujarAtst, "  Dibujarla como AT-ST");
        if (quiere != dibujarAtst) diferida = () => { dibujarAtst = quiere; if (puesta) Calcular(); };
        if (dibujarAtst && personaje != null && personaje.info != null)
            GUILayout.Label("Modelo: " + personaje.info.atribucion, tenue);
    }
}
