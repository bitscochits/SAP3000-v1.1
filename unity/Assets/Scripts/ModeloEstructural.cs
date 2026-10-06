/*
================================================================
  ModeloEstructural.cs
================================================================
  FUENTE DE VERDAD del modelo de datos en Unity.

  Antes habia DOS juegos de clases para lo mismo:
    VisorEstructura.cs      -> NodoJSON, ElementoJSON, ModeloJSON
    AnalizadorEstructural.cs-> Nodo, Seccion, Elemento
  incompatibles entre si, asi que el visor no podia mandar al
  servidor lo que dibujaba, y el analizador no podia dibujar lo
  que mandaba. Ahora ambos usan ESTAS clases.

  ----------------------------------------------------------------
  REGLA DE ORO DE JsonUtility
  ----------------------------------------------------------------
  JsonUtility (el parser JSON que trae Unity) tiene tres limites que
  mandan sobre todo el diseno de este archivo:

    1. NO lee diccionarios con claves arbitrarias.
       Por eso "secciones" es una LISTA, no un diccionario, y por eso
       la respuesta del servidor tambien viene en listas.

    2. Solo serializa campos PUBLICOS de clases marcadas
       [System.Serializable]. Las propiedades (get/set) las ignora.

    3. Serializa SIEMPRE todos los campos. Un array que no asignaste
       sale como []. El servidor esta preparado: trata la lista vacia
       como "ausente".

  Los nombres de los campos deben calzar EXACTO con las claves del
  JSON. Si renombras uno aca, se rompe en silencio: JsonUtility no
  avisa, simplemente deja el campo en su valor por defecto.
  Hay un test que lo verifica: test_contrato_unity.py

  Unidades: m, kN, kPa (consistentes con OpenSees).
================================================================
*/

using System.Collections.Generic;

// ================================================================
// PARTE 1: DEFINICION DEL MODELO
//   (lo que Unity lee de modelo_unity.json y manda al servidor)
// ================================================================

// OJO con el nombre: NO se puede llamar 'Material' a secas, porque
// choca con UnityEngine.Material (el material grafico). Como esta clase
// vive en el namespace global, le GANA al 'using UnityEngine', y
// cualquier 'new Material(Shader.Find(...))' del proyecto deja de
// compilar. Y en Unity un solo error de compilacion bloquea
// Add Component para TODOS los scripts.
[System.Serializable]
public class MaterialModelo
{
    public float fpc_MPa = 25f;    // resistencia del hormigon
    public float poisson = 0.2f;
    public float gamma = 25f;      // peso especifico kN/m3
}

[System.Serializable]
public class Seccion
{
    public string nombre;          // "C50x50", "VX30x60", "MURO_M1"...
    public float A;                // area m2
    public float Iy;               // inercia m4
    public float Iz;
    public float J;                // torsion m4

    // Dimensiones REALES en metros, para poder dibujar el perfil.
    // b = ancho (a lo largo del eje local y)
    // h = canto (a lo largo del eje local z)
    public float b;
    public float h;

    // Tamano en planta de un muro, cuando viene declarado en la SECCION
    // y no en el elemento. El modelo del LT2 lo manda por elemento (dos
    // muros pueden compartir seccion y medir distinto); el del edificio
    // de Ingenieria lo manda aca. El visor acepta los dos.
    public float largo;            // m, a lo largo del muro
    public float espesor;          // m

    // Material propio de la seccion, opcional. Solo lo traen las
    // secciones que NO son del hormigon del edificio: los tubos de
    // acero del voladizo metalico. En 0 significa "usa el material
    // global del modelo".
    public float E;                // kPa
    public float G;                // kPa
    public bool TienePerfil { get { return b > 0.001f && h > 0.001f; } }
    public bool TieneMuro { get { return largo > 0.001f && espesor > 0.001f; } }
}

[System.Serializable]
public class Nodo
{
    public int id;
    public float x, y, z;          // coordenadas OpenSees (Z vertical)

    public bool fijo;              // true = empotrado (los 6 GDL)

    // true = nodo intermedio creado al subdividir una viga. No es un
    // nudo del marco: existe para poder dibujar la flecha del vano.
    // El servidor lo ignora; solo cambia como se ve.
    public bool auxiliar;

