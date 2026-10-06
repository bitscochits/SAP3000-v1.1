# -*- coding: utf-8 -*-
r"""
================================================================
 calculo/opensees.py  -  EL MOTOR: EL UNICO QUE LLAMA A OPENSEES
================================================================
 Arma en OpenSees cualquier modelo del contrato (el edificio, el que
 manda Unity al reanalizar, el marco de prueba) y lo resuelve en uno o
 varios casos de carga. Lo usan el calculo por linea de comandos, el
 servidor (/analizar, /combinar), los anexos del laboratorio, la carga
 movil y la persona: UNA implementacion, para que el visor y la linea
 de comandos no puedan dar resultados distintos.

 QUE SOPORTA
   - Barras de cualquier seccion y orientacion. La geomTransf se elige
     por GEOMETRIA, no por la etiqueta 'tipo'.
   - vecxz explicito por elemento (los muros traen el suyo).
   - E y G por seccion (hormigon G35 en un cuerpo, G28 en el otro, acero).
   - Apoyos por grado de libertad, diafragmas rigidos y brazos.
   - Varios casos de carga sobre el MISMO modelo armado una vez.
   - Unidades: m, kN, kPa. Salida redondeada: desplazamientos a 8
     decimales (m), fuerzas a 4 (kN): nada se compara por debajo de eso.

 QUE NO SOPORTA: analisis no lineal ni elementos de area (un muro es
 una barra en su eje con brazos rigidos hasta las caras).

 La capacidad de las secciones (fibras, M-phi, P-M) tambien usa
 OpenSees, pero en un modelo propio de una seccion: calculo/capacidad.py.
================================================================
"""
from __future__ import annotations

import math
import os
import sys
import tempfile
import threading

import openseespy.opensees as ops

from calculo import edificio as _ed

# OpenSees es un SINGLETON global: ops.wipe() borra EL modelo, no "un"
# modelo. El servidor atiende pedidos en hilos concurrentes (/analizar y
# /combinar), asi que todo uso del motor desde ahi va bajo este lock.
LOCK = threading.Lock()

# Contrato de entrada y de respuesta: CONTRATO.md, "Servidor". En corto:
#   nodos [{id,x,y,z,fijo?,restricciones?[6]}], secciones (lista o dict:
#   {nombre,A,Iy,Iz,J,E?,G?}), elementos [{id,n1,n2,seccion,tipo,vecxz?}],
#   diafragmas [{nodo_maestro,nodos,perpendicular}], brazos_rigidos
#   [{maestro,esclavo,tipo beam|bar}], y las cargas en un caso
#   (cargas_nodales/cargas_distribuidas en la raiz) o en varios
#   (casos_de_carga). La respuesta va en LISTAS (JsonUtility no lee
#   diccionarios): desplazamientos, reacciones (solo nodos restringidos) y
#   fuerzas_elementos en EJES LOCALES, [N,Vy,Vz,T,My,Mz] por extremo.


# ============================================================
# SECCIONES Y ARMADO
# ============================================================
def normalizar_secciones(secciones):
    """
    'secciones' como DICCIONARIO {nombre: {A, Iy, Iz, J, E?, G?}}. Acepta la
    LISTA [{nombre, A, ...}], que es la forma que lee y escribe Unity
    (JsonUtility no sabe de diccionarios con claves arbitrarias).
    """
    if isinstance(secciones, dict):
        return secciones

    if not isinstance(secciones, list):
        raise ValueError("'secciones' debe ser un diccionario o una lista")

    out = {}
    for i, s in enumerate(secciones):
        nombre = s.get('nombre')
        if not nombre:
            raise ValueError(f"secciones[{i}] no tiene 'nombre'. En la forma "
                             f"de lista cada seccion debe traerlo.")
        if nombre in out:
            raise ValueError(f"La seccion '{nombre}' esta definida dos veces")
        faltan = [k for k in ('A', 'Iy', 'Iz', 'J') if k not in s]
        if faltan:
            raise ValueError(f"La seccion '{nombre}' no trae {faltan}")
        out[nombre] = {k: float(s[k]) for k in ('A', 'Iy', 'Iz', 'J')}
        # E y G POR SECCION, opcionales: sin esto no conviven acero y
        # hormigon (los tubos del voladizo, E = 200 GPa) ni dos hormigones
        # (el LT2 es G35 y el cuerpo antiguo G28).
        for k in ('E', 'G'):
            if k in s and s[k]:
                out[nombre][k] = float(s[k])
    return out


