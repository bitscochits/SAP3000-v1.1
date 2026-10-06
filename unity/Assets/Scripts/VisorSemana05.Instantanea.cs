/*
================================================================
  VisorSemana05.Instantanea.cs   (parte de VisorSemana04)
================================================================
  LOS SLIDERS DE LOS CASOS BASE, AL INSTANTE.

  El LAB de la Semana 5 pide que los sliders de los casos base
  actualicen INSTANTANEAMENTE la deformada, los resultados y el punto
  de demanda P-M. El caso LIBRE de VisorSemana04.Superposicion.cs pide
  la combinacion a Python (POST /combinar): es la referencia, pero
  necesita el servidor, espera 0.6 s tras el ultimo movimiento del
  slider y suma la ida y vuelta. Este archivo agrega el caso INSTANT,
  que combina en el momento y sin servidor; sus botones E1..E3 ponen
  los mismos factores que los estados precalculados por Python, para
  compararlos a la vista.

  ----------------------------------------------------------------
  POR QUE ESTO NO ROMPE LA REGLA DE ORO
  ----------------------------------------------------------------
  "Python/OpenSees calcula, el JSON transporta, Unity dibuja."  Aca
  Unity NO resuelve K*u = F: ni arma rigidez, ni invierte nada, ni
  toca el modelo. Hace tres cosas, todas sobre numeros que OpenSees ya
  calculo y que viajaron en semana04.json:

  1. ESCALAR Y SUMAR los cuatro casos base.  u, f y los esfuerzos a lo
     largo de la barra son lineales en lambda porque el modelo es
     elastico y K es la misma: es la superposicion, y Python la
     verifico contra una corrida explicita de OpenSees
     (semana04/verificar_semana04.py bloque [3], y
     semana05/verificar_superposicion.py por cuatro vias).

  2. RETABULAR antes de sumar.  Los casos base no vienen en las mismas
     estaciones: una viga con carga repartida trae 9 puntos en G (220
     de las 378 barras del LT2) y en Q (204), y solo 2 en EX y EY. No se pueden
     sumar indice a indice. Se lleva cada caso a la malla mas fina
     interpolando LINEALMENTE, y eso es exacto, no aproximado: sin carga
     repartida (w = 0) el axial y los cortes son constantes y los
     momentos son rectas, asi que la recta entre los dos extremos pasa
     por el valor de verdad en cualquier punto intermedio.

  3. REHACER LA DEMANDA, que NO es lineal y por eso no se suma.  Del f
     ya combinado salen (P, M) con la misma regla de
     demanda_capacidad.demanda() -- mirar los dos extremos y quedarse
     con el de mayor momento; en columna M = hypot(My, Mz), en muro
     solo el momento de su plano -- y Mn se interpola en la curva P-M
     de su familia, que la calculo Python con fibras y viaja en el
     anexo.  Son comparaciones e interpolaciones sobre datos de Python:
     ninguna propiedad de la seccion se calcula aca.

  Y no se cree por argumento: se comprueba.  CapturaSemana05 mueve
  estos sliders en la app real y deja en registro.txt los numeros que
  Unity calculo (DATO ins.*, float de 32 bits en G9);
  semana05_lab/verificar_instantanea.py --registro los compara contra
  Python, y sin --registro repite el algoritmo en Python sobre mas
  juegos de lambdas. La aritmetica es float32 (JsonUtility, Mathf) y la
  cota del verificador la incluye.

  ----------------------------------------------------------------
  CUANDO ESTO YA NO VALE
  ----------------------------------------------------------------
  La superposicion vale mientras K no cambie.  Si el usuario modifica
  el modelo (borra una barra, cambia una seccion, un apoyo o el
  material), los casos base del anexo son de OTRA estructura y sumarlos
  no significa nada: hay que reanalizar en OpenSees.  Por eso el caso
  INSTANT se marca desactualizado con el mismo aviso que el resto del
  anexo (EventosVisor.ModeloEditado).  La tabla completa de que exige
  reanalisis esta en semana05_lab/CRITERIOS_REANALISIS.md.
================================================================
*/

using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

public partial class VisorSemana04
{
    // ============================================================
    // ESTADO
    // ============================================================

    /// El nombre del caso que arma este archivo.
    public const string CASO_INSTANT = "INSTANT";

