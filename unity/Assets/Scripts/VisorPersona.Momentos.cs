/*
================================================================
  VisorPersona.Momentos.cs  --  los momentos que produce la persona
================================================================
  Dibuja el diagrama de momento de la viga cargada (con el quiebre
  bajo la carga) y de las barras que llegan a sus nodos (columnas y
  vigas vecinas), del lado traccionado como la Semana 4:

      My > 0 tracciona la fibra +z local  -> la curva va en +My * z_local
      Mz < 0 tracciona la fibra +y local  -> la curva va en -Mz * y_local

  ----------------------------------------------------------------
  DE DONDE SALEN (y por que no es calculo en C#)
  ----------------------------------------------------------------
  Cada caso unitario de influencias.json trae tambien el localForce de
  las barras que muestra su receptor, resuelto por OpenSees. Sumados
  con los MISMOS pesos que la deformada (VisorPersona.Deformada.cs,
  Sumar) dan k u de cada barra; la viga cargada suma su empotramiento
  perfecto (SumarEmpotramiento). Entre extremos M es lineal, y en la
  cargada tiene el quiebre de P (MyEn). Las tres formulas estan en
  VisorPersona.Deformada.cs y las lee influencias_persona.py [9]; el
  bloque [8] compara la suma con OpenSees resolviendo la carga directo.
  Esto no es licencia para mas: no hay D/C ni capacidad aca.
================================================================
*/

using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

public partial class VisorPersona
{
    static readonly Color COLOR_MOMENTO = new Color(1.00f, 0.78f, 0.25f);
    static readonly Color COLOR_MOMENTO_BORDE = new Color(0.80f, 0.40f, 0.05f);
    // El naranjo del borde: se lee sobre el hormigon claro y sobre el pasto.
    static readonly Color COLOR_ETIQUETA = new Color(0.95f, 0.45f, 0.05f);
    const int TRAMOS_MOMENTO = 10;

    bool verMomentos = true;
    float escalaMomento = -1f;                // m por kN m; la primera vez, la de Python
    readonly Dictionary<long, Dictionary<int, float[]>> fuerzasDecodificadas =
        new Dictionary<long, Dictionary<int, float[]>>();
    Dictionary<int, float[]> fuerzasPersona;  // barra -> localForce[12] combinado
    bool fuerzasIncompletas;
    float mCarga, mExtremoI, mExtremoJ, mMayor;
    int barraMayor = -1;

    // ============================================================
    // SUMAR (lo llaman Combinar y Sumar de VisorPersona.Deformada.cs)
    // ============================================================
    void PrepararFuerzas(ReceptorPersona r)
    {
        fuerzasIncompletas = false;
        if (r.elementos_m == null) { fuerzasPersona = null; return; }
        fuerzasPersona = new Dictionary<int, float[]>();
        foreach (int e in r.elementos_m) fuerzasPersona[e] = new float[12];
    }

    /// Los localForce de un caso, en kN y kN m (int16 por su escala).
    Dictionary<int, float[]> FuerzasDeCaso(int nodo, int gdl)
    {
        long k = Clave(nodo, gdl);
        Dictionary<int, float[]> d;
        if (fuerzasDecodificadas.TryGetValue(k, out d)) return d;
        int ic;
        if (!indiceCaso.TryGetValue(k, out ic)) return null;
        CasoInfluencia c = influencias.casos[ic];
        d = new Dictionary<int, float[]>();
        if (c.elementos != null && !string.IsNullOrEmpty(c.fuerzas))
        {
            byte[] b = Convert.FromBase64String(c.fuerzas);
            for (int e = 0; e < c.elementos.Length; e++)
            {
                var f = new float[12];
                for (int i = 0; i < 12; i++)
                {
                    int q = 12 * e + i;
                    short v = (short)(b[2 * q] | (b[2 * q + 1] << 8));
                    f[i] = v * ((i % 6) >= 3 ? c.escala_m : c.escala_f);
                }
                d[c.elementos[e]] = f;
            }
        }
        fuerzasDecodificadas[k] = d;
        return d;
    }

    void SumarFuerzas(int nodo, int gdl, float w)
    {
        if (fuerzasPersona == null) return;
        Dictionary<int, float[]> caso = FuerzasDeCaso(nodo, gdl);
        if (caso == null) { fuerzasIncompletas = true; return; }
        foreach (KeyValuePair<int, float[]> kv in fuerzasPersona)
        {
            float[] origen;
            if (!caso.TryGetValue(kv.Key, out origen)) { fuerzasIncompletas = true; continue; }
            float[] destino = kv.Value;
            for (int i = 0; i < 12; i++) destino[i] += w * origen[i];
        }
    }