def construir_modelo(data):
    """
    Ensambla el modelo en OpenSees (nodos, apoyos, elementos, diafragmas,
    brazos). NO aplica cargas ni resuelve.

    Devuelve (coords, avisos, nodos_restringidos).
    """
    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)

    # --- Material del modelo (lo usa la seccion que no trae el suyo) ---
    mat = data.get('material', {})
    fpc = mat.get('fpc_MPa', 25.0)
    poisson = mat.get('poisson', 0.2)
    Ec = 4700.0 * math.sqrt(fpc) * 1000.0    # kPa
    Gc = Ec / (2.0 * (1.0 + poisson))
    ops.uniaxialMaterial('Elastic', 1, Ec)

    avisos = []

    # --- Nodos ---
    coords = {}
    for nd in data['nodos']:
        nid = int(nd['id'])
        xyz = (float(nd['x']), float(nd['y']), float(nd['z']))
        coords[nid] = xyz
        ops.node(nid, *xyz)

    # --- Apoyos ---
    # "fijo": true -> empotrado. "restricciones": [6 enteros] -> a medida.
    # Una lista VACIA es ausente (JsonUtility manda [] en un nodo libre).
    nodos_restringidos = {}
    for nd in data['nodos']:
        nid = int(nd['id'])
        r = nd.get('restricciones') or None
        if r is None:
            r = [1, 1, 1, 1, 1, 1] if nd.get('fijo', False) else None
        if r is None:
            continue
        if len(r) != 6:
            raise ValueError(f"Nodo {nid}: 'restricciones' debe tener 6 "
                             f"valores [ux,uy,uz,rx,ry,rz], vinieron {len(r)}")
        r = [int(v) for v in r]
        if any(v not in (0, 1) for v in r):
            raise ValueError(f"Nodo {nid}: 'restricciones' solo acepta 0 o 1")
        if any(r):
            ops.fix(nid, *r)
            nodos_restringidos[nid] = r

    # --- Elementos ---
    # La transformacion se elige por la GEOMETRIA (calculo/edificio.
    # es_vertical), no por la etiqueta: un muro vertical que no se llamara
    # "columna" recibia vecxz = (0,0,1), PARALELO a su eje, y OpenSees moria.
    sec = normalizar_secciones(data['secciones'])
    transfs = {}          # vecxz -> tag, para no redefinir transformaciones
    prox_transf = [1]

    def tag_transf(vecxz):
        clave = tuple(round(v, 9) for v in vecxz)
        if clave not in transfs:
            t = prox_transf[0]
            prox_transf[0] += 1
            ops.geomTransf('Linear', t, *clave)
            transfs[clave] = t
        return transfs[clave]

    for el in data['elementos']:
        eid = int(el['id'])
        n1, n2 = int(el['n1']), int(el['n2'])

        if n1 not in coords or n2 not in coords:
            raise ValueError(f"Elemento {eid} referencia un nodo inexistente "
                             f"(n1={n1}, n2={n2})")

        p1, p2 = coords[n1], coords[n2]
        dx, dy, dz = (p2[0]-p1[0], p2[1]-p1[1], p2[2]-p1[2])
        L = math.sqrt(dx*dx + dy*dy + dz*dz)
        if L < 1e-9:
            raise ValueError(f"Elemento {eid} tiene largo cero "
                             f"(nodos {n1} y {n2} coinciden)")

        es_vertical = _ed.es_vertical(p1, p2)

        # vecxz define el plano local x-z y NO puede ser paralelo al eje.
        # Vertical -> (1,0,0); cualquier otro -> (0,0,1), que deja el eje
        # local z en el plano vertical: la gravedad flecta "hacia abajo" en
        # ejes locales. "vecxz": [] desde Unity significa "sin override".
        vecxz = el.get('vecxz') or None
        if vecxz is not None:
            if len(vecxz) != 3:
                raise ValueError(f"Elemento {eid}: 'vecxz' debe tener 3 "
                                 f"componentes, vinieron {len(vecxz)}")
            vecxz = (float(vecxz[0]), float(vecxz[1]), float(vecxz[2]))
            norma = math.sqrt(sum(v*v for v in vecxz))
            if norma < 1e-9:
                raise ValueError(f"Elemento {eid}: vecxz es el vector nulo")
            cx = dy*vecxz[2] - dz*vecxz[1]
            cy = dz*vecxz[0] - dx*vecxz[2]
            cz = dx*vecxz[1] - dy*vecxz[0]
            if math.sqrt(cx*cx + cy*cy + cz*cz) / (L * norma) < 1e-6:
                raise ValueError(
                    f"Elemento {eid}: el vecxz {vecxz} es paralelo al eje del "
                    f"elemento. Elige otro (para un elemento vertical usa "
                    f"(1,0,0); para uno horizontal, (0,0,1)).")
        else:
            vecxz = (1.0, 0.0, 0.0) if es_vertical else (0.0, 0.0, 1.0)

        transf = tag_transf(vecxz)

        # Cruce de inercias, SOLO en elementos no verticales. En el contrato
        # Iz es la de GRAVEDAD (b h^3/12); con vecxz = (0,0,1) la gravedad
        # flecta alrededor del eje local y, que resiste la posicion Iy.
        if el['seccion'] not in sec:
            raise ValueError(f"Elemento {eid} usa la seccion "
                             f"'{el['seccion']}', que no esta definida")
        s_el = sec[el['seccion']]
        if es_vertical:
            Iy_pass, Iz_pass = s_el['Iy'], s_el['Iz']
        else:
            Iy_pass = s_el['Iz']   # inercia de gravedad -> posicion Iy
            Iz_pass = s_el['Iy']   # inercia lateral    -> posicion Iz

        # Aviso si la etiqueta no calza con la geometria: no es error
        # (manda la geometria), pero delata un dato mal armado.
        tipo = el.get('tipo', '')
        if tipo == 'columna' and not es_vertical:
            avisos.append(f"Elemento {eid} dice tipo='columna' pero NO es "
                          f"vertical; se trato como barra inclinada/horizontal.")
        elif tipo.startswith('viga') and es_vertical:
            avisos.append(f"Elemento {eid} dice tipo='{tipo}' pero ES "
                          f"vertical; se trato como elemento vertical.")

        # La seccion puede traer su propio material; si no, el del modelo.
        E_el = s_el.get('E', Ec)
        G_el = s_el.get('G', Gc if 'E' not in s_el
                        else E_el / (2.0 * (1.0 + 0.3)))
        ops.element('elasticBeamColumn', eid, n1, n2,
                    s_el['A'], E_el, G_el, s_el['J'],
                    Iy_pass, Iz_pass, transf)

    # --- Brazos rigidos (rigidLink) ---
    # El edificio NO los usa (sus brazos son barras x100: un rigidLink pelea
    # con el diafragma), pero el contrato los admite.
    for br in data.get('brazos_rigidos', []):
        m, e = int(br['maestro']), int(br['esclavo'])
        if m not in coords or e not in coords:
            raise ValueError(f"Brazo rigido {m}->{e} referencia un nodo "
                             f"inexistente")
        if m == e:
            raise ValueError(f"Brazo rigido invalido: maestro y esclavo son "
                             f"el mismo nodo ({m})")
        tipo_br = br.get('tipo', 'beam')
        if tipo_br not in ('beam', 'bar'):
            raise ValueError(f"Brazo rigido {m}->{e}: tipo debe ser "
                             f"'beam' o 'bar', vino '{tipo_br}'")
        ops.rigidLink(tipo_br, m, e)

    # --- Diafragmas rigidos ---
    for i, dia in enumerate(data.get('diafragmas', [])):
        maestro = int(dia['nodo_maestro'])
        esclavos = [int(n) for n in dia['nodos'] if int(n) != maestro]
        perp = int(dia.get('perpendicular', 3))

        if maestro not in coords:
            raise ValueError(f"Diafragma {i}: el nodo maestro {maestro} no "
                             f"existe. Crealo en 'nodos' (normalmente en el "
                             f"centro de masa del piso).")
        faltan = [n for n in esclavos if n not in coords]
        if faltan:
            raise ValueError(f"Diafragma {i}: nodos inexistentes {faltan}")
        if not esclavos:
            raise ValueError(f"Diafragma {i}: no tiene nodos esclavos")
        if perp not in (1, 2, 3):
            raise ValueError(f"Diafragma {i}: 'perpendicular' debe ser "
                             f"1, 2 o 3 (vino {perp})")

        ejes = {1: 0, 2: 1, 3: 2}[perp]
        cota_m = coords[maestro][ejes]
        fuera = [n for n in esclavos
                 if abs(coords[n][ejes] - cota_m) > 1e-6]
        if fuera:
            raise ValueError(
                f"Diafragma {i}: los nodos {fuera} no estan en el mismo plano "
                f"que el maestro {maestro}. Un diafragma rigido exige que "
                f"todos compartan la cota.")

        ops.rigidDiaphragm(perp, maestro, *esclavos)

        # El diafragma ata solo los GDL EN SU PLANO (perp=3: ux, uy, rz). Los
        # de fuera del plano del maestro quedan sueltos y la matriz singular:
        # se fijan, salvo que ya vengan restringidos.
        if maestro not in nodos_restringidos:
            fuera_plano = {3: [0, 0, 1, 1, 1, 0],
                           2: [0, 1, 0, 1, 0, 1],
                           1: [1, 0, 0, 0, 1, 1]}[perp]
            ops.fix(maestro, *fuera_plano)
            nodos_restringidos[maestro] = fuera_plano
            avisos.append(
                f"Diafragma {i}: se restringieron los DOF fuera del plano del "
                f"nodo maestro {maestro} para evitar una matriz singular.")

    return coords, avisos, nodos_restringidos


