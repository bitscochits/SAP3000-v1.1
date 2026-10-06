/*
================================================================
  CapturaPersona.cs
================================================================
  Fotos y registro de la pestana Persona con su deformada, sin tocar la
  app:

      LaboratorioEstructural.exe -capturarPersona <carpeta>

  Espera el modelo y influencias.json, pone al caminante (100 kN) en el
  primer piso, en la region tributaria mas grande de una viga, saca
  fotos, lo hace caminar 3 m, sube un piso y vuelve a sacar. En registro.txt deja lo
  que Unity SUMO (VisorPersona.Captura_Registro, float en G9) para que
  python semana05_lab/influencias_persona.py <ed> --verificar
  --registro <carpeta>/registro.txt lo cruce con OpenSees. Cierra con
  0, o con 2 si falto algo o hubo errores en el log.
================================================================
*/

using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEngine;

public class CapturaPersona : MonoBehaviour
{
    const float TOPE_ESPERA_S = 90f;
    const int CALIDAD_JPG = 92;
    const float P_KN = 100f;

    public string carpeta;
    readonly List<string> registro = new List<string>();
    int nErrores;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Arrancar()
    {
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
        {
            if (args[i] != "-capturarPersona") continue;
            new GameObject("CapturaPersona").AddComponent<CapturaPersona>().carpeta = args[i + 1];
            return;
        }
    }

    void OnEnable() { Application.logMessageReceived += AlLog; }
    void OnDisable() { Application.logMessageReceived -= AlLog; }

    void AlLog(string texto, string pila, LogType tipo)
    {
        if (tipo == LogType.Error || tipo == LogType.Exception || tipo == LogType.Assert)
        {
            nErrores++;
            registro.Add("ERROR del log: " + texto);
        }
    }

    IEnumerator Start()
    {
        Directory.CreateDirectory(carpeta);
        float tope = Time.realtimeSinceStartup + TOPE_ESPERA_S;
        VisorEstructura visor = null;
        VisorPersona persona = null;
        CamaraOrbital cam = null;
        while (Time.realtimeSinceStartup < tope)
        {
            visor = visor ?? FindAnyObjectByType<VisorEstructura>();
            persona = persona ?? FindAnyObjectByType<VisorPersona>();
            cam = cam ?? FindAnyObjectByType<CamaraOrbital>();
            if (visor != null && persona != null && cam != null && visor.Modelo != null) break;
            yield return new WaitForSecondsRealtime(0.5f);
        }
        if (visor == null || persona == null || cam == null || visor.Modelo == null)
        {
            Fin("ERROR: no cargo el modelo, la persona o la camara antes de " + TOPE_ESPERA_S + " s", 2);
            yield break;
        }
        AjustesVista.realista = true;
        AjustesVista.suelo = true;
        AjustesVista.relieve = false;
        EventosVisor.AvisarVistaCambio();
        yield return new WaitForSecondsRealtime(1f);

        if (!persona.Captura_Poner(1, P_KN))
        {
            Fin("ERROR: no se pudo poner la persona en el piso 2", 2);
            yield break;
        }
        while (!persona.Captura_InfluenciasListas && Time.realtimeSinceStartup < tope)
            yield return new WaitForSecondsRealtime(0.25f);
        registro.Add("influencias: " + persona.Captura_Estado);
        if (!persona.Captura_InfluenciasListas)
        {
            Fin("ERROR: no se leyo influencias.json", 2);
            yield break;
        }
        persona.Captura_Poner(1, P_KN);           // de nuevo, ya con los casos leidos
        yield return new WaitForSecondsRealtime(1f);
        registro.Add(persona.Captura_Registro());
        VisorQA qa = FindAnyObjectByType<VisorQA>();
        if (qa != null) qa.ElegirPestana("Persona");

        cam.EncuadrarTodo();
        float d = cam.distancia;
        Vector3 donde = persona.Captura_Donde;
        // De costado a la viga cargada (y un poco en diagonal): ahi se ve su flecha.
        float lado = persona.Captura_RumboViga + 90f + 15f;
        yield return Foto(cam, "persona_1_edificio", cam.centro, d * 1.2f, 25f, 215f);
        yield return Foto(cam, "persona_2_cerca", donde, 14f, 12f, lado);

        persona.Captura_Caminar(new Vector2(3f, 0f));
        yield return new WaitForSecondsRealtime(1f);
        registro.Add(persona.Captura_Registro());
        yield return Foto(cam, "persona_3_camino", persona.Captura_Donde, 14f, 12f, persona.Captura_RumboViga + 105f);

        // Sube un piso (el ascensor tarda 0.7 s) y vuelve a sumar alla.
        bool subio = persona.Captura_CambiarPiso(+1);
        yield return new WaitForSecondsRealtime(1.5f);
        registro.Add("piso: " + (subio ? "subio a " : "NO subio, sigue en ") + persona.Captura_Piso);
        registro.Add(persona.Captura_Registro());
        yield return Foto(cam, "persona_4_otro_piso", persona.Captura_Donde, 16f, 18f, persona.Captura_RumboViga + 105f);

        // Desde la cabina: la camara la maneja la persona, asi que la foto
        // va sin mover la orbital. Camina 2 m para ver el paso.
        persona.Captura_Cabina(true);
        persona.Captura_Caminar(new Vector2(0f, 2f));
        persona.Captura_Mirar(persona.Captura_RumboViga + 180f, 15f);   // a lo largo de la viga, hacia adentro
        yield return new WaitForSecondsRealtime(1.5f);
        registro.Add("cabina: " + (persona.Captura_EnCabina ? "adentro" : "NO entro") + ", camara en "
                     + Camera.main.transform.position.ToString("F2"));
        yield return FotoTalCual("persona_5_cabina");
        persona.Captura_Cabina(false);
        yield return new WaitForSecondsRealtime(0.5f);

        bool ok = nErrores == 0 && !registro.Exists(l => l.Contains("sin deformada"));
        Fin(null, ok ? 0 : 2);
    }

