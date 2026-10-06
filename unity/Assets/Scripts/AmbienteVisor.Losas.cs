/*
================================================================
  AmbienteVisor.Losas.cs
================================================================
  Las LOSAS por piso de la vista realista. Solo DIBUJO: sin ellas el
  edificio se leia como una grilla de vigas sobre el hoyo de la
  excavacion, no como un edificio.

  ----------------------------------------------------------------
  DE DONDE SALEN (nada inventado, nada calculado)
  ----------------------------------------------------------------
  - Los poligonos: areas_tributarias del JSON, los mismos que dibuja la
    capa "Areas tributarias" y que carga el bloque "Que lo carga". Los
    calcula Python (cada pano recortado a 45 grados, trapecios y
    triangulos, o sea convexos). Aca solo se triangulan en abanico. En el
    LT2: 243 entradas en 5 cotas.
  - La cota: el 'z' de cada entrada (el nivel del diafragma del modelo).
  - La cara superior va 1 cm sobre el canto de la viga MAS FRECUENTE de
    esa cota (V 0.60x0.80 en el LT2: z + 0.41). Criterio de dibujo: las
    vigas se dibujan centradas en su eje (VisorEstructura.CrearPerfil) y
    con la losa en z asomaban 40 cm por encima, como vigas invertidas; con
    la cara justo en el canto, las dos caras peleaban en profundidad.
  - El espesor, ESPESOR_LOSA = 0.15 m, es de dibujo: el modelo no tiene
    losa como elemento (la carga llega a las vigas por area tributaria y
    la rigidez en planta la da el diafragma).

  ----------------------------------------------------------------
  REGLAS
  ----------------------------------------------------------------
  - SIN collider: el click sigue llegando a las vigas y columnas.
  - Fuera de ObjetosDeElementos: ni el mapa D/C ni la seleccion las tocan.
  - Solo en la vista realista y con AjustesVista.losas. La transparencia
    de URP no sirve (la build quita sus keywords, ver el encabezado de
    AmbienteVisor), asi que en vez de translucidas se ESCONDEN cuando
    taparian algo: deformada (no la siguen), carga movil, diagramas y mapa
    D/C. Con algo seleccionado se abre un POZO: se esconden los panos que
    tocan la seleccion en planta (a MARGEN_POZO) desde su cota hacia
    arriba, para verla desde arriba sin perder el resto del edificio.
  - Un objeto por entrada de areas_tributarias (no uno por piso): es lo que
    permite abrir el pozo.
  - Respetan el filtro de piso (AjustesVista.EnCotaVisible).
================================================================
*/

using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using UnityEngine.Rendering;

public partial class AmbienteVisor
{
    /// Espesor de dibujo de la losa (m). No es un dato del modelo.
    const float ESPESOR_LOSA = 0.15f;

    /// Cuanto sobre el canto de la viga va la cara superior (m): lo justo
    /// para que las dos caras no peleen en profundidad.
    const float SOBRE_EL_CANTO = 0.01f;

    /// Distancia en planta (m) desde la seleccion a la que un pano se
    /// esconde para abrir el pozo. 1 m toma los panos que tocan la barra o
    /// el nudo sin vaciar el piso.
    const float MARGEN_POZO = 1.0f;

    /// Hormigon de losa: algo mas claro que columnas y vigas, para que el
    /// piso se distinga de lo que lo sostiene.
    static readonly Color C_LOSA = new Color(0.86f, 0.85f, 0.82f);

    private Transform raizLosas;
    private readonly List<GameObject> losas = new List<GameObject>();
    private readonly List<float> cotasLosas = new List<float>();
    private readonly List<Rect> plantaLosas = new List<Rect>();     // x, y OpenSees
    private readonly List<Mesh> mallasLosas = new List<Mesh>();
    private ModeloEstructural modeloLosas;      // de que modelo son las losas dibujadas
    private Material matLosa;

