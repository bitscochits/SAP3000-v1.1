/*
================================================================
  VisorSemana04.Diagramas.cs   (parte de VisorSemana04)
================================================================
  Los diagramas de esfuerzos en 3D: My, Mz, Vz, Vy, N o T del caso
  activo, sobre la geometria SIN deformar.

  Los valores a lo largo de la barra vienen del JSON (estaciones x y
  el esfuerzo en cada una). Aca solo se unen con rectas, se escalan y
  se llevan al costado de la barra que corresponde.

  POR QUE MALLAS COMBINADAS: con el edificio completo son cientos de
  barras con hasta ocho tramos cada una. Un GameObject por tramo
  serian miles de objetos; dos mallas (positivo y negativo) mas un
  contorno son tres, se dibujen una barra o todas.

  POR QUE UNLIT Y LAS DOS CARAS: el diagrama es una superficie plana.
  Con luz se ve negra cuando la camara la mira de canto, y el material
  descarta la cara de atras, asi que desde el otro lado desapareceria.

  SIN COLLIDER: la seleccion es por raycast y tiene que seguir pegando
  en las barras del visor, no en el diagrama que las rodea.
================================================================
*/

using System.Collections.Generic;
using System.Globalization;
using UnityEngine;
using UnityEngine.Rendering;

public partial class VisorSemana04
{
    private string firmaDibujo = null;

    /// Por que no se dibujo ningun diagrama, en una linea para el panel.
    /// Vacio si se dibujo algo (o si el toggle esta apagado, que ya se ve).
    /// Casi todas las formas de no ver nada terminan en una salida temprana
    /// de Redibujar(): sin esto, el visor se queda mudo.
    public string MotivoSinDiagrama { get; private set; } = "";

    /// true si hay algun diagrama dibujado en la escena. Lo mira
    /// AmbienteVisor para esconder las losas de dibujo, que lo taparian.
    public bool HayDiagramaDibujado { get { return creados.Count > 0; } }

    /// Un aviso para LEER el diagrama que si se dibujo. Hoy uno solo: en
    /// un muro, la cinta del eje de su plano queda dentro de la placa.
    public string AvisoDeLectura { get; private set; } = "";
    // El mayor |valor| dibujado, por grupo: lo que mide la leyenda.
    private float mayorBarrasDibujado, mayorMurosDibujado;

    /// Rehace los diagramas solo si cambio algo de lo que los define.
    /// VisorQA lo llama cada vez que redibuja sus capas, y eso pasa en
    /// cada click: sin la firma se reharian mallas sin razon.
    public void Refrescar()
    {
        if (Firma() != firmaDibujo) Redibujar();
    }

    string Firma()
    {
        string capas = visor == null ? "" :
            $"{visor.verColumnas}{visor.verVigas}{visor.verMuros}{visor.verBrazos}";
        string piso = qa != null ? qa.soloNivel.ToString(CultureInfo.InvariantCulture) : "-";
        // Cuantas barras tiene el modelo: si el editor agrega o borra una,
        // la firma cambia y el diagrama se rehace. Sin esto quedaba en
        // pantalla el de una barra que ya no existe.
        string modelo = (visor == null || visor.Modelo == null
                         || visor.Modelo.elementos == null)
            ? "-" : visor.Modelo.elementos.Count.ToString(CultureInfo.InvariantCulture);
        // versionCasos: con el MISMO nombre de caso (LIBRE, reemplazado por
        // otra respuesta de /combinar) los numeros son otros, y sin esto el
        // diagrama viejo quedaba en pantalla. La cota visible es el filtro
        // de piso comun de AjustesVista (semana05/CONTRATO.md, 2.1).
        string cota = AjustesVista.HayFiltroDePiso
            ? AjustesVista.cotaVisible.ToString("0.000", CultureInfo.InvariantCulture) : "todas";
        return $"{casoActivo}|{versionCasos}|{magnitud}|{mostrarDiagramas}|{soloSeleccionado}|{modelo}|"
             + $"{multiplicadorEscala.ToString(CultureInfo.InvariantCulture)}|"
             + $"{largoDiagramaMaximo.ToString(CultureInfo.InvariantCulture)}|"
             + $"{Seleccionado}|{piso}|{cota}|{capas}|{AnexoCalzaConElModelo}|{AnexoDesactualizado}";
    }