    /// Los cuatro factores, en el orden de CASOS_BASE.
    private readonly float[] Ins_lambda = { 1f, 1f, 0f, 0f };

    /// Los casos base, en este orden, tal como los nombra el anexo.
    private static readonly string[] Ins_BASE = { "G", "Q", "EX", "EY" };

    /// Una barra, con los cuatro casos base ya llevados a la MISMA
    /// malla de estaciones. Se arma una vez al cargar el anexo.
    private class Ins_Barra
    {
        public int id;
        public float[] x;                 // la malla comun, de 0 a L
        public float[][] f;               // [caso][12]
        public float[][] w;               // [caso][3]
        public float[][][] mag;           // [caso][magnitud 0..5][estacion]
        public ElementoS4 elemento;       // tipo, familia, momento_en_el_plano
    }

    private readonly List<Ins_Barra> Ins_barras = new List<Ins_Barra>();
    private readonly List<DespNodo> Ins_nodos = new List<DespNodo>();
    private float[][] Ins_uBase;          // [caso][nodo * 6 + gdl]
    private bool Ins_listo;
    private string Ins_aviso = "";

    /// Cuanto tardo la ultima combinacion, en milisegundos.
    private float Ins_msUltima;

    /// Cuantas veces se combino desde que se abrio la app. La captura
    /// lo usa para comprobar que el SEGUNDO movimiento del slider
    /// tambien reemplaza el caso (el error que tuvo tipo = "combinacion").
    private int Ins_version;

    /// El orden de las magnitudes dentro de Ins_Barra.mag.
    private static readonly string[] Ins_MAG = { "N", "Vy", "Vz", "T", "My", "Mz" };

    // ============================================================
    // PREPARACION  (una vez, al cargar el anexo)
    // ============================================================

    /// Deja los cuatro casos base retabulados a una malla comun por
    /// barra. Es lo unico caro, y se hace una sola vez: despues, mover
    /// un slider es multiplicar y sumar.
    private void Ins_Preparar()
    {
        Ins_barras.Clear();
        Ins_nodos.Clear();
        Ins_uBase = null;
        Ins_listo = false;
        Ins_aviso = "";

        if (Anexo == null || Anexo.casos == null)
        {
            Ins_aviso = "todavia no hay anexo cargado";
            return;
        }

        // --- los cuatro casos base tienen que estar ---
        var caso = new CasoS4[Ins_BASE.Length];
        for (int c = 0; c < Ins_BASE.Length; c++)
        {
            caso[c] = Anexo.casos.Find(x => x.nombre == Ins_BASE[c]);
            if (caso[c] == null)
            {
                Ins_aviso = $"el anexo no trae el caso base '{Ins_BASE[c]}'";
                return;
            }
        }

        // --- desplazamientos: la lista de nodos la fija G ---
        var filaPorNodo = new Dictionary<int, int>();
        foreach (DespNodo d in caso[0].desplazamientos)
        {
            filaPorNodo[d.id] = Ins_nodos.Count;
            Ins_nodos.Add(new DespNodo { id = d.id });
        }
        Ins_uBase = new float[Ins_BASE.Length][];
        for (int c = 0; c < Ins_BASE.Length; c++)
        {
            var v = new float[Ins_nodos.Count * 6];
            foreach (DespNodo d in caso[c].desplazamientos)
            {
                int fila;
                if (!filaPorNodo.TryGetValue(d.id, out fila)) continue;
                int k = fila * 6;
                v[k] = d.ux; v[k + 1] = d.uy; v[k + 2] = d.uz;
                v[k + 3] = d.rx; v[k + 4] = d.ry; v[k + 5] = d.rz;
            }
            Ins_uBase[c] = v;
        }

        // --- esfuerzos: una malla comun por barra ---
        var porId = new Dictionary<int, EsfuerzosS4>[Ins_BASE.Length];
        for (int c = 0; c < Ins_BASE.Length; c++)
        {
            porId[c] = new Dictionary<int, EsfuerzosS4>();
            foreach (EsfuerzosS4 s in caso[c].esfuerzos) porId[c][s.id] = s;
        }

        foreach (EsfuerzosS4 sG in caso[0].esfuerzos)
        {
            // La malla mas fina de los cuatro: la de la barra cargada.
            float[] malla = sG.x;
            for (int c = 1; c < Ins_BASE.Length; c++)
            {
                EsfuerzosS4 s;
                if (porId[c].TryGetValue(sG.id, out s) && s.x != null && s.x.Length > malla.Length)
                    malla = s.x;
            }

            var barra = new Ins_Barra
            {
                id = sG.id,
                x = malla,
                f = new float[Ins_BASE.Length][],
                w = new float[Ins_BASE.Length][],
                mag = new float[Ins_BASE.Length][][],
                elemento = ElementoPorId(sG.id),
            };

            for (int c = 0; c < Ins_BASE.Length; c++)
            {
                EsfuerzosS4 s;
                if (!porId[c].TryGetValue(sG.id, out s))
                {
                    barra.f[c] = new float[12];
                    barra.w[c] = new float[3];
                    barra.mag[c] = Ins_Ceros(Ins_MAG.Length, malla.Length);
                    continue;
                }
                barra.f[c] = s.f != null && s.f.Length == 12 ? s.f : new float[12];
                barra.w[c] = s.w != null && s.w.Length == 3 ? s.w : new float[3];
                barra.mag[c] = new float[Ins_MAG.Length][];
                int nOrigen = s.x != null ? s.x.Length : 0;
                for (int m = 0; m < Ins_MAG.Length; m++)
                    barra.mag[c][m] = Ins_ALaMalla(Magnitud(s, Ins_MAG[m]), nOrigen, malla.Length);
            }
            Ins_barras.Add(barra);
        }

        Ins_listo = true;
    }