# ============================================================
# CARGAS Y SOLUCION
# ============================================================
def aplicar_cargas(caso, tag, nodos_validos=None, elementos_validos=None):
    """
    Define el patron de carga 'tag' con las cargas del caso. Antes valida
    que cada carga apunte a algo que existe: si no, OpenSees solo avisa por
    consola y DESCARTA la carga, y el equilibrio cierra igual. Editando en
    Unity (borrar una barra deja su carga huerfana) pasaria a cada rato.
    """
    nombre = caso.get('nombre', 'el caso')

    ops.timeSeries('Linear', tag)
    ops.pattern('Plain', tag, tag)

    for c in caso.get('cargas_nodales', []):
        if nodos_validos is not None and int(c['nodo']) not in nodos_validos:
            raise ValueError(
                f"En '{nombre}': hay una carga sobre el nodo {c['nodo']}, "
                f"que no existe. Si lo borraste, borra tambien su carga.")

    for c in caso.get('cargas_distribuidas', []):
        if elementos_validos is not None and int(c['elemento']) not in elementos_validos:
            raise ValueError(
                f"En '{nombre}': hay una carga sobre el elemento "
                f"{c['elemento']}, que no existe. Si lo borraste, borra "
                f"tambien su carga.")

    for c in caso.get('cargas_nodales', []):
        ops.load(int(c['nodo']),
                 float(c.get('fx', 0.0)), float(c.get('fy', 0.0)),
                 float(c.get('fz', 0.0)), float(c.get('mx', 0.0)),
                 float(c.get('my', 0.0)), float(c.get('mz', 0.0)))

    for c in caso.get('cargas_distribuidas', []):
        ops.eleLoad('-ele', int(c['elemento']), '-type', '-beamUniform',
                    float(c.get('wy', 0.0)), float(c.get('wz', 0.0)),
                    float(c.get('wx', 0.0)))


