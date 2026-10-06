/*
================================================================
  VisorPersona.Deformada.cs  --  lo que la persona le HACE al edificio
================================================================
  VisorPersona.cs dice a que elemento le llega el peso de la persona.
  Esta parte muestra, mientras camina, la DEFORMADA que produce: el
  edificio entero y la elastica de la viga cargada, con la persona
  hundiendose con ella.

  ----------------------------------------------------------------
  POR QUE NO ES CALCULO EN C#
  ----------------------------------------------------------------
  python semana05_lab/influencias_persona.py <ed> resuelve en OpenSees
  UNA carga unitaria por cada nodo que puede recibir a la persona (Fz =
  1 kN hacia abajo, Mx y My = 1 kN m) y las deja en
  StreamingAssets/influencias.json. El modelo es lineal, asi que la
  carga P en la abscisa alfa de una viga es la suma de a lo mas SEIS de
  esos casos, con los pesos de Hermite (las fuerzas nodales equivalentes
  que OpenSees ensambla para eleLoad -beamPoint). Es la misma licencia
  que los sliders del LAB 5 (CLAUDE.md seccion 6): combinar casos ya
  resueltos.

  Dentro de la viga cargada se suma la flecha biempotrada: Python
  exporta la flexibilidad L^3/(E I) de cada viga y aca solo se evalua
  la forma ADIMENSIONAL phi(xi, alfa). E e I no entran al C#.

  Las copias de las formulas (N1..N4, FormaLocal, los seis Sumar() y
  UzEn) las LEE el bloque [3] de influencias_persona.py y las compara
  con las de Python: si se cambia una linea aca, la suite lo dice.

  ----------------------------------------------------------------
  CONTRATO
  ----------------------------------------------------------------
  - Lee influencias.json con LectorStreaming y lo cruza con el modelo
    por su huella (info.n_nodos, info.n_elementos), como el relieve.
  - Deformada con la API de CONTRATO.md 2.3: la pone al moverse (eso
    es pedirla) y la quita SOLO si sigue siendo la suya.
  - Al caminar se aplica a lo mas cada INTERVALO_S: AplicarDeformada
    rehace todo el edificio.
================================================================
*/

using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

// ================================================================
// CLASES DEL JSON (influencias.json). Un campo por linea de clase y
// sin metodos: influencias_persona.py [4] las compara con el JSON.
// ================================================================
[Serializable]
public class InfluenciasPersona
{
    public InfoInfluencias info;
    public GrupoInfluencias[] grupos;
    public CasoInfluencia[] casos;
    public ReceptorPersona[] receptores;
}

[Serializable]
public class InfoInfluencias
{
    public string edificio, generado_por, unidades, _por_que;
    public string _supuesto_receptor, _supuesto_punto_en_la_viga, _supuesto_muro, _supuesto_P;
    public int n_nodos, n_elementos, n_casos;
    public float P_por_defecto_kN, escala_deformada, largo_dibujo_m, segundos_opensees;
    public float escala_momento, largo_momento_m;
}

[Serializable]
public class GrupoInfluencias
{
    public int[] nodos;
}

[Serializable]
public class CasoInfluencia
{
    public int nodo, grupo;
    public string gdl, datos;
    public float escala_t, escala_r;
    public int[] elementos;
    public float escala_f, escala_m;
    public string fuerzas;
}

[Serializable]
public class ReceptorPersona
{
    public int elemento, nodo, n1, n2;
    public string tipo;
    public float z, L, flex, dx, dy;
    public int[] elementos_m;
}

public partial class VisorPersona
{
    const string ARCHIVO_INFLUENCIAS = "influencias.json";
    const int GDL_FZ = 0, GDL_MX = 1, GDL_MY = 2;
    const float INTERVALO_S = 0.08f;          // al caminar: a lo mas ~12 redibujos por segundo
    const int TRAMOS_ELASTICA = 24;
    static readonly Color COLOR_ELASTICA = new Color(1.00f, 0.20f, 0.60f);