    private static float[][] Ins_Ceros(int filas, int largo)
    {
        var v = new float[filas][];
        for (int i = 0; i < filas; i++) v[i] = new float[largo];
        return v;
    }

    /// Lleva los valores de un caso a la malla comun, interpolando
    /// linealmente. Exacto cuando la barra no tiene carga repartida en
    /// ese caso (el axial y los cortes son constantes y los momentos
    /// rectas); cuando si la tiene, su malla YA es la fina y se copia.
    ///
    /// SE INTERPOLA POR FRACCION DE INDICE, NO POR x.  Las dos mallas
    /// van de 0 a L y son equiespaciadas -- lo exige y lo comprueba
    /// semana04/verificar_semana04.py, bloque [1] --, asi que el punto i
    /// de una malla de n puntos esta en la fraccion i/(n-1) de la barra,
    /// exactamente. Usar la x del anexo mete su redondeo a 4 decimales
    /// (hasta 5e-5 m) multiplicado por la pendiente del momento, que es
    /// el corte: en la viga 337 bajo G el corte llega a 272 kN, asi que
    /// el error llega a 1.4e-2 kN m (se midieron 1.1e-2), doscientas
    /// veces el redondeo de las fuerzas. Por indice, ese error no existe.
    private static float[] Ins_ALaMalla(float[] valor, int nOrigen, int nDestino)
    {
        var salida = new float[nDestino];
        if (valor == null || valor.Length == 0 || valor.Length != nOrigen) return salida;
        if (nOrigen == nDestino)
        {
            System.Array.Copy(valor, salida, valor.Length);
            return salida;
        }
        if (nOrigen == 1)
        {
            for (int i = 0; i < nDestino; i++) salida[i] = valor[0];
            return salida;
        }
        for (int i = 0; i < nDestino; i++)
        {
            // La misma fraccion de la barra, en indices del origen.
            float p = nDestino == 1 ? 0f : (float)i / (nDestino - 1) * (nOrigen - 1);
            int j = Mathf.Clamp(Mathf.FloorToInt(p), 0, nOrigen - 2);
            float frac = p - j;
            salida[i] = valor[j] + (valor[j + 1] - valor[j]) * frac;
        }
        return salida;
    }

    // ============================================================
    // LA COMBINACION  (cada vez que se mueve un slider)
    // ============================================================

