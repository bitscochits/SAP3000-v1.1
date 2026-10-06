# -*- coding: utf-8 -*-
r"""
================================================================
 calculo/sismo.py  -  QUE HACE EL EDIFICIO CUANDO LO EMPUJAN
================================================================
 Revisa un caso lateral: carga aplicada, corte basal, sentido de la
 deformada, torsion de piso y centro de rigidez, de dos formas:

   revisar(caso)                      los casos EX/EY DEL MODELO (los del
                                      edificio, que resuelve /analizar)
   analizar(modelo, caso_carga, res)  sobre lo que ya esta en memoria (es
                                      lo que usa la Parte B del laboratorio,
                                      con EX/EY armados con los parametros)

 Correr:
   python sap.py revisar sismo
   python sap.py revisar sismo EX
   python sap.py revisar sismo EY --detalle

 CORTE BASAL. Sumar todas las filas de `reacciones` lo da al doble: un
 nodo de diafragma reacciona tambien a su restriccion, que es interna.
 La separacion es POR GRADO DE LIBERTAD y esta en opensees.equilibrio();
 aca se le pide, no se reimplementa.

 SENTIDO DE LA DEFORMADA. Tres cosas que el equilibrio no garantiza:
 cada piso va hacia donde lo empujan; el desplazamiento crece con la
 altura sin devolverse; el movimiento no se sale de su direccion.
 Se miden DENTRO DE CADA CUERPO, que se separan por conectividad.

 TORSION DE PISO. El diafragma se traslada y ademas gira. Cociente de
 irregularidad torsional (NCh433 / ASCE 7):

     r = u_max / u_prom,   u_prom = media de los DOS EXTREMOS del piso

 r > 1.2 irregular, r > 1.4 extrema. No se mide sobre el maestro (esta
 en el centro de masa y no ve la torsion) ni con la media de todos
 los nodos (se arrastra hacia donde hay mas nodos). Y no se informa en
 un piso que casi no se mueve: es un cociente entre casi-ceros.
================================================================
"""
from __future__ import annotations

import math
import sys

from calculo import edificio as _ed
from calculo import opensees

LATERALES = ('EX', 'EY')

# Cocientes de irregularidad torsional de NCh433 / ASCE 7.
TORSION_IRREGULAR = 1.2
TORSION_EXTREMA = 1.4

# Por debajo de esta fraccion del desplazamiento del techo, el piso
# practicamente no se mueve y su cociente de torsion no significa nada:
# es un cociente entre dos numeros casi nulos. Pasa en los pisos que
# estan contra el terreno -- en el edificio de Ingenieria el primer
# nivel da 0.04 mm contra 21 mm del techo, y ahi el cociente salia 1.97
# por puro ruido.
MINIMO_PARA_MEDIR_TORSION = 0.02

# Cuanto puede moverse el edificio en la direccion que NO se empuja,
# como fraccion de la direccion empujada, antes de que sea sospechoso
# de ejes cruzados. Una planta asimetrica acopla algo; el doble no.
TOL_FUERA_DE_DIRECCION = 1.0


def direccion_de(caso):
    """'EX' -> ('fx', 'ux', 'uy', 0), o sea que y componentes mirar."""
    if caso.upper().endswith('X'):
        return 'fx', 'ux', 'uy', 0
    return 'fy', 'uy', 'ux', 1