    public void Redibujar()
    {
        Limpiar();
        firmaDibujo = Firma();
        mayorBarrasDibujado = mayorMurosDibujado = 0f;
        MotivoSinDiagrama = AvisoDeLectura = "";
        if (Anexo == null || visor == null || visor.Modelo == null)
        {
            MotivoSinDiagrama = "no hay anexo o no hay modelo cargado";
            return;
        }
        // Un anexo de otro edificio tiene los mismos ids en otras barras:
        // dibujarlo pondria esfuerzos de una barra sobre otra.
        if (!mostrarDiagramas) return;          // el toggle se ve apagado
        // Con el modelo editado pasa lo mismo que con otro edificio: los
        // esfuerzos son de otra geometria (una columna borrada cambia los
        // de todo su entorno).
        if (AnexoDesactualizado)
        {
            MotivoSinDiagrama = "el modelo se edito: los esfuerzos son del modelo ORIGINAL "
                              + "(recalcula y re-exporta)";
            return;
        }
        if (!AnexoCalzaConElModelo)
        {
            MotivoSinDiagrama = "el anexo es de otro edificio: mira el AVISO de arriba";
            return;
        }
        if (CasoActivo() == null)
        {
            MotivoSinDiagrama = $"el caso activo '{casoActivo}' no esta en el anexo: "
                              + "elige uno de los botones de caso";
            return;
        }

        List<Elemento> barras = BarrasADibujar();
        if (barras.Count == 0)
        {
            // Se comprueba antes de afirmarlo: la barra puede no estar en el
            // modelo, o estar y no ser un brazo (capa apagada, filtro de piso).
            Elemento sel = null;
            if (Seleccionado >= 0 && visor.Modelo.elementos != null)
                foreach (Elemento x in visor.Modelo.elementos)
                    if (x.id == Seleccionado) { sel = x; break; }
            MotivoSinDiagrama = !soloSeleccionado
                ? "ninguna barra visible: revisa el filtro de piso y las capas"
                : Seleccionado < 0
                    ? "no hay ninguna barra seleccionada"
                    : sel == null
                        ? $"la barra {Seleccionado} ya no esta en el modelo"
                        : sel.EsBrazo
                            ? "la barra seleccionada no lleva diagrama: es un brazo rigido"
                            : $"la barra {Seleccionado} no tiene esfuerzos en este caso";
            return;
        }

        // Escala puramente grafica: el mayor |valor| dibujado se lleva a
        // largoDiagramaMaximo metros. Los muros llevan la suya: toman
        // momentos y cortes de miles de kN, y con una sola escala el
        // diagrama de una viga del mismo piso quedaria de centimetros.
        // La leyenda dice las dos. El valor ya viene del JSON; buscar el
        // mayor no es calcular estructura.
        foreach (Elemento e in barras)
        {
            float[] v = Magnitud(EsfuerzosDe(e.id), magnitud);
            if (v == null) continue;
            foreach (float q in v)
            {
                if (EsMuro(e)) mayorMurosDibujado = Mathf.Max(mayorMurosDibujado, Mathf.Abs(q));
                else mayorBarrasDibujado = Mathf.Max(mayorBarrasDibujado, Mathf.Abs(q));
            }
        }

        if (mayorBarrasDibujado <= 1e-9f && mayorMurosDibujado <= 1e-9f)
        {
            MotivoSinDiagrama = $"{magnitud} vale 0 en todo lo dibujado: prueba otra "
                              + "magnitud (las que mandan llevan * en el panel)";
            return;
        }
        if (soloSeleccionado && barras.Count == 1 && EsMuro(barras[0])
            && visor.verMuros)
        {
            // Lo que esconde la cinta no es el nombre de la magnitud sino su
            // DIRECCION: todo lo que se dibuja en el eje del plano del muro
            // (My, Vz, N, T, wz en un muro de 'My'; Mz, Vy, wy en uno de
            // 'Mz') sale a lo largo de la placa y queda dentro de ella. Si
            // la capa Muros esta apagada no hay placa donde esconderse.
            ElementoS4 s4 = ElementoPorId(barras[0].id);
            if (s4 != null && EjeDeDibujo(magnitud) == s4.momento_en_el_plano)
                AvisoDeLectura = "el diagrama va en el plano del muro y queda dentro "
                               + "de la placa: apaga la capa Muros o sube la escala";
        }

        var positivo = new Malla();
        var negativo = new Malla();
        var contorno = new Lineas();
        foreach (Elemento e in barras)
            AgregarDiagrama(e, EsfuerzosDe(e.id), EscalaDe(e), positivo, negativo, contorno);
        // Con perfiles (vista realista) la barra es una caja de b x h y el
        // diagrama, que nace en el eje, quedaba adentro: se dibujan delgadas
        // mientras tienen diagrama. Los muros no (su placa ya existia).
        visor.FijarBarrasDelgadas(barras.FindAll(x => !EsMuro(x)).ConvertAll(x => x.id));
        barrasAdelgazadas = true;

        Crear(positivo.Construir("Diagrama_" + magnitud + "_positivo"), colorPositivo);
        Crear(negativo.Construir("Diagrama_" + magnitud + "_negativo"), colorNegativo);
        Crear(contorno.Construir("Diagrama_" + magnitud + "_contorno"), colorContorno);

        if (Seleccionado >= 0)
        {
            Elemento sel = barras.Find(x => x.id == Seleccionado);
            if (sel != null) EtiquetasDe(sel, EsfuerzosDe(sel.id), EscalaDe(sel));
        }
    }

