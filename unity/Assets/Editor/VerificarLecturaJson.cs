/*
================================================================
  VerificarLecturaJson.cs   (Editor)
================================================================
  Le hace leer a Unity DE VERDAD, con JsonUtility y con la clase raiz
  que usa cada lector, los cinco JSON del visor que hay en
  StreamingAssets, y deja lo que leyo -- reserializado con
  JsonUtility.ToJson -- en build/verificacion_jsonutility.json:

      modelo.json        ModeloEstructural    (VisorEstructura)
      resultados.json    Resultados           (VisorResultados)
      carga_movil.json   AnexoCargaMovil      (VisorCargaMovil)
      persona.json       InfluenciasPersona   (VisorPersona)
      relieve.json       RelieveJson          (AmbienteVisor)

  verificacion/unity.py (bloque jsonutility) compara cada valor del
  reporte contra el archivo que escribio Python: un float calza si su
  float32 es el mismo (JsonUtility.ToJson escribe el float de ida y
  vuelta), un entero o un texto si es igual.

  POR QUE HACE FALTA: JsonUtility no avisa cuando una clave no calza con
  un campo; lo deja en su valor por defecto y sigue. El bloque contratos
  compara NOMBRES leyendo el C# como texto; solo esto prueba que el
  parser de Unity llena cada campo con el numero correcto.

  Uso, sin abrir el editor (lo hace verificacion/unity.py jsonutility):

      Unity.exe -batchmode -quit -nographics -projectPath <unity>
                -executeMethod VerificarLecturaJson.Verificar
                -logFile <log>

  Tambien desde el menu Laboratorio / Verificar lectura de los JSON; en
  ese caso no cierra el editor. La raiz del proyecto (donde va build/) se
  busca por su marca, setup.ps1 y sap.py (LectorStreaming.RaizDelRepo).
================================================================
*/

using System;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using UnityEditor;
using UnityEngine;

public static class VerificarLecturaJson
{
    /// El reporte, en <raiz>/build/.
    public const string SALIDA = "verificacion_jsonutility.json";

    [MenuItem("Laboratorio/Verificar lectura de los JSON")]
    public static void Verificar()
    {
        var errores = new List<string>();
        string raiz = LectorStreaming.RaizDelRepo();
        if (raiz == null)
        {
            raiz = Directory.GetParent(Directory.GetParent(Application.dataPath).FullName).FullName;
            errores.Add("no aparecio la raiz del proyecto (setup.ps1 y sap.py) subiendo desde "
                        + Application.dataPath + ": el reporte queda en " + raiz);
        }
        string salida = Path.Combine(raiz, "build", SALIDA);
        string carpeta = Path.Combine(Application.dataPath, "StreamingAssets");

        var partes = new List<string>
        {
            Leer<ModeloEstructural>("modelo", VisorEstructura.ARCHIVO, carpeta, errores, m =>
                m.info == null ? "sin info"
                : m.nodos == null || m.nodos.Count == 0 ? "sin nodos"
                : m.elementos == null || m.elementos.Count == 0 ? "sin elementos" : null),
            Leer<Resultados>("resultados", VisorResultados.ARCHIVO, carpeta, errores, r =>
                r.info == null ? "sin info"
                : r.casos == null || r.casos.Count == 0 ? "sin casos"
                : r.elementos == null || r.elementos.Count == 0 ? "sin elementos"
                : r.familias == null || r.familias.Count == 0 ? "sin familias"
                : r.superposicion == null || r.superposicion.estados == null || r.superposicion.estados.Count == 0
                    ? "sin el bloque superposicion (estados)"
                : r.cargas_y_armadura == null || r.cargas_y_armadura.info == null
                  || r.cargas_y_armadura.cargas == null || r.cargas_y_armadura.cargas.Count == 0
                    ? "sin el bloque cargas_y_armadura (info, cargas)" : null),
            Leer<AnexoCargaMovil>("carga_movil", VisorCargaMovil.ARCHIVO, carpeta, errores, c =>
                c.info == null ? "sin info"
                : c.recorrido == null ? "sin recorrido"
                : c.posiciones == null || c.posiciones.Count == 0 ? "sin posiciones" : null),
            Leer<InfluenciasPersona>("persona", VisorPersona.ARCHIVO, carpeta, errores, p =>
                p.info == null ? "sin info"
                : p.casos == null || p.casos.Length == 0 ? "sin casos"
                : p.receptores == null || p.receptores.Length == 0 ? "sin receptores" : null),
            Leer<RelieveJson>("relieve", AmbienteVisor.ARCHIVO, carpeta, errores, t =>
                t.info == null ? "sin info"
                : t.z == null || t.z.Length != t.nx * t.ny ? "z no trae nx x ny cotas" : null),
        };

        var sb = new StringBuilder();
        sb.Append("{\n\"generado_por\": \"unity/Assets/Editor/VerificarLecturaJson.cs\",\n");
        sb.Append("\"unity\": ").Append(Texto(Application.unityVersion)).Append(",\n");
        sb.Append("\"streaming_assets\": ").Append(Texto(carpeta)).Append(",\n");
        sb.Append("\"archivos\": {\n").Append(string.Join(",\n", partes.ToArray())).Append("\n},\n");
        var textos = new List<string>();
        foreach (string e in errores) textos.Add(Texto(e));
        sb.Append("\"errores\": [").Append(string.Join(", ", textos.ToArray())).Append("]\n}\n");

        Directory.CreateDirectory(Path.GetDirectoryName(salida));
        File.WriteAllText(salida, sb.ToString(), new UTF8Encoding(false));

        if (errores.Count > 0)
            foreach (string e in errores) Debug.LogError("VERIFICACION JSONUTILITY: " + e);
        else
            Debug.Log("VERIFICACION JSONUTILITY OK -> " + salida);

        // Solo en batch: desde el menu, Exit cerraria el editor.
        if (Application.isBatchMode) EditorApplication.Exit(errores.Count > 0 ? 1 : 0);
    }