def cuerpos(modelo):
    r"""
    Agrupa los diafragmas por CUERPO. Devuelve {maestro: n_cuerpo}.

    ----------------------------------------------------------------
    POR QUE HACE FALTA
    ----------------------------------------------------------------
    El conjunto tiene dos edificios unidos por una junta de
    dilatacion, o sea DIEZ diafragmas: dos por nivel, uno de cada
    cuerpo. Ordenarlos por cota y recorrerlos en fila compara el
    tercer piso de un cuerpo contra el segundo del otro, y entonces
    "el piso de arriba se mueve menos que el de abajo" salta seis
    veces sin que nada este mal.

    ----------------------------------------------------------------
    COMO SE DECIDE, SIN UN UMBRAL INVENTADO
    ----------------------------------------------------------------
    Dos diafragmas son el mismo cuerpo si hay un ELEMENTO que va de
    uno al otro: una columna o un muro que sube de un piso al
    siguiente. Es conectividad estructural, no distancia en planta, y
    por eso no hace falta elegir cuanto es "lejos". En el conjunto,
    justamente, ningun elemento cruza la junta -- es libre -- asi que
    los dos cuerpos salen separados solos.
    """
    de_nodo = {}
    for i, d in enumerate(modelo.get('diafragmas', [])):
        de_nodo[int(d['nodo_maestro'])] = i
        for n in d.get('nodos', []):
            de_nodo.setdefault(int(n), i)

    padre = list(range(len(modelo.get('diafragmas', []))))

    def raiz(i):
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for e in modelo.get('elementos', []):
        a = de_nodo.get(int(e['n1']))
        b = de_nodo.get(int(e['n2']))
        if a is None or b is None or a == b:
            continue
        ra, rb = raiz(a), raiz(b)
        if ra != rb:
            padre[ra] = rb

    etiqueta, salida = {}, {}
    for i, d in enumerate(modelo.get('diafragmas', [])):
        r = raiz(i)
        if r not in etiqueta:
            etiqueta[r] = len(etiqueta)
        salida[int(d['nodo_maestro'])] = etiqueta[r]
    return salida


def centro_de_rigidez(modelo, eje_carga):
    r"""
    Donde esta el centro de rigidez del primer piso, en la coordenada
    PERPENDICULAR a la carga, y donde el centro geometrico de la
    planta. La distancia entre los dos es la excentricidad, y es la
    que explica la torsion.

    Aproximado, y a proposito: todos los verticales de un piso tienen
    la misma altura, asi que su rigidez lateral k = 12EI/L^3 es
    proporcional a I y la altura se cancela al hacer el promedio
    ponderado. Lo que se busca no es un numero de calculo sino
    entender de donde sale el giro.

    QUE INERCIA USAR. La de la flexion EN EL PLANO DE LA CARGA. Un
    muro que corre en Y resiste EY con su inercia FUERTE; el mismo
    muro resiste EX con la debil, que es mil veces menor. Usar
    siempre la misma inercia pondria el centro de rigidez en el medio
    y no se veria nada.
    """
    nodos = {int(n['id']): n for n in modelo['nodos']}
    secciones = {s['nombre']: s for s in modelo.get('secciones', [])}
    zs = sorted({float(n['z']) for n in modelo['nodos']})
    if not zs:
        return None
    base = zs[0]

    num = den = 0.0
    coords = []
    for e in modelo['elementos']:
        if e.get('tipo') not in ('columna', 'muro'):
            continue
        n1 = nodos.get(int(e['n1']))
        if n1 is None or abs(float(n1['z']) - base) > 1e-6:
            continue
        s = secciones.get(e.get('seccion'))
        if not s:
            continue
        d = e.get('dir_largo') or [1.0, 0.0]
        corre_en_x = abs(d[0]) >= abs(d[1])
        # I para flexion en el plano de la carga
        if eje_carga == 'x':
            I = float(s['Iz']) if corre_en_x else float(s['Iy'])
            pos = float(n1['y'])          # perpendicular a la carga
        else:
            I = float(s['Iz']) if not corre_en_x else float(s['Iy'])
            pos = float(n1['x'])
        num += I * pos
        den += I
        coords.append(pos)

    if den <= 0 or not coords:
        return None
    return {
        'centro_rigidez': num / den,
        'centro_geometrico': (min(coords) + max(coords)) / 2.0,
        'ancho': max(coords) - min(coords),
        'coordenada': 'Y' if eje_carga == 'x' else 'X',
    }


def revisar(caso='EX', modelo=None, resueltos=None):
    """
    El informe de un caso lateral DEL MODELO. Lo resuelve en memoria
    (opensees.resolver_edificio, ~0.3 s), o usa `resueltos` si ya vienen.
    """
    modelo = modelo if modelo is not None else _ed.estructura()
    if resueltos is None:
        resueltos, _avisos = opensees.resolver_edificio(modelo)
    res = next((r for r in resueltos if r.get('caso') == caso), None)
    caso_carga = next((c for c in modelo.get('casos_de_carga', [])
                       if c.get('nombre') == caso), None)
    if caso_carga is None or res is None:
        raise SystemExit('el edificio no trae el caso %s' % caso)
    return analizar(modelo, caso_carga, res, caso, _ed.NOMBRE)