    static bool EsMuro(Elemento e) { return e.tipo == "muro"; }

    /// En que eje local se dibuja cada magnitud, dicho como el momento que
    /// usa ese mismo eje: "Mz" para lo que va en y local, "My" para lo que
    /// va en z local. Es la regla de DireccionDeDibujo, en una sola parte.
    static string EjeDeDibujo(string m)
    {
        return (m == "Mz" || m == "Vy" || m == "wy") ? "Mz" : "My";
    }

    /// Metros de dibujo por unidad de esfuerzo, segun el grupo de la barra.
    float EscalaDe(Elemento e)
    {
        float mayor = EsMuro(e) ? mayorMurosDibujado : mayorBarrasDibujado;
        return mayor > 1e-9f ? largoDiagramaMaximo * multiplicadorEscala / mayor : 0f;
    }

    // true si este script pidio barras delgadas al visor y no las devolvio.
    private bool barrasAdelgazadas = false;

    void Limpiar()
    {
        if (barrasAdelgazadas && visor != null) visor.FijarBarrasDelgadas(null);
        barrasAdelgazadas = false;
        foreach (GameObject g in creados)
        {
            if (g == null) continue;
            MeshFilter mf = g.GetComponent<MeshFilter>();
            if (mf != null && mf.sharedMesh != null) Destroy(mf.sharedMesh);
            Destroy(g);
        }
        creados.Clear();
    }

    List<Elemento> BarrasADibujar()
    {
        var lista = new List<Elemento>();
        foreach (Elemento e in visor.Modelo.elementos)
        {
            // Un brazo rigido es un artificio numerico del muro: su
            // diagrama no dice nada y taparia el del muro. Tampoco si
            // se lo selecciona.
            if (e.EsBrazo) continue;
            if (soloSeleccionado)
            {
                if (e.id == Seleccionado) lista.Add(e);
                continue;
            }
            // Visibles = las que el visor dibujo, que respeta sus capas, y
            // que pasan el filtro de piso. El filtro es la regla comun de
            // AjustesVista (la cota MENOR de la barra); el de VisorQA se
            // sigue mirando mientras su panel use soloNivel. Si los dos
            // existen, dicen lo mismo; si uno no esta puesto, no filtra.
            if (visor.ObjetoDeElemento(e.id) == null) continue;
            Nodo a = visor.Modelo.NodoPorId(e.n1);
            Nodo b = visor.Modelo.NodoPorId(e.n2);
            if (a == null || b == null) continue;
            if (!AjustesVista.ElementoEnCotaVisible(a.z, b.z)) continue;
            if (qa != null && !qa.NivelVisible(Mathf.Min(a.z, b.z))) continue;
            lista.Add(e);
        }
        return lista;
    }

    static float[] Magnitud(EsfuerzosS4 s, string m)
    {
        if (s == null) return null;
        switch (m)
        {
            case "N": return s.N;
            case "Vy": return s.Vy;
            case "Vz": return s.Vz;
            case "T": return s.T;
            case "Mz": return s.Mz;
            case "wy": return Repartida(s, 1);
            case "wz": return Repartida(s, 2);
            default: return s.My;
        }
    }

    /// La carga repartida es constante a lo largo de la barra: se repite en
    /// cada estacion para que el dibujo de siempre la trate igual que a un
    /// esfuerzo. w del JSON: 0 = wx, 1 = wy, 2 = wz, en ejes locales.
    static float[] Repartida(EsfuerzosS4 s, int componente)
    {
        if (s == null || s.x == null || s.w == null || s.w.Length < 3) return null;
        var v = new float[s.x.Length];
        for (int k = 0; k < v.Length; k++) v[k] = s.w[componente];
        return v;
    }