def resolver_caso():
    """Analisis estatico lineal de un paso. Devuelve 0 si convergio."""
    ops.wipeAnalysis()
    ops.system('BandGeneral')      # mas robusto que BandSPD con eleLoad
    ops.numberer('RCM')
    ops.constraints('Transformation')   # necesario para diafragmas/rigidLink
    ops.integrator('LoadControl', 1.0)
    ops.algorithm('Linear')
    ops.analysis('Static')
    ok = ops.analyze(1)
    ops.reactions()
    return ok


def extraer_resultados(data, nodos_restringidos):
    """Desplazamientos (8 decimales), reacciones y esfuerzos (4) del estado actual."""
    res = {
        'desplazamientos': [],
        'reacciones': [],
        'fuerzas_elementos': [],
    }
    max_disp = 0.0

    for nd in data['nodos']:
        nid = int(nd['id'])
        d = [ops.nodeDisp(nid, i) for i in range(1, 7)]
        res['desplazamientos'].append({
            'id': nid,
            'ux': round(d[0], 8), 'uy': round(d[1], 8), 'uz': round(d[2], 8),
            'rx': round(d[3], 8), 'ry': round(d[4], 8), 'rz': round(d[5], 8),
        })
        m = max(abs(d[0]), abs(d[1]), abs(d[2]))
        if m > max_disp:
            max_disp = m

        if nid in nodos_restringidos:
            r = [ops.nodeReaction(nid, i) for i in range(1, 7)]
            res['reacciones'].append({
                'id': nid,
                'fx': round(r[0], 4), 'fy': round(r[1], 4), 'fz': round(r[2], 4),
                'mx': round(r[3], 4), 'my': round(r[4], 4), 'mz': round(r[5], 4),
            })

    for el in data['elementos']:
        eid = int(el['id'])
        # localForce, NUNCA eleForce: eleForce da fuerzas GLOBALES, y en una
        # viga que corre en Y el momento de gravedad saldria como "torsion".
        f = ops.eleResponse(eid, 'localForce')
        res['fuerzas_elementos'].append({
            'id': eid,
            'f': [round(v, 4) for v in f],
        })

    # La mayor COMPONENTE |ux|, |uy| o |uz| (los anexos informan la NORMA:
    # son dos numeros distintos a proposito).
    res['max_desplazamiento'] = round(max_disp, 8)
    return res