def analizar(modelo, caso_carga, res, caso='EX', nombre=''):
    r"""
    El informe del caso lateral a partir de lo que ya esta en memoria:
    el modelo, el caso de carga que se aplico y el resultado resuelto.

    Existe separado de revisar() para que el laboratorio pueda revisar
    un EX/EY que acaba de construir con los parametros del profesor. La
    logica es una sola; lo unico que cambia es de donde vienen los datos.
    """
    campo_f, u_dir, u_otra, idx = direccion_de(caso)

    nodos = {int(n['id']): n for n in modelo['nodos']}
    desp = {int(d['id']): d for d in res.get('desplazamientos', [])}
    maestros = {int(d['nodo_maestro']): d for d in modelo.get('diafragmas', [])}

    # ---- carga lateral aplicada, por nivel ----
    aplicada = {}
    for c in caso_carga.get('cargas_nodales', []):
        f = float(c.get(campo_f, 0.0))
        if abs(f) < 1e-12:
            continue
        n = int(c['nodo'])
        aplicada[n] = aplicada.get(n, 0.0) + f
    total_aplicado = sum(aplicada.values())

    # ---- corte basal ----
    # Se lo pide a opensees.equilibrio(), que separa por GRADO DE
    # LIBERTAD. Ver la nota del encabezado sobre por que la regla
    # facil no sirve.
    eq = opensees.equilibrio(modelo, caso_carga, res)
    corte_real = eq['reaccion_kN'][idx]
    corte_todo = sum(float(r.get(campo_f, 0.0))
                     for r in res.get('reacciones', []))

    # ---- pisos ----
    pisos = []
    for m, dia in sorted(maestros.items(),
                         key=lambda kv: float(nodos[kv[0]]['z'])):
        z = float(nodos[m]['z'])
        dm = desp.get(m, {})
        u_m = float(dm.get(u_dir, 0.0))
        v_m = float(dm.get(u_otra, 0.0))
        rz = float(dm.get('rz', 0.0))

        # Los nodos del piso, para medir la torsion donde se ve.
        us, radios = [], []
        for s in dia.get('nodos', []):
            s = int(s)
            if s not in desp or s not in nodos:
                continue
            us.append(float(desp[s].get(u_dir, 0.0)))
            radios.append(math.hypot(float(nodos[s]['x']) - float(nodos[m]['x']),
                                     float(nodos[s]['y']) - float(nodos[m]['y'])))
        if us:
            # Definicion de NCh433 / ASCE 7: el promedio es la media de
            # los DOS EXTREMOS del piso, no la de todos sus nodos.
            u_max = max(us, key=abs)
            u_min = min(us, key=abs)
            u_prom = (max(us) + min(us)) / 2.0
            u_prom_todos = sum(us) / len(us)
            cociente = abs(u_max) / abs(u_prom) if abs(u_prom) > 1e-15 else 0.0
        else:
            u_max = u_min = u_prom = u_prom_todos = u_m
            cociente = 1.0

        pisos.append({
            'maestro': m, 'z': z,
            'F': aplicada.get(m, 0.0),
            'u': u_m, 'u_fuera': v_m, 'rz': rz,
            'u_max': u_max, 'u_min': u_min, 'u_prom': u_prom,
            'u_prom_todos': u_prom_todos,
            'cociente_torsion': cociente,
            'n_nodos': len(us),
            'radio_max': max(radios) if radios else 0.0,
            'giro_en_el_borde': abs(rz) * (max(radios) if radios else 0.0),
        })

    # A que cuerpo pertenece cada piso, y su techo, para poder medir
    # cada edificio contra si mismo.
    de_cuerpo = cuerpos(modelo)
    for p in pisos:
        p['cuerpo'] = de_cuerpo.get(p['maestro'], 0)
    techo = {}
    for p in pisos:
        techo[p['cuerpo']] = max(techo.get(p['cuerpo'], 0.0), abs(p['u']))

    # El cociente de torsion solo tiene sentido donde el piso se mueve.
    for p in pisos:
        t = techo.get(p['cuerpo'], 0.0)
        p['se_mueve'] = t > 0 and abs(p['u']) >= MINIMO_PARA_MEDIR_TORSION * t

    cr = centro_de_rigidez(modelo, 'x' if u_dir == 'ux' else 'y')

    return {
        'edificio': nombre, 'caso': caso, 'direccion': u_dir,
        'centro_de_rigidez': cr,
        'aplicado_kN': total_aplicado,
        'corte_basal_kN': corte_real,
        'confiable': eq['confiable'],
        'cargas_sin_convertir': eq['cargas_sin_convertir'],
        'corte_sumando_todo_kN': corte_todo,
        'pisos': pisos,
        'nodos': nodos, 'desp': desp,
    }


