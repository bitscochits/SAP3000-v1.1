/*
================================================================
  ConstruirApp.cs   (Editor)
================================================================
  Compila el visor como aplicacion, para que se pueda abrir sin el
  editor de Unity. Tres destinos, un solo camino de compilacion:

    Construir()          Windows   build/LaboratorioEstructural.exe
    ConstruirWeb()       Web       build/web/index.html
    ConstruirAndroid()   Android   build/android/LaboratorioEstructural.apk

  Uso desde la terminal (lo hace comun/lanzar_unity.py, con Unity
  CERRADO; un batch con el editor abierto sale con error):

      python comun/lanzar_unity.py build --forzar     (Windows)
      python comun/lanzar_unity.py web                (Web)
      python comun/lanzar_unity.py android            (Android)

  que corren, por ejemplo:

      Unity.exe -batchmode -quit -nographics -projectPath <ruta> \
                -buildTarget WebGL -executeMethod ConstruirApp.ConstruirWeb

  o desde el editor abierto: menu  Laboratorio / Construir ...

  IMPORTANTE: los JSON van en StreamingAssets, que Unity copia TAL
  CUAL dentro de la build. Por eso la app lee el mismo archivo que
  genero Python y no una copia embebida: si se regenera el modelo,
  basta con volver a copiarlo ('lanzar_unity.py sincronizar <ed>') y
  la app de Windows o la Web ya lo muestran, sin recompilar. En
  Android StreamingAssets queda DENTRO del .apk: ahi si hay que
  recompilar.

  ----------------------------------------------------------------
  POR QUE ANDROID SOLO AVISA
  ----------------------------------------------------------------
  Este equipo no tiene el modulo "Android Build Support" (Pedro:
  movil es la ultima prioridad y no se instala Android). El metodo
  queda escrito y probado en compilacion para que el dia que se
  instale el modulo baste con correrlo; mientras tanto sale con un
  mensaje que dice que falta y como se instala, sin tocar nada.
================================================================
*/

using System.IO;
using UnityEditor;
using UnityEditor.Build;
using UnityEditor.Build.Reporting;
using UnityEngine;

public static class ConstruirApp
{
    const string ESCENA = "Assets/Scenes/SampleScene.unity";
    const string NOMBRE = "LaboratorioEstructural";

    // El id de la plantilla ('com.UnityTechnologies.com.unity.template.
    // urpblank') choca con cualquier otra app hecha con la misma
    // plantilla instalada en el telefono: Android la reemplazaria.
    const string ID_ANDROID = "cl.uandes.grupo7.laboratorio";

    // La version del editor que declara el proyecto, para el mensaje de
    // como instalar un modulo (tiene que ser el de ESA version).
    const string VERSION_EDITOR = "6000.5.10f1";

    // Shaders que el visor pide por nombre con Shader.Find(). Hay que
    // declararlos como "always included" o la build los ELIMINA.
    static readonly string[] SHADERS_NECESARIOS = {
        "Universal Render Pipeline/Lit",
        "Universal Render Pipeline/Unlit",
        "Sprites/Default",          // lo usa el TextMesh de los IDs
    };

    // ============================================================
    // LOS TRES DESTINOS
    // ============================================================

    /// Windows. El nombre NO cambia: lanzar_unity.py llama
    /// 'ConstruirApp.Construir' desde antes de que hubiera otros.
    [MenuItem("Laboratorio/Construir app standalone")]
    public static void Construir()
    {
        if (!Soportado(BuildTarget.StandaloneWindows64, "Windows Build Support (IL2CPP o Mono)"))
            return;
        Preparar();
        Compilar(BuildTarget.StandaloneWindows64, Path.Combine("build", NOMBRE + ".exe"));
    }

    /// Web (WebGL). Se abre desde el navegador del telefono sirviendo
    /// build/web con cualquier servidor estatico, por ejemplo:
    ///     cd build\web
    ///     ..\..\.venv\Scripts\python.exe -m http.server 8080 --bind 0.0.0.0
    [MenuItem("Laboratorio/Construir Web")]
    public static void ConstruirWeb()
    {
        if (!Soportado(BuildTarget.WebGL, "Web Build Support"))
            return;
        Preparar();

        // POR QUE Disabled: el proyecto venia con Brotli y sin
        // "Decompression Fallback". Chrome y Firefox solo descomprimen
        // Brotli por HTTPS; servido por HTTP en la red local (que es
        // como se prueba en el telefono) la pagina se queda cargando sin
        // decir por que. Sin compresion pesa mas, pero carga en
        // cualquier servidor. Se fija por codigo para que el ajuste
        // quede a la vista en el diff de ProjectSettings y no dependa de
        // que alguien lo haya tocado a mano en Player Settings.
        PlayerSettings.WebGL.compressionFormat = WebGLCompressionFormat.Disabled;

        Compilar(BuildTarget.WebGL, Path.Combine("build", "web"));
    }