    /// Lee 'archivo' con JsonUtility como un T y devuelve su entrada del
    /// reporte: "clave": {archivo, clase, bytes, md5, leido}. 'leido' es el
    /// objeto reserializado, o null si no se pudo leer (y el motivo va a
    /// errores). 'forma' dice que falta en lo leido, o null.
    static string Leer<T>(string clave, string archivo, string carpeta, List<string> errores,
                          Func<T, string> forma) where T : class
    {
        string ruta = Path.Combine(carpeta, archivo);
        string leido = "null", md5 = "";
        long bytes = 0;
        if (!File.Exists(ruta))
        {
            errores.Add(clave + ": no existe " + ruta);
        }
        else
        {
            byte[] b = File.ReadAllBytes(ruta);
            bytes = b.Length;
            md5 = Md5(b);
            T obj = null;
            try
            {
                obj = JsonUtility.FromJson<T>(File.ReadAllText(ruta));
            }
            catch (Exception ex)
            {
                errores.Add(clave + ": JsonUtility no lo pudo leer como " + typeof(T).Name + ": " + ex.Message);
            }
            if (obj != null)
            {
                string motivo = forma(obj);
                if (motivo != null) errores.Add(clave + " (" + typeof(T).Name + "): " + motivo);
                leido = JsonUtility.ToJson(obj);
            }
            else if (errores.Count == 0 || !errores[errores.Count - 1].StartsWith(clave + ":"))
            {
                errores.Add(clave + ": JsonUtility devolvio null");
            }
        }
        return Texto(clave) + ": {\"archivo\": " + Texto(archivo) + ", \"clase\": " + Texto(typeof(T).Name)
               + ", \"bytes\": " + bytes + ", \"md5\": " + Texto(md5) + ", \"leido\": " + leido + "}";
    }

    static string Md5(byte[] b)
    {
        using (MD5 h = MD5.Create())
        {
            var sb = new StringBuilder(32);
            foreach (byte x in h.ComputeHash(b)) sb.Append(x.ToString("x2"));
            return sb.ToString();
        }
    }

    /// Un texto como literal JSON (comillas, barras y controles escapados).
    static string Texto(string s)
    {
        if (s == null) return "null";
        var sb = new StringBuilder(s.Length + 2);
        sb.Append('"');
        foreach (char c in s)
        {
            switch (c)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                default:
                    if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                    else sb.Append(c);
                    break;
            }
        }
        sb.Append('"');
        return sb.ToString();
    }
}
