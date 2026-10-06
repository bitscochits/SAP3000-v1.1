/*
================================================================
  ConfigurarEscena.cs   (Editor)
================================================================
  Arma la escena del laboratorio: deja el Visor, las capas de QA,
  Semana 3, Semana 4, el analizador y la camara orbital conectados
  entre si, y limpia los componentes cuyo script ya no existe.

  Existe para que el montaje de la escena sea REPRODUCIBLE. Si la
  escena se pierde o alguien la deja a medias, se rehace con un
  comando en vez de a mano arrastrando componentes:

      Unity -> menu  Laboratorio / Configurar escena

  o desde la terminal, sin abrir el editor:

      Unity.exe -batchmode -quit -projectPath <ruta> \
                -executeMethod ConfigurarEscena.Configurar

  Es idempotente: correrlo dos veces no duplica nada.

  OJO: ConstruirApp lo llama antes de cada build, y termina con
  SaveScene. En el editor, si la escena abierta tiene cambios sin
  guardar, primero se pregunta (OpenScene la recargaria del disco y
  los perderia sin avisar).
================================================================
*/

using System.Collections.Generic;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

public static class ConfigurarEscena
{
    const string RUTA_ESCENA = "Assets/Scenes/SampleScene.unity";

    [MenuItem("Laboratorio/Configurar escena")]
    public static void Configurar()
    {
        // En batch no hay a quien preguntar y no hay cambios sin guardar
        // (la escena recien se abre). En el editor, "Cancelar" deja todo
        // como estaba: mejor no configurar que borrar trabajo de alguien.
        if (!Application.isBatchMode
            && !EditorSceneManager.SaveCurrentModifiedScenesIfUserWantsTo())
        {
            Debug.LogWarning("Configurar escena cancelado: la escena abierta "
                             + "tenia cambios sin guardar.");
            return;
        }

        var escena = EditorSceneManager.OpenScene(RUTA_ESCENA,
                                                  OpenSceneMode.Single);

        // --- Scripts perdidos ---
        // Va antes de buscar los objetos. La escena traia un GameObject
        // 'Editor' con un script cuyo guid no existe en ningun .meta: un
        // resto de cuando EditorEstructura vivia ahi (hoy esta en
        // 'Analizador'). No hacia nada, pero Unity avisaba "The referenced
        // script ... is missing" en cada Play y en cada build, justo en la
        // Console donde se buscan los errores de verdad.
        int perdidos = QuitarScriptsPerdidos(escena);

        // --- Visor ---
        GameObject goVisor = GameObject.Find("Visor");
        if (goVisor == null)
        {
            goVisor = new GameObject("Visor");
            Debug.Log("Se creo el GameObject 'Visor'.");
        }

        VisorEstructura visor = Obtener<VisorEstructura>(goVisor);
        VisorQA qa = Obtener<VisorQA>(goVisor);
        // Semana 4: esfuerzos, diagramas, P-M y trazabilidad. VisorQA lo
        // agrega solo si falta, pero asi queda guardado en la escena.
        VisorSemana04 s4 = Obtener<VisorSemana04>(goVisor);

        // --- Semana 3: cargas, sismo y armadura ---
        // Vive en su propio GameObject, como en la escena versionada.
        // VisorQA NO lo agrega si falta (solo muestra "no hay VisorSemana03
        // en la escena"), asi que sin esta linea una escena rehecha con el
        // menu perdia las flechas de carga, la deformada sismica y la
        // enfierradura sin ningun error.
        // Se busca el componente en TODA la escena (tambien inactivo) antes
        // de mirar el nombre del objeto: VisorQA y CapturaSemana04 lo
        // toman con FindAnyObjectByType, asi que si alguien lo movio a otro
        // objeto, crear un segundo dejaria a cada uno leyendo uno distinto.
        VisorSemana03 s3 = Object.FindAnyObjectByType<VisorSemana03>(
            FindObjectsInactive.Include);
        bool s3Nuevo = s3 == null;
        if (s3Nuevo)
        {
            GameObject goS3 = GameObject.Find("VisorSemana03");
            if (goS3 == null)
            {
                goS3 = new GameObject("VisorSemana03");
                Debug.Log("Se creo el GameObject 'VisorSemana03'.");
            }
            s3 = Obtener<VisorSemana03>(goS3);
            // Los dos que en la escena se apagaron a proposito. Con
            // enfierrarTodas la jaula de UNA columna se copia en todas y
            // las deja negras; jaulaDetalle pone una columna gigante al
            // costado. Solo al crearlo: si el componente ya estaba, manda
            // lo que se eligio en el Inspector.
            s3.enfierrarTodas = false;
            s3.jaulaDetalle = false;
        }

        // --- Analizador + Editor (modificar el modelo en vivo) ---
        // Necesitan el servidor Flask corriendo:
        //     python semana05/servidor_s5.py
        // Sin el, el visor funciona igual: solo no se puede reanalizar.
        GameObject goAnalizador = GameObject.Find("Analizador");
        if (goAnalizador == null) goAnalizador = new GameObject("Analizador");
        AnalizadorEstructural analizador = Obtener<AnalizadorEstructural>(goAnalizador);
        EditorEstructura editor = Obtener<EditorEstructura>(goAnalizador);

        // --- Camara ---
        Camera cam = Camera.main;
        if (cam == null)
        {
            GameObject goCam = new GameObject("Main Camera");
            goCam.tag = "MainCamera";
            cam = goCam.AddComponent<Camera>();
            Debug.Log("Se creo la Main Camera.");
        }

        CamaraOrbital orbital = Obtener<CamaraOrbital>(cam.gameObject);

        // --- Cableado ---
        // Se hace por codigo y no arrastrando en el Inspector para que
        // quede registrado que apunta a que.
        qa.visor = visor;
        qa.camara = cam;
        qa.orbital = orbital;
        orbital.visor = visor;

        analizador.visor = visor;
        // Al iniciar NO se consulta al servidor: la app tiene que abrir
        // igual aunque el servidor no este corriendo. El reanalisis se
        // dispara a mano desde el panel del editor.
        analizador.analizarAlIniciar = false;

        editor.visor = visor;
        editor.analizador = analizador;
        editor.camara = orbital;

        EditorUtility.SetDirty(qa);
        EditorUtility.SetDirty(s4);
        EditorUtility.SetDirty(s3);
        EditorUtility.SetDirty(orbital);
        EditorUtility.SetDirty(analizador);
        EditorUtility.SetDirty(editor);
        EditorSceneManager.MarkSceneDirty(escena);
        EditorSceneManager.SaveScene(escena);

        Debug.Log("Escena configurada: Visor + VisorQA + VisorSemana04 + "
                  + "VisorSemana03 + Analizador + CamaraOrbital conectados y "
                  + $"guardados ({perdidos} script(s) perdido(s) quitado(s)).");
    }