    // Restriccion por grado de libertad: [ux,uy,uz,rx,ry,rz], 1 = fijo.
    // Vacio o ausente -> manda 'fijo'. Una rotula es [1,1,1,0,0,0].
    public int[] restricciones;

    // Deformada precalculada del caso G, para dibujar sin servidor: las
    // traslaciones y los GIROS, que curvan la barra (VisorEstructura.CurvaDe).
    public float ux, uy, uz, rx, ry, rz;
}

[System.Serializable]
public class Elemento
{
    public int id;
    public int n1, n2;             // nodos que conecta
    public string seccion;         // debe existir en la lista de secciones
    // "columna", "viga_x", "viga_y", "muro", "brazo"/"brazo_rigido",
    // "pilar_metal", "diagonal". Los dos edificios no usan los mismos
    // nombres: comparar con EsMuro/EsBrazo y no con literales sueltos.
    public string tipo;

    // Orienta el eje fuerte de la seccion. Vacio = automatico segun la
    // geometria. Necesario para muros: hacia donde apunta su plano.
    public float[] vecxz;

    // Ejes locales YA CALCULADOS en Python, en coordenadas OpenSees.
    // Unity los DIBUJA; no los deduce. Deducirlos en C# seria duplicar
    // la convencion de geomTransf, y esa copia terminaria divergiendo
    // del modelo real sin que nadie se entere.
    public float[] localX;
    public float[] localY;
    public float[] localZ;

    // Solo para tipo == "muro": su tamano real en planta.
    // El muro se modela como UNA barra en su eje baricentrico ("columna
    // ancha"), asi que sin esto se dibujaria como una columna delgada y
    // no se podria comparar contra el plano.
    public float largo;
    public float espesor;

    // Hacia donde corre el LARGO del muro en planta (x, y de OpenSees).
    // Viene calculado desde Python. NO se deduce de vecxz: en un muro
    // vecxz es la NORMAL al muro, no su direccion, y deducirlo dibujaba
    // todos los muros girados 90 grados.
    public float[] dir_largo;

    // Area tributaria TOTAL de la viga (m2) y su carga de gravedad
    // (kN/m), calculadas en Python. Las traen Ingenieria y el conjunto;
    // el LT2 no las exporta por elemento (quedan en 0) y su area esta
    // en areas_tributarias. Para leerla, ModeloEstructural
    // .AreaTributariaTotal(id), que elige la fuente. Un campo por linea:
    // comun/test_contrato_unity.py los lee como texto.
    public float area_tributaria;
    public float w_gravedad;

    public bool EsMuro { get { return tipo == "muro"; } }

    // "brazo" (LT2) y "brazo_rigido" (Ingenieria) son lo mismo. Los
    // dos edificios nombran distinto al mismo elemento, y el visor
    // tiene que aceptar los dos: si aca falta uno, esos brazos se
    // dibujan como barra normal en vez de linea fina, y parecen vigas
    // que no existen.
    public bool EsBrazo
    {
        get { return tipo == "brazo" || tipo == "brazo_rigido"; }
    }
}


// ================================================================
// AREAS TRIBUTARIAS
//   El poligono de losa que descarga sobre una viga, ya recortado
//   por las bisectrices a 45 grados. Viene calculado de Python.
// ================================================================
[System.Serializable]
public class VerticePlanta
{
    public float x, y;             // coordenadas de planta (OpenSees)
}

[System.Serializable]
public class AreaTributaria
{
    public int elemento;           // elementTag de la viga que carga
    public int nivel;
    public float area;             // m2
    public float luz;              // m
    public float qG;               // kN/m2
    public float carga_total;      // kN   = qG * area
    public float w;                // kN/m = carga_total / luz (SOLO la losa)
    // "Que lo carga" completo, de Python (edificios/lt2/exportar_unity.py,
    // leido de lo que el modelo le aplico a eleLoad): el peso propio lineal
    // de la barra y la w total que recibe OpenSees en G (= wz del diagrama
    // de G). w + w_peso_propio = w_total_G lo comprueba test_contrato_unity;
    // Unity no suma. En 0 si el edificio no los exporta (Ingenieria) o si
    // la barra es un muro (su losa y su peso van como cargas nodales).
    public float w_peso_propio;    // kN/m
    public float w_total_G;        // kN/m
    public float z;                // cota del piso
    // Los poligonos vienen CONCATENADOS (JsonUtility no lee listas de
    // listas) y 'tamanos' dice cuantos vertices tiene cada uno.
    public VerticePlanta[] vertices;
    public int[] tamanos;
    public int n_poligonos;