    // Quien puede pedir que se escondan. Se buscan sin apuro (Update).
    private VisorSemana04 s4Losas;
    private VisorCargaMovil movilLosas;
    private float proximaBusquedaLosas = 0f;
    private string selTipoLosas = EventosVisor.TIPO_NINGUNO;
    private int selIdLosas = -1;

    void AlCambiarSeleccionLosas(string tipo, int id)
    {
        selTipoLosas = tipo ?? EventosVisor.TIPO_NINGUNO;
        selIdLosas = id;
    }

    /// Mismo trato que el suelo: si algo falla se avisa y se sigue, para que
    /// Aplicar() y su MaterialesCambiados lleguen siempre.
    void ActualizarLosasSinCortar()
    {
        try { ActualizarLosas(); }
        catch (Exception ex) { Debug.LogException(ex); }
    }

    /// Arma las mallas una sola vez por modelo cargado: los poligonos vienen
    /// del JSON y una edicion en Unity no los cambia.
    void ActualizarLosas()
    {
        ModeloEstructural modelo = visor.Modelo;
        if (ReferenceEquals(modelo, modeloLosas)) return;
        BorrarLosas();
        modeloLosas = modelo;
        if (modelo.areas_tributarias == null || modelo.areas_tributarias.Count == 0) return;

        if (raizLosas == null)
        {
            raizLosas = new GameObject("Losas").transform;
            raizLosas.SetParent(transform, false);
        }
        var cantos = new Dictionary<int, float>();
        var areaPorCota = new SortedDictionary<int, float>();
        var poligonosPorCota = new SortedDictionary<int, int>();
        foreach (AreaTributaria a in modelo.areas_tributarias)
        {
            if (a == null || a.vertices == null) continue;
            int clave = Mathf.RoundToInt(a.z * 100f);     // al cm, como las z del JSON
            float canto;
            if (!cantos.TryGetValue(clave, out canto)) cantos[clave] = canto = CantoTipico(modelo, a.z);
            float arriba = a.z + 0.5f * canto + SOBRE_EL_CANTO;
            float area;
            int poligonos;
            Rect planta;
            Mesh malla = MallaDeLosa(a, arriba, arriba - ESPESOR_LOSA, out area, out poligonos, out planta);
            if (malla == null) continue;
            malla.name = "Losa_" + a.elemento + "_z" + a.z.ToString("0.00", CultureInfo.InvariantCulture);
            mallasLosas.Add(malla);

            GameObject go = new GameObject(malla.name);
            go.transform.SetParent(raizLosas, false);
            go.AddComponent<MeshFilter>().sharedMesh = malla;
            MeshRenderer mr = go.AddComponent<MeshRenderer>();
            mr.shadowCastingMode = ShadowCastingMode.On;
            mr.receiveShadows = true;
            // Sin Collider a proposito (ver el encabezado).
            losas.Add(go);
            cotasLosas.Add(a.z);
            plantaLosas.Add(planta);

            float acum;
            areaPorCota.TryGetValue(clave, out acum);
            areaPorCota[clave] = acum + area;
            int n;
            poligonosPorCota.TryGetValue(clave, out n);
            poligonosPorCota[clave] = n + poligonos;
        }
        var resumen = new List<string>();
        foreach (KeyValuePair<int, float> kv in areaPorCota)
            resumen.Add(string.Format(CultureInfo.InvariantCulture,
                "z {0:F2}: {1} poligonos, {2:F1} m2 dibujados, cara superior {3:F2}",
                kv.Key / 100f, poligonosPorCota[kv.Key], kv.Value,
                kv.Key / 100f + 0.5f * cantos[kv.Key] + SOBRE_EL_CANTO));
        Debug.Log("AmbienteVisor: losas de dibujo desde areas_tributarias (" + losas.Count + " entradas): "
                  + string.Join("; ", resumen.ToArray()));
        firmaVisibilidadLosas = null;
        ActualizarVisibilidadLosas(true);
    }

