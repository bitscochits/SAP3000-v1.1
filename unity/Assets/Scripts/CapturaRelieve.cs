/*
================================================================
  CapturaRelieve.cs
================================================================
  Fotos del relieve del sitio, sin tocar la app:

      LaboratorioEstructural.exe -capturarRelieve <carpeta>

  Espera a que el modelo y el relieve esten cargados, pone la vista
  realista con el suelo y el relieve, y saca cuatro fotos (dos
  isometricas opuestas, la planta y una de cerca del edificio) mas un
  registro.txt con lo que dice AjustesVista.relieveEstado y los errores
  del log. Despues cierra la app (codigo 0, o 2 si algo falto).

  Es la misma forma que CapturaSemana05 (que deja el relieve APAGADO:
  sus fotos son de antes). Mueve solo la camara y las capas.
================================================================
*/

using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using UnityEngine;

public class CapturaRelieve : MonoBehaviour
{
    const float TOPE_ESPERA_S = 90f;
    const int CALIDAD_JPG = 92;

    public string carpeta;
    private readonly List<string> registro = new List<string>();
    private int nErrores;

    [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
    static void Arrancar()
    {
        string[] args = Environment.GetCommandLineArgs();
        for (int i = 0; i < args.Length - 1; i++)
        {
            if (args[i] != "-capturarRelieve") continue;
            var go = new GameObject("CapturaRelieve");
            go.AddComponent<CapturaRelieve>().carpeta = args[i + 1];
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
        else if (texto.StartsWith("AmbienteVisor:")) registro.Add(texto);
    }

    IEnumerator Start()
    {
        Directory.CreateDirectory(carpeta);
        float tope = Time.realtimeSinceStartup + TOPE_ESPERA_S;
        VisorEstructura visor = null;
        CamaraOrbital cam = null;
        while (Time.realtimeSinceStartup < tope)
        {
            visor = visor ?? FindAnyObjectByType<VisorEstructura>();
            cam = cam ?? FindAnyObjectByType<CamaraOrbital>();
            bool relieveListo = AjustesVista.relieveEstado.StartsWith("Relieve del sitio")
                             || AjustesVista.relieveEstado.StartsWith("Sin relieve");
            if (visor != null && cam != null && visor.Modelo != null && relieveListo) break;
            yield return new WaitForSecondsRealtime(0.5f);
        }
        registro.Add("relieveEstado: " + AjustesVista.relieveEstado);
        if (visor == null || cam == null || visor.Modelo == null)
        {
            registro.Add("ERROR: no cargo el modelo o la camara antes de " + TOPE_ESPERA_S + " s");
            Escribir();
            Application.Quit(2);
            yield break;
        }
        registro.Add("edificio: " + (visor.Modelo.info != null ? visor.Modelo.info.edificio : "?"));

        AjustesVista.realista = true;
        AjustesVista.suelo = true;
        AjustesVista.relieve = true;
        EventosVisor.AvisarVistaCambio();
        yield return new WaitForSecondsRealtime(1f);

        cam.EncuadrarTodo();
        Vector3 centro = cam.centro;
        float d = cam.distancia;
        yield return Foto(cam, "relieve_1_iso_suroeste", centro, d * 2.6f, 28f, 225f);
        yield return Foto(cam, "relieve_2_iso_noreste", centro, d * 2.6f, 28f, 45f);
        yield return Foto(cam, "relieve_3_planta", centro, d * 3.0f, 89f, 0f);
        yield return Foto(cam, "relieve_4_cerca", centro, d * 1.1f, 18f, 200f);

        Escribir();
        Application.Quit(nErrores == 0 && AjustesVista.relieveEstado.StartsWith("Relieve del sitio") ? 0 : 2);
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

    void Escribir()
    {
        registro.Add("errores del log: " + nErrores);
        File.WriteAllLines(Path.Combine(carpeta, "registro.txt"), registro);
    }
}
