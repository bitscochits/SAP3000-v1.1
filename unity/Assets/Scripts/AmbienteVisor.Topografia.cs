/*
================================================================
  AmbienteVisor.Topografia.cs
================================================================
  El RELIEVE DEL SITIO alrededor del edificio: el terreno natural
  del campus, como una malla de pasto con un hueco donde esta el
  edificio. Solo DIBUJO: ningun calculo lee el terreno.

  ----------------------------------------------------------------
  DE DONDE SALE (nada deducido aca)
  ----------------------------------------------------------------
  StreamingAssets/topografia.json, que arma Python:
      edificios/conjunto/topografia.py  ->  data/unity/topografia_<ed>.json
      comun/lanzar_unity.py sincronizar <ed>  ->  StreamingAssets/topografia.json
  Python ubica el relieve con el techo del cuerpo antiguo trazado en
  Google Earth, saca las cotas del DEM Copernicus GLO-30 y lo calza en
  vertical con los apoyos en terreno. Los supuestos, con su por que,
  estan en edificios/conjunto/sitio/sitio.json. Aca solo se lee la
  malla (x0, y0, paso, nx, ny, z) y los huecos, en coordenadas del
  modelo (OpenSees), y se pasa a Unity con Ejes.AUnity.

  ----------------------------------------------------------------
  REGLAS
  ----------------------------------------------------------------
  - Se lee con LectorStreaming (UnityWebRequest): asi tambien anda en
    la build Web del telefono, donde StreamingAssets es una URL.
  - Si el archivo no esta, o es de otro modelo, no se dibuja nada y el
    panel lo dice (AjustesVista.relieveEstado). Los JSON del visor no
    traen info.edificio: el relieve trae cuantos nodos y elementos tiene
    el modelo para el que se armo (info.n_nodos, info.n_elementos), y se
    compara AL CARGAR el modelo. Editarlo despues (pestana Modificar)
    no borra el relieve.
  - Tres partes, con los materiales del suelo: la cara de arriba
    (pasto), los taludes (tierra) en el borde de cada hueco hasta la
    cota del terreno del modelo (cota_fondo) y en el borde exterior de
    la zona, y el fondo de cada hueco (el fondo de la excavacion).
  - Con el relieve a la vista se APAGA el plano del suelo (no sus
    hijos, las terrazas): el plano en la cota de arranque taparia la
    parte del relieve que queda mas abajo (la quebrada del oeste).
  - SIN collider, como el suelo: la seleccion es un Physics.Raycast
    que se queda con el primer collider.
  - Depende solo del JSON: se arma una vez por modelo.
================================================================
*/

using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using UnityEngine.Rendering;

[Serializable]
public class TopografiaJson
{
    public InfoTopografia info;
    public float x0, y0, paso;          // primer nodo de la malla y lado (m, OpenSees)
    public int nx, ny;                  // nodos en x y en y
    public float sin_dato;              // la cota de los nodos fuera de la zona
    public float cota_fondo;            // la cota del terreno del modelo (info.cota_terreno)
    public float[] z;                   // ny filas de nx cotas (OpenSees z, m)
    public HuecoTopografia[] huecos;    // la planta de cada cuerpo mas un margen
    public VerticePlanta[] techo_foto;  // el techo trazado en Google Earth, en el modelo
}

[Serializable]
public class InfoTopografia
{
    public string edificio, generado_por, fuente, atribucion, zona, _por_que;
    public int n_nodos, n_elementos;    // la huella del modelo del visor
    public double rumbo_x_grados, lon_centro_techo, lat_centro_techo;
    public float desfase_vertical_m, residuo_rms_m;
}

[Serializable]
public class HuecoTopografia
{
    public float x1, y1, x2, y2;
}

public partial class AmbienteVisor
{
    const string ARCHIVO_TOPOGRAFIA = "topografia.json";
    /// Cuanto baja el talud del borde exterior bajo la cota mas baja de la
    /// zona: un bloque de terreno, como una maqueta, en vez de una sabana.
    const float FALDON_EXTERIOR = 3f;

    private GameObject relieve;
    private TopografiaJson topografia;
    private int pedidoRelieve;           // sube en cada modelo cargado: descarta respuestas viejas
    private string firmaRelieve;

    // ============================================================
    // CARGA
    // ============================================================
    /// Lo llama ActualizarSueloSinCortar en cada carga y cada redibujado:
    /// la malla depende solo del JSON, asi que se arma una vez.
    void ActualizarRelieve()
    {
        if (topografia != null) ConstruirRelieve();
    }