    // --- lo leido ---
    InfluenciasPersona influencias;
    string estadoInfluencias = "";
    object modeloDeInfluencias;               // el visor.Modelo para el que se pidio
    readonly Dictionary<long, int> indiceCaso = new Dictionary<long, int>();
    readonly Dictionary<long, float[]> decodificados = new Dictionary<long, float[]>();
    readonly Dictionary<int, List<ReceptorPersona>> receptoresPorElemento = new Dictionary<int, List<ReceptorPersona>>();
    int[][] posGrupo;                         // por grupo: indice del nodo en visor.Modelo.nodos
    float[] acum;

    // --- lo que se muestra ---
    bool verDeformada = true;
    bool deformadaPuesta;
    bool deformadaPendiente;
    float ultimoAplicado = -10f;
    float factorPrevio;
    float escalaPersona = -1f;
    List<DespNodo> deformadaPersona;
    ReceptorPersona recActual;
    float alfaActual, pesoAplicado, uzCarga, mayorMm, msUltima;
    int nodoMayor = -1, casosUsados;

    // ============================================================
    // LEER influencias.json
    // ============================================================
    /// Lo pide Poner(): la primera vez y cada vez que cambia el modelo.
    void PrepararInfluencias()
    {
        if (!Listo() || ReferenceEquals(modeloDeInfluencias, visor.Modelo)) return;
        modeloDeInfluencias = visor.Modelo;
        influencias = null;
        indiceCaso.Clear();
        decodificados.Clear();
        receptoresPorElemento.Clear();
        estadoInfluencias = "Leyendo " + ARCHIVO_INFLUENCIAS + "...";
        StartCoroutine(LeerInfluencias(visor.Modelo, visor.Modelo.nodos.Count, visor.Modelo.elementos.Count));
    }

    IEnumerator LeerInfluencias(object pedido, int nNodos, int nElementos)
    {
        string texto = null, error = null;
        yield return LectorStreaming.Leer(ARCHIVO_INFLUENCIAS, t => texto = t, e => error = e);
        if (!ReferenceEquals(pedido, modeloDeInfluencias)) yield break;   // llego otro modelo
        InfluenciasPersona t2 = null;
        if (error == null)
        {
            try { t2 = JsonUtility.FromJson<InfluenciasPersona>(texto); }
            catch (Exception ex) { error = "no se pudo leer: " + ex.Message; }
        }
        if (error != null || t2 == null || t2.info == null || t2.casos == null || t2.receptores == null)
        {
            estadoInfluencias = "Sin deformada: " + (error ?? ARCHIVO_INFLUENCIAS + " viene vacio")
                + ". Se arma con python semana05_lab/influencias_persona.py <edificio> y se copia con "
                + "lanzar_unity.py sincronizar <edificio>.";
            yield break;
        }
        if (t2.info.n_nodos != nNodos || t2.info.n_elementos != nElementos)
        {
            estadoInfluencias = string.Format("Sin deformada: {0} es de '{1}' ({2} nodos, {3} elementos) y el "
                + "modelo tiene {4} nodos y {5} elementos. Se copia con lanzar_unity.py sincronizar <edificio>.",
                ARCHIVO_INFLUENCIAS, t2.info.edificio, t2.info.n_nodos, t2.info.n_elementos, nNodos, nElementos);
            yield break;
        }
        var idx = new Dictionary<int, int>();
        for (int i = 0; i < visor.Modelo.nodos.Count; i++) idx[visor.Modelo.nodos[i].id] = i;
        posGrupo = new int[t2.grupos.Length][];
        for (int g = 0; g < t2.grupos.Length; g++)
        {
            int[] ns = t2.grupos[g].nodos;
            posGrupo[g] = new int[ns.Length];
            for (int i = 0; i < ns.Length; i++)
            {
                int m;
                posGrupo[g][i] = idx.TryGetValue(ns[i], out m) ? m : -1;
            }
        }
        for (int c = 0; c < t2.casos.Length; c++) indiceCaso[Clave(t2.casos[c].nodo, Gdl(t2.casos[c].gdl))] = c;
        foreach (ReceptorPersona r in t2.receptores)
        {
            List<ReceptorPersona> l;
            if (!receptoresPorElemento.TryGetValue(r.elemento, out l))
                receptoresPorElemento[r.elemento] = l = new List<ReceptorPersona>();
            l.Add(r);
        }
        acum = new float[6 * visor.Modelo.nodos.Count];
        influencias = t2;
        if (escalaPersona <= 0f) escalaPersona = t2.info.escala_deformada;
        estadoInfluencias = string.Format(CultureInfo.InvariantCulture,
            "{0} casos unitarios de '{1}', resueltos por OpenSees en Python ({2}) en {3:F0} s.",
            t2.casos.Length, t2.info.edificio, t2.info.generado_por, t2.info.segundos_opensees);
        if (puesta) PedirDeformadaPersona();
    }