def problemas(inf):
    """Lo que no cumple. Lista vacia = el caso esta sano."""
    malos = []
    pisos = inf['pisos']

    # 1. equilibrio lateral
    if not inf.get('confiable', True):
        malos.append('%s: %d carga(s) distribuidas no se pudieron convertir '
                     'a globales; el equilibrio no da veredicto'
                     % (inf['caso'], inf.get('cargas_sin_convertir', 0)))
        return malos
    err = abs(inf['aplicado_kN'] + inf['corte_basal_kN'])
    escala = max(abs(inf['aplicado_kN']), 1.0)
    if err / escala > 1e-6:
        malos.append('%s: se aplicaron %.3f kN y al suelo bajan %.3f kN'
                     % (inf['caso'], inf['aplicado_kN'],
                        -inf['corte_basal_kN']))

    # 2. cada piso va hacia donde lo empujan
    signo = 1.0 if inf['aplicado_kN'] >= 0 else -1.0
    for p in pisos:
        if abs(p['u']) > 1e-12 and p['u'] * signo < 0:
            malos.append('%s: el piso %+.2f se mueve al reves de la carga '
                         '(u = %.6g m)' % (inf['caso'], p['z'], p['u']))

    # 3. la deformada crece con la altura, DENTRO DE CADA CUERPO
    por_cuerpo = {}
    for p in pisos:
        por_cuerpo.setdefault(p.get('cuerpo', 0), []).append(p)
    for _c, lista in sorted(por_cuerpo.items()):
        for a, b in zip(lista, lista[1:]):
            if not (a.get('se_mueve', True) and b.get('se_mueve', True)):
                continue
            if abs(b['u']) < abs(a['u']) - 1e-12:
                malos.append('%s: en el cuerpo %d el piso %+.2f se mueve '
                             'MENOS que el de abajo (%.6g contra %.6g m)'
                             % (inf['caso'], _c, b['z'], b['u'], a['u']))

    # 4. no se sale de su direccion
    for p in pisos:
        if abs(p['u']) > 1e-12 and \
                abs(p['u_fuera']) > TOL_FUERA_DE_DIRECCION * abs(p['u']):
            malos.append('%s: en el piso %+.2f el movimiento fuera de la '
                         'direccion de la carga (%.6g m) supera al de la '
                         'direccion empujada (%.6g m)'
                         % (inf['caso'], p['z'], p['u_fuera'], p['u']))
    return malos