def construir_y_resolver(data):
    """
    Construye el modelo UNA vez y resuelve todos sus casos sobre el. Con
    'casos_de_carga' la respuesta trae 'casos' (cada uno con su equilibrio);
    con las cargas en la raiz, la forma plana de un solo caso.
    """
    coords, avisos, restringidos = construir_modelo(data)

    casos = data.get('casos_de_carga')
    multi = casos is not None
    if not multi:
        casos = [{
            'nombre': data.get('nombre_caso', 'unico'),
            'cargas_nodales': data.get('cargas_nodales', []),
            'cargas_distribuidas': data.get('cargas_distribuidas', []),
        }]

    nodos_validos = set(coords)
    elementos_validos = {int(e['id']) for e in data['elementos']}

    resultados_casos = []
    todo_ok = True
    tag_previo = None

    for i, caso in enumerate(casos):
        tag = 100 + i
        nombre = caso.get('nombre', f'caso_{i+1}')

        # Volver al estado inicial antes de cada caso: sin reset() se
        # acumulan los desplazamientos, sin setTime(0) el timeSeries escala
        # por el tiempo (el 2o caso valdria doble) y sin remove() las cargas
        # del caso anterior siguen actuando.
        if tag_previo is not None:
            ops.remove('loadPattern', tag_previo)
        ops.reset()
        ops.setTime(0.0)

        aplicar_cargas(caso, tag, nodos_validos, elementos_validos)
        tag_previo = tag

        ok = resolver_caso()
        if ok != 0:
            todo_ok = False

        r = extraer_resultados(data, restringidos)
        r['nombre'] = nombre
        r['ok'] = (ok == 0)
        resultados_casos.append(r)

    salida = {'ok': todo_ok, 'error': '', 'avisos': avisos}

    if multi:
        # El equilibrio de cada caso con la regla por grado de libertad: una
        # sola definicion, y Unity solo la muestra.
        for caso, r in zip(casos, resultados_casos):
            r['equilibrio'] = _equilibrio_del_caso(data, caso, r, avisos)
        salida['casos'] = resultados_casos
    else:
        r = resultados_casos[0]
        salida.update({
            'max_desplazamiento': r['max_desplazamiento'],
            'desplazamientos': r['desplazamientos'],
            'reacciones': r['reacciones'],
            'fuerzas_elementos': r['fuerzas_elementos'],
        })

    return salida