    static long Clave(int nodo, int gdl) { return (long)nodo * 4 + gdl; }

    static int Gdl(string g) { return g == "Fz" ? GDL_FZ : g == "Mx" ? GDL_MX : GDL_MY; }

    /// Los desplazamientos de UN caso, en el orden de los nodos de su grupo.
    float[] CasoDecodificado(int nodo, int gdl, out int grupo)
    {
        grupo = -1;
        long k = Clave(nodo, gdl);
        int ic;
        if (!indiceCaso.TryGetValue(k, out ic)) return null;
        CasoInfluencia c = influencias.casos[ic];
        grupo = c.grupo;
        float[] u;
        if (decodificados.TryGetValue(k, out u)) return u;
        byte[] b = Convert.FromBase64String(c.datos);
        u = new float[b.Length / 2];
        for (int i = 0; i < u.Length; i++)
        {
            short q = (short)(b[2 * i] | (b[2 * i + 1] << 8));
            u[i] = q * ((i % 6) < 3 ? c.escala_t : c.escala_r);
        }
        decodificados[k] = u;
        return u;
    }

    ReceptorPersona ReceptorDe(int elemento, float z)
    {
        List<ReceptorPersona> l;
        if (!receptoresPorElemento.TryGetValue(elemento, out l)) return null;
        foreach (ReceptorPersona r in l) if (Mathf.Abs(r.z - z) < 0.02f) return r;
        return null;
    }

    // ============================================================
    // LAS FORMULAS (copias de influencias_persona.py; su bloque [3]
    // lee estas lineas y las compara con las de Python)
    // ============================================================
    static float N1(float a) { return 1f - 3f * a * a + 2f * a * a * a; }
    static float N2(float a) { return a - 2f * a * a + a * a * a; }
    static float N3(float a) { return 3f * a * a - 2f * a * a * a; }
    static float N4(float a) { return -a * a + a * a * a; }

    /// La flecha de la viga biempotrada con la carga en alfa, sin unidades
    /// (se multiplica por P L^3/EI, que trae el JSON como flex).
    static float FormaLocal(float xi, float alfa)
    {
        if (xi > alfa) { xi = 1f - xi; alfa = 1f - alfa; }
        return (1f - alfa) * (1f - alfa) * xi * xi * (3f * alfa - (1f + 2f * alfa) * xi) / 6f;
    }

    /// uz (m) en xi de la viga cargada en a: Hermite de sus nodos en el
    /// plano vertical de la viga mas la flecha local.
    static float UzEn(ReceptorPersona r, DespNodo di, DespNodo dj, float xi, float a, float P)
    {
        return N1(xi) * di.uz - N2(xi) * r.L * (-r.dy * di.rx + r.dx * di.ry)
             + N3(xi) * dj.uz - N4(xi) * r.L * (-r.dy * dj.rx + r.dx * dj.ry)
             - P * r.flex * FormaLocal(xi, a);
    }

    /// La deformada de la carga P en a del receptor r, en acum.
    /// La deformada de la carga P en a del receptor r, en acum, y los
    /// esfuerzos de extremo de sus barras en fuerzasPersona: los MISMOS
    /// pesos para las dos cosas.
    void Combinar(ReceptorPersona r, float a, float P)
    {
        Array.Clear(acum, 0, acum.Length);
        casosUsados = 0;
        PrepararFuerzas(r);                 // VisorPersona.Momentos.cs
        if (r.tipo == "nodo")
        {
            Sumar(r.nodo, GDL_FZ, P);
            return;
        }
        Sumar(r.n1, GDL_FZ, P * N1(a));
        Sumar(r.n1, GDL_MX, P * r.L * N2(a) * -r.dy);
        Sumar(r.n1, GDL_MY, P * r.L * N2(a) * r.dx);
        Sumar(r.n2, GDL_FZ, P * N3(a));
        Sumar(r.n2, GDL_MX, P * r.L * N4(a) * -r.dy);
        Sumar(r.n2, GDL_MY, P * r.L * N4(a) * r.dx);
        float[] propia;
        if (fuerzasPersona != null && fuerzasPersona.TryGetValue(r.elemento, out propia))
            SumarEmpotramiento(propia, r, a, P);
    }

