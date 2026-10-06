/*
================================================================
  AmbienteVisor.Terrazas.cs
================================================================
  El TERRENO EN NIVELES. El suelo de AmbienteVisor.cs es un plano en
  info.cota_terreno, el nivel MAS BAJO (la base). Cada nivel de
  info.terrenos que queda mas arriba se dibuja aca como una TERRAZA:
  una losa de pasto a su z sobre su region en planta, con muros
  verticales de tierra hasta la base en todos sus bordes. Solo DIBUJO:
  ningun calculo lee el terreno.

  ----------------------------------------------------------------
  DE DONDE SALE (nada deducido aca)
  ----------------------------------------------------------------
  - La z y la region: info.terrenos, que arma Python desde el perfil de
    cada edificio ('terreno.terrazas'), con la misma definicion con que
    el modelo crea sus apoyos (edificios/ingenieria/export_unity.py,
    terrenos()). El conjunto las recibe ya calzadas
    (edificios/conjunto/exportar_unity.py, terrenos_del_conjunto()).
    Contrato: semana05/CONTRATO.md.
  - Sin info.terrenos, o con solo la base, no se dibuja nada: el suelo
    es el de siempre.
  - Hoy hay una: la de Ingenieria, en su z 3.96 local (-4.01 en el
    conjunto), el segundo N.R. de su planta de fundaciones, bajo sus 39
    apoyos en terreno. Con un solo plano esos apoyos se dibujaban 3.96 m
    en el aire.

  ----------------------------------------------------------------
  REGLAS
  ----------------------------------------------------------------
  - NADA ENTERRADO NI TAPADO: lo que baja bajo la cara de la terraza
    (columnas y muros que llegan a la base) se recorta alrededor con
    HuecoDelSuelo.CalcularTerraza (AmbienteVisor.cs): las mismas
    estampas, cierre y techo del hueco del suelo. Un recinto de muros que
    baja a la base se ve como un pozo; un apoyo de la terraza queda con
    tierra debajo, salvo que este SOBRE un muro que baja (entonces se ve
    encima del muro).
  - SIN collider, como el suelo: la seleccion es un Physics.Raycast que
    se queda con el primer collider, y una terraza con collider se
    comeria el click a lo que esta dentro de sus pozos.
  - Hijo del objeto "Suelo": se prende y se apaga con el (capa Suelo), y
    AplicarMaterialesSuelo le pone los mismos materiales: pasto arriba y
    tierra en los muros en la vista realista; mate en la tecnica y con el
    mapa D/C. No proyecta sombra (igual que el suelo); la recibe.
  - Depende solo de la geometria ORIGINAL (no de la deformada), como el
    suelo: con la misma firma no se rehace la malla.
  - Los muros de tierra son de UNA cara y miran hacia afuera de la
    terraza (hacia el hueco, en un pozo): desde afuera se ve el talud, y
    el lado de adelante de un pozo no tapa lo que hay dentro.
================================================================
*/

using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using UnityEngine;
using UnityEngine.Rendering;

public partial class AmbienteVisor
{
    /// La celda de la terraza es la MITAD de la del suelo (0.25 m en los
    /// tres edificios). El recorte pasa a 0.35-1.0 m del eje de lo que
    /// baja, y el borde del marching squares cae en el punto medio entre
    /// muestras: con 0.5 m la tierra del apoyo (23.02, 64.10) de
    /// Ingenieria, a 0.60 m de un muro, quedaba en una sola muestra.
    const double DIVISOR_CELDA_TERRAZA = 2.0;

    private GameObject terrazas;
    private string firmaTerrazas;