def _equilibrio_del_caso(data, caso, r, avisos):
    """equilibrio(), o None con un aviso: un chequeo que falla no tumba un analisis resuelto."""
    try:
        return equilibrio(data, caso, r)
    except Exception as e:
        avisos.append("No se pudo calcular el equilibrio de '%s': %s"
                      % (caso.get('nombre', '?'), e))
        return None


# ============================================================
# EQUILIBRIO: LA UNICA SUMA DE REACCIONES VALIDA
# ============================================================
def diafragmas(modelo):
    """
    (maestros, maestro_de {nodo: maestro}, en_diafragma, atadas): los nodos
    que ata algun diafragma y los indices de traslacion que ata (0 = x,
    1 = y, 2 = z). maestro_de toma el primer diafragma que nombra al nodo.
    """
    maestros, maestro_de, atadas = set(), {}, set()
    for d in modelo.get('diafragmas', []) or []:
        m = int(d['nodo_maestro'])
        maestros.add(m)
        maestro_de.setdefault(m, m)
        for n in d.get('nodos', []) or []:
            maestro_de.setdefault(int(n), m)
        p = int(d.get('perpendicular', 3))
        atadas |= {0: {1, 2}, 1: {1, 2}, 2: {0, 2}, 3: {0, 1}}.get(p, {0, 1})
    return maestros, maestro_de, set(maestro_de), atadas


def cuenta_en(nid, gdl, maestros, en_diafragma, atadas) -> bool:
    """
    Si la reaccion del nodo `nid` en la traslacion `gdl` (0, 1, 2) entra al
    equilibrio global. NO toda fila de reacciones es una reaccion de apoyo:
    nodeReaction en un nodo de diafragma trae tambien la fuerza de la
    RESTRICCION, que es interna (se cancela de a pares dentro del piso).
    Sumarla dobla el corte basal. La separacion es POR GDL:

      - en lo que ata el diafragma (x, y con perpendicular 3) solo valen los
        nodos fuera de todo diafragma: los apoyos de la base;
      - en z vale cualquier restringido salvo el MAESTRO, cuyo uz lo fijo el
        solver por necesidad numerica y no es un apoyo.

    No se puede descartar el nodo entero: los arranques de muro escalonados
    son apoyos verticales de verdad y a la vez estan en un diafragma.
    """
    if nid in maestros:
        return False
    return not (gdl in atadas and nid in en_diafragma)