    /// Lo llama AlCargarModelo: un modelo NUEVO, se vuelve a leer el archivo.
    void PedirRelieveDelModelo()
    {
        pedidoRelieve++;
        topografia = null;
        BorrarRelieve();
        AjustesVista.relieveEstado = "Buscando el relieve del sitio...";
        StartCoroutine(PedirTopografia(pedidoRelieve, visor.Modelo.nodos.Count, visor.Modelo.elementos.Count));
    }

    IEnumerator PedirTopografia(int pedido, int nNodos, int nElementos)
    {
        string texto = null, error = null;
        yield return LectorStreaming.Leer(ARCHIVO_TOPOGRAFIA, t => texto = t, e => error = e);
        // Se cargo otro modelo mientras se leia: esta respuesta ya no sirve.
        if (pedido != pedidoRelieve) yield break;

        if (error != null)
        {
            AjustesVista.relieveEstado = "Sin relieve: no hay StreamingAssets/topografia.json (lo arma "
                + "edificios/conjunto/topografia.py y lo copia lanzar_unity.py sincronizar).";
            Debug.Log("AmbienteVisor: " + AjustesVista.relieveEstado);
            yield break;
        }
        TopografiaJson t = null;
        try { t = JsonUtility.FromJson<TopografiaJson>(texto); }
        catch (Exception ex) { Debug.LogException(ex); }
        string problema = null;
        if (t == null || t.info == null) problema = "no se pudo leer topografia.json";
        else if (t.info.n_nodos != nNodos || t.info.n_elementos != nElementos)
            problema = string.Format("topografia.json es de '{0}' ({1} nodos, {2} elementos) y el modelo "
                + "cargado tiene {3} nodos y {4} elementos: se copia con lanzar_unity.py sincronizar <edificio>",
                t.info.edificio, t.info.n_nodos, t.info.n_elementos, nNodos, nElementos);
        else if (t.z == null || t.nx < 2 || t.ny < 2 || t.z.Length != t.nx * t.ny)
            problema = "topografia.json no trae nx x ny cotas";
        if (problema != null)
        {
            AjustesVista.relieveEstado = "Sin relieve: " + problema + ".";
            Debug.LogWarning("AmbienteVisor: " + AjustesVista.relieveEstado);
            yield break;
        }

        topografia = t;
        AjustesVista.relieveEstado = string.Format(CultureInfo.InvariantCulture,
            "Relieve del sitio ({5}): {0}, interpolado en una malla cada {1:F0} m; ubicado con el techo del cuerpo antiguo en "
            + "Google Earth (+x del modelo a {2:F1} grados del norte) y calzado con los apoyos en terreno "
            + "(desfase {3:F2} m, residuo rms {4:F2} m). Solo dibujo.",
            t.info.fuente, t.paso, t.info.rumbo_x_grados, t.info.desfase_vertical_m, t.info.residuo_rms_m,
            t.info.edificio);
        if (visor != null && visor.Modelo != null) ConstruirRelieve();
    }

    // ============================================================
    // LA MALLA
    // ============================================================
    void ConstruirRelieve()
    {
        TopografiaJson t = topografia;
        string firma = t.info.edificio + "|" + t.nx + "x" + t.ny + "|" + t.paso.ToString(CultureInfo.InvariantCulture);
        if (relieve != null && firma == firmaRelieve) { AplicarVisibilidadRelieve(); return; }

        Mesh malla = MallaDelRelieve(t);
        if (relieve == null)
        {
            // Sin Collider a proposito (ver el encabezado). Recibe sombra, no la proyecta.
            relieve = new GameObject("Relieve");
            relieve.transform.SetParent(transform, false);
            relieve.AddComponent<MeshFilter>();
            MeshRenderer mr = relieve.AddComponent<MeshRenderer>();
            mr.shadowCastingMode = ShadowCastingMode.Off;
            mr.receiveShadows = true;
        }
        MeshFilter mf = relieve.GetComponent<MeshFilter>();
        if (mf.sharedMesh != null) Destroy(mf.sharedMesh);
        mf.sharedMesh = malla;
        firmaRelieve = firma;
        AplicarMaterialesSuelo();
        AplicarVisibilidadRelieve();
        Debug.Log(string.Format(CultureInfo.InvariantCulture,
            "AmbienteVisor: relieve del sitio de {0} x {1} nodos cada {2:F1} m, {3} huecos, fondo en z = {4:F2}.",
            t.nx, t.ny, t.paso, t.huecos != null ? t.huecos.Length : 0, t.cota_fondo));
    }