    /// Hacia donde se corre la curva, en coordenadas de Unity, y con que
    /// signo. My, Vz, N y T van en z local; Mz y Vy en y local. Mz lleva
    /// el signo cambiado para quedar del lado traccionado (encabezado de
    /// VisorSemana04.cs). Los ejes vienen del modelo en coordenadas de
    /// OpenSees y se pasan a Unity con el mismo swap que las posiciones.
    static bool DireccionDeDibujo(Elemento e, string m, out Vector3 dir, out float signo)
    {
        bool enY = EjeDeDibujo(m) == "Mz";
        float[] v = enY ? e.localY : e.localZ;
        signo = (m == "Mz") ? -1f : 1f;
        dir = Vector3.zero;
        if (v == null || v.Length < 3) return false;
        dir = Ejes.AUnity(v[0], v[1], v[2]).normalized;
        return dir.sqrMagnitude > 0.5f;
    }

    void AgregarDiagrama(Elemento e, EsfuerzosS4 s, float escala,
                         Malla positivo, Malla negativo, Lineas contorno)
    {
        float[] v = Magnitud(s, magnitud);
        if (v == null || s.x == null || v.Length < 2 || v.Length != s.x.Length) return;
        Nodo na = visor.Modelo.NodoPorId(e.n1);
        Nodo nb = visor.Modelo.NodoPorId(e.n2);
        if (na == null || nb == null) return;
        Vector3 dir;
        float signo;
        if (!DireccionDeDibujo(e, magnitud, out dir, out signo)) return;

        Vector3 pa = Ejes.PosicionDe(na), pb = Ejes.PosicionDe(nb);
        float L = s.x[s.x.Length - 1];
        if (L <= 1e-6f) return;

        // El color dice el signo del esfuerzo; el lado lo dice la
        // convencion de dibujo. Por eso se guardan los dos.
        float crudoAnt = v[0];
        Vector3 baseAnt = pa;
        Vector3 puntaAnt = pa + dir * (signo * v[0] * escala);
        contorno.Agregar(baseAnt, puntaAnt);

        for (int k = 1; k < v.Length; k++)
        {
            float crudo = v[k];
            Vector3 baseK = Vector3.Lerp(pa, pb, s.x[k] / L);
            Vector3 puntaK = baseK + dir * (signo * crudo * escala);

            if (crudoAnt * crudo >= 0f)
            {
                Malla malla = (crudoAnt + crudo) >= 0f ? positivo : negativo;
                malla.Cuadrilatero(baseAnt, baseK, puntaK, puntaAnt);
            }
            else
            {
                // Cambia de signo dentro del tramo: se parte en el cero de
                // la recta entre las dos estaciones, cada mitad con su color.
                float t = crudoAnt / (crudoAnt - crudo);
                Vector3 cero = Vector3.Lerp(baseAnt, baseK, t);
                (crudoAnt > 0f ? positivo : negativo).Triangulo(baseAnt, cero, puntaAnt);
                (crudo > 0f ? positivo : negativo).Triangulo(cero, baseK, puntaK);
            }
            contorno.Agregar(puntaAnt, puntaK);
            crudoAnt = crudo;
            baseAnt = baseK;
            puntaAnt = puntaK;
        }
        contorno.Agregar(pb, puntaAnt);
        contorno.Agregar(pa, pb);
    }

    void Crear(Mesh malla, Color color)
    {
        if (malla == null) return;
        var go = new GameObject(malla.name);
        go.AddComponent<MeshFilter>().sharedMesh = malla;
        go.AddComponent<MeshRenderer>().sharedMaterial = MaterialDe(color);
        creados.Add(go);
    }

    Material MaterialDe(Color color)
    {
        Material mat;
        if (materiales.TryGetValue(color, out mat)) return mat;
        // El Unlit de URP esta en la lista de shaders que ConstruirApp
        // mete siempre en la build; si no esta, el del visor.
        Shader sh = Shader.Find("Universal Render Pipeline/Unlit");
        if (sh == null) sh = VisorEstructura.ShaderCompatible();
        mat = new Material(sh);
        mat.color = color;
        if (mat.HasProperty("_BaseColor")) mat.SetColor("_BaseColor", color);
        materiales[color] = mat;
        return mat;
    }

