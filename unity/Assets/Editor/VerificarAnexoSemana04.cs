/*
================================================================
  VerificarAnexoSemana04.cs   (Editor)
================================================================
  Le hace leer semana04.json a Unity DE VERDAD, con JsonUtility, y
  deja por escrito lo que leyo en build/verificacion_unity_semana04.json,
  para que semana04/verificar_unity_semana04.py lo compare campo a
  campo contra lo que escribio Python.

  POR QUE HACE FALTA: JsonUtility no avisa cuando una clave no calza
  con un campo; lo deja en cero y sigue. semana04/test_contrato_semana04.py
  compara nombres leyendo el C# con una regex, pero solo esto prueba que
  el parser de Unity llena cada campo con el numero correcto.

  Uso, sin abrir el editor (lo hace verificar_unity_semana04.py):

      Unity.exe -batchmode -quit -nographics -projectPath <unity>
                -executeMethod VerificarAnexoSemana04.Verificar
                -logFile <log>

  Tambien desde el menu Laboratorio / Verificar anexo Semana 4; en ese
  caso no cierra el editor.
================================================================
*/

using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class VerificarAnexoSemana04
{
    [System.Serializable]
    public class ReporteUnityS4
    {
        public string edificio;
        public string caso_por_defecto;
        public int columna_demo;
        public int muro_demo;
        public int n_casos;
        public int n_elementos;
        public int n_familias;
        public string[] nombres_casos;
        public int n_desplazamientos_caso_defecto;
        public int n_esfuerzos_caso_defecto;
        public int n_demandas_caso_defecto;
        public DespNodo primer_desplazamiento;
        public EsfuerzosS4 esfuerzos_columna_demo;
        public DemandaS4 demanda_columna_demo;
        public DemandaS4 demanda_muro_demo;
        public FamiliaPM familia_columna_demo;
        public ElementoS4 elemento_columna_demo;
        public ElementoS4 elemento_muro_demo;
        public int esfuerzos_revisados;
        public string[] errores;
    }

    [MenuItem("Laboratorio/Verificar anexo Semana 4")]
    public static void Verificar()
    {
        string ruta = Path.Combine(Application.dataPath, "StreamingAssets", "semana04.json");
        string raiz = Directory.GetParent(Application.dataPath).Parent.FullName;
        string salida = Path.Combine(raiz, "build", "verificacion_unity_semana04.json");
        var errores = new List<string>();
        var r = new ReporteUnityS4();

        AnexoSemana04 a = null;
        if (!File.Exists(ruta))
            errores.Add("no existe " + ruta);
        else
            a = JsonUtility.FromJson<AnexoSemana04>(File.ReadAllText(ruta));

        if (a == null || a.info == null || a.casos == null || a.elementos == null || a.familias == null)
        {
            errores.Add("JsonUtility devolvio un anexo incompleto (info, casos, elementos o familias)");
            Terminar(r, errores, salida);
            return;
        }

        r.edificio = a.info.edificio;
        r.caso_por_defecto = a.info.caso_por_defecto;
        r.columna_demo = a.info.columna_demo;
        r.muro_demo = a.info.muro_demo;
        r.n_casos = a.casos.Count;
        r.n_elementos = a.elementos.Count;
        r.n_familias = a.familias.Count;
        r.nombres_casos = a.casos.ConvertAll(c => c.nombre).ToArray();

        CasoS4 def = a.casos.Find(c => c.nombre == a.info.caso_por_defecto);
        if (def == null)
        {
            errores.Add("el caso por defecto '" + a.info.caso_por_defecto + "' no esta entre los casos");
            def = a.casos.Count > 0 ? a.casos[0] : null;
        }
        if (def != null && def.desplazamientos != null && def.esfuerzos != null && def.demandas != null)
        {
            r.n_desplazamientos_caso_defecto = def.desplazamientos.Count;
            r.n_esfuerzos_caso_defecto = def.esfuerzos.Count;
            r.n_demandas_caso_defecto = def.demandas.Count;
            r.primer_desplazamiento = def.desplazamientos.Count > 0 ? def.desplazamientos[0] : null;
            r.esfuerzos_columna_demo = def.esfuerzos.Find(s => s.id == a.info.columna_demo);
            r.demanda_columna_demo = def.demandas.Find(d => d.id == a.info.columna_demo);
            r.demanda_muro_demo = def.demandas.Find(d => d.id == a.info.muro_demo);
        }
        else
        {
            errores.Add("el caso por defecto no trae desplazamientos, esfuerzos o demandas");
        }

        r.elemento_columna_demo = a.elementos.Find(e => e.id == a.info.columna_demo);
        if (r.elemento_columna_demo != null && r.elemento_columna_demo.familia >= 0
            && r.elemento_columna_demo.familia < a.familias.Count)
            r.familia_columna_demo = a.familias[r.elemento_columna_demo.familia];

        // En la columna momento_en_el_plano es "", el mismo valor que deja
        // JsonUtility cuando la clave no calza: solo un muro lo prueba.
        r.elemento_muro_demo = a.elementos.Find(e => e.id == a.info.muro_demo);
        if (r.elemento_muro_demo == null || string.IsNullOrEmpty(r.elemento_muro_demo.momento_en_el_plano))
            errores.Add("el muro_demo no trae momento_en_el_plano: la clave no calzo");

        // Forma de TODO el anexo, no solo de los demo.
        var ids = new HashSet<int>();
        foreach (ElementoS4 e in a.elementos) ids.Add(e.id);
        int revisados = 0;
        foreach (CasoS4 c in a.casos)
        {
            if (c.esfuerzos == null) { errores.Add(c.nombre + ": sin esfuerzos"); continue; }
            foreach (EsfuerzosS4 s in c.esfuerzos)
            {
                revisados++;
                if (s.f == null || s.f.Length != 12)
                    Anotar(errores, $"{c.nombre} elem {s.id}: f no trae 12 valores");
                int n = Largo(s.x);
                if (n < 2 || Largo(s.N) != n || Largo(s.Vy) != n || Largo(s.Vz) != n
                    || Largo(s.T) != n || Largo(s.My) != n || Largo(s.Mz) != n)
                    Anotar(errores, $"{c.nombre} elem {s.id}: estaciones de distinto largo");
                if (Largo(s.w) != 3)
                    Anotar(errores, $"{c.nombre} elem {s.id}: w no trae 3 valores");
            }
            if (c.demandas != null)
                foreach (DemandaS4 d in c.demandas)
                    if (d.familia < 0 || d.familia >= a.familias.Count || !ids.Contains(d.id))
                        Anotar(errores, $"{c.nombre} demanda {d.id}: familia o id invalido");
        }
        foreach (FamiliaPM f in a.familias)
        {
            int n = Largo(f.P);
            if (n < 3 || Largo(f.Mn) != n || Largo(f.Mmax) != n || f.de == null || f.de.Length != n)
                Anotar(errores, $"familia {f.indice}: P, Mn, Mmax y de de distinto largo");
        }

        // Un campo que JsonUtility dejo en su valor por defecto delata una
        // clave que no calzo: E, A o el tag vacios no son posibles.
        ElementoS4 ec = r.elemento_columna_demo;
        if (ec == null)
            errores.Add("no encontre el elemento columna_demo en el anexo");
        else if (ec.E_kPa <= 0f || ec.A <= 0f || string.IsNullOrEmpty(ec.tag_opensees)
                 || ec.restr_n1 == null || ec.restr_n1.Length != 6)
            errores.Add("el elemento columna_demo trae E, A, tag o restricciones vacios: una clave no calzo");

        r.esfuerzos_revisados = revisados;
        Terminar(r, errores, salida);
    }

    static int Largo(float[] v) { return v == null ? -1 : v.Length; }

    static void Anotar(List<string> errores, string texto)
    {
        if (errores.Count < 50) errores.Add(texto);
    }

    static void Terminar(ReporteUnityS4 r, List<string> errores, string salida)
    {
        r.errores = errores.ToArray();
        Directory.CreateDirectory(Path.GetDirectoryName(salida));
        File.WriteAllText(salida, JsonUtility.ToJson(r, true));

        if (errores.Count > 0)
            foreach (string e in errores) Debug.LogError("VERIFICACION ANEXO S4: " + e);
        else
            Debug.Log("VERIFICACION ANEXO S4 OK -> " + salida);

        // Solo en batch: desde el menu, Exit cerraria el editor.
        if (Application.isBatchMode) EditorApplication.Exit(errores.Count > 0 ? 1 : 0);
    }
}