    void BorrarLosas()
    {
        foreach (GameObject go in losas) if (go != null) Destroy(go);
        foreach (Mesh m in mallasLosas) if (m != null) Destroy(m);
        losas.Clear();
        cotasLosas.Clear();
        plantaLosas.Clear();
        mallasLosas.Clear();
        modeloLosas = null;
    }

    /// El canto (h) de la seccion de viga que mas se repite entre las barras
    /// horizontales con los dos nodos en esa cota. Criterio de DIBUJO (ver
    /// el encabezado); 0 si no hay vigas con seccion.
    static float CantoTipico(ModeloEstructural modelo, float z)
    {
        if (modelo.elementos == null) return 0f;
        var cuenta = new Dictionary<float, int>();
        foreach (Elemento e in modelo.elementos)
        {
            if (e == null || e.EsMuro || e.EsBrazo) continue;
            Nodo a = modelo.NodoPorId(e.n1), b = modelo.NodoPorId(e.n2);
            if (a == null || b == null) continue;
            if (Mathf.Abs(a.z - z) > TOL_EN_COTA || Mathf.Abs(b.z - z) > TOL_EN_COTA) continue;
            Seccion s = modelo.SeccionPorNombre(e.seccion);
            if (s == null || !s.TienePerfil) continue;
            int n;
            cuenta.TryGetValue(s.h, out n);
            cuenta[s.h] = n + 1;
        }
        float canto = 0f;
        int mas = 0;
        foreach (KeyValuePair<float, int> kv in cuenta)
            if (kv.Value > mas || (kv.Value == mas && kv.Key > canto)) { canto = kv.Key; mas = kv.Value; }
        return canto;
    }