    /// <summary>
    /// Recorre los poligonos devolviendo (inicio, cantidad) de cada uno.
    ///
    /// NO se puede dividir vertices.Length entre n_poligonos: los
    /// poligonos NO miden todos lo mismo. Una viga interior toma un
    /// TRAPECIO de un pano (4 vertices) y un TRIANGULO del otro (3),
    /// o sea 7 en total; repartir 7/2 = 3 mezcla los vertices de uno
    /// con los del otro y dibuja lineas cruzadas que no existen.
    /// </summary>
    public System.Collections.Generic.IEnumerable<int[]> Poligonos()
    {
        if (vertices == null || vertices.Length < 3) yield break;

        if (tamanos != null && tamanos.Length > 0)
        {
            int inicio = 0;
            foreach (int cuantos in tamanos)
            {
                if (cuantos >= 3 && inicio + cuantos <= vertices.Length)
                    yield return new[] { inicio, cuantos };
                inicio += cuantos;
            }
            yield break;
        }

        // Sin 'tamanos' (JSON viejo): al menos dibujar todo como UN
        // poligono, que es preferible a inventar una particion mala.
        yield return new[] { 0, vertices.Length };
    }
}

[System.Serializable]
public class Diafragma
{
    public int nodo_maestro;       // normalmente el centro de masa del piso
    public int[] nodos;            // nodos esclavos (misma cota)
    public int perpendicular = 3;  // 3 = diafragma horizontal
}

[System.Serializable]
public class BrazoRigido
{
    public int maestro;
    public int esclavo;
    public string tipo = "beam";   // "beam" = traslaciones Y rotaciones
}

[System.Serializable]
public class CargaNodal
{
    public int nodo;
    public float fx, fy, fz;       // kN
    public float mx, my, mz;       // kN*m
}

[System.Serializable]
public class CargaDistribuida
{
    public int elemento;
    // Componentes en EJES LOCALES de la barra.
    // La gravedad va en wz (negativo) para vigas horizontales.
    public float wy, wz, wx;
}

[System.Serializable]
public class CasoDeCarga
{
    public string nombre;          // "G", "Q", "EX", "EY"
    public string descripcion;
    public List<CargaNodal> cargas_nodales;
    public List<CargaDistribuida> cargas_distribuidas;
}

[System.Serializable]
public class InfoModelo
{
    public string descripcion;
    public string unidades;
    public string caso_precalculado;
    public string nota;

    // "lt2", "ingenieria" o "conjunto". Lo usa el servidor para nombrar
    // el Excel del reanalisis (results/excel/reanalisis_<edificio>.xlsx).
    // Vacio si el exportador no lo escribe (hoy ninguno lo hace).
    public string edificio;

    // Cota z (OpenSees, m) del nivel de terreno MAS BAJO, del perfil del
    // edificio; -9999 = el JSON no la trae. 'terrenos': cada nivel con su
    // region en planta (NivelTerreno, al final); vacio = solo este plano.
    public float cota_terreno = -9999f;
    public List<NivelTerreno> terrenos;
}

// Contenedor: representa modelo_unity.json completo.
// Este MISMO objeto se manda al servidor sin transformar nada.
[System.Serializable]
public class ModeloEstructural
{
    public InfoModelo info;
    public MaterialModelo material;   // la clave JSON sigue siendo 'material'
    public List<Seccion> secciones;
    public List<Nodo> nodos;
    public List<Elemento> elementos;
    public List<Diafragma> diafragmas;
    public List<BrazoRigido> brazos_rigidos;
    public List<CasoDeCarga> casos_de_carga;
    public List<AreaTributaria> areas_tributarias;