    /// Android (APK). Sin el modulo instalado solo avisa y sale.
    [MenuItem("Laboratorio/Construir Android (APK)")]
    public static void ConstruirAndroid()
    {
        // El chequeo va ANTES de tocar la escena o los PlayerSettings:
        // si falta el modulo no se modifica nada del proyecto.
        if (!Soportado(BuildTarget.Android, "Android Build Support (con OpenJDK y Android SDK & NDK Tools)"))
            return;
        Preparar();

        // Lo que la plantilla dejaba mal o implicito, fijado por codigo
        // (reproducible y visible en el diff de ProjectSettings.asset).
        // IL2CPP + ARM64 es lo que Google Play exige y lo que el proyecto
        // ya tenia; se repite aca para que no dependa de eso.
        var nt = NamedBuildTarget.Android;
        PlayerSettings.SetApplicationIdentifier(nt, ID_ANDROID);
        PlayerSettings.SetScriptingBackend(nt, ScriptingImplementation.IL2CPP);
        PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
        // El panel y la vista del edificio estan pensados en horizontal;
        // en vertical el panel tapa casi todo el modelo.
        PlayerSettings.defaultInterfaceOrientation = UIOrientation.LandscapeLeft;
        // Un .apk se instala directo (adb install o copiandolo); un .aab
        // solo sirve para subirlo a Google Play.
        EditorUserBuildSettings.buildAppBundle = false;

        Compilar(BuildTarget.Android,
                 Path.Combine("build", "android", NOMBRE + ".apk"));
    }

    // ============================================================
    // EL CAMINO COMUN
    // ============================================================

    /// Lo que toda build necesita antes de compilar.
    static void Preparar()
    {
        // La escena tiene que estar armada antes de compilarla: si el
        // Visor no tiene sus componentes, la build sale vacia y el
        // error recien se ve al ejecutarla.
        ConfigurarEscena.Configurar();

        AsegurarShadersIncluidos();
    }

    /// true si el editor tiene el modulo del destino. Si no, lo dice
    /// (dialogo en el editor, error en el log en batch) y, en batch,
    /// sale con 1: sin eso Unity terminaria con 0 y el lanzador creeria
    /// que compilo.
    ///
    /// No se instala nada desde aca: instalar un modulo baja gigas y
    /// pide permisos de administrador; lo decide una persona.
    static bool Soportado(BuildTarget destino, string modulo)
    {
        BuildTargetGroup grupo = BuildPipeline.GetBuildTargetGroup(destino);
        if (BuildPipeline.IsBuildTargetSupported(grupo, destino))
            return true;

        string mensaje =
            $"Este editor de Unity no tiene el modulo '{modulo}', "
            + $"asi que no se puede compilar para {destino}. No se modifico nada del proyecto.\n\n"
            + $"Para instalarlo (baja varios GB y pide permisos): Unity Hub > Installs > "
            + $"{VERSION_EDITOR} > Add modules > {modulo}. Despues cerrar y volver a abrir Unity.";

        // 'BUILD FALLO' es la clave que busca lanzar_unity._errores_del_log.
        Debug.LogError("BUILD FALLO: falta un modulo. " + mensaje);
        if (Application.isBatchMode)
            EditorApplication.Exit(1);
        else
            EditorUtility.DisplayDialog("Falta un modulo de Unity", mensaje, "Entendido");
        return false;
    }