    /// Cara superior, inferior y bordes de cada poligono de una entrada. Los
    /// bordes entre poligonos vecinos quedan dentro de la losa (no se ven);
    /// los del perimetro son el canto. UV en metros / REPETICION_HORMIGON,
    /// en coordenadas del mundo: dos panos vecinos empalman la textura.
    static Mesh MallaDeLosa(AreaTributaria a, float yArriba, float yAbajo, out float area, out int poligonos, out Rect planta)
    {
        area = 0f;
        poligonos = 0;
        float minX = float.MaxValue, minY = float.MaxValue, maxX = float.MinValue, maxY = float.MinValue;
        var v = new List<Vector3>();
        var uv = new List<Vector2>();
        var tri = new List<int>();
        var p = new List<Vector3>();
        foreach (int[] pol in a.Poligonos())
        {
            p.Clear();
            for (int k = 0; k < pol[1]; k++)
            {
                VerticePlanta q = a.vertices[pol[0] + k];
                Vector3 w = Ejes.AUnity(q.x, q.y, 0f);
                // El cierre repetido (primero = ultimo) o puntos duplicados.
                if (p.Count > 0 && (w - p[p.Count - 1]).sqrMagnitude < 1e-6f) continue;
                p.Add(w);
            }
            if (p.Count > 2 && (p[0] - p[p.Count - 1]).sqrMagnitude < 1e-6f) p.RemoveAt(p.Count - 1);
            if (p.Count < 3) continue;

            Vector3 centro = Vector3.zero;
            foreach (Vector3 w in p) centro += w;
            centro /= p.Count;
            float a2 = 0f;
            for (int k = 1; k + 1 < p.Count; k++)
                a2 += Vector3.Cross(p[k] - p[0], p[k + 1] - p[0]).y;
            if (Mathf.Abs(a2) < 2e-4f) continue;       // degenerado
            area += Mathf.Abs(a2) * 0.5f;
            poligonos++;
            foreach (Vector3 w in p)
            {
                // Unity (x, y, z) = OpenSees (x, z, y): la planta es (w.x, w.z).
                minX = Mathf.Min(minX, w.x); maxX = Mathf.Max(maxX, w.x);
                minY = Mathf.Min(minY, w.z); maxY = Mathf.Max(maxY, w.z);
            }

            // Caras de arriba (normal +Y) y de abajo (-Y), en abanico.
            foreach (bool deArriba in new[] { true, false })
            {
                float y = deArriba ? yArriba : yAbajo;
                int i0 = v.Count;
                foreach (Vector3 w in p)
                {
                    v.Add(new Vector3(w.x, y, w.z));
                    uv.Add(new Vector2(w.x / REPETICION_HORMIGON, w.z / REPETICION_HORMIGON));
                }
                for (int k = 1; k + 1 < p.Count; k++)
                    Triangulo(v, tri, i0, i0 + k, i0 + k + 1, deArriba ? Vector3.up : Vector3.down);
            }

            // Bordes: normal horizontal hacia afuera del poligono.
            for (int k = 0; k < p.Count; k++)
            {
                Vector3 a0 = p[k], a1 = p[(k + 1) % p.Count];
                float largo = (a1 - a0).magnitude;
                if (largo < 1e-3f) continue;
                Vector3 medio = (a0 + a1) * 0.5f;
                Vector3 afuera = Vector3.Cross(Vector3.up, a1 - a0).normalized;
                if (Vector3.Dot(afuera, medio - centro) < 0f) afuera = -afuera;
                int i0 = v.Count;
                v.Add(new Vector3(a0.x, yAbajo, a0.z)); uv.Add(new Vector2(0f, 0f));
                v.Add(new Vector3(a1.x, yAbajo, a1.z)); uv.Add(new Vector2(largo / REPETICION_HORMIGON, 0f));
                v.Add(new Vector3(a1.x, yArriba, a1.z)); uv.Add(new Vector2(largo / REPETICION_HORMIGON, ESPESOR_LOSA / REPETICION_HORMIGON));
                v.Add(new Vector3(a0.x, yArriba, a0.z)); uv.Add(new Vector2(0f, ESPESOR_LOSA / REPETICION_HORMIGON));
                Triangulo(v, tri, i0, i0 + 1, i0 + 2, afuera);
                Triangulo(v, tri, i0, i0 + 2, i0 + 3, afuera);
            }
        }
        planta = poligonos > 0 ? Rect.MinMaxRect(minX, minY, maxX, maxY) : new Rect();
        if (tri.Count == 0) return null;
        Mesh malla = new Mesh();
        if (v.Count > 65000) malla.indexFormat = IndexFormat.UInt32;
        malla.SetVertices(v);
        malla.SetUVs(0, uv);
        malla.SetTriangles(tri, 0);
        malla.RecalculateNormals();
        malla.RecalculateTangents();         // para el mapa normal de la losa (AmbienteVisor.Recursos.cs)
        malla.RecalculateBounds();
        return malla;
    }

    /// Agrega el triangulo con el orden que deja su cara hacia 'normal'
    /// (Unity toma como frente el lado de Cross(b - a, c - a)).
    static void Triangulo(List<Vector3> v, List<int> tri, int a, int b, int c, Vector3 normal)
    {
        Vector3 n = Vector3.Cross(v[b] - v[a], v[c] - v[a]);
        if (Vector3.Dot(n, normal) >= 0f) { tri.Add(a); tri.Add(b); tri.Add(c); }
        else { tri.Add(a); tri.Add(c); tri.Add(b); }
    }

    // ------------------------------------------------------------
    // CUANDO SE VEN
    // ------------------------------------------------------------
    // Estado aplicado, para tocar SetActive y el material solo si cambia.
    private string firmaVisibilidadLosas = null;