    // --- Indice de areas tributarias por elementTag ---
    [System.NonSerialized]
    private Dictionary<int, AreaTributaria> _tribPorElemento;

    /// Area tributaria de una viga. null si esa viga no carga losa
    /// (una columna, por ejemplo).
    ///
    /// OJO: devuelve UNA entrada. En el LT2 cada viga tiene una sola; en
    /// Ingenieria y el conjunto una viga puede tener varias (un trapecio
    /// de cada pano) y esta devuelve la ultima. Se conserva por
    /// compatibilidad; lo nuevo usa TributariasDe y AreaTributariaTotal.
    public AreaTributaria TributariaDe(int elementTag)
    {
        if (_tribPorElemento == null)
        {
            _tribPorElemento = new Dictionary<int, AreaTributaria>();
            if (areas_tributarias != null)
                foreach (AreaTributaria a in areas_tributarias)
                    _tribPorElemento[a.elemento] = a;
        }
        AreaTributaria r;
        return _tribPorElemento.TryGetValue(elementTag, out r) ? r : null;
    }

    [System.NonSerialized]
    private Dictionary<int, List<AreaTributaria>> _tribsPorElemento;

    private static readonly List<AreaTributaria> SIN_TRIBUTARIAS = new List<AreaTributaria>();

    /// TODAS las entradas de area tributaria de una viga, en el orden
    /// del JSON. Lista vacia (nunca null) si no carga losa. No
    /// modificar la lista devuelta: es la del indice.
    public List<AreaTributaria> TributariasDe(int elementTag)
    {
        if (_tribsPorElemento == null)
        {
            _tribsPorElemento = new Dictionary<int, List<AreaTributaria>>();
            if (areas_tributarias != null)
                foreach (AreaTributaria a in areas_tributarias)
                {
                    List<AreaTributaria> l;
                    if (!_tribsPorElemento.TryGetValue(a.elemento, out l))
                        _tribsPorElemento[a.elemento] = l = new List<AreaTributaria>();
                    l.Add(a);
                }
        }
        List<AreaTributaria> r;
        return _tribsPorElemento.TryGetValue(elementTag, out r) ? r : SIN_TRIBUTARIAS;
    }

    /// Area tributaria total de una viga, en m2. Si el elemento trae
    /// 'area_tributaria' (> 0), es ese numero, calculado en Python. Si
    /// no (el LT2), la suma de sus entradas de areas_tributarias.
    /// comun/test_contrato_unity.py comprueba que las dos fuentes
    /// coinciden donde existen ambas, asi que no es una segunda
    /// definicion: es leer la que haya.
    public float AreaTributariaTotal(int elementTag)
    {
        Elemento e = ElementoPorId(elementTag);
        if (e != null && e.area_tributaria > 0f) return e.area_tributaria;
        float suma = 0f;
        foreach (AreaTributaria a in TributariasDe(elementTag)) suma += a.area;
        return suma;
    }

    // --- Indice de elementos por elementTag ---
    [System.NonSerialized]
    private Dictionary<int, Elemento> _porElemento;
    [System.NonSerialized]
    private int _elementosAlIndexar = -1;

    /// Busca un elemento por id. null si no existe. El indice se rehace
    /// solo si cambia la cantidad de elementos; quien los edite sin
    /// cambiar la cantidad llama a InvalidarIndice().
    public Elemento ElementoPorId(int id)
    {
        if (elementos == null) return null;
        if (_porElemento == null || _elementosAlIndexar != elementos.Count)
        {
            _porElemento = new Dictionary<int, Elemento>();
            foreach (Elemento e in elementos) _porElemento[e.id] = e;
            _elementosAlIndexar = elementos.Count;
        }
        Elemento r;
        return _porElemento.TryGetValue(id, out r) ? r : null;
    }

    // --- Indices para buscar rapido (no se serializan) ---
    [System.NonSerialized]
    private Dictionary<int, Nodo> _porId;

    /// Busca un nodo por id. Devuelve null si no existe.
    public Nodo NodoPorId(int id)
    {
        if (_porId == null)
        {
            _porId = new Dictionary<int, Nodo>();
            if (nodos != null)
                foreach (Nodo n in nodos) _porId[n.id] = n;
        }
        Nodo r;
        return _porId.TryGetValue(id, out r) ? r : null;
    }