    /// Los numeros del panel, despues de sumar.
    void CerrarMomentos(ReceptorPersona r, float a, float P)
    {
        mCarga = mExtremoI = mExtremoJ = mMayor = 0f;
        barraMayor = -1;
        if (fuerzasPersona == null) return;
        float[] f;
        if (r.tipo == "viga" && fuerzasPersona.TryGetValue(r.elemento, out f))
        {
            mCarga = MyEn(f, a * r.L, a * r.L, P);
            mExtremoI = MyEn(f, 0f, a * r.L, P);
            mExtremoJ = MyEn(f, r.L, a * r.L, P);
        }
        // La otra barra con mas momento (una columna, casi siempre).
        foreach (KeyValuePair<int, float[]> kv in fuerzasPersona)
        {
            if (kv.Key == r.elemento) continue;
            Elemento e = visor.Modelo.ElementoPorId(kv.Key);
            if (e == null || e.EsMuro || e.EsBrazo) continue;
            float m = Mathf.Max(Mathf.Max(Mathf.Abs(kv.Value[4]), Mathf.Abs(kv.Value[10])),
                                Mathf.Max(Mathf.Abs(kv.Value[5]), Mathf.Abs(kv.Value[11])));
            if (m > mMayor) { mMayor = m; barraMayor = kv.Key; }
        }
    }

    // ============================================================
    // DIBUJO
    // ============================================================
    /// Lo llama Dibujar (VisorPersona.cs) despues de la persona.
    void DibujarMomentos()
    {
        if (!verMomentos || recActual == null || fuerzasPersona == null || influencias == null) return;
        if (escalaMomento <= 0f) escalaMomento = influencias.info.escala_momento;
        var vs = new List<Vector3>();
        var ts = new List<int>();
        Vector3 etiquetaEn = Vector3.zero;
        bool hayEtiqueta = false;
        foreach (KeyValuePair<int, float[]> kv in fuerzasPersona)
        {
            Elemento e = visor.Modelo.ElementoPorId(kv.Key);
            if (e == null || e.EsMuro || e.EsBrazo) continue;
            Nodo na = visor.Modelo.NodoPorId(e.n1), nb = visor.Modelo.NodoPorId(e.n2);
            if (na == null || nb == null) continue;
            float L = Vector3.Distance(new Vector3(na.x, na.y, na.z), new Vector3(nb.x, nb.y, nb.z));
            if (L < 1e-6f) continue;
            bool cargada = recActual.tipo == "viga" && e.id == recActual.elemento;
            float aL = cargada ? alfaActual * L : 0f, P = cargada ? pesoAplicado : 0f;
            float[] f = kv.Value;

            var xs = new List<float>();
            for (int k = 0; k <= TRAMOS_MOMENTO; k++) xs.Add(L * k / TRAMOS_MOMENTO);
            if (cargada) { xs.Add(aL); xs.Sort(); }
            // My o Mz: el que mas momento tenga; la viga cargada, siempre My.
            float mayY = 0f, mayZ = 0f;
            foreach (float x in xs) { mayY = Mathf.Max(mayY, Mathf.Abs(MyEn(f, x, aL, P))); mayZ = Mathf.Max(mayZ, Mathf.Abs(MzEn(f, x))); }
            bool usaY = cargada || mayY >= mayZ;
            Vector3 eje = usaY ? VersorOS(e.localZ) : -VersorOS(e.localY);
            if (eje == Vector3.zero) continue;
            Vector3 hacia = Ejes.AUnity(eje.x, eje.y, eje.z);

            int inicio = vs.Count;
            for (int k = 0; k < xs.Count; k++)
            {
                float m = usaY ? MyEn(f, xs[k], aL, P) : MzEn(f, xs[k]);
                Vector3 b = BaseDeLaBarra(na, nb, xs[k] / L, cargada);
                vs.Add(b);
                vs.Add(b + hacia * (m * escalaMomento));
                if (cargada && Mathf.Abs(xs[k] - aL) < 1e-6f) { etiquetaEn = b + hacia * (m * escalaMomento); hayEtiqueta = true; }
            }
            for (int k = 0; k + 1 < xs.Count; k++)
            {
                int b0 = inicio + 2 * k, t0 = b0 + 1, b1 = b0 + 2, t1 = b0 + 3;
                // las dos caras: el diagrama es plano y se mira de los dos lados
                ts.AddRange(new[] { b0, t0, t1, b0, t1, b1, b0, t1, t0, b0, b1, t1 });
            }
            // el borde, para leerlo contra la losa
            var lr = new GameObject("SQ4_Momento_" + e.id).AddComponent<LineRenderer>();
            lr.positionCount = xs.Count;
            for (int k = 0; k < xs.Count; k++) lr.SetPosition(k, vs[inicio + 2 * k + 1]);
            lr.startWidth = lr.endWidth = cargada ? 0.06f : 0.04f;
            lr.sharedMaterial = MaterialDe(COLOR_MOMENTO_BORDE);
            lr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
            creados.Add(lr.gameObject);
        }
        if (vs.Count == 0) return;
        var malla = new Mesh { name = "SQ4_Momentos" };
        if (vs.Count > 65000) malla.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
        malla.SetVertices(vs);
        malla.SetTriangles(ts, 0);
        malla.RecalculateBounds();
        var go = new GameObject("SQ4_Momentos");
        go.AddComponent<MeshFilter>().sharedMesh = malla;
        var mr = go.AddComponent<MeshRenderer>();
        mr.sharedMaterial = MaterialDe(COLOR_MOMENTO);
        mr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        creados.Add(go);

        if (hayEtiqueta)
        {
            var et = new GameObject("SQ4_M_carga");
            et.transform.position = etiquetaEn + Vector3.down * 0.35f;
            TextMesh tm = et.AddComponent<TextMesh>();
            tm.text = "M = " + F(mCarga, "0.0") + " kN m";
            tm.characterSize = 0.09f;
            tm.fontSize = 60;
            tm.color = COLOR_ETIQUETA;
            tm.anchor = TextAnchor.MiddleCenter;
            et.AddComponent<MirarCamara>();
            creados.Add(et);
        }
    }