    /// Lo que la carga P en a le agrega al localForce de SU viga: las
    /// fuerzas de empotramiento perfecto, P por N1..N4 (Vz_i, My_i, Vz_j, My_j).
    static void SumarEmpotramiento(float[] f, ReceptorPersona r, float a, float P)
    {
        f[2] += P * N1(a);
        f[4] += -P * r.L * N2(a);
        f[8] += P * N3(a);
        f[10] += -P * r.L * N4(a);
    }

    /// My(x) de una barra con extremos f; P (kN, hacia abajo) en a si es la
    /// cargada, 0 si no. Lineal entre extremos mas el quiebre de P.
    static float MyEn(float[] f, float x, float a, float P) { return -(f[4] + x * f[2] - P * Mathf.Max(0f, x - a)); }

    /// Mz(x): sin carga en y local, lineal entre extremos.
    static float MzEn(float[] f, float x) { return -(f[5] - x * f[1]); }

    void Sumar(int nodo, int gdl, float w)
    {
        int g;
        float[] u = CasoDecodificado(nodo, gdl, out g);
        if (u == null) return;
        int[] pos = posGrupo[g];
        for (int i = 0; i < pos.Length; i++)
        {
            int m = pos[i];
            if (m < 0) continue;
            int k = 6 * i, q = 6 * m;
            for (int d = 0; d < 6; d++) acum[q + d] += w * u[k + d];
        }
        SumarFuerzas(nodo, gdl, w);         // VisorPersona.Momentos.cs
        casosUsados++;
    }

    /// Fraccion de la viga donde cae la persona: su proyeccion sobre el eje.
    float Proyeccion(ReceptorPersona r)
    {
        Nodo a = visor.Modelo.NodoPorId(r.n1);
        if (a == null || r.L <= 0f) return 0f;
        return Mathf.Clamp01(((x - a.x) * r.dx + (y - a.y) * r.dy) / r.L);
    }

    // ============================================================
    // APLICAR
    // ============================================================
    void PedirDeformadaPersona() { deformadaPendiente = true; }

    /// Lo llama Update en cada cuadro: aplica lo pedido si ya paso INTERVALO_S.
    void AplicarDeformadaSiToca()
    {
        if (!deformadaPendiente || Time.unscaledTime - ultimoAplicado < INTERVALO_S) return;
        deformadaPendiente = false;
        ultimoAplicado = Time.unscaledTime;
        if (!puesta || ultimo == null || influencias == null || modeloEditado) return;
        if (!verDeformada && !verMomentos) { QuitarDeformadaPersona(); redibujar = true; return; }
        ReceptorPersona r = ultimo.receptora >= 0 ? ReceptorDe(ultimo.receptora, ultimo.z) : null;
        // Fuera de toda losa no carga nada: se quita la deformada (vuelve al pisar losa).
        if (r == null) { QuitarDeformadaPersona(); return; }

        float t0 = Time.realtimeSinceStartup;
        float a = r.tipo == "viga" ? Proyeccion(r) : 0f;
        Combinar(r, a, pesoKN);
        var lista = new List<DespNodo>(visor.Modelo.nodos.Count);
        float mayor = 0f;
        int nMayor = -1;
        for (int i = 0; i < visor.Modelo.nodos.Count; i++)
        {
            int q = 6 * i;
            var d = new DespNodo
            {
                id = visor.Modelo.nodos[i].id,
                ux = acum[q], uy = acum[q + 1], uz = acum[q + 2],
                rx = acum[q + 3], ry = acum[q + 4], rz = acum[q + 5],
            };
            lista.Add(d);
            float m = Mathf.Sqrt(d.ux * d.ux + d.uy * d.uy + d.uz * d.uz);
            if (m > mayor) { mayor = m; nMayor = d.id; }
        }
        recActual = r;
        alfaActual = a;
        pesoAplicado = pesoKN;
        deformadaPersona = lista;
        uzCarga = r.tipo == "viga" ? UzEn(r, DespDe(r.n1), DespDe(r.n2), a, a, pesoAplicado) : DespDe(r.nodo).uz;
        mayorMm = mayor * 1000f;
        nodoMayor = nMayor;
        CerrarMomentos(r, a, pesoAplicado);   // VisorPersona.Momentos.cs
        msUltima = (Time.realtimeSinceStartup - t0) * 1000f;

        // Solo los momentos: no se toca la deformada del visor, y como
        // nada redibuja, se pide redibujar la persona.
        if (!verDeformada)
        {
            QuitarSoloDeformada();
            redibujar = true;
            return;
        }
        if (!deformadaPuesta)
        {
            factorPrevio = visor.factorEscala;
            deformadaPuesta = true;
        }
        visor.mostrarDeformada = true;
        visor.factorEscala = escalaPersona;
        // La flecha DENTRO de la viga cargada no esta en ningun nodo: se la
        // pasa al visor para que la viga (tambien la de la vista realista)
        // se doble de verdad, no solo el resaltado.
        visor.FlechaEnVano = FlechaPersona;
        visor.AplicarDeformada(lista);      // redibuja: AlRedibujar rehace la persona y la elastica
    }