    /// Hay que llamarlo si se agregan o quitan nodos, elementos,
    /// secciones o areas tributarias.
    public void InvalidarIndice()
    {
        _porId = null;
        _porSeccion = null;
        _porElemento = null;
        _tribPorElemento = null;
        _tribsPorElemento = null;
    }

    [System.NonSerialized]
    private Dictionary<string, Seccion> _porSeccion;

    /// Busca una seccion por nombre. null si no existe.
    public Seccion SeccionPorNombre(string nombre)
    {
        if (string.IsNullOrEmpty(nombre)) return null;
        if (_porSeccion == null)
        {
            _porSeccion = new Dictionary<string, Seccion>();
            if (secciones != null)
                foreach (Seccion s in secciones) _porSeccion[s.nombre] = s;
        }
        Seccion r;
        return _porSeccion.TryGetValue(nombre, out r) ? r : null;
    }

    public CasoDeCarga CasoPorNombre(string nombre)
    {
        if (casos_de_carga == null) return null;
        foreach (CasoDeCarga c in casos_de_carga)
            if (c.nombre == nombre) return c;
        return null;
    }
}


// ================================================================
// PARTE 2: RESPUESTA DEL SERVIDOR
// ================================================================

[System.Serializable]
public class DespNodo
{
    public int id;
    public float ux, uy, uz;       // traslaciones (m)
    public float rx, ry, rz;       // rotaciones (rad)
}

[System.Serializable]
public class ReacNodo
{
    public int id;
    public float fx, fy, fz;       // kN
    public float mx, my, mz;       // kN*m
}

[System.Serializable]
public class FuerzaElemento
{
    public int id;
    // Esfuerzos en EJES LOCALES de la barra (no globales):
    // [N_i,Vy_i,Vz_i,T_i,My_i,Mz_i, N_j,Vy_j,Vz_j,T_j,My_j,Mz_j]
    // Bajo gravedad: cortante vertical en Vz (idx 2),
    // momento flector en My (idx 4 y 10).
    public float[] f;

    public float N_i  { get { return f != null && f.Length > 0 ? f[0] : 0f; } }
    public float Vz_i { get { return f != null && f.Length > 2 ? f[2] : 0f; } }
    public float My_i { get { return f != null && f.Length > 4 ? f[4] : 0f; } }
    public float My_j { get { return f != null && f.Length > 10 ? f[10] : 0f; } }
}

// El equilibrio global de un caso, calculado en Python por
// comun/calcular.equilibrio() y devuelto por el servidor. Las mismas
// claves que ese dict. Un campo por linea y sin metodos.
//
// POR QUE NO SE SUMA EN C#: nodeReaction en un nodo de diafragma trae
// la fuerza interna de la restriccion. Sumar la lista de reacciones
// dobla el corte basal (CLAUDE.md, seccion 4, "Reacciones"); la
// separacion por grado de libertad vive en Python y aca solo se lee.
//
// OJO JsonUtility: si la respuesta no trae 'equilibrio', el campo puede
// quedar null o como un EquilibrioCaso vacio (arreglos null o de largo
// 0), segun como lo construya el serializador. "Vino" se pregunta asi,
// que cubre los dos:
//   c.equilibrio != null && c.equilibrio.aplicada_kN != null
//       && c.equilibrio.aplicada_kN.Length == 3
[System.Serializable]
public class EquilibrioCaso
{
    public float[] aplicada_kN;        // [Fx, Fy, Fz] cargas aplicadas
    public float[] reaccion_kN;        // [Fx, Fy, Fz] reacciones que cuentan
    public float[] error_kN;           // aplicada + reaccion, por eje
    public int cargas_sin_convertir;   // cargas que no se pudieron sumar
    public int nodos_en_diafragma;
    public bool confiable;             // cargas_sin_convertir == 0
}

// Un caso de carga resuelto (G, Q, EX, EY...).
[System.Serializable]
public class CasoResultado
{
    public string nombre;
    public bool ok;
    public float max_desplazamiento;
    public List<DespNodo> desplazamientos;
    public List<ReacNodo> reacciones;
    public List<FuerzaElemento> fuerzas_elementos;
    public EquilibrioCaso equilibrio;
}