    /// Quita los componentes cuyo script ya no existe, en todos los
    /// objetos de la escena (tambien hijos e inactivos). Si un objeto
    /// queda solo con su Transform y sin hijos, no hacia otra cosa que
    /// sostener ese script: se borra entero, para no dejar un objeto
    /// vacio que confunde. Devuelve cuantos componentes quito.
    static int QuitarScriptsPerdidos(Scene escena)
    {
        int quitados = 0;
        var vacios = new List<GameObject>();
        foreach (GameObject raiz in escena.GetRootGameObjects())
        {
            foreach (Transform t in raiz.GetComponentsInChildren<Transform>(true))
            {
                GameObject go = t.gameObject;
                if (GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(go) == 0)
                    continue;
                // En una instancia de prefab el componente pertenece al
                // prefab: quitarlo desde la escena no se puede, se avisa.
                if (PrefabUtility.IsPartOfPrefabInstance(go))
                {
                    Debug.LogWarning($"'{go.name}' tiene scripts perdidos pero "
                                     + "es parte de un prefab: arreglarlo en el prefab.");
                    continue;
                }
                int n = GameObjectUtility.RemoveMonoBehavioursWithMissingScript(go);
                quitados += n;
                Debug.Log($"Se quitaron {n} script(s) perdido(s) de '{go.name}'.");
                if (go.GetComponents<Component>().Length == 1 && t.childCount == 0)
                    vacios.Add(go);
            }
        }
        foreach (GameObject go in vacios)
        {
            Debug.Log($"Se borro '{go.name}': solo sostenia scripts perdidos.");
            Object.DestroyImmediate(go);
        }
        return quitados;
    }

    /// Devuelve el componente, agregandolo solo si falta. Asi la
    /// funcion se puede correr las veces que sea sin duplicar.
    static T Obtener<T>(GameObject go) where T : Component
    {
        T c = go.GetComponent<T>();
        if (c == null)
        {
            c = go.AddComponent<T>();
            Debug.Log($"Se agrego {typeof(T).Name} a '{go.name}'.");
        }
        return c;
    }
}