def equilibrio(modelo, caso, res):
    """
    La carga aplicada contra lo que reaccionan los apoyos, por grado de
    libertad (ver cuenta_en). Las distribuidas vienen en ejes locales y se
    pasan a globales con localX/Y/Z si el elemento los trae (los mismos que
    se le mostraron a Unity) o con la regla del solver si no.

    Si una carga no se puede convertir, NO emite veredicto: 'confiable' queda
    en False y dice cuantas quedaron fuera. Un equilibrio que ignora en
    silencio parte de la carga es peor que no tenerlo.
    """
    aplicada = [0.0, 0.0, 0.0]
    for c in caso.get('cargas_nodales', []):
        for i, k in enumerate(('fx', 'fy', 'fz')):
            aplicada[i] += float(c.get(k, 0.0))

    nodos = {int(n['id']): n for n in modelo['nodos']}
    elementos = {int(e['id']): e for e in modelo['elementos']}

    sin_convertir = 0
    for c in caso.get('cargas_distribuidas', []):
        eid = int(c['elemento'])
        e = elementos.get(eid)
        if e is None:
            sin_convertir += 1
            continue

        a, b = nodos[int(e['n1'])], nodos[int(e['n2'])]
        pi = (a['x'], a['y'], a['z'])
        pj = (b['x'], b['y'], b['z'])

        if e.get('localX') and e.get('localY') and e.get('localZ'):
            base = {'wx': e['localX'], 'wy': e['localY'], 'wz': e['localZ']}
            L = math.sqrt(sum((pj[k] - pi[k]) ** 2 for k in range(3)))
        else:
            vecxz = e.get('vecxz') or _ed.vecxz_por_defecto(pi, pj)
            base, L = _ed.ejes_locales(pi, pj, [float(v) for v in vecxz])

        if base is None:
            sin_convertir += 1
            continue

        for k in ('wx', 'wy', 'wz'):
            w = float(c.get(k, 0.0))
            if w:
                for i in range(3):
                    aplicada[i] += w * L * base[k][i]

    maestros, _maestro_de, en_diafragma, atadas = diafragmas(modelo)
    reaccion = [0.0, 0.0, 0.0]
    for r in res.get('reacciones', []):
        nid = int(r['id'])
        for i, k in enumerate(('fx', 'fy', 'fz')):
            if cuenta_en(nid, i, maestros, en_diafragma, atadas):
                reaccion[i] += float(r.get(k, 0.0))

    return {
        'aplicada_kN': [round(v, 4) for v in aplicada],
        'reaccion_kN': [round(v, 4) for v in reaccion],
        'error_kN': [round(aplicada[i] + reaccion[i], 8) for i in range(3)],
        'cargas_sin_convertir': sin_convertir,
        'nodos_en_diafragma': len(en_diafragma),
        'confiable': sin_convertir == 0,
    }


def filas_que_cuentan(modelo, reacciones):
    """
    Cuantas filas de reaccion entran en Fx, Fy y Fz, preguntandoselo a
    equilibrio() con 1 kN en cada fila y ninguna carga: la 'reaccion' que
    devuelve es el conteo. Asi la regla sigue teniendo una sola definicion.
    """
    unos = {'reacciones': [{'id': r['id'], 'fx': 1.0, 'fy': 1.0, 'fz': 1.0,
                            'mx': 0.0, 'my': 0.0, 'mz': 0.0} for r in reacciones]}
    cuenta = equilibrio(modelo, {'cargas_nodales': [], 'cargas_distribuidas': []}, unos)
    return [int(round(v)) for v in cuenta['reaccion_kN']]


# ============================================================
# LOS CASOS DEL MODELO
# ============================================================
def resolver_edificio(modelo=None, solo_caso=None):
    """
    Los casos de carga que trae el edificio (G, Q, EX, EY: los "casos del
    modelo", los mismos que resuelve /analizar cuando Unity reanaliza),
    resueltos sobre el modelo armado una vez. Devuelve (lista de resultados
    por caso, avisos); cada resultado lleva su equilibrio y el nombre y la
    descripcion del caso.

    No son los casos del LABORATORIO (calculo/laboratorio.py: q y Cs de
    entrada/laboratorio.json): solo G coincide entre las dos fuentes.
    """
    modelo = modelo if modelo is not None else _ed.estructura()
    problemas = _ed.validar(modelo)
    if problemas:
        raise ValueError('el edificio tiene %d problema(s):\n  - %s'
                         % (len(problemas), '\n  - '.join(problemas[:10])))
    casos = modelo.get('casos_de_carga', [])
    if solo_caso:
        casos = [c for c in casos if c.get('nombre') == solo_caso]
        if not casos:
            raise ValueError('el caso %r no esta en el edificio' % solo_caso)
    data = dict(modelo)
    data['casos_de_carga'] = casos
    salida = construir_y_resolver(data)
    resueltos = []
    for caso, res in zip(casos, salida.get('casos') or [salida]):
        res = dict(res)
        res['edificio'] = _ed.NOMBRE
        res['caso'] = caso.get('nombre', 'unico')
        res['descripcion'] = caso.get('descripcion', '')
        res['equilibrio'] = equilibrio(modelo, caso, res)
        resueltos.append(res)
    return resueltos, salida.get('avisos', [])