    /// Arma (o reusa) la malla de las terrazas. La llama
    /// ActualizarSueloSinCortar() despues del suelo, que tiene que existir:
    /// la terraza es su hijo.
    void ActualizarTerrazas()
    {
        if (suelo == null || visor == null || visor.Modelo == null) return;
        ModeloEstructural modelo = visor.Modelo;
        string aviso;
        float cota = CotaDelTerreno(modelo, out aviso);

        // Los niveles SOBRE la base, con los poligonos de una misma z
        // juntos (el mapa de la terraza es la union: sin paredes entre dos
        // poligonos que se tocan).
        SortedDictionary<float, List<List<double[]>>> porZ = new SortedDictionary<float, List<List<double[]>>>();
        Dictionary<float, string> nombres = new Dictionary<float, string>();
        if (modelo.info != null && modelo.info.terrenos != null)
        {
            foreach (NivelTerreno t in modelo.info.terrenos)
            {
                if (t == null || t.vertices == null || t.vertices.Count < 3) continue;   // la base
                if (t.z <= cota + AjustesVista.TOLERANCIA_COTA)
                {
                    Debug.LogWarning(string.Format(CultureInfo.InvariantCulture,
                        "AmbienteVisor: el nivel de terreno '{0}' (z = {1:F2}) no esta sobre la base "
                        + "({2:F2}); no se dibuja como terraza.", t.nombre, t.z, cota));
                    continue;
                }
                float z = Mathf.Round(t.z * 100f) / 100f;
                List<List<double[]>> polis;
                if (!porZ.TryGetValue(z, out polis))
                {
                    polis = new List<List<double[]>>();
                    porZ[z] = polis;
                    nombres[z] = t.nombre;
                }
                polis.Add(t.vertices.ConvertAll(v => new double[] { v.x, v.y }));
            }
        }
        if (porZ.Count == 0)
        {
            BorrarTerrazas();
            return;
        }

        double minX = double.MaxValue, minY = double.MaxValue, maxX = double.MinValue, maxY = double.MinValue;
        foreach (Nodo n in modelo.nodos)
        {
            minX = Math.Min(minX, n.x); maxX = Math.Max(maxX, n.x);
            minY = Math.Min(minY, n.y); maxY = Math.Max(maxY, n.y);
        }
        double celda = CeldaPara(minX, minY, maxX, maxY) / DIVISOR_CELDA_TERRAZA;

        // Lo que hay bajo, en y sobre la cara de cada terraza: las mismas
        // listas que usa el hueco del suelo (ReunirGeometria). De ahi sale
        // tambien la firma.
        List<float> zs = new List<float>(porZ.Keys);
        List<List<double[]>[]> geometria = new List<List<double[]>[]>();
        StringBuilder firma = new StringBuilder();
        firma.Append(cota.ToString("F3", CultureInfo.InvariantCulture)).Append('|')
             .Append(celda.ToString("F3", CultureInfo.InvariantCulture));
        foreach (float z in zs)
        {
            List<double[]> est = new List<double[]>(), techo = new List<double[]>(), apoyos = new List<double[]>();
            double zFondo;
            ReunirGeometria(modelo, z, est, techo, apoyos, out zFondo);
            geometria.Add(new[] { est, techo, apoyos });
            double s = 0;
            foreach (List<double[]> p in porZ[z])
                foreach (double[] q in p) s += q[0] * 1.9 + q[1] * 2.3;
            firma.Append('|').Append(Firma(z, est, techo, apoyos))
                 .Append('|').Append(s.ToString("F3", CultureInfo.InvariantCulture));
        }
        string f = firma.ToString();
        if (terrazas != null && f == firmaTerrazas) return;

        List<Vector3> v3 = new List<Vector3>();
        List<Vector3> nor = new List<Vector3>();
        List<Vector2> uv = new List<Vector2>();
        List<int> triArriba = new List<int>(), triPared = new List<int>();
        float yBase = cota - BAJO_LA_COTA;
        StringBuilder log = new StringBuilder();
        for (int k = 0; k < zs.Count; k++)
        {
            float z = zs[k];
            List<double[]>[] g = geometria[k];
            HuecoDelSuelo.Resultado r = HuecoDelSuelo.CalcularTerraza(porZ[z], g[0], g[1], g[2], celda);
            int conTierra = 0;
            foreach (bool b in r.suelo) if (b) conTierra++;
            MallaTerraza(r, z - BAJO_LA_COTA, yBase, v3, nor, uv, triArriba, triPared);
            log.Append(string.Format(CultureInfo.InvariantCulture,
                " Terraza '{0}' en z = {1:F2} m ({2} poligono(s)): {3:F0} m2 de tierra, {4:F0} m2 "
                + "recortados alrededor de {5} estampas que bajan a la base; {6} apoyos sobre tierra, "
                + "{7} sobre la estructura que baja.",
                nombres[z], z, porZ[z].Count, conTierra * celda * celda, r.areaHueco, g[0].Count,
                r.apoyosUsados, r.apoyosSobreSubterraneo));
        }

        Mesh m = new Mesh { name = "TerrazasAmbiente" };
        if (v3.Count > 65000) m.indexFormat = IndexFormat.UInt32;
        m.SetVertices(v3);
        m.SetNormals(nor);
        m.SetUVs(0, uv);
        // Tres submallas, como el suelo, para usar sus mismos materiales:
        // 0 pasto, 1 tierra de los muros, 2 (vacia) el fondo.
        m.subMeshCount = 3;
        m.SetTriangles(triArriba, 0);
        m.SetTriangles(triPared, 1);
        m.SetTriangles(new List<int>(), 2);
        m.RecalculateTangents();             // para el mapa normal (AmbienteVisor.Recursos.cs)
        m.RecalculateBounds();

        if (terrazas == null)
        {
            // Sin Collider a proposito (ver el encabezado).
            terrazas = new GameObject("Terrazas");
            terrazas.transform.SetParent(suelo.transform, false);
            terrazas.AddComponent<MeshFilter>();
            MeshRenderer mr = terrazas.AddComponent<MeshRenderer>();
            mr.shadowCastingMode = ShadowCastingMode.Off;
            mr.receiveShadows = true;
        }
        MeshFilter mf = terrazas.GetComponent<MeshFilter>();
        if (mf.sharedMesh != null) Destroy(mf.sharedMesh);
        mf.sharedMesh = m;
        firmaTerrazas = f;
        AplicarMaterialesSuelo();

        Debug.Log(string.Format(CultureInfo.InvariantCulture,
            "AmbienteVisor: {0} nivel(es) de terreno sobre la base (z = {1:F2} m, info.terrenos), "
            + "celda {2:F2} m, {3} vertices.", zs.Count, cota, celda, v3.Count) + log);
    }