    /// La flecha biempotrada de la viga cargada, para VisorEstructura.CurvaDe
    /// (m, ejes OpenSees). Cero en cualquier otra barra, o si la deformada
    /// que se dibuja ya no es la de la persona.
    Vector3 FlechaPersona(int id, float xi)
    {
        if (recActual == null || recActual.tipo != "viga" || id != recActual.elemento) return Vector3.zero;
        if (!DeformadaPersonaSigue()) return Vector3.zero;
        return new Vector3(0f, 0f, -pesoAplicado * recActual.flex * FormaLocal(xi, alfaActual));
    }

    void SoltarFlechaEnVano()
    {
        if (visor != null && visor.FlechaEnVano == (Func<int, float, Vector3>)FlechaPersona) visor.FlechaEnVano = null;
    }

    DespNodo DespDe(int id)
    {
        if (deformadaPersona != null)
            foreach (DespNodo d in deformadaPersona) if (d.id == id) return d;
        return new DespNodo { id = id };
    }

    /// true si lo que dibuja el visor sigue siendo esta deformada (la misma
    /// prueba que VisorCargaMovil.MiDeformadaSigue).
    bool DeformadaPersonaSigue()
    {
        if (!deformadaPuesta || !visor.mostrarDeformada || !visor.HayDeformada || deformadaPersona == null) return false;
        Nodo n = visor.Modelo.NodoPorId(nodoMayor);
        if (n == null) return true;
        DespNodo d = DespDe(nodoMayor);
        Vector3 esperada = Ejes.PosicionDeformada(n, d.ux, d.uy, d.uz, visor.factorEscala);
        return (visor.PosicionActual(n) - esperada).sqrMagnitude < 1e-8f;
    }

    /// Quita la deformada SOLO si sigue siendo la suya (CONTRATO.md 2.3).
    void QuitarDeformadaPersona()
    {
        deformadaPendiente = false;
        if (!deformadaPuesta || visor == null) { recActual = null; SoltarFlechaEnVano(); return; }
        bool mia = DeformadaPersonaSigue();
        recActual = null;
        SoltarFlechaEnVano();
        deformadaPuesta = false;
        if (!mia) return;
        visor.LimpiarDeformada();
        visor.factorEscala = factorPrevio;
        visor.Redibujar();
    }

    /// Quita la deformada del visor (si sigue siendo suya) pero deja lo
    /// calculado: los momentos se siguen mostrando.
    void QuitarSoloDeformada()
    {
        SoltarFlechaEnVano();
        if (!deformadaPuesta || visor == null) return;
        bool mia = DeformadaPersonaSigue();
        deformadaPuesta = false;
        if (!mia) return;
        visor.LimpiarDeformada();
        visor.factorEscala = factorPrevio;
        visor.Redibujar();
    }