    /// Con el relieve a la vista se apaga el PLANO del suelo, no sus hijos.
    void AplicarVisibilidadRelieve()
    {
        bool ver = AjustesVista.relieve && relieve != null && topografia != null;
        if (relieve != null) relieve.SetActive(ver);
        if (suelo != null)
        {
            MeshRenderer mr = suelo.GetComponent<MeshRenderer>();
            if (mr != null) mr.enabled = !ver;
        }
    }

    void BorrarRelieve()
    {
        if (relieve == null) return;
        MeshFilter mf = relieve.GetComponent<MeshFilter>();
        if (mf != null && mf.sharedMesh != null) Destroy(mf.sharedMesh);
        Destroy(relieve);
        relieve = null;
        firmaRelieve = null;
        if (suelo != null)
        {
            MeshRenderer mr = suelo.GetComponent<MeshRenderer>();
            if (mr != null) mr.enabled = true;
        }
    }

    /// Submallas: 0 la cara de arriba (pasto), 1 los taludes (tierra),
    /// 2 el fondo de los huecos. Cada celda de la red es un cuadrado de
    /// cuatro nodos; va arriba si sus cuatro nodos tienen cota y su
    /// centro no cae en un hueco.
    static Mesh MallaDelRelieve(TopografiaJson t)
    {
        int nx = t.nx, ny = t.ny;
        float corte = t.sin_dato * 0.5f;
        Func<int, int, bool> conCota = (i, j) => t.z[j * nx + i] > corte;
        Func<int, int, Vector3> nodo = (i, j) => Ejes.AUnity(t.x0 + i * t.paso, t.y0 + j * t.paso, t.z[j * nx + i]);

        float zMin = float.MaxValue;
        foreach (float v in t.z) if (v > corte) zMin = Mathf.Min(zMin, v);
        float zFaldon = zMin - FALDON_EXTERIOR;

        // Estado de cada celda: 0 nada, 1 terreno, 2 hueco.
        int cx = nx - 1, cy = ny - 1;
        int[,] estado = new int[cx, cy];
        for (int j = 0; j < cy; j++)
            for (int i = 0; i < cx; i++)
            {
                int conDato = (conCota(i, j) ? 1 : 0) + (conCota(i + 1, j) ? 1 : 0)
                            + (conCota(i + 1, j + 1) ? 1 : 0) + (conCota(i, j + 1) ? 1 : 0);
                float xc = t.x0 + (i + 0.5f) * t.paso, yc = t.y0 + (j + 0.5f) * t.paso;
                if (EnHueco(t, xc, yc)) estado[i, j] = conDato > 0 ? 2 : 0;
                else estado[i, j] = conDato == 4 ? 1 : 0;
            }

        List<Vector3> v3 = new List<Vector3>();
        List<Vector2> uv = new List<Vector2>();
        List<int> triArriba = new List<int>(), triTalud = new List<int>(), triFondo = new List<int>();
        int[] id = new int[nx * ny];
        for (int k = 0; k < id.Length; k++) id[k] = -1;
        Func<int, int, int> vertice = (i, j) =>
        {
            int k = j * nx + i;
            if (id[k] >= 0) return id[k];
            Vector3 p = nodo(i, j);
            id[k] = v3.Count;
            v3.Add(p);
            uv.Add(new Vector2(p.x / REPETICION_PASTO, p.z / REPETICION_PASTO));
            return id[k];
        };

        for (int j = 0; j < cy; j++)
            for (int i = 0; i < cx; i++)
            {
                if (estado[i, j] == 1)
                {
                    int a = vertice(i, j), b = vertice(i + 1, j), c = vertice(i + 1, j + 1), d = vertice(i, j + 1);
                    // Horario visto desde arriba (x a la derecha, z hacia adelante).
                    triArriba.Add(a); triArriba.Add(d); triArriba.Add(c);
                    triArriba.Add(a); triArriba.Add(c); triArriba.Add(b);
                }
                else if (estado[i, j] == 2)
                {
                    float x1 = t.x0 + i * t.paso, x2 = x1 + t.paso, y1 = t.y0 + j * t.paso, y2 = y1 + t.paso;
                    float zf = t.cota_fondo - BAJO_LA_COTA;
                    Cuadro(v3, uv, triFondo, Ejes.AUnity(x1, y1, zf), Ejes.AUnity(x1, y2, zf),
                           Ejes.AUnity(x2, y2, zf), Ejes.AUnity(x2, y1, zf), Vector3.up, REPETICION_TIERRA);
                }
            }

        // Taludes: cada lado de una celda de terreno que da a un hueco (baja
        // hasta el fondo y mira hacia el hueco) o al borde de la zona (baja
        // al faldon y mira hacia afuera).
        int[] di = { 0, 1, 0, -1 }, dj = { -1, 0, 1, 0 };
        for (int j = 0; j < cy; j++)
            for (int i = 0; i < cx; i++)
            {
                if (estado[i, j] != 1) continue;
                for (int k = 0; k < 4; k++)
                {
                    int vi = i + di[k], vj = j + dj[k];
                    int vecino = (vi >= 0 && vj >= 0 && vi < cx && vj < cy) ? estado[vi, vj] : 0;
                    if (vecino == 1) continue;
                    // Los dos nodos del lado compartido, en la red.
                    int ai, aj, bi, bj;
                    switch (k)
                    {
                        case 0: ai = i; aj = j; bi = i + 1; bj = j; break;
                        case 1: ai = i + 1; aj = j; bi = i + 1; bj = j + 1; break;
                        case 2: ai = i + 1; aj = j + 1; bi = i; bj = j + 1; break;
                        default: ai = i; aj = j + 1; bi = i; bj = j; break;
                    }
                    Vector3 pa = nodo(ai, aj), pb = nodo(bi, bj);
                    float abajo = vecino == 2 ? t.cota_fondo - BAJO_LA_COTA : zFaldon;
                    Vector3 qa = new Vector3(pa.x, abajo, pa.z), qb = new Vector3(pb.x, abajo, pb.z);
                    // Hacia donde mira: al hueco, o hacia afuera de la zona.
                    Vector3 afuera = new Vector3(di[k], 0f, dj[k]);
                    Cuadro(v3, uv, triTalud, pa, pb, qb, qa, afuera, REPETICION_TIERRA);
                }
            }

        Mesh m = new Mesh { name = "Relieve" };
        if (v3.Count > 65000) m.indexFormat = IndexFormat.UInt32;
        m.SetVertices(v3);
        m.SetUVs(0, uv);
        m.subMeshCount = 3;
        m.SetTriangles(triArriba, 0);
        m.SetTriangles(triTalud, 1);
        m.SetTriangles(triFondo, 2);
        m.RecalculateNormals();
        m.RecalculateTangents();             // para el mapa normal del pasto (AmbienteVisor.Recursos.cs)
        m.RecalculateBounds();
        return m;
    }