    /// Arma el caso INSTANT con estos cuatro factores y lo registra,
    /// para que el panel, la deformada, los diagramas, la P-M y el mapa
    /// D/C lo muestren como a cualquier otro caso.
    public CasoS4 Ins_Combinar(float[] lam)
    {
        if (!Ins_listo) Ins_Preparar();
        if (!Ins_listo) return null;
        float t0 = Time.realtimeSinceStartup;

        var caso = new CasoS4
        {
            nombre = CASO_INSTANT,
            // TIPO_SUPERPOSICION, no "combinacion": Hook_RegistrarCasoExterno
            // solo REEMPLAZA un caso que ya exista si es de este tipo. Con
            // "combinacion" el primer movimiento del slider registraba INSTANT
            // y todos los siguientes eran rechazados: la deformada, los
            // diagramas y la P-M quedaban congelados en el primer lambda.
            tipo = TIPO_SUPERPOSICION,
            descripcion = Ins_Descripcion(lam),
            factores = new[] { lam[0], lam[1], lam[2], lam[3] },
            desplazamientos = new List<DespNodo>(Ins_nodos.Count),
            esfuerzos = new List<EsfuerzosS4>(Ins_barras.Count),
            demandas = new List<DemandaS4>(),
        };

        // --- desplazamientos: sum(lambda * u) ---
        float mayor = 0f;
        for (int n = 0; n < Ins_nodos.Count; n++)
        {
            int k = n * 6;
            float ux = 0f, uy = 0f, uz = 0f, rx = 0f, ry = 0f, rz = 0f;
            for (int c = 0; c < Ins_BASE.Length; c++)
            {
                float l = lam[c];
                if (l == 0f) continue;
                float[] u = Ins_uBase[c];
                ux += l * u[k]; uy += l * u[k + 1]; uz += l * u[k + 2];
                rx += l * u[k + 3]; ry += l * u[k + 4]; rz += l * u[k + 5];
            }
            caso.desplazamientos.Add(new DespNodo
            {
                id = Ins_nodos[n].id, ux = ux, uy = uy, uz = uz, rx = rx, ry = ry, rz = rz,
            });
            mayor = Mathf.Max(mayor, Mathf.Sqrt(ux * ux + uy * uy + uz * uz));
        }
        caso.max_desplazamiento_mm = mayor * 1000f;

        // --- esfuerzos: sum(lambda * f) y sum(lambda * magnitud) ---
        foreach (Ins_Barra b in Ins_barras)
        {
            var s = new EsfuerzosS4 { id = b.id, x = b.x, f = new float[12], w = new float[3] };
            for (int c = 0; c < Ins_BASE.Length; c++)
            {
                float l = lam[c];
                if (l == 0f) continue;
                for (int i = 0; i < 12; i++) s.f[i] += l * b.f[c][i];
                for (int i = 0; i < 3; i++) s.w[i] += l * b.w[c][i];
            }
            var mag = new float[Ins_MAG.Length][];
            for (int m = 0; m < Ins_MAG.Length; m++)
            {
                var v = new float[b.x.Length];
                for (int c = 0; c < Ins_BASE.Length; c++)
                {
                    float l = lam[c];
                    if (l == 0f) continue;
                    float[] baseM = b.mag[c][m];
                    for (int i = 0; i < v.Length; i++) v[i] += l * baseM[i];
                }
                mag[m] = v;
            }
            s.N = mag[0]; s.Vy = mag[1]; s.Vz = mag[2];
            s.T = mag[3]; s.My = mag[4]; s.Mz = mag[5];
            caso.esfuerzos.Add(s);

            DemandaS4 d = Ins_Demanda(b, s.f);
            if (d != null) caso.demandas.Add(d);
        }

        Ins_msUltima = (Time.realtimeSinceStartup - t0) * 1000f;
        Ins_version++;
        // Sin esto OrigenDe() diria "combinado en Python por
        // semana04/exportar_unity.py", que es falso para este caso.
        Sup_origenes[CASO_INSTANT] = "combinado en Unity (VisorSemana05.Instantanea.cs): escala y suma "
                                   + "los casos base G, Q, EX y EY de " + nombreArchivo + " y rehace la "
                                   + "demanda con la regla de Python; no resuelve nada. Comprobado contra "
                                   + "Python por semana05_lab/verificar_instantanea.py. Factores: "
                                   + Sup_TextoFactores(caso.factores) + ".";
        RegistrarCasoExterno(caso);
        return caso;
    }

    private static string Ins_Descripcion(float[] lam)
    {
        var sb = new System.Text.StringBuilder();
        for (int c = 0; c < Ins_BASE.Length; c++)
        {
            if (lam[c] == 0f) continue;
            if (sb.Length > 0) sb.Append(lam[c] >= 0f ? " + " : " - ");
            else if (lam[c] < 0f) sb.Append("-");
            sb.Append(Mathf.Abs(lam[c]).ToString("0.00", CultureInfo.InvariantCulture))
              .Append(' ').Append(Ins_BASE[c]);
        }
        return sb.Length > 0 ? sb.ToString() : "0 (todos los factores en cero)";
    }