    void BorrarTerrazas()
    {
        firmaTerrazas = null;
        if (terrazas == null) return;
        MeshFilter mf = terrazas.GetComponent<MeshFilter>();
        if (mf != null && mf.sharedMesh != null) Destroy(mf.sharedMesh);
        Destroy(terrazas);
        terrazas = null;
    }

    /// La malla de UNA terraza, agregada a las listas: la cara de arriba
    /// (submalla 0) por 'marching squares' sobre las muestras de tierra,
    /// como el suelo (ConstruirMalla, AmbienteVisor.cs), y un muro de
    /// tierra (submalla 1) en cada tramo de borde, de la cara (yT) a la
    /// base (yB). Sin fondo: bajo un pozo de la terraza se ve el suelo de
    /// la base, que sigue entero.
    static void MallaTerraza(HuecoDelSuelo.Resultado h, float yT, float yB, List<Vector3> v,
                             List<Vector3> nor, List<Vector2> uv, List<int> triArriba, List<int> triPared)
    {
        Dictionary<long, int> ids = new Dictionary<long, int>();
        int nx = h.nx, ny = h.ny;
        double c = h.celda;
        long ancho = 2L * ny + 3;

        // Vertice en coordenadas DOBLES de la red (esquinas pares, puntos
        // medios impares), compartido entre celdas vecinas: sin grietas.
        Func<int, int, int> vertice = (i2, j2) =>
        {
            long clave = i2 * ancho + j2;
            int id;
            if (ids.TryGetValue(clave, out id)) return id;
            float x = (float)(h.x0 + i2 * 0.5 * c), z = (float)(h.y0 + j2 * 0.5 * c);
            id = v.Count;
            v.Add(new Vector3(x, yT, z));
            nor.Add(Vector3.up);
            uv.Add(new Vector2(x / REPETICION_PASTO, z / REPETICION_PASTO));
            ids[clave] = id;
            return id;
        };

        int[] ci = { 0, 2, 2, 0 };     // esquinas de la celda en dobles: c0 c1 c2 c3
        int[] cj = { 0, 0, 2, 2 };
        int[] ei = { 1, 2, 1, 0 };     // punto medio del lado k (entre ck y ck+1)
        int[] ej = { 0, 1, 2, 1 };
        List<int> poli = new List<int>(6);
        List<bool> esMedio = new List<bool>(6);
        for (int j = 0; j < ny; j++)
        {
            for (int i = 0; i < nx; i++)
            {
                bool[] s = { h.Suelo(i, j), h.Suelo(i + 1, j), h.Suelo(i + 1, j + 1), h.Suelo(i, j + 1) };
                if (!s[0] && !s[1] && !s[2] && !s[3]) continue;
                bool todas = s[0] && s[1] && s[2] && s[3];

                poli.Clear(); esMedio.Clear();
                for (int k = 0; k < 4; k++)
                {
                    int k1 = (k + 1) % 4;
                    if (s[k]) { poli.Add(vertice(2 * i + ci[k], 2 * j + cj[k])); esMedio.Add(false); }
                    if (s[k] != s[k1]) { poli.Add(vertice(2 * i + ei[k], 2 * j + ej[k])); esMedio.Add(true); }
                }
                if (poli.Count < 3) continue;
                for (int k = 1; k + 1 < poli.Count; k++)
                    Triangulo(triArriba, v, poli[0], poli[k], poli[k + 1], Vector3.up);
                if (todas) continue;

                // Muros: cada par de puntos medios seguidos es un tramo del
                // borde. Pared() los orienta lejos de la tierra de la celda.
                Vector3 centro = Vector3.zero;
                int nTierra = 0;
                for (int k = 0; k < 4; k++)
                {
                    if (!s[k]) continue;
                    centro += new Vector3((float)(h.x0 + (i + ci[k] / 2) * c), 0f, (float)(h.y0 + (j + cj[k] / 2) * c));
                    nTierra++;
                }
                centro /= Mathf.Max(nTierra, 1);
                for (int k = 0; k < poli.Count; k++)
                {
                    int k1 = (k + 1) % poli.Count;
                    if (esMedio[k] && esMedio[k1])
                        Pared(v, nor, uv, triPared, v[poli[k]], v[poli[k1]], centro, yT, yB);
                }
            }
        }
    }
}