    /// Al editar el modelo el editor ya limpio la deformada: solo se
    /// devuelve la escala y se olvida (los casos son del modelo original).
    void SoltarDeformadaPersona()
    {
        if (deformadaPuesta && visor != null) visor.factorEscala = factorPrevio;
        deformadaPuesta = false;
        deformadaPendiente = false;
        recActual = null;
        SoltarFlechaEnVano();
    }

    // ============================================================
    // DIBUJO
    // ============================================================
    bool DeformadaVisible()
    {
        return recActual != null && deformadaPuesta && visor.mostrarDeformada && DeformadaPersonaSigue();
    }

    /// Cuanto baja, dibujado, el punto donde esta parada (m, ya escalado).
    float DescensoDibujado()
    {
        return DeformadaVisible() ? uzCarga * visor.factorEscala : 0f;
    }

    /// La elastica de la viga cargada, con la flecha local, a la altura
    /// del resaltado. false si no hay (sin deformada, o es un muro).
    bool DibujarElastica(int id, Vector3 alto, float grosor)
    {
        if (!DeformadaVisible() || recActual.tipo != "viga" || recActual.elemento != id) return false;
        Nodo a = visor.Modelo.NodoPorId(recActual.n1), b = visor.Modelo.NodoPorId(recActual.n2);
        if (a == null || b == null) return false;
        DespNodo di = DespDe(a.id), dj = DespDe(b.id);
        float esc = visor.factorEscala;
        var xs = new List<float>();
        for (int k = 0; k <= TRAMOS_ELASTICA; k++) xs.Add(k / (float)TRAMOS_ELASTICA);
        xs.Add(alfaActual);
        xs.Sort();
        GameObject go = new GameObject("SQ4_Elastica");
        LineRenderer lr = go.AddComponent<LineRenderer>();
        lr.positionCount = xs.Count;
        for (int k = 0; k < xs.Count; k++)
        {
            float xi = xs[k];
            // En planta, lineal: en un diafragma rigido la viga se traslada y
            // gira entera. En vertical, Hermite mas la flecha local (UzEn).
            float ux = (1f - xi) * di.ux + xi * dj.ux, uy = (1f - xi) * di.uy + xi * dj.uy;
            float uz = UzEn(recActual, di, dj, xi, alfaActual, pesoAplicado);
            lr.SetPosition(k, Ejes.AUnity(a.x + xi * (b.x - a.x) + ux * esc,
                                          a.y + xi * (b.y - a.y) + uy * esc,
                                          a.z + xi * (b.z - a.z) + uz * esc) + alto);
        }
        lr.startWidth = lr.endWidth = grosor;
        lr.sharedMaterial = MaterialDe(COLOR_ELASTICA);
        lr.shadowCastingMode = UnityEngine.Rendering.ShadowCastingMode.Off;
        creados.Add(go);
        return true;
    }

    /// El punto donde la carga entra a la viga (o el nodo del muro), deformado.
    bool PuntoDeCarga(out Vector3 p)
    {
        p = Vector3.zero;
        if (!DeformadaVisible()) return false;
        float esc = visor.factorEscala;
        if (recActual.tipo == "nodo")
        {
            Nodo n = visor.Modelo.NodoPorId(recActual.nodo);
            if (n == null) return false;
            p = visor.PosicionActual(n);
            return true;
        }
        Nodo a = visor.Modelo.NodoPorId(recActual.n1), b = visor.Modelo.NodoPorId(recActual.n2);
        if (a == null || b == null) return false;
        DespNodo di = DespDe(a.id), dj = DespDe(b.id);
        float t = alfaActual;
        p = Ejes.AUnity(a.x + t * (b.x - a.x) + ((1f - t) * di.ux + t * dj.ux) * esc,
                        a.y + t * (b.y - a.y) + ((1f - t) * di.uy + t * dj.uy) * esc,
                        a.z + t * (b.z - a.z) + uzCarga * esc);
        return true;
    }