    /// Un punto del eje de la barra como se dibuja: entre sus nodos (con
    /// la deformada, si es la de la persona) y, en la cargada, con su
    /// flecha dentro del vano.
    Vector3 BaseDeLaBarra(Nodo na, Nodo nb, float xi, bool cargada)
    {
        Vector3 p = Vector3.Lerp(visor.PosicionActual(na), visor.PosicionActual(nb), xi);
        if (cargada && DeformadaVisible())
        {
            DespNodo di = DespDe(na.id), dj = DespDe(nb.id);
            float extra = UzEn(recActual, di, dj, xi, alfaActual, pesoAplicado) - ((1f - xi) * di.uz + xi * dj.uz);
            p += Vector3.up * (extra * visor.factorEscala);
        }
        return p;
    }

    /// Un eje local del JSON (ejes OpenSees) como versor; cero si no viene.
    static Vector3 VersorOS(float[] v)
    {
        if (v == null || v.Length < 3) return Vector3.zero;
        var r = new Vector3(v[0], v[1], v[2]);
        return r.sqrMagnitude > 1e-8f ? r.normalized : Vector3.zero;
    }

    // ============================================================
    // PANEL
    // ============================================================
    void PanelMomentos(GUIStyle texto, GUIStyle tenue, GUIStyle aviso, GUIStyle boton)
    {
        if (influencias == null) return;
        GUILayout.Space(PanelUI.Px(4f));
        bool quiere = GUILayout.Toggle(verMomentos, "  Ver los momentos que produce");
        if (quiere != verMomentos)
            diferida = () => { verMomentos = quiere; PedirDeformadaPersona(); redibujar = true; };
        if (!verMomentos) return;
        float rec = influencias.info.escala_momento;
        float esc = escalaMomento > 0f ? escalaMomento : rec;
        GUILayout.Label($"Escala de momentos: {F(esc * 100f, "0.###")} cm por kN m (recomendada "
                        + $"{F(rec * 100f, "0.###")}: con {F(influencias.info.P_por_defecto_kN, "0")} kN el mayor "
                        + $"se dibuja {F(influencias.info.largo_momento_m, "0.0")} m)", tenue);
        float e = GUILayout.HorizontalSlider(esc, 0.1f * rec, 4f * rec);
        if (GUILayout.Button("Momentos: volver a la recomendada", boton)) e = rec;
        if (Mathf.Abs(e - esc) > 1e-4f * rec)
        {
            escalaMomento = e;
            redibujar = true;
        }
        if (!puesta || recActual == null) return;
        if (recActual.tipo == "viga")
            GUILayout.Label($"MOMENTO bajo la carga: {F(mCarga, "0.00")} kN m (negativo: tracciona abajo). En los extremos de la viga "
                            + $"{recActual.elemento}: {F(mExtremoI, "0.00")} (nodo {recActual.n1}) y "
                            + $"{F(mExtremoJ, "0.00")} kN m (nodo {recActual.n2}).", texto);
        else
            GUILayout.Label("MOMENTOS: la carga entra al nodo del muro, y un muro no lleva diagrama: se "
                            + "dibujan las barras que llegan a ese nodo.", texto);
        if (barraMayor >= 0)
            GUILayout.Label($"La otra barra con mas momento: {Nombre(barraMayor)}, {F(mMayor, "0.00")} kN m "
                            + "en un extremo.", texto);
        GUILayout.Label("Del lado traccionado, como la Semana 4. Unity suma los esfuerzos de extremo de los "
                        + "mismos casos unitarios (OpenSees) y, en la viga cargada, el empotramiento de la "
                        + "carga; entre extremos M es lineal, con el quiebre de P bajo la carga.", tenue);
        if (fuerzasIncompletas)
            GUILayout.Label("Faltan esfuerzos de alguna barra en influencias.json: vuelve a correr "
                            + "influencias_persona.py.", aviso);
    }
}