def imprimir(inf, detalle=False):
    print('  caso %s   empuja en %s' % (inf['caso'], inf['direccion'][-1].upper()))
    print()
    print('    carga lateral aplicada      %12.3f kN' % inf['aplicado_kN'])
    print('    corte basal (apoyos)        %12.3f kN' % inf['corte_basal_kN'])
    print('    sumando TODAS las filas     %12.3f kN   <- lo que NO hay que '
          'hacer' % inf['corte_sumando_todo_kN'])
    err = abs(inf['aplicado_kN'] + inf['corte_basal_kN'])
    print('    error                       %12.3e kN  (%.2e relativo)'
          % (err, err / max(abs(inf['aplicado_kN']), 1.0)))
    print()
    cr = inf.get('centro_de_rigidez')
    if cr:
        e = cr['centro_rigidez'] - cr['centro_geometrico']
        print('    centro de rigidez en %s   %8.2f m' % (cr['coordenada'],
                                                         cr['centro_rigidez']))
        print('    centro geometrico        %8.2f m' % cr['centro_geometrico'])
        print('    excentricidad            %8.2f m   = %.0f %% del ancho '
              '(%.2f m)' % (e, 100 * abs(e) / max(cr['ancho'], 1e-9),
                            cr['ancho']))
        quietos = [p for p in inf['pisos'] if not p.get('se_mueve', True)]
        if quietos:
            print('    (calculado en el primer piso. Este edificio tiene %d '
                  'piso(s) contra el terreno' % len(quietos))
            print('     que casi no se mueven, asi que esta excentricidad no '
                  'representa a los que si.)')
        print()
    print('    %8s %11s %13s %13s %11s %9s  %s'
          % ('cota', 'F [kN]', 'u [mm]', 'fuera [mm]', 'rz [urad]',
             'u_max/u_prom', ''))
    varios = len({p.get('cuerpo', 0) for p in inf['pisos']}) > 1
    for p in inf['pisos']:
        if varios:
            print('    cuerpo %d' % p.get('cuerpo', 0), end='')
        if not p.get('se_mueve', True):
            print('    %+8.2f %11.2f %13.4f %13.4f %11.2f %9s  %s'
                  % (p['z'], p['F'], p['u'] * 1000, p['u_fuera'] * 1000,
                     p['rz'] * 1e6, '-',
                     'el piso casi no se mueve: el cociente no dice nada'))
            continue
        nota = ''
        if p['cociente_torsion'] >= TORSION_EXTREMA:
            nota = '<-- torsion EXTREMA'
        elif p['cociente_torsion'] >= TORSION_IRREGULAR:
            nota = '<-- irregularidad torsional'
        print('    %+8.2f %11.2f %13.4f %13.4f %11.2f %9.3f  %s'
              % (p['z'], p['F'], p['u'] * 1000, p['u_fuera'] * 1000,
                 p['rz'] * 1e6, p['cociente_torsion'], nota))

    if detalle:
        print()
        print('    cuanto del borde es GIRO y no traslacion:')
        for p in inf['pisos']:
            print('      cota %+6.2f   rz x r_max = %8.4f mm   contra '
                  'u del centro de masa = %8.4f mm   (%.1f %%)'
                  % (p['z'], p['giro_en_el_borde'] * 1000, p['u'] * 1000,
                     100 * p['giro_en_el_borde'] / max(abs(p['u']), 1e-15)))
        print()
        print('    el cociente segun las dos definiciones de promedio:')
        print('      %8s %11s %11s %13s %13s'
              % ('cota', 'u_max', 'u_min', 'r (extremos)', 'r (todos)'))
        for p in inf['pisos']:
            rt = (abs(p['u_max']) / abs(p['u_prom_todos'])
                  if abs(p['u_prom_todos']) > 1e-15 else 0.0)
            print('      %+8.2f %11.4f %11.4f %13.3f %13.3f'
                  % (p['z'], p['u_max'] * 1000, p['u_min'] * 1000,
                     p['cociente_torsion'], rt))


def main(argv):
    casos = [a.upper() for a in argv if a.upper() in LATERALES] or \
        list(LATERALES)
    detalle = '--detalle' in argv

    print('=' * 74)
    print('  SISMO PSEUDOESTATICO EN %s' % _ed.NOMBRE.upper())
    print('=' * 74)

    malos = []
    modelo = _ed.estructura()
    resueltos, _avisos = opensees.resolver_edificio(modelo)
    for caso in casos:
        inf = revisar(caso, modelo, resueltos)
        print()
        imprimir(inf, detalle)
        malos += problemas(inf)

    print()
    print('=' * 74)
    if malos:
        print('  %d PROBLEMA(S)' % len(malos))
        for m in malos:
            print('    - %s' % m)
        print('=' * 74)
        return 1
    print('  LA DEFORMADA VA HACIA DONDE EMPUJA, CRECE CON LA ALTURA Y EL')
    print('  CORTE BASAL CIERRA')
    print('=' * 74)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
