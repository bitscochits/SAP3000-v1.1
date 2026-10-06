/*
================================================================
  RecursosRealistas.cs  (Editor)
================================================================
  Arma, UNA vez, los recursos de la vista realista que no se pueden
  crear en tiempo de ejecucion sin perderse en la build:

    Resources/Ambiente/Mat_<item>.mat   URP/Lit con color + mapa normal
                                         (Texturas/<item>/color.jpg y
                                         normal_gl.jpg) y el mapa de
                                         detalle que rompe el patron
                                         (detalle.png, detalle.json)
    Resources/Ambiente/Cielo.mat        Skybox/Panoramic con el HDRI
                                         (Texturas/cielo/cielo_2k_suelo.hdr: el HDRI
                                         con suelo bajo el horizonte)
    Resources/Ambiente/PerfilRealista.asset  post-proceso de la vista
                                         realista (ACES, color, bloom)

  POR QUE ASSETS Y NO CODIGO: la build borra las variantes de shader que
  ningun material usa. Un material creado con 'new Material' y el
  keyword _NORMALMAP se ve en el editor y sale plano en el exe; el
  Skybox/Panoramic ni siquiera llegaria. Como estos materiales viven en
  Resources, la build los incluye con sus shaders y variantes.
  AmbienteVisor.cs los carga con Resources.Load y, si no estan, sigue
  con las texturas procedurales.

  Tambien deja bien importadas las texturas (el normal como NormalMap;
  importado como imagen comun el relieve sale al reves y sin aviso).

  Correr (con el editor cerrado):
    Unity.exe -batchmode -quit -projectPath unity
              -executeMethod RecursosRealistas.Crear -logFile <log>
  o el menu Laboratorio > Recursos de la vista realista.
================================================================
*/

using System.IO;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

public static class RecursosRealistas
{
    [System.Serializable]
    class SolDelCielo { public float giro_grados; }
    [System.Serializable]
    class Detalle { public string item; public float escala; }
    [System.Serializable]
    class Detalles { public Detalle[] items; }

    const string CARPETA = "Assets/Resources/Ambiente";
    const string TEXTURAS = CARPETA + "/Texturas";
    static readonly string[] ITEMS = { "hormigon_visto", "hormigon_losa", "pasto", "tierra", "acero" };

    [MenuItem("Laboratorio/Recursos de la vista realista")]
    public static void Crear()
    {
        int hechos = 0;
        foreach (string item in ITEMS)
        {
            string color = TEXTURAS + "/" + item + "/color.jpg";
            string normal = TEXTURAS + "/" + item + "/normal_gl.jpg";
            if (!File.Exists(color) || !File.Exists(normal))
            {
                Debug.LogWarning("RecursosRealistas: falta " + item + " (" + color + " o " + normal + ")");
                continue;
            }
            Importar(color, false);
            Importar(normal, true);
            Material m = MaterialDe(CARPETA + "/Mat_" + item + ".mat", Shader.Find("Universal Render Pipeline/Lit"));
            m.SetTexture("_BaseMap", AssetDatabase.LoadAssetAtPath<Texture2D>(color));
            m.SetTexture("_BumpMap", AssetDatabase.LoadAssetAtPath<Texture2D>(normal));
            m.SetFloat("_BumpScale", 1f);
            m.EnableKeyword("_NORMALMAP");
            m.SetColor("_BaseColor", Color.white);
            m.SetFloat("_Smoothness", 0.1f);
            PonerDetalle(m, item);
            EditorUtility.SetDirty(m);
            hechos++;
        }

        string hdr = TEXTURAS + "/cielo/cielo_2k_suelo.hdr";
        if (File.Exists(hdr))
        {
            var ti = (TextureImporter)AssetImporter.GetAtPath(hdr);
            ti.textureShape = TextureImporterShape.Texture2D;
            ti.mipmapEnabled = false;          // sin mipmaps: la costura del panorama no se ve
            ti.wrapModeU = TextureWrapMode.Repeat;
            ti.wrapModeV = TextureWrapMode.Clamp;
            ti.textureCompression = TextureImporterCompression.CompressedHQ;
            ti.SaveAndReimport();
            Material cielo = MaterialDe(CARPETA + "/Cielo.mat", Shader.Find("Skybox/Panoramic"));
            cielo.SetTexture("_MainTex", AssetDatabase.LoadAssetAtPath<Texture2D>(hdr));
            cielo.SetFloat("_Mapping", 1f);    // latitud-longitud
            cielo.SetFloat("_ImageType", 0f);  // 360 grados
            cielo.SetFloat("_Exposure", 1f);
            // El giro que pone el sol del HDRI donde esta la luz de la vista
            // realista: lo calcula comun/recursos_realistas.py (sol.json).
            string sol = TEXTURAS + "/cielo/sol.json";
            if (File.Exists(sol))
                cielo.SetFloat("_Rotation", JsonUtility.FromJson<SolDelCielo>(File.ReadAllText(sol)).giro_grados);
            else Debug.LogWarning("RecursosRealistas: falta " + sol + " (correr comun/recursos_realistas.py)");
            EditorUtility.SetDirty(cielo);
            hechos++;
        }
        else Debug.LogWarning("RecursosRealistas: falta " + hdr);

        CrearPerfil(CARPETA + "/PerfilRealista.asset");
        hechos++;
        AssetDatabase.SaveAssets();
        Debug.Log("RecursosRealistas: " + hechos + " recursos en " + CARPETA);
    }