    void ActualizarVisibilidadLosas(bool forzar)
    {
        if (losas.Count == 0) return;
        if (Time.unscaledTime >= proximaBusquedaLosas && (s4Losas == null || movilLosas == null))
        {
            proximaBusquedaLosas = Time.unscaledTime + 1f;
            if (s4Losas == null) s4Losas = FindAnyObjectByType<VisorSemana04>();
            if (movilLosas == null) movilLosas = FindAnyObjectByType<VisorCargaMovil>();
        }

        bool alguna = AjustesVista.losas && AjustesVista.realista && visor != null && visor.Modelo != null
                      && !(visor.mostrarDeformada && visor.HayDeformada)
                      && !(movilLosas != null && movilLosas.Activo)
                      && !(s4Losas != null && (s4Losas.MapaDCActivo || s4Losas.HayDiagramaDibujado));
        float zSel = float.PositiveInfinity;
        Vector2 selA = Vector2.zero, selB = Vector2.zero;
        bool haySel = alguna && Seleccion(visor.Modelo, out zSel, out selA, out selB);

        var sb = new System.Text.StringBuilder(losas.Count);
        for (int i = 0; i < losas.Count; i++)
        {
            float z = cotasLosas[i];
            bool ver = alguna && AjustesVista.EnCotaVisible(z);
            if (ver && haySel && z > zSel - AjustesVista.TOLERANCIA_COTA
                && DistanciaARect(plantaLosas[i], selA, selB) < MARGEN_POZO)
                ver = false;
            sb.Append(ver ? '1' : '0');
        }
        string firma = sb.ToString();
        if (!forzar && firma == firmaVisibilidadLosas) return;
        firmaVisibilidadLosas = firma;

        if (matLosa == null && firma.IndexOf('1') >= 0)
        {
            matLosa = NuevoMaterialReal("Losa", "hormigon_losa", C_LOSA, 0.10f, 0f,
                                        Vector2.one * (REPETICION_HORMIGON / TILE_LOSA_M));
            if (matLosa == null)
            {
                CrearTexturas();
                matLosa = NuevoMaterial("Losa", texHormigon, C_LOSA, 0.10f, 0f, Vector2.one);
            }
        }
        for (int i = 0; i < losas.Count; i++)
        {
            if (losas[i] == null) continue;
            bool ver = firma[i] == '1';
            if (ver)
            {
                MeshRenderer mr = losas[i].GetComponent<MeshRenderer>();
                if (mr != null && mr.sharedMaterial != matLosa) mr.sharedMaterial = matLosa;
            }
            if (losas[i].activeSelf != ver) losas[i].SetActive(ver);
        }
    }

    /// La cota mas baja de lo seleccionado y su planta como segmento (un
    /// nodo o una columna: los dos extremos iguales). false sin seleccion.
    bool Seleccion(ModeloEstructural m, out float zMin, out Vector2 a, out Vector2 b)
    {
        zMin = float.PositiveInfinity;
        a = b = Vector2.zero;
        if (selTipoLosas == EventosVisor.TIPO_ELEMENTO)
        {
            Elemento e = m.ElementoPorId(selIdLosas);
            Nodo n1 = e != null ? m.NodoPorId(e.n1) : null;
            Nodo n2 = e != null ? m.NodoPorId(e.n2) : null;
            if (n1 == null || n2 == null) return false;
            zMin = Mathf.Min(n1.z, n2.z);
            a = new Vector2(n1.x, n1.y);
            b = new Vector2(n2.x, n2.y);
            return true;
        }
        if (selTipoLosas == EventosVisor.TIPO_NODO)
        {
            Nodo n = m.NodoPorId(selIdLosas);
            if (n == null) return false;
            zMin = n.z;
            a = b = new Vector2(n.x, n.y);
            return true;
        }
        return false;
    }

    /// Distancia en planta de un segmento a un rectangulo (0 si se tocan).
    /// Muestreado cada 0.5 m: es para abrir un pozo de dibujo, no un calculo.
    static float DistanciaARect(Rect r, Vector2 a, Vector2 b)
    {
        int pasos = Mathf.Clamp(Mathf.CeilToInt(Vector2.Distance(a, b) / 0.5f), 1, 200);
        float menor = float.MaxValue;
        for (int k = 0; k <= pasos; k++)
        {
            Vector2 p = Vector2.Lerp(a, b, k / (float)pasos);
            float dx = Mathf.Max(r.xMin - p.x, 0f, p.x - r.xMax);
            float dy = Mathf.Max(r.yMin - p.y, 0f, p.y - r.yMax);
            menor = Mathf.Min(menor, Mathf.Sqrt(dx * dx + dy * dy));
        }
        return menor;
    }
}