    /// Compila la escena para 'destino' en '<raiz del repo>/<rutaRelativa>'.
    /// Para Windows y Android la ruta es el ejecutable; para Web, la
    /// carpeta donde queda index.html.
    static void Compilar(BuildTarget destino, string rutaRelativa)
    {
        string salida = Path.Combine(RaizDelRepo(), rutaRelativa);
        // Windows y Android reciben un archivo: se crea su carpeta. Web
        // recibe la carpeta misma, y Unity la llena.
        string carpeta = destino == BuildTarget.WebGL ? salida : Path.GetDirectoryName(salida);
        Directory.CreateDirectory(carpeta);

        // La app habla con el servidor de Python por HTTP simple: localhost
        // (M1, sliders de superposicion) o la IP del PC en la red local
        // (celular). ProjectSettings venia con "Not allowed", que en el
        // player corta esas peticiones con "Insecure connection not allowed";
        // el editor no lo aplica, por eso en Play funcionaba. Un servidor de
        // laboratorio en el propio PC no tiene HTTPS. Se fija aca, en el
        // camino comun, para que ninguna build salga sin esto.
        PlayerSettings.insecureHttpOption = InsecureHttpOption.AlwaysAllowed;

        var opciones = new BuildPlayerOptions
        {
            scenes = new[] { ESCENA },
            locationPathName = salida,
            target = destino,
            options = BuildOptions.None,
        };

        BuildReport reporte = BuildPipeline.BuildPlayer(opciones);
        BuildSummary r = reporte.summary;

        if (r.result == BuildResult.Succeeded)
        {
            Debug.Log($"BUILD OK -> {opciones.locationPathName} "
                      + $"({destino}, {r.totalSize / 1048576} MB, {r.totalTime.TotalSeconds:F0} s)");
        }
        else
        {
            Debug.LogError($"BUILD FALLO: {destino} {r.result}, "
                           + $"{r.totalErrors} errores");
            // En batchmode hay que forzar el codigo de salida, si no
            // Unity termina con 0 y el notebook cree que salio bien.
            if (Application.isBatchMode)
                EditorApplication.Exit(1);
        }
    }

    /// La raiz del repositorio, buscada SUBIENDO hasta su marca, con la
    /// misma regla que comun/rutas.py (MARCAS = '.git', 'setup.ps1'):
    /// contar carpetas hacia arriba apunta a otro lado sin fallar si el
    /// proyecto de Unity cambia de profundidad. Si no aparece la marca
    /// (un ZIP sin .git ni setup.ps1), se cae a la carpeta que contiene
    /// el proyecto, que es donde estuvo siempre.
    static string RaizDelRepo()
    {
        string proyecto = Directory.GetParent(Application.dataPath).FullName;
        for (DirectoryInfo d = new DirectoryInfo(proyecto); d != null; d = d.Parent)
        {
            if (Directory.Exists(Path.Combine(d.FullName, ".git"))
                || File.Exists(Path.Combine(d.FullName, ".git"))
                || File.Exists(Path.Combine(d.FullName, "setup.ps1")))
                return d.FullName;
        }
        return Directory.GetParent(proyecto).FullName;
    }

    /// <summary>
    /// Mete los shaders que se piden con Shader.Find() en la lista
    /// "Always Included Shaders" de Graphics Settings.
    ///
    /// POR QUE HACE FALTA
    /// Al compilar, Unity ELIMINA los shaders que no ve referenciados
    /// por ningun material de la escena. El visor no usa materiales de
    /// asset: los crea en runtime con
    ///     new Material(Shader.Find("Universal Render Pipeline/Lit"))
    /// y Shader.Find() en una build solo encuentra lo que quedo dentro.
    ///
    /// Sintoma cuando falta: en el editor se ve todo bien, pero la app
    /// compilada tira
    ///     "No encontre ningun shader utilizable. Todo se vera magenta."
    ///     ArgumentNullException: Value cannot be null
    /// y no dibuja nada. Es un error que SOLO aparece en la build.
    /// </summary>
    static void AsegurarShadersIncluidos()
    {
        var activo = AssetDatabase.LoadAllAssetsAtPath(
            "ProjectSettings/GraphicsSettings.asset");
        if (activo == null || activo.Length == 0)
        {
            Debug.LogWarning("No pude abrir GraphicsSettings.asset; "
                             + "los shaders podrian eliminarse en la build.");
            return;
        }

        var so = new SerializedObject(activo[0]);
        var lista = so.FindProperty("m_AlwaysIncludedShaders");
        if (lista == null) return;

        int agregados = 0;
        foreach (string nombre in SHADERS_NECESARIOS)
        {
            Shader sh = Shader.Find(nombre);
            if (sh == null)
            {
                Debug.LogWarning($"El shader '{nombre}' no existe en este "
                                 + "proyecto; se omite.");
                continue;
            }

            bool ya = false;
            for (int i = 0; i < lista.arraySize; i++)
            {
                if (lista.GetArrayElementAtIndex(i).objectReferenceValue == sh)
                {
                    ya = true;
                    break;
                }
            }
            if (ya) continue;

            lista.InsertArrayElementAtIndex(lista.arraySize);
            lista.GetArrayElementAtIndex(lista.arraySize - 1)
                 .objectReferenceValue = sh;
            agregados++;
            Debug.Log($"Shader incluido en la build: {nombre}");
        }

        if (agregados > 0)
        {
            so.ApplyModifiedProperties();
            AssetDatabase.SaveAssets();
        }
        Debug.Log($"Shaders always-included: {lista.arraySize} "
                  + $"({agregados} agregados ahora)");
    }
}