    // ============================================================
    // PANEL
    // ============================================================
    /// El peso, en escala logaritmica de 0.3 a 300 kN, y dos atajos.
    void PanelPeso(GUIStyle boton)
    {
        float l = GUILayout.HorizontalSlider(Mathf.Log(pesoKN), Mathf.Log(0.3f), Mathf.Log(300f));
        float nuevo = Redondear2(Mathf.Exp(l));
        GUILayout.BeginHorizontal();
        if (GUILayout.Button("Persona 0.80 kN", boton)) nuevo = 0.80f;
        float P0 = influencias != null ? influencias.info.P_por_defecto_kN : 100f;
        if (GUILayout.Button("Carga movil " + F(P0, "0") + " kN", boton)) nuevo = P0;
        GUILayout.EndHorizontal();
        if (Mathf.Abs(nuevo - pesoKN) > 1e-4f * pesoKN)
        {
            pesoKN = nuevo;
            PedirDeformadaPersona();
        }
        PanelPersonaje(PanelUI.Tenue ?? GUI.skin.label);    // VisorPersona.Personaje.cs
    }

    static float Redondear2(float v)
    {
        if (v <= 0f) return v;
        float p = Mathf.Pow(10f, Mathf.Floor(Mathf.Log10(v)) - 1f);
        return Mathf.Round(v / p) * p;
    }