    // ============================================================
    // LA DEMANDA, QUE NO SE SUMA
    // ============================================================

    /// (P, M) del f combinado y su Mn en la curva de la familia. Es la
    /// misma regla de semana03/demanda_capacidad.demanda() y
    /// capacidad_en(): mirar los dos extremos, quedarse con el de mayor
    /// momento, e interpolar en la curva que calculo Python.
    private DemandaS4 Ins_Demanda(Ins_Barra b, float[] f)
    {
        ElementoS4 e = b.elemento;
        if (e == null || e.familia < 0 || Anexo.familias == null
            || e.familia >= Anexo.familias.Count || f == null || f.Length < 12) return null;

        bool muro = e.tipo == "muro";
        // El momento del plano de un muro lo dice el anexo (el eje de
        // inercia mayor); una columna usa el resultante.
        bool planoEsMy = e.momento_en_el_plano != "Mz";

        // extremo i: P = f[0], My = f[4], Mz = f[5]
        // extremo j: P = -f[6], My = f[10], Mz = f[11]
        float Pi = f[0], Myi = f[4], Mzi = f[5];
        float Pj = -f[6], Myj = f[10], Mzj = f[11];

        float Mi, Mfi, Mj, Mfj;
        if (muro)
        {
            Mi = Mathf.Abs(planoEsMy ? Myi : Mzi);
            Mfi = Mathf.Abs(planoEsMy ? Mzi : Myi);
            Mj = Mathf.Abs(planoEsMy ? Myj : Mzj);
            Mfj = Mathf.Abs(planoEsMy ? Mzj : Myj);
        }
        else
        {
            Mi = Mathf.Sqrt(Myi * Myi + Mzi * Mzi); Mfi = 0f;
            Mj = Mathf.Sqrt(Myj * Myj + Mzj * Mzj); Mfj = 0f;
        }

        bool ganaJ = Mj > Mi;
        float P = ganaJ ? Pj : Pi;
        float M = ganaJ ? Mj : Mi;
        float Mfuera = ganaJ ? Mfj : Mfi;

        float Mn = Ins_CapacidadEn(P, Anexo.familias[e.familia]);
        float u = Mn > 1e-9f ? M / Mn : 9999f;

        return new DemandaS4
        {
            id = b.id,
            familia = e.familia,
            P = P,
            M = M,
            M_fuera_plano = Mfuera,
            extremo = ganaJ ? "j (superior)" : "i (inferior)",
            Mn = Mn,
            u = u,
            pasa = u <= 1f,
        };
    }

    /// Mn a esa compresion, interpolado en la curva P-M. Fuera del rango
    /// devuelve 0, igual que demanda_capacidad.capacidad_en(): con una
    /// traccion mayor que la pura, o una compresion mayor que la pura,
    /// no queda momento resistente.
    private static float Ins_CapacidadEn(float P, FamiliaPM fam)
    {
        if (fam == null || fam.P == null || fam.Mn == null || fam.P.Length < 2) return 0f;
        int n = fam.P.Length;
        if (P <= fam.P[0] || P >= fam.P[n - 1]) return 0f;
        for (int i = 0; i + 1 < n; i++)
        {
            float p1 = fam.P[i], p2 = fam.P[i + 1];
            if (p1 <= P && P <= p2)
            {
                float d = p2 - p1;
                if (Mathf.Abs(d) < 1e-9f) return Mathf.Max(fam.Mn[i], fam.Mn[i + 1]);
                return fam.Mn[i] + (fam.Mn[i + 1] - fam.Mn[i]) * ((P - p1) / d);
            }
        }
        return 0f;
    }

    // ============================================================
    // LO QUE VE EL USUARIO
    // ============================================================