    /// El mapa de detalle (URP/Lit, x2) que rompe el patron de lejos: lo
    /// arma y lo escala comun/recursos_realistas.py (detalle.png y
    /// detalle.json). Gris LINEAL: 0.5 deja el color igual.
    static void PonerDetalle(Material m, string item)
    {
        string ruta = TEXTURAS + "/" + item + "/detalle.png";
        string json = TEXTURAS + "/detalle.json";
        Detalle d = null;
        if (File.Exists(json))
            foreach (Detalle x in JsonUtility.FromJson<Detalles>(File.ReadAllText(json)).items)
                if (x.item == item) d = x;
        if (d == null || !File.Exists(ruta))
        {
            m.SetTexture("_DetailAlbedoMap", null);
            m.DisableKeyword("_DETAIL_MULX2");
            return;
        }
        var ti = (TextureImporter)AssetImporter.GetAtPath(ruta);
        ti.textureType = TextureImporterType.Default;
        ti.sRGBTexture = false;
        ti.wrapMode = TextureWrapMode.Repeat;
        ti.anisoLevel = 8;
        ti.filterMode = FilterMode.Trilinear;
        ti.mipmapEnabled = true;
        ti.SaveAndReimport();
        m.SetTexture("_DetailAlbedoMap", AssetDatabase.LoadAssetAtPath<Texture2D>(ruta));
        m.SetTextureScale("_DetailAlbedoMap", new Vector2(d.escala, d.escala));
        m.SetFloat("_DetailAlbedoMapScale", 1f);
        m.EnableKeyword("_DETAIL_MULX2");
    }

    static void Importar(string ruta, bool esNormal)
    {
        var ti = (TextureImporter)AssetImporter.GetAtPath(ruta);
        ti.textureType = esNormal ? TextureImporterType.NormalMap : TextureImporterType.Default;
        ti.sRGBTexture = !esNormal;
        ti.wrapMode = TextureWrapMode.Repeat;
        ti.anisoLevel = 8;
        ti.filterMode = FilterMode.Trilinear;
        ti.maxTextureSize = 1024;
        ti.mipmapEnabled = true;
        ti.SaveAndReimport();
    }

    static Material MaterialDe(string ruta, Shader shader)
    {
        Material m = AssetDatabase.LoadAssetAtPath<Material>(ruta);
        if (m == null)
        {
            m = new Material(shader);
            AssetDatabase.CreateAsset(m, ruta);
        }
        else m.shader = shader;
        return m;
    }

    /// El post-proceso de la vista realista: tonos ACES (mas contraste que
    /// el Neutral de la escena), un poco de exposicion y saturacion, bloom
    /// suave en lo que brilla y la viñeta de la escena. La tecnica sigue
    /// con el perfil de la escena: este solo se prende en la realista.
    static void CrearPerfil(string ruta)
    {
        VolumeProfile p = AssetDatabase.LoadAssetAtPath<VolumeProfile>(ruta);
        if (p == null)
        {
            p = ScriptableObject.CreateInstance<VolumeProfile>();
            AssetDatabase.CreateAsset(p, ruta);
        }
        for (int i = p.components.Count - 1; i >= 0; i--)
        {
            Object.DestroyImmediate(p.components[i], true);
            p.components.RemoveAt(i);
        }
        Tonemapping t = p.Add<Tonemapping>(true);
        t.mode.value = TonemappingMode.ACES;
        ColorAdjustments c = p.Add<ColorAdjustments>(true);
        c.postExposure.value = 0.15f;
        c.contrast.value = 4f;
        c.saturation.value = -4f;
        Bloom b = p.Add<Bloom>(true);
        b.threshold.value = 1.1f;
        b.intensity.value = 0.35f;
        b.scatter.value = 0.6f;
        Vignette v = p.Add<Vignette>(true);
        v.intensity.value = 0.22f;
        v.smoothness.value = 0.35f;
        foreach (VolumeComponent comp in p.components)
            if (!AssetDatabase.IsSubAsset(comp)) AssetDatabase.AddObjectToAsset(comp, p);
        EditorUtility.SetDirty(p);
    }
}