[System.Serializable]
public class RespuestaServidor
{
    public bool ok;
    public string error;

    // Etiquetas 'tipo' que no calzan con la geometria real del elemento.
    // No son errores (el modelo se resolvio igual), pero delatan datos
    // mal importados del DXF.
    public List<string> avisos;

    // --- Forma PLANA: cuando se manda un solo caso de carga ---
    public float max_desplazamiento;
    public List<DespNodo> desplazamientos;
    public List<ReacNodo> reacciones;
    public List<FuerzaElemento> fuerzas_elementos;

    // --- Forma MULTI-CASO: cuando se manda "casos_de_carga" ---
    // Si viene con contenido, manda esta y se ignora la plana.
    public List<CasoResultado> casos;

    // --- Libro Excel del reanalisis ---
    // Ruta ABSOLUTA del .xlsx que el servidor escribio con comun/excel.py
    // despues de resolver (results/excel/reanalisis_<ed>.xlsx), o vacio
    // si no lo escribio; en ese caso excel_error dice por que. Un null
    // del JSON puede llegar como null o como "": preguntar con
    // string.IsNullOrEmpty.
    public string excel;
    public string excel_error;

    /// Normaliza ambas formas a una lista de casos.
    public List<CasoResultado> ComoCasos()
    {
        if (casos != null && casos.Count > 0) return casos;

        List<CasoResultado> l = new List<CasoResultado>();
        if (desplazamientos != null && desplazamientos.Count > 0)
        {
            l.Add(new CasoResultado {
                nombre = "unico", ok = ok,
                max_desplazamiento = max_desplazamiento,
                desplazamientos = desplazamientos,
                reacciones = reacciones,
                fuerzas_elementos = fuerzas_elementos
            });
        }
        return l;
    }
}


// ================================================================
// PARTE 3: CONVERSION DE EJES  (el swap que todos olvidan)
// ================================================================
public static class Ejes
{
    /// OpenSees usa Z vertical; Unity usa Y vertical.
    ///   Unity(x, z_opensees, y_opensees)
    /// Si el edificio se ve "acostado", este swap esta mal.
    public static UnityEngine.Vector3 AUnity(float x, float y_os, float z_os)
    {
        return new UnityEngine.Vector3(x, z_os, y_os);
    }

    public static UnityEngine.Vector3 PosicionDe(Nodo n)
    {
        return AUnity(n.x, n.y, n.z);
    }

    /// Posicion deformada = original + desplazamiento * escala.
    /// Siempre se parte de la coordenada ORIGINAL: si se acumulara
    /// sobre la posicion actual, cada recalculo correria la estructura.
    public static UnityEngine.Vector3 PosicionDeformada(
        Nodo n, float ux, float uy, float uz, float escala)
    {
        return AUnity(n.x + ux * escala,
                      n.y + uy * escala,
                      n.z + uz * escala);
    }
}


// ================================================================
// PARTE 4: ETIQUETAS EN LOS OBJETOS DE LA ESCENA
//   conectan el GameObject con el nodeTag/eleTag de OpenSees
// ================================================================
public class DatoNodo : UnityEngine.MonoBehaviour { public int idNodo; }
public class DatoElemento : UnityEngine.MonoBehaviour { public int idElemento; }


// ================================================================
// PARTE 5: EL TERRENO EN NIVELES (info.terrenos)
//   Va al final del archivo para no correr las lineas que citan los
//   documentos (CLAUDE.md, seccion 6).
//
//   Un nivel del terreno: la BASE (vertices vacio: todo el plano, en
//   info.cota_terreno) o una TERRAZA, un nivel mas alto con su region
//   en planta (x, y OpenSees, sentido antihorario). Lo arma Python
//   desde el perfil de cada edificio; AmbienteVisor.Terrazas.cs lo
//   dibuja. Contrato: semana05/CONTRATO.md.
// ================================================================
[System.Serializable]
public class NivelTerreno
{
    public string nombre;
    public float z;
    public List<VerticePlanta> vertices;
}