    /// Los cuatro sliders. Lo llama el panel de la Semana 5.
    public void Ins_DibujarControles()
    {
        if (!Ins_listo && Anexo != null) Ins_Preparar();

        GUILayout.Label("--- Superposicion INSTANTANEA en Unity (Semana 5) ---");
        PanelUI.Marcar("ins.sliders");   // para que la captura lleve el scroll hasta aca
        if (!Ins_listo)
        {
            GUILayout.Label("no disponible: " + Ins_aviso);
            return;
        }
        // La superposicion vale mientras K no cambie. Si el modelo se edito,
        // estos sliders siguen sumando los casos base del modelo ORIGINAL:
        // el mismo aviso que E1..E3 y LIBRE, decidido en Layout como ellos.
        if (Sup_hayDesactualizadoEnLayout)
            GUILayout.Label("AVISO: el modelo se edito (" + MotivoDesactualizado + "). Estos sliders "
                            + "suman los casos base del modelo ORIGINAL; para esta geometria hay que "
                            + "reanalizar (pestana Modificar).", PanelUI.Aviso ?? GUI.skin.label);

        bool cambio = false;
        for (int c = 0; c < Ins_BASE.Length; c++)
        {
            GUILayout.BeginHorizontal();
            GUILayout.Label($"{Ins_BASE[c]}  {Ins_lambda[c].ToString("0.00", CultureInfo.InvariantCulture)}",
                            GUILayout.Width(70f));
            float v = GUILayout.HorizontalSlider(Ins_lambda[c], -2f, 2f);
            GUILayout.EndHorizontal();
            // Un paso de 0.05: el slider no tiembla y los numeros del
            // panel son legibles.
            v = Mathf.Round(v * 20f) / 20f;
            if (!Mathf.Approximately(v, Ins_lambda[c])) { Ins_lambda[c] = v; cambio = true; }
        }

        // Los mismos factores que E1..E3 precalculados por Python: apretar
        // uno y despues el E de arriba muestra el mismo caso por dos caminos.
        GUILayout.BeginHorizontal();
        if (GUILayout.Button("E1  1.0G+1.0Q")) { Ins_Fijar(1f, 1f, 0f, 0f); cambio = true; }
        if (GUILayout.Button("E2  1.2G+1.6Q")) { Ins_Fijar(1.2f, 1.6f, 0f, 0f); cambio = true; }
        GUILayout.EndHorizontal();
        GUILayout.BeginHorizontal();
        if (GUILayout.Button("E3  1.2G+1.0Q-1.4EX")) { Ins_Fijar(1.2f, 1f, -1.4f, 0f); cambio = true; }
        if (GUILayout.Button("todo en cero")) { Ins_Fijar(0f, 0f, 0f, 0f); cambio = true; }
        GUILayout.EndHorizontal();

        // Diferido a LateUpdate, como todo lo que cambia el estado desde el
        // panel (VisorSemana04.Panel.Diferir): combinar y redibujar a mitad
        // de un evento de OnGUI cambia la cantidad de controles y salta
        // "Getting control N's position..." (CLAUDE.md, trampa IMGUI).
        if (cambio) Diferir(Ins_Aplicar);

        GUILayout.Label($"{Ins_Descripcion(Ins_lambda)}");
        // Siempre una linea, con o sin combinacion previa: asi la cantidad
        // de controles no depende de si ya se combino.
        GUILayout.Label(Ins_version == 0
            ? "todavia no se combino: mueve un slider o aprieta un boton"
            : $"combinado en Unity en {Ins_msUltima.ToString("0.00", CultureInfo.InvariantCulture)} ms "
              + $"({Ins_barras.Count} barras, {Ins_nodos.Count} nodos; combinacion n. {Ins_version})");
    }

    private void Ins_Fijar(float g, float q, float ex, float ey)
    {
        Ins_lambda[0] = g; Ins_lambda[1] = q; Ins_lambda[2] = ex; Ins_lambda[3] = ey;
    }

    /// Recombina con los factores actuales y deja el caso activo en
    /// INSTANT, para que todo lo que ya sabe dibujar un caso lo muestre.
    public void Ins_Aplicar()
    {
        if (Ins_Combinar(Ins_lambda) != null) ElegirCaso(CASO_INSTANT);
    }

    /// Los factores de ahora, para quien los necesite (la comparacion
    /// contra Python, las capturas).
    public float[] Ins_Lambdas { get { return Ins_lambda; } }

    /// Milisegundos de la ultima combinacion.
    public float Ins_MsUltima { get { return Ins_msUltima; } }

    /// Cuantas veces se combino. Sube en cada Ins_Combinar.
    public int Ins_Version { get { return Ins_version; } }
}