# ============================================================
# MUCHOS PATRONES SOBRE UN MODELO (carga movil, persona)
# ============================================================
class Resolutor:
    """
    Arma el modelo UNA vez (construir_modelo, lo mismo que /analizar) y
    resuelve un patron de carga a la vez con el ciclo de construir_y_resolver:
    remove del patron anterior, reset, setTime(0), patron nuevo, resolver_caso.
    Lo usan la carga movil (30 posiciones de una P) y la persona (un caso
    unitario por GDL de cada nodo receptor): miles de casos sin rearmar nada.

        puntuales  [(eid, Px, Py, Pz, xL)] en ejes locales (beamPoint)
        nodales    [(nid, [fx, fy, fz, mx, my, mz])] globales
    """

    def __init__(self, modelo, tag_base=7000):
        self.modelo = modelo
        self.coords, self.avisos, self.restr = construir_modelo(modelo)
        self.tag = tag_base
        self.tag_previo = None
        self.ids_nodos = [int(n['id']) for n in modelo['nodos']]
        self.ids_elem = [int(e['id']) for e in modelo['elementos']]
        self.n_resueltos = 0

    def resolver(self, puntuales=(), nodales=()):
        if self.tag_previo is not None:
            ops.remove('loadPattern', self.tag_previo)
        ops.reset()
        ops.setTime(0.0)
        self.tag += 1
        ops.timeSeries('Linear', self.tag)
        ops.pattern('Plain', self.tag, self.tag)
        for eid, Px, Py, Pz, xL in puntuales:
            ops.eleLoad('-ele', int(eid), '-type', '-beamPoint',
                        float(Py), float(Pz), float(xL), float(Px))
        for nid, f in nodales:
            ops.load(int(nid), *[float(v) for v in f])
        self.tag_previo = self.tag
        ok = resolver_caso()
        if ok != 0:
            raise SystemExit('OpenSees no convergio (analyze = %d)' % ok)
        self.n_resueltos += 1
        return ok

    def extraer(self):
        """Los resultados redondeados como los devuelve el servidor."""
        return extraer_resultados(self.modelo, self.restr)

    def desplazamientos(self, ids=None):
        return {n: [ops.nodeDisp(n, i) for i in range(1, 7)]
                for n in (self.ids_nodos if ids is None else ids)}

    def reacciones(self):
        return {n: [ops.nodeReaction(n, i) for i in range(1, 7)] for n in self.restr}

    def fuerzas(self, elementos=None):
        """localForce (sin redondear) de esas barras, del ultimo caso resuelto."""
        return {int(e): list(ops.eleResponse(int(e), 'localForce'))
                for e in (self.ids_elem if elementos is None else elementos)}


# ============================================================
# LOS AVISOS QUE OPENSEES ESCRIBE EN LA CONSOLA
# ============================================================
class AvisosDeOpenSees(object):
    r"""
    Junta lo que OpenSees escribe en stderr mientras corre el bloque.

    La curva P-M sale de momento-curvatura hasta la falla, y Newton se
    atasca justo en el peak del hormigon: OpenSees imprime 'analyze failed'
    y capacidad.momento_curvatura lo rescata con ModifiedNewton y pasos
    chicos. Son avisos esperados, pero en una defensa en vivo tapan la
    salida. No se esconden: se cuentan y se dice de donde vienen.

    OpenSees escribe desde C++ al DESCRIPTOR 2, no a sys.stderr, asi que
    hay que redirigir el descriptor y no el objeto de Python.
    """

    def __enter__(self):
        sys.stderr.flush()
        self._tmp = tempfile.TemporaryFile()
        self._copia = os.dup(2)
        os.dup2(self._tmp.fileno(), 2)
        return self

    def __exit__(self, *exc):
        sys.stderr.flush()
        os.dup2(self._copia, 2)
        os.close(self._copia)
        self._tmp.seek(0)
        self.texto = self._tmp.read().decode('utf-8', 'replace')
        self._tmp.close()
        self.fallos = self.texto.count('analyze failed')
        return False

    def resumen(self):
        if not self.texto.strip():
            return None
        return ('OpenSees aviso %d vez(ces) "analyze failed" dentro de '
                'capacidad.interaccion: es el M-phi que se atasca en el peak '
                'del hormigon; se rescata con ModifiedNewton y, si no, el '
                'motivo queda en la curva' % self.fallos)