    // ------------------------------------------------------------
    // Etiquetas de la barra seleccionada: el valor en i, en j y el
    // mayor del tramo con su x.
    // ------------------------------------------------------------
    void EtiquetasDe(Elemento e, EsfuerzosS4 s, float escala)
    {
        float[] v = Magnitud(s, magnitud);
        if (v == null || s.x == null || v.Length != s.x.Length || v.Length == 0) return;
        Nodo na = visor.Modelo.NodoPorId(e.n1);
        Nodo nb = visor.Modelo.NodoPorId(e.n2);
        Vector3 dir;
        float signo;
        if (na == null || nb == null || !DireccionDeDibujo(e, magnitud, out dir, out signo)) return;

        Vector3 pa = Ejes.PosicionDe(na), pb = Ejes.PosicionDe(nb);
        float L = s.x[s.x.Length - 1];
        string u = UnidadDe(magnitud);
        int ultimo = v.Length - 1;

        int kMax = 0;
        for (int k = 1; k < v.Length; k++)
            if (Mathf.Abs(v[k]) > Mathf.Abs(v[kMax])) kMax = k;

        EtiquetaEn(pa, dir, signo * v[0] * escala, $"{magnitud} i = {F(v[0], "0.0")} {u}");
        EtiquetaEn(pb, dir, signo * v[ultimo] * escala, $"{magnitud} j = {F(v[ultimo], "0.0")} {u}");
        if (kMax != 0 && kMax != ultimo && L > 1e-6f)
        {
            Vector3 bk = Vector3.Lerp(pa, pb, s.x[kMax] / L);
            EtiquetaEn(bk, dir, signo * v[kMax] * escala,
                       $"max {F(v[kMax], "0.0")} {u} en x = {F(s.x[kMax], "0.00")} m");
        }
    }

    void EtiquetaEn(Vector3 baseP, Vector3 dir, float desplazamiento, string texto)
    {
        // Un poco mas alla de la punta, para no quedar encima de la malla.
        float extra = desplazamiento >= 0f ? 0.35f : -0.35f;
        var go = new GameObject("Etiqueta_S4");
        go.transform.position = baseP + dir * (desplazamiento + extra);
        TextMesh tm = go.AddComponent<TextMesh>();
        tm.text = texto;
        tm.characterSize = 0.14f;
        tm.fontSize = 60;
        tm.color = colorEtiqueta;
        tm.anchor = TextAnchor.MiddleCenter;
        go.AddComponent<MirarCamara>();
        creados.Add(go);
    }

    static string UnidadDe(string m)
    {
        if (m == "wy" || m == "wz") return "kN/m";
        return (m == "N" || m == "Vy" || m == "Vz") ? "kN" : "kN*m";
    }

    // ------------------------------------------------------------
    // Acumuladores de geometria
    // ------------------------------------------------------------
    class Malla
    {
        readonly List<Vector3> v = new List<Vector3>();
        readonly List<int> t = new List<int>();

        /// Las dos caras, con vertices propios cada una: compartirlos
        /// haria que las normales se anularan.
        public void Triangulo(Vector3 a, Vector3 b, Vector3 c)
        {
            int i = v.Count;
            v.Add(a); v.Add(b); v.Add(c);
            t.Add(i); t.Add(i + 1); t.Add(i + 2);
            i = v.Count;
            v.Add(a); v.Add(c); v.Add(b);
            t.Add(i); t.Add(i + 1); t.Add(i + 2);
        }

        public void Cuadrilatero(Vector3 a, Vector3 b, Vector3 c, Vector3 d)
        {
            Triangulo(a, b, c);
            Triangulo(a, c, d);
        }

        public Mesh Construir(string nombre)
        {
            if (v.Count == 0) return null;
            var m = new Mesh { name = nombre };
            if (v.Count > 65000) m.indexFormat = IndexFormat.UInt32;
            m.SetVertices(v);
            m.SetTriangles(t, 0);
            m.RecalculateNormals();
            m.RecalculateBounds();
            return m;
        }
    }

    class Lineas
    {
        readonly List<Vector3> v = new List<Vector3>();
        readonly List<int> indices = new List<int>();

        public void Agregar(Vector3 a, Vector3 b)
        {
            int k = v.Count;
            v.Add(a); v.Add(b);
            indices.Add(k); indices.Add(k + 1);
        }

        public Mesh Construir(string nombre)
        {
            if (v.Count == 0) return null;
            var m = new Mesh { name = nombre };
            if (v.Count > 65000) m.indexFormat = IndexFormat.UInt32;
            m.SetVertices(v);
            m.SetIndices(indices, MeshTopology.Lines, 0);
            m.RecalculateBounds();
            return m;
        }
    }
}
