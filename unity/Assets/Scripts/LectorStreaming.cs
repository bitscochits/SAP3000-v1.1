/*
================================================================
  LectorStreaming.cs
================================================================
  Lee un archivo de StreamingAssets con UnityWebRequest, en una
  corrutina. Una sola definicion para todos los visores.

  ----------------------------------------------------------------
  POR QUE NO File.ReadAllText
  ----------------------------------------------------------------
  En Windows y en el editor StreamingAssets es una carpeta normal y
  File.ReadAllText funciona. En Android vive DENTRO del .apk
  ("jar:file://...!/assets/") y en Web es una URL ("https://..."):
  File.Exists da false y el visor diria "no encontre el archivo"
  aunque este. UnityWebRequest entiende las tres formas.

  ----------------------------------------------------------------
  USO
  ----------------------------------------------------------------
      StartCoroutine(LectorStreaming.Leer("semana04.json",
          texto => { ... JsonUtility.FromJson<...>(texto) ... },
          error => { Aviso = error; }));

  Exactamente uno de los dos callbacks se llama, una vez. 'nombre' es
  relativo a StreamingAssets; una ruta absoluta o una URL se usan tal
  cual.
================================================================
*/

using System;
using System.Collections;
using System.IO;
using UnityEngine;
using UnityEngine.Networking;

public static class LectorStreaming
{
    /// La URL con que se pide el archivo. Sin esquema ('C:/...' en
    /// Windows) se arma un file:/// con System.Uri, que escapa los
    /// espacios de la ruta ("Metodos computacionales"): pegar "file://"
    /// a mano deja la URL con espacios.
    public static string UrlDe(string nombre)
    {
        // Una URL se usa tal cual. Va ANTES de Path.Combine: en Windows
        // "http://..." no es una ruta con raiz, y Combine la pegaria
        // detras de la carpeta de StreamingAssets.
        if (!string.IsNullOrEmpty(nombre) && nombre.Contains("://")) return nombre;
        string ruta = Path.Combine(Application.streamingAssetsPath, nombre ?? "");
        if (ruta.Contains("://")) return ruta;
        try
        {
            return new Uri(Path.GetFullPath(ruta)).AbsoluteUri;
        }
        catch (Exception)
        {
            return "file://" + ruta;
        }
    }

    // ------------------------------------------------------------
    // ARCHIVOS QUE SE ABREN CON OTRO PROGRAMA (el Excel)
    // ------------------------------------------------------------

    /// El nombre fijo del Excel en StreamingAssets. Lo copia ahi
    /// 'comun/lanzar_unity.py sincronizar <ed>' desde
    /// data/excel/<ed>_resultados.xlsx.
    public const string EXCEL_RESULTADOS = "resultados.xlsx";

    /// Donde esta el Excel de resultados en ESTE equipo, o null si no hay.
    /// Primero StreamingAssets/resultados.xlsx (el de la app y el del
    /// editor tras sincronizar). En el editor, si falta, el versionado
    /// data/excel/<edificio>_resultados.xlsx del repo (Assets esta en
    /// unity/Assets, asi que la raiz del repo es dos carpetas arriba).
    /// En Android y Web StreamingAssets no es una carpeta: devuelve null.
    public static string RutaExcelResultados(string edificio)
    {
        string enStreaming = Path.Combine(Application.streamingAssetsPath, EXCEL_RESULTADOS);
        if (!enStreaming.Contains("://") && File.Exists(enStreaming)) return enStreaming;
        if (Application.isEditor && !string.IsNullOrEmpty(edificio))
        {
            string repo = Path.GetFullPath(Path.Combine(Application.dataPath, "..", ".."));
            string versionado = Path.Combine(repo, "data", "excel", edificio + "_resultados.xlsx");
            if (File.Exists(versionado)) return versionado;
        }
        return null;
    }

    /// Abre un archivo local con el programa del sistema (Excel para un
    /// .xlsx). Devuelve false y el motivo si no existe o no se puede.
    public static bool AbrirArchivo(string ruta, out string error)
    {
        error = "";
        if (string.IsNullOrEmpty(ruta) || !File.Exists(ruta))
        {
            error = "No existe el archivo: " + (ruta ?? "(sin ruta)");
            return false;
        }
        try
        {
            Application.OpenURL(new Uri(Path.GetFullPath(ruta)).AbsoluteUri);
            return true;
        }
        catch (Exception ex)
        {
            error = "No pude abrir " + ruta + ": " + ex.Message;
            return false;
        }
    }

    /// Lee el archivo completo como texto UTF-8.
    public static IEnumerator Leer(string nombre, Action<string> ok, Action<string> error)
    {
        string url = UrlDe(nombre);
        using (UnityWebRequest req = UnityWebRequest.Get(url))
        {
            yield return req.SendWebRequest();

            if (req.result == UnityWebRequest.Result.Success)
            {
                string texto = req.downloadHandler.text;
                if (ok != null) ok(texto);
            }
            else
            {
                // El mensaje dice QUE archivo y POR QUE: "Cannot connect
                // to destination host" en un file:// quiere decir que no
                // existe.
                string msg = $"No pude leer {nombre} ({url}): {req.error}";
                if (error != null) error(msg);
                else Debug.LogError("LectorStreaming: " + msg);
            }
        }
    }
}