    static bool EnHueco(TopografiaJson t, float x, float y)
    {
        if (t.huecos == null) return false;
        foreach (HuecoTopografia h in t.huecos)
            if (x >= h.x1 && x <= h.x2 && y >= h.y1 && y <= h.y2) return true;
        return false;
    }

    /// Un cuadrilatero p0-p1-p2-p3 con vertices propios (los taludes y el
    /// fondo no comparten normal con la cara de arriba), con la cara de
    /// adelante mirando hacia 'mira'. UV en metros / repeticion.
    static void Cuadro(List<Vector3> v3, List<Vector2> uv, List<int> tri, Vector3 p0, Vector3 p1,
                       Vector3 p2, Vector3 p3, Vector3 mira, float rep)
    {
        int b = v3.Count;
        v3.Add(p0); v3.Add(p1); v3.Add(p2); v3.Add(p3);
        bool vertical = Mathf.Abs(mira.y) < 0.5f;
        foreach (Vector3 p in new[] { p0, p1, p2, p3 })
            uv.Add(vertical ? new Vector2((p.x + p.z) / rep, p.y / rep) : new Vector2(p.x / rep, p.z / rep));
        // Unity: la cara de adelante es la de Cross(b - a, c - a).
        bool derecho = Vector3.Dot(Vector3.Cross(p1 - p0, p2 - p0), mira) > 0f;
        if (derecho) { tri.Add(b); tri.Add(b + 1); tri.Add(b + 2); tri.Add(b); tri.Add(b + 2); tri.Add(b + 3); }
        else { tri.Add(b); tri.Add(b + 2); tri.Add(b + 1); tri.Add(b); tri.Add(b + 3); tri.Add(b + 2); }
    }
}
