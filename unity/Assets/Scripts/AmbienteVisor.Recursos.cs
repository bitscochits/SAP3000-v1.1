/*
================================================================
  AmbienteVisor.Recursos.cs  --  texturas, cielo y post-proceso reales
================================================================
  La vista realista con recursos descargados (CC0, de ambientCG y Poly
  Haven; Resources/Ambiente/LICENCIAS.md) en vez de los procedurales:

    - Materiales con color + mapa normal (Resources/Ambiente/Mat_<item>):
      hormigon visto (columnas, vigas, muros), losa, pasto, tierra y
      acero. Aca se COPIAN y se les pone la repeticion, el tinte de cada
      categoria y la suavidad; la copia conserva el keyword _NORMALMAP.
    - El cielo: un HDRI de Poly Haven (Resources/Ambiente/Cielo, shader
      Skybox/Panoramic), girado para que su sol quede donde esta la luz
      del sol de la vista realista (las sombras y el cielo coinciden).
    - Un Volume global con Resources/Ambiente/PerfilRealista (tonos
      ACES, color, bloom suave), prendido SOLO en la realista: la
      tecnica sigue con el perfil de la escena.

  Los arma, una vez y en el editor, unity/Assets/Editor/
  RecursosRealistas.cs: como assets en Resources la build los incluye
  con sus variantes de shader (un 'new Material' con _NORMALMAP saldria
  plano en el exe). Si falta cualquiera, se usa lo de antes (texturas
  procedurales, cielo procedural) sin aviso de error: es solo dibujo.
================================================================
*/

using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

public partial class AmbienteVisor
{
    const string RECURSOS = "Ambiente/";
    // Cuanto del tinte de cada categoria va sobre la textura real: lo
    // justo para distinguir columnas de vigas sin pintar el hormigon.
    const float MEZCLA_TINTE = 0.3f;
    // Cuantos metros cubre una imagen de cada recurso (los de ambientCG y
    // Poly Haven son de 1 a 3 m). Las UV del suelo y de la losa vienen en
    // REPETICION_* metros: el material reescala.
    const float TILE_PASTO_M = 3f;
    const float TILE_TIERRA_M = 2.5f;
    const float TILE_LOSA_M = 2f;
    // Grass005 es un verde claro y saturado: con los tonos ACES se veia
    // fluorescente. Este tinte (a MEZCLA_TINTE) lo baja a pasto de verdad.
    static readonly Color C_PASTO_REAL = new Color(0.55f, 0.62f, 0.45f);
    // El hormigon descargado tiene el albedo de un hormigon real (Concrete006:
    // sRGB 135, 0.25 lineal); las procedurales eran casi blancas (0.88) y la
    // luz de la realista se ajusto con ellas. Con este factor queda en ~0.40,
    // el de un hormigon a la intemperie, en vez de verse negro (1.6 lo dejaba
    // lavado con la luz azul del cielo HDRI).
    const float BRILLO_HORMIGON = 1.3f;

    readonly Dictionary<string, Material> basesReales = new Dictionary<string, Material>();
    Volume volumenRealista;

    /// El material base de un item, o null si no esta.
    Material BaseReal(string item)
    {
        Material m;
        if (basesReales.TryGetValue(item, out m)) return m;
        m = Resources.Load<Material>(RECURSOS + "Mat_" + item);
        basesReales[item] = m;
        return m;
    }

    /// El item de textura de cada categoria de barra.
    static string ItemDe(string categoria)
    {
        return categoria == "metal" ? "acero" : "hormigon_visto";
    }

    /// Una copia del material real con su repeticion y tinte; null si no
    /// hay recurso (y entonces se usa NuevoMaterial con la procedural).
    Material NuevoMaterialReal(string nombre, string item, Color tinte, float suavidad, float metalico,
                               Vector2 repeticion)
    {
        Material b = BaseReal(item);
        if (b == null) return null;
        var m = new Material(b) { name = nombre };
        if (m.HasProperty("_BaseMap")) m.SetTextureScale("_BaseMap", repeticion);
        float mezcla = MEZCLA_TINTE;
        if (item == "acero")
        {
            // Metal038 es acero galvanizado (metalness 1, rugosidad media
            // 0.36 en su mapa): se ve metal, con poco del tinte de categoria.
            metalico = 0.9f;
            suavidad = 0.6f;
            mezcla = 0.2f;
        }
        Color c = Color.Lerp(Color.white, tinte, mezcla);
        if (item.StartsWith("hormigon")) c *= BRILLO_HORMIGON;
        c.a = 1f;
        m.color = c;
        FijarSiExiste(m, "_BaseColor", c);
        FijarSiExiste(m, "_Smoothness", suavidad);
        FijarSiExiste(m, "_Metallic", metalico);
        misMateriales.Add(m);
        return m;
    }

    /// El cielo HDRI, o null si no esta.
    Material CieloReal()
    {
        return Resources.Load<Material>(RECURSOS + "Cielo");
    }

    /// Prende o apaga el post-proceso de la realista.
    void AplicarVolumen(bool realista)
    {
        if (volumenRealista == null)
        {
            if (!realista) return;
            VolumeProfile perfil = Resources.Load<VolumeProfile>(RECURSOS + "PerfilRealista");
            if (perfil == null) return;
            var go = new GameObject("AmbienteVisor_PostRealista");
            go.transform.SetParent(transform, false);
            volumenRealista = go.AddComponent<Volume>();
            volumenRealista.isGlobal = true;
            volumenRealista.priority = 10f;           // sobre el volumen de la escena
            volumenRealista.sharedProfile = perfil;
        }
        volumenRealista.enabled = realista;
    }
}