    IEnumerator Foto(CamaraOrbital cam, string nombre, Vector3 centro, float distancia, float pitch, float yaw)
    {
        const BindingFlags B = BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Instance;
        typeof(CamaraOrbital).GetField("pitch", B).SetValue(cam, pitch);
        typeof(CamaraOrbital).GetField("yaw", B).SetValue(cam, yaw);
        cam.centro = centro;
        cam.distancia = distancia;
        yield return new WaitForSecondsRealtime(1.5f);
        yield return new WaitForEndOfFrame();
        Texture2D tex = ScreenCapture.CaptureScreenshotAsTexture();
        try { File.WriteAllBytes(Path.Combine(carpeta, nombre + ".jpg"), tex.EncodeToJPG(CALIDAD_JPG)); }
        finally { Destroy(tex); }
        registro.Add(string.Format(System.Globalization.CultureInfo.InvariantCulture,
            "foto {0}: distancia {1:F1} m, pitch {2:F0}, yaw {3:F0}", nombre, distancia, pitch, yaw));
    }

    IEnumerator FotoTalCual(string nombre)
    {
        yield return new WaitForEndOfFrame();
        Texture2D tex = ScreenCapture.CaptureScreenshotAsTexture();
        try { File.WriteAllBytes(Path.Combine(carpeta, nombre + ".jpg"), tex.EncodeToJPG(CALIDAD_JPG)); }
        finally { Destroy(tex); }
        registro.Add("foto " + nombre + ": la camara de la cabina");
    }

    void Fin(string motivo, int codigo)
    {
        if (motivo != null) registro.Add(motivo);
        registro.Add("errores del log: " + nErrores);
        File.WriteAllLines(Path.Combine(carpeta, "registro.txt"), registro);
        Application.Quit(codigo);
    }
}