    void PanelDeformada(GUIStyle texto, GUIStyle tenue, GUIStyle aviso, GUIStyle boton)
    {
        GUILayout.Space(PanelUI.Px(4f));
        bool quiere = GUILayout.Toggle(verDeformada, "  Ver la deformada que produce (al instante)");
        // El cambio se difiere: hecho aca, este mismo evento dibujaria menos
        // controles que su Layout (la trampa de IMGUI de CLAUDE.md).
        if (quiere != verDeformada)
            diferida = () => { verDeformada = quiere; if (!quiere) QuitarSoloDeformada(); PedirDeformadaPersona(); };
        if (influencias == null)
        {
            GUILayout.Label(estadoInfluencias.Length > 0 ? estadoInfluencias
                            : "La deformada se lee al poner la persona.",
                            estadoInfluencias.StartsWith("Sin") ? aviso : tenue);
            return;
        }
        float rec = influencias.info.escala_deformada;
        GUILayout.Label($"Escala de dibujo x{F(escalaPersona, "0")} (recomendada x{F(rec, "0")}: con "
                        + $"{F(influencias.info.P_por_defecto_kN, "0")} kN el peor caso se dibuja "
                        + $"{F(influencias.info.largo_dibujo_m, "0.0")} m)", tenue);
        float e = GUILayout.HorizontalSlider(escalaPersona, 1f, 4f * rec);
        if (GUILayout.Button("Volver a la recomendada", boton)) e = rec;
        if (Mathf.Abs(e - escalaPersona) > 1e-3f)
        {
            escalaPersona = Mathf.Round(e);
            PedirDeformadaPersona();
        }
        if (modeloEditado)
        {
            GUILayout.Label("El modelo se edito: los casos unitarios son del original, asi que la "
                            + "deformada de la persona se apago.", aviso);
            return;
        }
        if (!puesta || recActual == null || !verDeformada) return;
        string donde = recActual.tipo == "viga"
            ? $"{Nombre(recActual.elemento)} en a/L = {F(alfaActual, "0.00")} ({F(alfaActual * recActual.L, "0.00")} m "
              + $"de su nodo {recActual.n1}, L = {F(recActual.L, "0.00")} m)"
            : $"el nodo {recActual.nodo} de {Nombre(recActual.elemento)} (carga nodal, como la losa en G)";
        GUILayout.Label($"DEFORMADA: {F(pesoAplicado, "0.##")} kN en {donde}", texto);
        GUILayout.Label($"Flecha bajo la carga: {F(uzCarga * 1000f, "0.000")} mm.  El nodo que mas se "
                        + $"mueve: {F(mayorMm, "0.000")} mm (nodo {nodoMayor}).", texto);
        GUILayout.Label($"Unity sumo {casosUsados} de {influencias.casos.Length} casos unitarios en "
                        + $"{F(msUltima, "0.0")} ms; cada caso lo resolvio OpenSees en Python. La viga "
                        + "cargada (magenta) lleva ademas la flecha biempotrada.", tenue);
    }

    // ============================================================
    // PARA CapturaPersona (fotos y registro, sin tocar el panel)
    // ============================================================
    public bool Captura_InfluenciasListas { get { return influencias != null; } }
    public string Captura_Estado { get { return estadoInfluencias; } }

    /// Pone la persona en el piso dado, en el centro de la region
    /// tributaria mas grande de una viga de ese piso, con peso P.
    public bool Captura_Poner(int indicePiso, float P)
    {
        LeerPisos();
        if (pisos.Count == 0) return false;
        piso = Mathf.Clamp(indicePiso, 0, pisos.Count - 1);
        Poner();
        AreaTributaria mejor = null;
        foreach (AreaTributaria a in visor.Modelo.areas_tributarias)
        {
            if (a == null || a.vertices == null || Mathf.Abs(a.z - pisos[piso]) > 0.02f) continue;
            Elemento e = visor.Modelo.ElementoPorId(a.elemento);
            if (e == null || e.tipo == null || !e.tipo.StartsWith("viga")) continue;
            if (mejor == null || a.area > mejor.area) mejor = a;
        }
        if (mejor == null) return false;
        foreach (List<VerticePlanta> pol in Poligonos(mejor))
        {
            Vector2 c = Centro(pol);
            x = c.x; y = c.y;
            break;
        }
        pesoKN = P;
        Calcular();
        PedirDeformadaPersona();
        return true;
    }

    /// Camina d metros (ejes OpenSees), en pasos chicos como con las flechas.
    public void Captura_Caminar(Vector2 d)
    {
        int n = Mathf.Max(1, Mathf.CeilToInt(d.magnitude / 0.05f));
        for (int k = 0; k < n; k++)
        {
            x += d.x / n; y += d.y / n;
            AlCaminar(d / n);
        }
        Calcular();
        PedirDeformadaPersona();
    }

    public Vector3 Captura_Donde { get { return Ejes.AUnity(x, y, ultimo != null ? ultimo.z : 0f); } }

    /// Rumbo (grados, como el yaw de Unity) de la viga cargada en planta.
    public float Captura_RumboViga
    {
        get { return recActual != null && recActual.tipo == "viga" ? Mathf.Atan2(recActual.dx, recActual.dy) * Mathf.Rad2Deg : 0f; }
    }

    /// Una linea con lo que Unity sumo y dibujo, para cruzarla con Python
    /// (influencias_persona.py --registro). Float de 32 bits en G9.
    public string Captura_Registro()
    {
        if (recActual == null) return "persona: sin deformada (" + estadoInfluencias + ")";
        var ci = CultureInfo.InvariantCulture;
        var sb = new System.Text.StringBuilder();
        sb.AppendFormat(ci, "persona: elemento {0} tipo {1} alfa {2:G9} P {3:G9} uz_carga {4:G9} mayor_mm {5:G9} "
            + "nodo_mayor {6} casos {7} ms {8:F2} escala {9:G9}",
            recActual.elemento, recActual.tipo, alfaActual, pesoAplicado, uzCarga, mayorMm, nodoMayor,
            casosUsados, msUltima, visor.factorEscala);
        float[] fc;
        if (recActual.tipo == "viga" && fuerzasPersona != null && fuerzasPersona.TryGetValue(recActual.elemento, out fc))
            sb.AppendFormat(ci, " M_carga {0:G9}", mCarga);
        foreach (int id in new[] { recActual.n1, recActual.n2, nodoMayor })
        {
            DespNodo d = DespDe(id);
            sb.AppendFormat(ci, " | nodo {0} {1:G9} {2:G9} {3:G9} {4:G9} {5:G9} {6:G9}",
                            id, d.ux, d.uy, d.uz, d.rx, d.ry, d.rz);
        }
        // los esfuerzos de extremo de la viga cargada y de la barra con mas momento
        if (fuerzasPersona != null)
            foreach (int id in new[] { recActual.elemento, barraMayor })
            {
                float[] f;
                if (!fuerzasPersona.TryGetValue(id, out f)) continue;
                sb.Append(" | barra ").Append(id.ToString(ci));
                for (int i = 0; i < 12; i++) sb.Append(' ').Append(f[i].ToString("G9", ci));
            }
        return sb.ToString();
    }
}
