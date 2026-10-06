/*
================================================================
  ConfigurarEscena.cs   (Editor)
================================================================
  Arma la escena del laboratorio y deja sus piezas conectadas entre si:

    Visor            VisorEstructura + PanelVisor + VisorResultados
    Analizador       ClienteReanalisis + EditorEstructura
    CargasYArmadura  VisorCargasYArmadura
    Main Camera      CamaraOrbital

  y limpia los componentes cuyo script ya no existe. AmbienteVisor,
  VisorCargaMovil, VisorPersona y Capturas no van en la escena: se crean
  solos al cargarla (RuntimeInitializeOnLoadMethod).

  Existe para que el montaje de la escena sea REPRODUCIBLE. Si la
  escena se pierde o alguien la deja a medias, se rehace con un
  comando en vez de a mano arrastrando componentes:

      Unity -> menu  Laboratorio / Configurar escena

  o desde la terminal, sin abrir el editor:

      Unity.exe -batchmode -quit -projectPath <ruta> \
                -executeMethod ConfigurarEscena.Configurar

  Es idempotente: correrlo dos veces no duplica nada, y la segunda vez
  no guarda (no hay nada que cambiar), asi que SampleScene.unity queda
  byte a byte igual. Solo guarda si agrego, renombro, conecto o quito
  algo; al guardar, Unity descarta los campos que la escena tenia
  guardados y que ya no existen en el C# (nombreArchivo,
  archivoSuperposicion, colorSeleccion y anchoPanel del editor,
  analizarAlIniciar...).

  OJO: ConstruirApp lo llama antes de cada build. En el editor, si la
  escena abierta tiene cambios sin guardar, primero se pregunta
  (OpenScene la recargaria del disco y los perderia sin avisar).
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

    // El objeto de las cargas y la armadura. Antes se llamaba como su
    // script de entonces; se renombra al configurar.
    const string OBJETO_CARGAS = "CargasYArmadura";

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
        var cambios = new List<string>();

        // --- Scripts perdidos ---
        // Va antes de buscar los objetos: un componente cuyo script no
        // existe no hace nada, pero Unity avisa "The referenced script ...
        // is missing" en cada Play y en cada build, justo en la Console
        // donde se buscan los errores de verdad.
        int perdidos = QuitarScriptsPerdidos(escena);
        if (perdidos > 0) cambios.Add(perdidos + " script(s) perdido(s) quitado(s)");

        // --- Visor ---
        GameObject goVisor = GameObject.Find("Visor");
        if (goVisor == null)
        {
            goVisor = new GameObject("Visor");
            cambios.Add("se creo el GameObject 'Visor'");
        }
        VisorEstructura visor = Obtener<VisorEstructura>(goVisor, cambios);
        PanelVisor qa = Obtener<PanelVisor>(goVisor, cambios);
        // Resultados: esfuerzos, diagramas, P-M y trazabilidad. PanelVisor lo
        // agrega solo si falta, pero asi queda guardado en la escena.
        Obtener<VisorResultados>(goVisor, cambios);

        // --- Cargas y armadura ---
        // Vive en su propio GameObject. Se busca el componente en TODA la
        // escena (tambien inactivo) antes de mirar el nombre del objeto:
        // PanelVisor y Capturas lo toman con FindAnyObjectByType, asi que si
        // alguien lo movio a otro objeto, crear un segundo dejaria a cada uno
        // leyendo uno distinto. Sus valores por defecto son los que la escena
        // guarda (enfierrarTodas y jaulaDetalle apagados): creado de cero se
        // ve igual.
        VisorCargasYArmadura s3 = Object.FindAnyObjectByType<VisorCargasYArmadura>(
            FindObjectsInactive.Include);
        if (s3 == null)
        {
            GameObject goS3 = GameObject.Find(OBJETO_CARGAS);
            if (goS3 == null)
            {
                goS3 = new GameObject(OBJETO_CARGAS);
                cambios.Add("se creo el GameObject '" + OBJETO_CARGAS + "'");
            }
            s3 = Obtener<VisorCargasYArmadura>(goS3, cambios);
        }
        else if (s3.gameObject.name != OBJETO_CARGAS
                 && s3.gameObject.GetComponents<Component>().Length == 2)
        {
            // Un objeto DEDICADO (su Transform y este componente) con otro
            // nombre: el de antes. Si comparte objeto con otros componentes,
            // ese nombre es del otro y no se toca.
            string antes = s3.gameObject.name;
            s3.gameObject.name = OBJETO_CARGAS;
            cambios.Add("'" + antes + "' renombrado a '" + OBJETO_CARGAS + "'");
        }

        // --- Analizador + Editor (modificar el modelo en vivo) ---
        // El reanalisis necesita el servidor corriendo (python sap.py
        // servidor). Sin el, el visor funciona igual: solo no se puede
        // reanalizar. Al iniciar NO se consulta al servidor: el reanalisis
        // se pide a mano desde la pestana Modificar.
        GameObject goAnalizador = GameObject.Find("Analizador");
        if (goAnalizador == null)
        {
            goAnalizador = new GameObject("Analizador");
            cambios.Add("se creo el GameObject 'Analizador'");
        }
        ClienteReanalisis analizador = Obtener<ClienteReanalisis>(goAnalizador, cambios);
        EditorEstructura editor = Obtener<EditorEstructura>(goAnalizador, cambios);

        // --- Camara ---
        Camera cam = Camera.main;
        if (cam == null)
        {
            GameObject goCam = new GameObject("Main Camera");
            goCam.tag = "MainCamera";
            cam = goCam.AddComponent<Camera>();
            cambios.Add("se creo la Main Camera");
        }
        CamaraOrbital orbital = Obtener<CamaraOrbital>(cam.gameObject, cambios);

        // --- Cableado ---
        // Se hace por codigo y no arrastrando en el Inspector para que
        // quede registrado que apunta a que. Solo se asigna (y se cuenta
        // como cambio) lo que no apunta ya a donde corresponde.
        if (qa.visor != visor) { qa.visor = visor; Marcar(qa, cambios, "PanelVisor.visor"); }
        if (qa.camara != cam) { qa.camara = cam; Marcar(qa, cambios, "PanelVisor.camara"); }
        if (qa.orbital != orbital) { qa.orbital = orbital; Marcar(qa, cambios, "PanelVisor.orbital"); }
        if (orbital.visor != visor) { orbital.visor = visor; Marcar(orbital, cambios, "CamaraOrbital.visor"); }
        if (analizador.visor != visor) { analizador.visor = visor; Marcar(analizador, cambios, "ClienteReanalisis.visor"); }
        if (editor.visor != visor) { editor.visor = visor; Marcar(editor, cambios, "EditorEstructura.visor"); }
        if (editor.analizador != analizador) { editor.analizador = analizador; Marcar(editor, cambios, "EditorEstructura.analizador"); }
        if (editor.camara != orbital) { editor.camara = orbital; Marcar(editor, cambios, "EditorEstructura.camara"); }

        if (cambios.Count == 0)
        {
            Debug.Log("Escena configurada: ya estaba armada (Visor + PanelVisor + VisorResultados, "
                      + "CargasYArmadura, Analizador, CamaraOrbital). No se guardo nada.");
            return;
        }
        EditorUtility.SetDirty(s3);
        EditorSceneManager.MarkSceneDirty(escena);
        EditorSceneManager.SaveScene(escena);
        Debug.Log("Escena configurada y guardada (" + cambios.Count + " cambio(s)): "
                  + string.Join("; ", cambios.ToArray()));
    }

    static void Marcar(Object o, List<string> cambios, string que)
    {
        EditorUtility.SetDirty(o);
        cambios.Add(que + " conectado");
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
    static T Obtener<T>(GameObject go, List<string> cambios) where T : Component
    {
        T c = go.GetComponent<T>();
        if (c == null)
        {
            c = go.AddComponent<T>();
            cambios.Add($"se agrego {typeof(T).Name} a '{go.name}'");
        }
        return c;
    }
}
