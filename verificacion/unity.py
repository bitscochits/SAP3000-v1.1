# -*- coding: utf-8 -*-
r"""
================================================================
 verificacion/unity.py  -  LO QUE LEE UNITY, CONTRA LO QUE ESCRIBE PYTHON
================================================================
 JsonUtility (el parser de Unity) NO avisa cuando una clave no calza
 con un campo: deja la variable en su valor por defecto y sigue. Una
 clave mal escrita no da error ni warning, da un modelo que se dibuja
 raro (un 'uz' mal escrito es una deformada plana; un 'area', areas
 tributarias en cero). Y el C# copia a mano algunas formulas de Python
 para dibujar al instante: dos copias divergen en silencio. Este archivo
 junta todo lo que se comprueba LEYENDO el C# o haciendo leer a Unity:

   python -m verificacion.unity                    los cuatro bloques
   python -m verificacion.unity contratos          (U1)
   python -m verificacion.unity transcripciones    (U2)
   python -m verificacion.unity nombres_y_copias   (U3)
   python -m verificacion.unity jsonutility        (U4, abre Unity en batch)

 contratos
   Cada JSON que lee el visor contra las clases [System.Serializable]
   que lo leen, en las dos direcciones donde el contrato lo exige (una
   clave sin campo se pierde; un campo sin clave queda en 0, "" o null),
   con los tipos, los arreglos anidados (JsonUtility no los lee) y los
   largos que el visor da por supuestos:
     salidas/modelo.json        ModeloEstructural   (y su coherencia: ejes
                                locales, muros, terreno, w*L = q*A, losa +
                                peso propio = lo que recibe OpenSees)
     salidas/resultados.json    Resultados, sus bloques 'superposicion' y
                                'cargas_y_armadura', y la escala de la
                                deformada
     POST /combinar, GET /estados y PeticionCombinar (el servidor con
                                app.test_client: sin red, mismo codigo)
     salidas/carga_movil.json   AnexoCargaMovil
     salidas/persona.json       InfluenciasPersona
     salidas/relieve.json       RelieveJson
     Resources/Personaje/atst.json  PersonajeJson
     la respuesta de /analizar al modelo como lo manda JsonUtility
                                (float32, listas vacias, solo los campos
                                del C#)
   y que ninguna clase choque con UnityEngine. Si falta un .cs o una
   clase es FALLA, nunca PEND: un .cs que cambio de carpeta no puede
   dejar a su guardia leyendo la nada.

 transcripciones
   VisorEstructura.CurvaDe (la barra dibujada con las funciones de forma
   del elemento) contra elastica.desplazamiento_en, y la persona
   (N1..N4, FormaLocal, los seis Sumar, UzEn, el empotramiento, MyEn,
   MzEn) contra elastica: se LEEN las lineas del C#, se traducen a
   Python y se evaluan con numeros al azar (semilla fija).

 nombres_y_copias
   Las constantes ARCHIVO del C# = calculo.rutas.NOMBRES_EN_UNITY, y lo
   que hay en StreamingAssets (proyecto y cada build) y en la app AR es
   byte a byte lo de salidas/.

 jsonutility
   Unity en batch (Editor/VerificarLecturaJson.cs) lee los cinco JSON
   con sus clases y los vuelve a escribir; aca se compara campo a campo:
   un float calza si su float32 es el mismo, un entero o un texto si es
   igual. Sale con 2 si Unity tiene el proyecto abierto.

 Ninguna verificacion escribe en salidas/: comparan.
================================================================
"""
from __future__ import annotations

import argparse
import copy
import decimal
import hashlib
import io
import json
import math
import os
import random
import re
import sys
import time

from calculo import edificio as _ed
from calculo import elastica
from calculo import rutas
from calculo import superposicion as sp
from verificacion.comun import (Informe, arreglos_anidados, campos_de_clases, f32, tipo_calza,
                                titulo)
# Lo que manda Unity al servidor (JsonUtility.ToJson del modelo: solo los
# campos del C#, float32, listas vacias) tiene UNA definicion, la del
# reanalisis.
from verificacion.motor import como_jsonutility, esquema_csharp

BLOQUES = ('contratos', 'transcripciones', 'nombres_y_copias', 'jsonutility')

# Las constantes del C# con el nombre de cada archivo que lee el visor,
# por clave de rutas.NOMBRES_EN_UNITY: (archivo .cs, constante).
ARCHIVOS_CS = {
    'modelo': ('VisorEstructura.cs', 'ARCHIVO'),
    'resultados': ('VisorResultados.cs', 'ARCHIVO'),
    'carga_movil': ('VisorCargaMovil.cs', 'ARCHIVO'),
    'persona': ('VisorPersona.Deformada.cs', 'ARCHIVO'),
    'relieve': ('AmbienteVisor.Relieve.cs', 'ARCHIVO'),
    'excel': ('LectorStreaming.cs', 'EXCEL_RESULTADOS'),
}

# Los largos que el contrato fija (calculo.esfuerzos): f es localForce
# en i y en j, factores son (lG, lQ, lEX, lEY), vecxz un vector y cada
# restriccion los 6 GDL del nodo.
LARGO_F = 12
LARGO_FACTORES = 4
LARGO_VECXZ = 3
LARGO_RESTR = 6
ESTACIONES = ('x', 'N', 'Vy', 'Vz', 'T', 'My', 'Mz')
CURVA = ('P', 'Mn', 'Mmax', 'de')

# Las clases C# que leen cada parte de un JSON chico (None = la raiz).
CLASES_PERSONA = {
    'InfluenciasPersona': None,
    'InfoInfluencias': 'info',
    'GrupoInfluencias': 'grupos',
    'CasoInfluencia': 'casos',
    'ReceptorPersona': 'receptores',
}
CLASES_RELIEVE = {'RelieveJson': None, 'InfoRelieve': 'info', 'HuecoRelieve': 'huecos',
                  'VerticePlanta': 'techo_foto'}

# La semilla de las transcripciones de la persona: con la misma, los
# tiros al azar son los mismos de siempre y el peor numero se compara.
SEMILLA_PERSONA = 20261005
SEMILLA_CURVA = 20260923

# Nuestras clases viven en el namespace GLOBAL, asi que le GANAN al
# 'using UnityEngine'. Declarar 'class Material' rompe cualquier
# 'new Material(Shader.Find(...))' del proyecto, y en Unity un solo error
# de compilacion bloquea Add Component para TODOS los scripts.
UNITYENGINE = {
    'Material', 'Mesh', 'Object', 'Transform', 'Camera', 'Light',
    'Renderer', 'Collider', 'Rigidbody', 'Texture', 'Shader', 'Color',
    'Vector2', 'Vector3', 'Vector4', 'Quaternion', 'Bounds', 'Ray',
    'Animation', 'Animator', 'Sprite', 'Canvas', 'Random', 'Debug',
    'Time', 'Input', 'Application', 'Resources', 'GameObject', 'Scene',
    'Component', 'Behaviour', 'MonoBehaviour', 'Event', 'Gradient',
}


# ============================================================
# LEER EL C#
# ============================================================
def fuente_cs(nombre, inf):
    """(ruta, texto) de un .cs del visor por su nombre, o (None, '') con
    una FALLA si no esta o esta dos veces (rutas.cs lo decide)."""
    try:
        ruta = rutas.cs(nombre)
    except FileNotFoundError as e:
        inf.check(False, 'existe %s bajo unity/Assets' % nombre, str(e))
        return None, ''
    with io.open(ruta, encoding='utf-8') as f:
        return ruta, f.read()


def clases_de(nombres, inf):
    """{clase: {campo: tipo}} de varios .cs juntos (FALLA si falta uno)."""
    clases = {}
    for nombre in nombres:
        ruta, _ = fuente_cs(nombre, inf)
        if ruta:
            clases.update(campos_de_clases(ruta))
    return clases


def sin_comentarios(src):
    return re.sub(r'//[^\n]*', '', re.sub(r'/\*.*?\*/', '', src, flags=re.S))


def _lista(nombres, tope=8):
    nombres = sorted(nombres)
    return ', '.join(nombres[:tope]) + (' ...' if len(nombres) > tope else '')


def leer_json(nombre, inf):
    """(objeto, texto) de salidas/<nombre>, o (None, '') con una FALLA."""
    ruta = rutas.salida(nombre)
    if not os.path.isfile(ruta):
        inf.check(False, 'existe %s' % rutas.relativa(ruta),
                  'se genera con  python sap.py preparar')
        return None, ''
    with io.open(ruta, encoding='utf-8') as f:
        texto = f.read()
    return json.loads(texto), texto


# ============================================================
# COMPARAR UN FLUJO DE OBJETOS CONTRA SUS CLASES
# ============================================================
def objetos_por_tipo(raiz, objeto, clases, salida=None):
    """
    {clase C#: [objetos del JSON que JsonUtility vuelca en ella]},
    siguiendo los TIPOS de los campos desde la clase raiz: un campo cuyo
    tipo es una clase del contrato (o una lista de ellas) lleva a sus
    objetos. Asi el mapa no se escribe a mano y no se queda atras.
    """
    salida = {} if salida is None else salida
    salida.setdefault(raiz, []).append(objeto)
    for campo, tipo in (clases.get(raiz) or {}).items():
        v = objeto.get(campo) if isinstance(objeto, dict) else None
        m = re.fullmatch(r'List<(\w+)>', tipo) or re.fullmatch(r'(\w+)\[\]', tipo)
        if m and m.group(1) in clases and isinstance(v, list):
            for x in v:
                if isinstance(x, dict):
                    objetos_por_tipo(m.group(1), x, clases, salida)
        elif tipo in clases and isinstance(v, dict):
            objetos_por_tipo(tipo, v, clases, salida)
    return salida


def comparar_clases(inf, titulo_flujo, objetos, clases, sin_clave_valida=(), sin_campo_valido=()):
    r"""
    objetos = {clase C#: [objetos del JSON que JsonUtility vuelca en ella]}.
    (a) toda clave tiene campo, (b) todo campo tiene clave en CADA objeto,
    y cada valor cabe en el tipo del campo. sin_clave_valida: pares
    (clase, campo) que el contrato dice que NO viajan en este flujo;
    sin_campo_valido: pares (clase, clave) que viajan y el visor no lee, a
    proposito (se dicen, no se callan).
    """
    print()
    print('  -- %s --' % titulo_flujo)
    for clase, lista in objetos.items():
        if not inf.check(clase in clases, '%s: la clase %s existe en el C#' % (titulo_flujo, clase)):
            continue
        if not inf.check(bool(lista), '%s: %s tiene objetos para compararla' % (titulo_flujo, clase)):
            continue
        campos = set(clases[clase])
        union = set().union(*(set(o) for o in lista))
        interseccion = set(lista[0]).intersection(*(set(o) for o in lista[1:]))
        declaradas = {c for (k, c) in sin_campo_valido if k == clase} & union
        sobran = union - campos - declaradas
        faltan = campos - interseccion - {c for (k, c) in sin_clave_valida if k == clase}

        print('    %-22s %7d objetos, %2d claves, %2d campos publicos'
              % (clase, len(lista), len(union), len(campos)))
        if declaradas:
            print('  [--  ] %s: %s.%s viajan y el visor no las lee (declaradas en el contrato)'
                  % (titulo_flujo, clase, '/'.join(sorted(declaradas))))
        inf.check(not sobran, '%s: %s (a) las claves del JSON tienen campo C#' % (titulo_flujo, clase),
                  'sin campo C#: %s' % _lista(sobran) if sobran else '')
        detalle = ''
        if faltan:
            detalle = 'sin clave en el JSON: %s' % ', '.join(
                '%s (falta en %d de %d)' % (c, sum(1 for o in lista if c not in o), len(lista))
                for c in sorted(faltan))
        inf.check(not faltan, '%s: %s (b) los %d campos C# tienen clave en todos los objetos'
                  % (titulo_flujo, clase, len(campos)), detalle)

        malos, revisados = {}, 0
        for o in lista:
            for campo, tipo in clases[clase].items():
                if campo not in o:
                    continue
                revisados += 1
                motivo = tipo_calza(tipo, o[campo], clases)
                if motivo and campo not in malos:
                    malos[campo] = '%s %s: %s (id %s)' % (tipo, campo, motivo, o.get('id', '-'))
        inf.check(not malos, '%s: %s, %d valores caben en el tipo de su campo'
                  % (titulo_flujo, clase, revisados),
                  '; '.join(malos[c] for c in sorted(malos)) if malos else '')


def texto_sin_no_finitos(inf, texto, que):
    r"""json.dumps y jsonify escriben NaN e Infinity sin quejarse; no son
    JSON y JsonUtility no los lee."""
    hallados = [t for t in ('NaN', 'Infinity') if re.search(r'[:\[,]\s*-?%s' % t, texto)]
    inf.check(not hallados, '%s: sin NaN ni Infinity en el texto' % que,
              'aparece: %s' % ', '.join(hallados) if hallados else '')


def contrato_simple(inf, js, clases, mapa, ignorar=()):
    r"""
    Las dos direcciones sobre una muestra por clase (la raiz, o el primer
    objeto de la lista): lo que hacian los JSON chicos (persona, relieve,
    personaje). 'mapa' = {clase: clave del JSON o None}.
    """
    for clase, clave in mapa.items():
        muestra = js if clave is None else (js[clave][0] if isinstance(js[clave], list) else js[clave])
        en_cs = set(clases.get(clase, {}))
        sin_campo = sorted(k for k in set(muestra) - en_cs if k not in ignorar)
        sin_clave = sorted(en_cs - set(muestra))
        inf.check(clase in clases and not sin_campo and not sin_clave,
                  'contrato JSON <-> C#: %s%s' % (clase, '' if not (sin_campo or sin_clave) else
                                                 ' (claves sin campo %s, campos sin clave %s)'
                                                 % (sin_campo, sin_clave)))


# ============================================================
# CONTRATOS: salidas/modelo.json -> ModeloEstructural
# ============================================================
# Claves que el C# no necesita, a proposito. La comparacion del modelo
# revisa en UNA direccion: que cada clave del JSON tenga su campo. Una
# clave sin campo no rompe el dibujo (JsonUtility la ignora), pero es un
# dato que Unity no ve y que PIERDE si vuelve a escribir el modelo con
# JsonUtility.ToJson (el reanalisis y 'Guardar JSON' del editor). Estas
# son datos de analisis o de procedencia que Unity no dibuja:
#
#   enfierradura                                 el fierro, para la capacidad
#   E, G, E_del_cuerpo, fpc_MPa, b_h_deducidos  el hormigon por cuerpo;
#                                               Unity no calcula
#   incluye_peso_propio                          separa losa de peso propio
#   forma                                        procedencia del poligono
#   cuerpos, extra                               de que cuerpos se armo
NO_VAN_AL_CSHARP = {
    'ModeloEstructural': ('resumen',),
    'InfoModelo': ('cuerpos', 'extra'),
    'Elemento': ('enfierradura',),
    'Seccion': ('E', 'G', 'E_del_cuerpo', 'fpc_MPa', 'b_h_deducidos'),
    'AreaTributaria': ('forma',),
    'CasoDeCarga': ('incluye_peso_propio',),
}


def _claves(lista):
    """Las claves de TODOS los objetos de una lista, no solo las del
    primero: el primer elemento es una columna y solo los muros traen
    largo/espesor/dir_largo; solo las entradas del LT2 traen qG, w y luz."""
    todas = set()
    for o in lista:
        todas |= set(o.keys())
    return sorted(todas)


def _decimales(v):
    exp = decimal.Decimal(repr(float(v))).normalize().as_tuple().exponent
    return max(0, -int(exp))


def _en_poligono(x, y, poli, tol=1e-6):
    """Dentro o sobre el borde (a menos de tol)."""
    dentro = False
    for k in range(len(poli)):
        (ax, ay), (bx, by) = poli[k - 1], poli[k]
        lx, ly = bx - ax, by - ay
        if (abs(lx * (y - ay) - ly * (x - ax)) <= tol * max((lx * lx + ly * ly) ** 0.5, 1.0)
                and min(ax, bx) - tol <= x <= max(ax, bx) + tol
                and min(ay, by) - tol <= y <= max(ay, by) + tol):
            return True
        if (ay > y) != (by > y) and x < ax + (y - ay) * lx / ly:
            dentro = not dentro
    return dentro


def _dist_seg(x, y, s):
    ax, ay, bx, by = s
    lx, ly = bx - ax, by - ay
    l2 = lx * lx + ly * ly
    u = 0.0 if l2 < 1e-12 else max(0.0, min(1.0, ((x - ax) * lx + (y - ay) * ly) / l2))
    return ((x - ax - u * lx) ** 2 + (y - ay - u * ly) ** 2) ** 0.5


def contrato_modelo(inf):
    datos, _ = leer_json('modelo', inf)
    ruta_cs, _ = fuente_cs('ModeloEstructural.cs', inf)
    if datos is None or ruta_cs is None:
        return
    clases = campos_de_clases(ruta_cs)
    print('  json    %s  (%d nodos, %d elementos)'
          % (rutas.relativa(rutas.salida('modelo')), len(datos['nodos']), len(datos['elementos'])))
    print('  clases C# encontradas: %d' % len(clases))

    def comparar(nombre_clase, muestra, ignorar=()):
        """Toda clave del JSON debe existir como campo publico en el C#."""
        if not inf.check(nombre_clase in clases, 'la clase %s existe en el C#' % nombre_clase):
            return
        campos = clases[nombre_clase]
        faltan = [k for k in muestra if k not in campos and k not in ignorar]
        inf.check(not faltan, '%s: todas las claves del JSON estan en el C#' % nombre_clase,
                  'sin campo C#: %s' % faltan if faltan else '')

    titulo('modelo [1] Cada clave del JSON tiene su campo en C#')
    comparar('ModeloEstructural', datos.keys(), NO_VAN_AL_CSHARP['ModeloEstructural'])
    comparar('Nodo', _claves(datos['nodos']))
    comparar('Elemento', _claves(datos['elementos']), NO_VAN_AL_CSHARP['Elemento'])
    comparar('Seccion', _claves(datos['secciones']), NO_VAN_AL_CSHARP['Seccion'])
    comparar('Diafragma', _claves(datos['diafragmas']))
    comparar('AreaTributaria', _claves(datos['areas_tributarias']), NO_VAN_AL_CSHARP['AreaTributaria'])
    vert = [v for t in datos['areas_tributarias'] for v in t['vertices']]
    if vert:
        comparar('VerticePlanta', _claves(vert))
    else:
        print('  [--  ] VerticePlanta: no hay poligonos tributarios exportados '
              '(el visor no dibuja esa capa)')
    comparar('CasoDeCarga', _claves(datos['casos_de_carga']), NO_VAN_AL_CSHARP['CasoDeCarga'])
    comparar('CargaDistribuida', _claves([c for caso in datos['casos_de_carga']
                                          for c in caso.get('cargas_distribuidas', [])]))
    nodales = [c for caso in datos['casos_de_carga'] for c in caso.get('cargas_nodales', [])]
    if nodales:
        comparar('CargaNodal', _claves(nodales))
    comparar('InfoModelo', datos['info'].keys(), NO_VAN_AL_CSHARP['InfoModelo'])

    # Un campo presente pero vacio es igual de malo que uno ausente: se
    # dibuja "algo" y parece que funciona.
    titulo('modelo [2] Los campos que Unity necesita SI traen datos')
    e0 = datos['elementos'][0]
    inf.check(bool(e0.get('localX')) and len(e0['localX']) == 3,
              'los elementos traen ejes locales calculados')
    inf.check(any(n['fijo'] for n in datos['nodos']), 'hay nodos marcados como apoyo')
    inf.check(len(datos['diafragmas']) > 0, 'hay diafragmas exportados')
    inf.check(len(datos['areas_tributarias']) > 0, 'hay areas tributarias exportadas')
    contrato_terreno(inf, datos, comparar)

    t0 = datos['areas_tributarias'][0]
    inf.check(t0['area'] > 0, 'las areas tributarias traen area')
    contrato_poligonos(inf, datos)
    contrato_muros(inf, datos)

    # Los datos de dibujo de cada muro (dir_largo, largo, espesor, vecxz)
    # los trae el dato del edificio con la convencion de SU cuerpo; que
    # calcen con esa convencion por rango de tag lo comprueba
    # verificacion.edificio (dato, E1).
    print('  [--  ] la convencion de muros por cuerpo (rango de tag) la comprueba '
          'verificacion.edificio dato (E1)')

    titulo('modelo [3] Coherencia numerica de lo exportado')
    contrato_cargas_modelo(inf, datos, clases)


def contrato_terreno(inf, datos, comparar):
    r"""
    El suelo del visor (AmbienteVisor) va en info.cota_terreno, DONDE
    ARRANCA LA ESTRUCTURA, y el terreno viaja en NIVELES (info.terrenos):
    la base (sin region: todo el plano) y cada TERRAZA con su region en
    planta. La trampa era un suelo plano sobre un terreno escalonado: los
    39 apoyos en terreno de la terraza oriente quedaban 3.96 m en el aire.
    El guardia es que CADA apoyo no auxiliar quede SOBRE un nivel (su z =
    la del nivel cuya region lo contiene, 0.01 m), contado por nivel.
    """
    if 'cota_terreno' not in datos['info']:
        print('  [--  ] info.cota_terreno no viene: el visor pone el suelo en '
              'el apoyo mas bajo, con aviso en la consola')
        return
    cota = datos['info']['cota_terreno']

    def es_apoyo(n):
        return not n.get('auxiliar') and (n.get('fijo') or any(n.get('restricciones') or []))

    zs = [n['z'] for n in datos['nodos'] if es_apoyo(n)]
    z0 = min(zs) if zs else min(n['z'] for n in datos['nodos'])
    n_ap = sum(1 for z in zs if abs(z - z0) <= 0.01)
    porz = {n['id']: n['z'] for n in datos['nodos']}
    cols = sum(1 for e in datos['elementos']
               if e.get('tipo') == 'columna'
               and abs(min(porz.get(e['n1'], 1e9), porz.get(e['n2'], 1e9)) - z0) <= 0.01)
    # 0.01 m = AjustesVista.TOLERANCIA_COTA, la del visor; las cotas traen
    # 2 decimales.
    inf.check(isinstance(cota, (int, float)) and cota > -9000 and abs(cota - z0) <= 0.01,
              'info.cota_terreno (%s m) esta donde arranca la estructura' % cota,
              '%d apoyo(s) y %d columna(s) arrancan en z = %+.2f m' % (n_ap, cols, z0))
    terr = datos['info'].get('terrenos')
    if terr is None:
        arriba = [z for z in zs if z - z0 > 0.01]
        inf.check(not arriba, 'info.terrenos viene, o ningun apoyo queda sobre el suelo dibujado',
                  '%d de %d apoyo(s) a %s m de la cota' % (len(arriba), len(zs), ', '.join(
                      '%.2f' % a for a in sorted({round(z - z0, 2) for z in arriba}))) if arriba else '')
        return
    comparar('NivelTerreno', _claves(terr))
    vt = [v for t in terr for v in (t.get('vertices') or [])]
    if vt:
        comparar('VerticePlanta', _claves(vt))
    bases = [t for t in terr if not t.get('vertices')]
    terrazas = [t for t in terr if t.get('vertices')]
    inf.check(len(bases) == 1 and abs(bases[0]['z'] - cota) <= 0.01
              and all(t['z'] > cota + 0.01 and len(t['vertices']) >= 3 for t in terrazas),
              'info.terrenos: UNA base sin region en info.cota_terreno y '
              'cada terraza mas arriba, con su poligono',
              '; '.join('%s %+.2f m (%s)' % (t['nombre'], t['z'], '%d vertices' % len(t['vertices'])
                                              if t.get('vertices') else 'todo el plano')
                        for t in terr))
    if len(bases) != 1:
        return
    polis = [(t, [(float(v['x']), float(v['y'])) for v in t['vertices']]) for t in terrazas]
    por_nivel = {}                # (z, nombre) -> [apoyos, bajo terraza]
    flotan, enterrados = [], []
    for n in datos['nodos']:
        if not es_apoyo(n):
            continue
        contienen = [bases[0]] + [t for t, p in polis if _en_poligono(n['x'], n['y'], p)]
        sobre = [t for t in contienen if abs(n['z'] - t['z']) <= 0.01]
        if not sobre:
            (flotan if n['z'] > max(t['z'] for t in contienen)
             else enterrados).append('%s (%.2f, %.2f, %+.2f)' % (n['id'], n['x'], n['y'], n['z']))
            continue
        nivel = max(sobre, key=lambda t: t['z'])
        cuenta = por_nivel.setdefault((nivel['z'], nivel['nombre']), [0, 0])
        cuenta[0] += 1
        # Sobre la base pero dentro de la huella de una terraza: la cara
        # de la terraza lo taparia, y el visor se la recorta alrededor
        # (HuecoDelSuelo.CalcularTerraza).
        if any(t['z'] > nivel['z'] + 0.01 for t in contienen):
            cuenta[1] += 1
    inf.check(not flotan and not enterrados,
              'cada apoyo no auxiliar queda SOBRE un nivel del terreno (su z '
              '= la del nivel cuya region lo contiene, 0.01 m)',
              '; '.join('%d en %+.2f (%s)' % (c[0], z, nom) for (z, nom), c in sorted(por_nivel.items()))
              + ('; FLOTANDO: %s' % flotan[:6] if flotan else '')
              + ('; ENTERRADOS: %s' % enterrados[:6] if enterrados else ''))
    for (z, nom), c in sorted(por_nivel.items()):
        if c[1]:
            print('  [--  ] %d de los %d apoyos de %s (%+.2f m) caen bajo la '
                  'huella de una terraza: bajan a la base, y el visor les '
                  'recorta la terraza alrededor para que se vean' % (c[1], c[0], nom, z))

    # Los apoyos de una terraza que estan SOBRE estructura que baja (a
    # menos de HuecoDelSuelo.HOLGURA_TERRAZA de su eje en planta): el visor
    # los deja sobre el muro o la columna, sin tierra alrededor. Se
    # informa con la misma geometria que ReunirGeometria y la constante
    # del C#, leida de la fuente: una sola definicion.
    _, src_av = fuente_cs('AmbienteVisor.cs', inf)
    m = re.search(r'const\s+double\s+HOLGURA_TERRAZA\s*=\s*([0-9.]+)', src_av)
    inf.check(m is not None or not terrazas,
              'AmbienteVisor.cs dibuja las terrazas (HuecoDelSuelo.HOLGURA_TERRAZA)')
    if m and terrazas:
        holg = float(m.group(1))
        pn = {n['id']: n for n in datos['nodos']}
        for t, p in polis:
            lim = t['z'] - 0.01
            segs = [(q['x'], q['y'], q['x'], q['y']) for q in datos['nodos'] if q['z'] < lim]
            for e in datos['elementos']:
                a, b = pn.get(e['n1']), pn.get(e['n2'])
                if a is None or b is None or min(a['z'], b['z']) >= lim:
                    continue
                dl = e.get('dir_largo') or []
                if e.get('tipo') == 'muro' and len(dl) >= 2 and e.get('largo', 0) > 0.01:
                    h = 0.5 * e['largo'] / max((dl[0] ** 2 + dl[1] ** 2) ** 0.5, 1e-9)
                    cx, cy = 0.5 * (a['x'] + b['x']), 0.5 * (a['y'] + b['y'])
                    segs.append((cx - dl[0] * h, cy - dl[1] * h, cx + dl[0] * h, cy + dl[1] * h))
                else:
                    segs.append((a['x'], a['y'], b['x'], b['y']))
            suyos = [n for n in datos['nodos'] if es_apoyo(n)
                     and abs(n['z'] - t['z']) <= 0.01 and _en_poligono(n['x'], n['y'], p)]
            sobre_est = [n['id'] for n in suyos
                         if segs and min(_dist_seg(n['x'], n['y'], s) for s in segs) < holg]
            print('  [--  ] %s: %d de sus %d apoyos estan sobre estructura que '
                  'baja a la base (a menos de %.2f m, HOLGURA_TERRAZA): el visor '
                  'los deja sobre ella; los otros %d, sobre la tierra de la terraza'
                  % (t['nombre'], len(sobre_est), len(suyos), holg, len(suyos) - len(sobre_est)))
    # Nada bajo la cota = el suelo no tapa nada y HuecoDelSuelo.Calcular()
    # entra por su rama sin estampas. Si algun dia hay estructura mas
    # abajo, el hueco la destapa: por eso se informa y no se exige.
    bajo = sum(1 for n in datos['nodos'] if n['z'] < cota - 0.01)
    print('  [--  ] %d nodo(s) bajo la cota: %s'
          % (bajo, 'el suelo no tapa nada y el visor no cava' if not bajo
             else 'AmbienteVisor cava el hueco para que se vean'))


def contrato_poligonos(inf, datos):
    r"""
    Los poligonos NO miden todos lo mismo: una viga interior toma un
    TRAPECIO de un pano (4 vertices) y un TRIANGULO del otro (3). Sin
    'tamanos', Unity partia los vertices por division entera (7 / 2 = 3)
    y dibujaba lineas cruzadas que no existen.
    """
    trib = datos['areas_tributarias']
    hay = any(t['vertices'] for t in trib)
    inf.check(hay, 'se exportan poligonos tributarios (el visor dibuja esa capa)')
    if hay:
        sin_tam = [t['elemento'] for t in trib if t['vertices'] and not t.get('tamanos')]
        inf.check(not sin_tam, 'toda area tributaria declara el tamano de cada poligono',
                  "sin 'tamanos': %d" % len(sin_tam) if sin_tam else '')
    descuadres = [t['elemento'] for t in trib if sum(t.get('tamanos', [])) != len(t['vertices'])]
    inf.check(not descuadres, 'sum(tamanos) = cantidad de vertices',
              'descuadrados: %s' % descuadres[:5] if descuadres else '')
    degenerados = [t['elemento'] for t in trib if any(k < 3 for k in t.get('tamanos', []))]
    inf.check(not degenerados, 'ningun poligono tiene menos de 3 vertices')
    mal_contados = [t['elemento'] for t in trib if len(t.get('tamanos', [])) != t['n_poligonos']]
    inf.check(not mal_contados, 'len(tamanos) = n_poligonos')
    # El caso que estaba roto tiene que existir en los datos; si no, este
    # chequeo pasaria por vacio. Solo aplica si se CONCATENAN los
    # poligonos de una viga (las entradas del LT2).
    concatena = any(t.get('n_poligonos', 1) > 1 for t in trib)
    if hay and not concatena:
        print('  [--  ] un poligono por entrada: no aplica el chequeo de trapecio + triangulo')
    if hay and concatena:
        mixtos = [t for t in trib if len(set(t.get('tamanos', []))) > 1]
        inf.check(len(mixtos) > 0, 'hay vigas con poligonos de distinto tamano (el caso que fallaba)',
                  '%d vigas mezclan trapecio y triangulo' % len(mixtos))


def contrato_muros(inf, datos):
    """Sin largo/espesor el visor dibuja los muros como columnas flacas;
    sin dir_largo los deduce con la convencion de un cuerpo y los del otro
    salen girados 90 grados."""
    muros = [e for e in datos['elementos'] if e['tipo'] == 'muro']
    if not inf.check(bool(muros), 'el modelo trae muros que revisar'):
        return
    sin_geom = [m['id'] for m in muros if m.get('largo', 0) <= 0 or m.get('espesor', 0) <= 0]
    inf.check(not sin_geom, 'los muros traen largo y espesor para dibujarlos',
              'sin geometria: %d' % len(sin_geom) if sin_geom else '')
    sin_vec = [m['id'] for m in muros if not m.get('vecxz') or len(m['vecxz']) < 3]
    inf.check(not sin_vec, 'los muros traen vecxz (orientacion de su eje fuerte)')
    sin_dir = [m['id'] for m in muros if not m.get('dir_largo') or len(m['dir_largo']) < 2]
    inf.check(not sin_dir, 'los muros traen dir_largo (el visor no tiene que deducirlo)',
              'sin dir_largo: %d (%s)' % (len(sin_dir), sin_dir[:5]) if sin_dir else '')
    # Unitario con la cota MEDIDA contra su causa: el versor sale del delta
    # en planta del muro sobre su 'largo', con 4 decimales del plano (la
    # norma se aleja de 1 hasta 1e-4/largo) y componentes a 6 decimales
    # (1e-6 mas).
    no_unitarios = []
    for m in muros:
        dl = m.get('dir_largo') or []
        if len(dl) < 2:
            continue
        norma = (float(dl[0]) ** 2 + float(dl[1]) ** 2) ** 0.5
        cota = 1e-4 / max(float(m.get('largo', 0.0)), 1e-9) + 1e-6
        if abs(norma - 1.0) > cota:
            no_unitarios.append((m['id'], round(norma, 6), round(cota, 8)))
    inf.check(not no_unitarios, 'dir_largo es unitario dentro del redondeo del plano '
              '(1e-4 m sobre el largo del muro)',
              'fuera de cota: %s' % no_unitarios[:5] if no_unitarios else '')
    # La SECCION y el ELEMENTO cuentan lo mismo: b = espesor (ancho), h =
    # largo (canto). Las dos lecturas dan el MISMO A, Iy e Iz: cruzarlas
    # no se nota en ningun numero.
    cruzadas = []
    for s in datos['secciones']:
        if not (s.get('largo', 0) > 1e-3 and s.get('espesor', 0) > 1e-3):
            continue
        if not (s.get('b', 0) > 1e-3 and s.get('h', 0) > 1e-3):
            continue
        if abs(s['b'] - s['espesor']) > 1e-3 or abs(s['h'] - s['largo']) > 1e-3:
            cruzadas.append('%s (b %.4g/esp %.4g, h %.4g/largo %.4g)'
                            % (s['nombre'], s['b'], s['espesor'], s['h'], s['largo']))
    inf.check(not cruzadas, 'en las secciones con los dos pares, b = espesor y h = largo',
              'cruzadas: %s' % cruzadas[:3] if cruzadas else '')


def contrato_cargas_modelo(inf, datos, clases):
    r"""
    w*L = q*A por entrada (las que traen la carga), el area de cada viga
    en sus dos lugares, los tags, y "que lo carga" completo: losa + peso
    propio = lo que recibe OpenSees en G.
    """
    trib = datos['areas_tributarias']
    CARGA = ('w', 'luz', 'qG')
    con_carga = [t for t in trib if all(k in t for k in CARGA)]
    sin_carga = [t for t in trib if not all(k in t for k in CARGA)]
    if con_carga:
        peor = max(abs(t['w'] * t['luz'] - t['qG'] * t['area']) for t in con_carga)
        inf.check(peor < 1e-3, 'en el JSON se cumple w*L = q*A viga por viga '
                  '(%d entradas con carga)' % len(con_carga), 'peor error %.3e kN' % peor)
        en_cero = [t['elemento'] for t in con_carga
                   if not (t['qG'] > 0 and t['w'] > 0 and t['luz'] > 0)]
        inf.check(not en_cero, 'las entradas que traen qG, w y luz los traen distintos de cero',
                  'en cero: %s' % en_cero[:5] if en_cero else '')
    if sin_carga:
        # Las entradas del cuerpo antiguo no traen la carga por viga: el
        # dato del edificio no la tiene. En Unity quedan en 0 y el
        # inspector lo dice; la conservacion de la losa se verifica sobre
        # el modelo (verificacion.edificio tributarias, E3).
        print('  [--  ] %d de %d entradas de area tributaria no traen qG, w ni luz:'
              % (len(sin_carga), len(trib)))
        print('         en Unity quedan en 0 y el inspector no puede mostrar la')
        print('         carga por viga; la conservacion la verifica')
        print('         verificacion.edificio tributarias (E3)')

    # El AREA de una viga, en sus dos lugares: las entradas (un trapecio
    # por pano) y el total sellado en el elemento ('area_tributaria'). El
    # inspector lee el total si esta y si no suma las entradas: tienen que
    # ser el mismo numero. Cota medida contra sus dos causas: el redondeo
    # (n entradas + el total, medio escalon cada uno, a los decimales que
    # muestran) y la coma flotante de la formula del cordon (4 k c^2 eps).
    entradas_de = {}
    for t in trib:
        entradas_de.setdefault(t['elemento'], []).append(float(t['area']))
    elem_de = {e['id']: e for e in datos['elementos']}
    con_total = {eid: v for eid, v in entradas_de.items() if 'area_tributaria' in elem_de.get(eid, {})}
    if con_total:
        c = max([abs(float(v)) for t in trib for p in t['vertices'] for v in (p['x'], p['y'])]
                + [abs(float(n[k])) for n in datos['nodos'] for k in ('x', 'y')])
        k = max([k for t in trib for k in t.get('tamanos', [])] + [3])
        flotante = 4 * k * c * c * sys.float_info.epsilon
        peor_q, peor_id, fuera = 0.0, None, []
        for eid, areas in con_total.items():
            total = float(elem_de[eid]['area_tributaria'])
            d = max(_decimales(a) for a in areas + [total])
            cota = (len(areas) + 1) * (0.5 * 10.0 ** -d + flotante)
            q = abs(sum(areas) - total) / cota
            if q > peor_q:
                peor_q, peor_id = q, eid
            if q > 1.0:
                fuera.append(eid)
        sin_entradas = [e['id'] for e in datos['elementos']
                        if float(e.get('area_tributaria') or 0.0) > 0.0 and e['id'] not in entradas_de]
        varias = sum(1 for v in con_total.values() if len(v) > 1)
        inf.check(not fuera and not sin_entradas,
                  'suma de las entradas de cada viga = elemento.area_tributaria '
                  '(%d vigas, %d con mas de una entrada)' % (len(con_total), varias),
                  'peor error/cota %.6f (viga %s)' % (peor_q, peor_id)
                  + ('; fuera de cota: %s' % fuera[:5] if fuera else '')
                  + ('; con area y sin entradas: %s' % sin_entradas[:5] if sin_entradas else ''))

    r = datos.get('resumen') or {}
    if 'error_equilibrio_kN' in r:
        inf.check(r['error_equilibrio_kN'] < 1e-6, 'el resumen reporta equilibrio cerrado',
                  'error %.3e kN' % r['error_equilibrio_kN'])
    else:
        print('  [--  ] el resumen del modelo no trae error_equilibrio_kN; el equilibrio de los '
              'casos lo verifica verificacion.motor casos_del_modelo (M2)')

    ids = [e['id'] for e in datos['elementos']]
    inf.check(len(ids) == len(set(ids)), 'los elementTag son unicos')
    ids_n = [n['id'] for n in datos['nodos']]
    inf.check(len(ids_n) == len(set(ids_n)), 'los nodeTag son unicos')
    nodos_set = set(ids_n)
    huerfanos = [e['id'] for e in datos['elementos']
                 if e['n1'] not in nodos_set or e['n2'] not in nodos_set]
    inf.check(not huerfanos, 'todos los elementos referencian nodos existentes',
              'huerfanos: %s' % huerfanos[:5] if huerfanos else '')
    tags = set(ids)
    inf.check(not [t['elemento'] for t in trib if t['elemento'] not in tags],
              'toda area tributaria apunta a un elemento existente')

    # "QUE LO CARGA" COMPLETO. El panel daba w 15.749 kN/m (solo la losa) y
    # el diagrama wz de G -27.749: los 12.000 de peso propio no se
    # explicaban. Entrada por entrada:
    #   w + w_peso_propio = w_total_G
    #   w_total_G = -wz de la carga repartida de G de esa barra
    # Cota medida contra el redondeo (tres medios escalones en la suma, dos
    # en la comparacion con wz) mas 4 eps |w_total_G|.
    cs_trib = clases.get('AreaTributaria', {})
    inf.check('w_peso_propio' in cs_trib and 'w_total_G' in cs_trib,
              'AreaTributaria del C# tiene w_peso_propio y w_total_G')
    PESO = ('w_peso_propio', 'w_total_G')
    con_peso = [t for t in trib if all(k in t for k in PESO)]
    sin_peso = [t for t in trib if not all(k in t for k in PESO)]
    wz_de_G = {}
    for caso in datos['casos_de_carga']:
        if caso['nombre'] == 'G':
            for c in caso.get('cargas_distribuidas', []):
                wz_de_G[int(c['elemento'])] = float(c.get('wz', 0.0))
    if con_peso:
        peor_suma = peor_suma_q = peor_wz = peor_wz_q = 0.0
        fuera_suma, fuera_wz, sin_wz = [], [], []
        for t in con_peso:
            w, pp, tot = float(t['w']), float(t['w_peso_propio']), float(t['w_total_G'])
            flot = 4 * sys.float_info.epsilon * abs(tot)
            d = max(_decimales(v) for v in (w, pp, tot))
            err = abs(w + pp - tot)
            q = err / (3 * 0.5 * 10.0 ** -d + flot)
            peor_suma, peor_suma_q = max(peor_suma, err), max(peor_suma_q, q)
            if q > 1.0:
                fuera_suma.append(t['elemento'])
            wz = wz_de_G.get(int(t['elemento']))
            if wz is None:
                sin_wz.append(t['elemento'])
                continue
            d = max(_decimales(tot), _decimales(wz))
            err = abs(-wz - tot)
            q = err / (2 * 0.5 * 10.0 ** -d + flot)
            peor_wz, peor_wz_q = max(peor_wz, err), max(peor_wz_q, q)
            if q > 1.0:
                fuera_wz.append(t['elemento'])
        inf.check(not fuera_suma, 'w (losa) + w_peso_propio = w_total_G en cada entrada '
                  '(%d entradas)' % len(con_peso),
                  'peor error %.1e kN/m, error/cota %.3f' % (peor_suma, peor_suma_q)
                  + ('; fuera de cota: %s' % fuera_suma[:5] if fuera_suma else ''))
        inf.check(not fuera_wz and not sin_wz,
                  'w_total_G = -wz de la carga repartida de G de la misma barra '
                  '(lo que recibe OpenSees)',
                  'peor error %.1e kN/m, error/cota %.3f' % (peor_wz, peor_wz_q)
                  + ('; fuera de cota: %s' % fuera_wz[:5] if fuera_wz else '')
                  + ('; sin carga repartida en G: %s' % sin_wz[:5] if sin_wz else ''))
    if sin_peso:
        tipo = {e['id']: e.get('tipo', '') for e in datos['elementos']}
        muros = [t for t in sin_peso if tipo.get(t['elemento']) == 'muro'
                 and int(t['elemento']) not in wz_de_G] if con_peso else []
        if muros:
            print('  [--  ] %d entradas de muro sin w_peso_propio ni w_total_G: su losa '
                  'y su peso propio llegan como cargas' % len(muros))
            print('         nodales, no hay w repartida que separar')
        resto = len(sin_peso) - len(muros)
        if resto:
            print('  [--  ] %d de %d entradas no traen w_peso_propio ni w_total_G: el panel'
                  % (resto, len(trib)))
            print('         no puede separar la losa del peso propio (el dato del cuerpo')
            print('         antiguo no las trae; el C# los deja en 0 y lo dice)')


# ============================================================
# CONTRATOS: salidas/resultados.json -> Resultados
# ============================================================
def objetos_del_anexo(anexo):
    """
    {clase C#: [objetos]} de la parte de los casos del laboratorio:
    raiz -> info, casos[] -> desplazamientos[], esfuerzos[], demandas[];
    elementos[]; familias[]. Los bloques 'superposicion' y
    'cargas_y_armadura' van aparte, cada uno con su flujo.
    """
    casos = anexo.get('casos') or []
    return {
        'Resultados': [anexo],
        'InfoResultados': [anexo.get('info') or {}],
        'CasoLab': casos,
        'DespNodo': [d for c in casos for d in c.get('desplazamientos') or []],
        'EsfuerzosBarra': [e for c in casos for e in c.get('esfuerzos') or []],
        'Demanda': [d for c in casos for d in c.get('demandas') or []],
        'ElementoOpenSees': anexo.get('elementos') or [],
        'FamiliaPM': anexo.get('familias') or [],
    }


def contrato_resultados(inf, anexo, texto):
    ruta_visor, src_visor = fuente_cs('VisorResultados.cs', inf)
    ruta_modelo, _ = fuente_cs('ModeloEstructural.cs', inf)
    if ruta_visor is None or ruta_modelo is None:
        return None
    print('  json    %s  (%.2f MB)' % (rutas.relativa(rutas.salida('resultados')),
                                      len(texto.encode('utf-8')) / 1048576.0))
    # DespNodo es del modelo base; el resto, del visor. Si el visor
    # redefiniera una clase del modelo, no compila: se avisa.
    del_modelo = campos_de_clases(ruta_modelo)
    del_visor = campos_de_clases(ruta_visor)
    repetidas = set(del_modelo) & set(del_visor)
    clases = dict(del_modelo)
    clases.update(del_visor)
    print('  c#      %s (%d clases) + %s (%d clases)'
          % (os.path.basename(ruta_visor), len(del_visor), os.path.basename(ruta_modelo), len(del_modelo)))
    inf.check(not repetidas, 'ninguna clase del visor repite nombre con el modelo base',
              'repetidas: %s' % _lista(repetidas) if repetidas else '')
    # El visor tiene que deserializar la RAIZ con Resultados: si lee con
    # otra clase, esto compararia contra algo que nadie usa.
    inf.check('FromJson<Resultados>' in sin_comentarios(src_visor),
              'VisorResultados.cs lee el archivo con JsonUtility.FromJson<Resultados>')
    for campo, clase in (('superposicion', 'Superposicion'), ('cargas_y_armadura', 'CargasYArmadura')):
        tipo = (del_visor.get('Resultados') or {}).get(campo)
        inf.check(tipo == clase, 'Resultados.%s es un %s (el bloque llega con el mismo archivo)'
                  % (campo, clase), 'tipo en el C#: %s' % tipo if tipo != clase else '')

    objetos = objetos_del_anexo(anexo)

    titulo('resultados [1] (a) toda clave del JSON tiene campo C#   (b) todo campo C# tiene clave')
    print('    (b) se exige en CADA objeto: basta uno sin la clave para un valor por defecto')
    for clase, lista in objetos.items():
        if not inf.check(clase in clases, '%s existe en el C#' % clase):
            continue
        if not inf.check(bool(lista), '%s: el JSON trae objetos para compararla' % clase):
            continue
        campos = set(clases[clase])
        union = set().union(*(set(o) for o in lista))
        interseccion = set(lista[0]).intersection(*(set(o) for o in lista[1:]))
        sobran = union - campos
        faltan = campos - interseccion
        print('    %-16s %7d objetos, %2d claves, %2d campos publicos'
              % (clase, len(lista), len(union), len(campos)))
        inf.check(not sobran, '%s (a): las %d claves del JSON tienen campo' % (clase, len(union)),
                  'sin campo C#: %s' % _lista(sobran) if sobran else '')
        detalle = ''
        if faltan:
            ausentes = {c: sum(1 for o in lista if c not in o) for c in faltan}
            detalle = 'sin clave en el JSON: %s' % ', '.join(
                '%s (falta en %d de %d)' % (c, n, len(lista)) for c, n in sorted(ausentes.items()))
        inf.check(not faltan, '%s (b): los %d campos C# tienen clave en todos los objetos'
                  % (clase, len(campos)), detalle)

    titulo('resultados [2] cada valor cabe en el tipo de su campo C#')
    print('    (un decimal en un int, texto en un float o null no dan error: dan 0)')
    for clase, lista in objetos.items():
        if clase not in clases or not lista:
            continue
        malos, revisados = {}, 0
        for o in lista:
            for campo, tipo in clases[clase].items():
                if campo not in o:
                    continue
                if clase == 'Resultados' and campo in ('superposicion', 'cargas_y_armadura'):
                    continue          # sus objetos los revisa su propio flujo
                revisados += 1
                motivo = tipo_calza(tipo, o[campo], clases)
                if motivo and campo not in malos:
                    malos[campo] = '%s %s: %s (id %s)' % (tipo, campo, motivo, o.get('id', '-'))
        inf.check(not malos, '%s: %d valores revisados contra su tipo' % (clase, revisados),
                  '; '.join(malos[c] for c in sorted(malos)) if malos else '')

    titulo('resultados [3] nada que JsonUtility no sepa leer')
    anidados = arreglos_anidados(anexo)
    inf.check(not anidados, 'ningun arreglo dentro de otro arreglo',
              'primeros: %s' % ', '.join(anidados) if anidados else '')
    texto_sin_no_finitos(inf, texto, 'resultados.json')

    titulo('resultados [4] los largos que el visor da por supuestos al dibujar')
    esf = objetos['EsfuerzosBarra']
    malos = [e.get('id') for e in esf if len(e.get('f') or []) != LARGO_F]
    inf.check(not malos, 'f tiene %d valores en los %d esfuerzos (localForce en i y j)'
              % (LARGO_F, len(esf)), 'ids: %s' % malos[:8] if malos else '')
    malos = [e.get('id') for e in esf if len({len(e.get(k) or []) for k in ESTACIONES}) != 1]
    largos = sorted({len(e.get('x') or []) for e in esf})
    inf.check(not malos, '%s del mismo largo en cada esfuerzo (largos presentes: %s)'
              % (', '.join(ESTACIONES), largos), 'ids: %s' % malos[:8] if malos else '')
    n_carg = (anexo.get('info') or {}).get('n_estaciones_cargada')
    raros = [n for n in largos if n not in (2, n_carg)]
    inf.check(not raros, 'las estaciones son 2 (barra sin carga) o n_estaciones_cargada = %s'
              % n_carg, 'largos inesperados: %s' % raros if raros else '')
    fams = objetos['FamiliaPM']
    malos = [f.get('indice') for f in fams if len({len(f.get(k) or []) for k in CURVA}) != 1]
    inf.check(not malos, '%s del mismo largo en las %d familias P-M' % (', '.join(CURVA), len(fams)),
              'indices: %s' % malos if malos else '')
    vacias = [f.get('indice') for f in fams if len(f.get('P') or []) < 3]
    inf.check(not vacias, 'toda curva P-M tiene al menos 3 puntos',
              'indices: %s' % vacias if vacias else '')
    casos = objetos['CasoLab']
    malos = [c.get('nombre') for c in casos if len(c.get('factores') or []) != LARGO_FACTORES]
    inf.check(not malos, 'factores tiene %d valores (lG lQ lEX lEY) en los %d casos'
              % (LARGO_FACTORES, len(casos)), 'casos: %s' % malos if malos else '')
    elems = objetos['ElementoOpenSees']
    malos = [e.get('id') for e in elems
             if len(e.get('vecxz') or []) != LARGO_VECXZ
             or len(e.get('restr_n1') or []) != LARGO_RESTR
             or len(e.get('restr_n2') or []) != LARGO_RESTR]
    inf.check(not malos, 'vecxz de %d y restr_n1/restr_n2 de %d en los %d elementos'
              % (LARGO_VECXZ, LARGO_RESTR, len(elems)), 'ids: %s' % malos[:8] if malos else '')

    titulo('resultados [5] las referencias entre bloques apuntan a algo que existe')
    info = anexo.get('info') or {}
    ids = {e.get('id') for e in elems}
    nombres = [c.get('nombre') for c in casos]
    inf.check(len(ids) == len(elems), 'los id de elemento son unicos (%d)' % len(elems))
    inf.check(len(set(nombres)) == len(nombres), 'los nombres de caso son unicos: %s'
              % ', '.join(map(str, nombres)))
    inf.check(info.get('caso_por_defecto') in nombres,
              'caso_por_defecto = %s esta entre los casos' % info.get('caso_por_defecto'))
    for clave in ('columna_demo', 'muro_demo'):
        inf.check(info.get(clave) in ids, '%s = %s es un elemento del anexo' % (clave, info.get(clave)))
    indices = [f.get('indice') for f in fams]
    inf.check(indices == list(range(len(fams))),
              'familias[i].indice == i (el visor indexa la lista con familia)')
    fuera = sorted({e.get('familia') for e in elems} - set(indices) - {-1})
    fuera += sorted({d.get('familia') for d in objetos['Demanda']} - set(indices))
    inf.check(not fuera, 'toda familia citada por un elemento o una demanda existe (o es -1)',
              'fuera de rango: %s' % fuera[:8] if fuera else '')
    ajenos = [c.get('nombre') for c in casos if {e.get('id') for e in c.get('esfuerzos') or []} != ids]
    inf.check(not ajenos, 'cada caso trae esfuerzos para exactamente los %d elementos' % len(ids),
              'casos: %s' % ajenos if ajenos else '')
    print('  [--  ] que StreamingAssets traiga esta misma copia lo comprueba nombres_y_copias (U3)')

    titulo('resultados [6] la escala grafica de la deformada (info.escala_deformada)')
    print('    El visor la usa de valor por defecto: si viene en 0 se queda con la que tenia,')
    print('    y si no calza con el criterio la deformada sale de otro tamano que el declarado.')
    # El criterio y sus numeros los pone calculo.esfuerzos: aca no se
    # reimplementan (una sola definicion de cada cosa).
    from calculo.esfuerzos import escala_deformada
    esc = info.get('escala_deformada')
    numero = isinstance(esc, (int, float)) and not isinstance(esc, bool)
    inf.check(numero and esc > 0, 'escala_deformada = %s, mayor que 0' % esc)
    inf.check(isinstance(info.get('_escala_deformada_por_que'), str)
              and len(info.get('_escala_deformada_por_que') or '') > 0,
              'el criterio viaja al lado, en _escala_deformada_por_que',
              (info.get('_escala_deformada_por_que') or '')[:150] + ' ...')
    if numero and esc > 0:
        ref = escala_deformada(_ed.estructura(), casos)
        inf.check(esc == ref['escala'],
                  'es la que calcula esfuerzos.escala_deformada para %s: x%g' % (_ed.NOMBRE, ref['escala']),
                  'el anexo trae x%s' % esc if esc != ref['escala'] else '')
        # El objetivo declarado, con la tolerancia MEDIDA contra el
        # redondeo: la escala se redondea a 2 cifras (paso), asi que el
        # largo dibujado cae hasta medio paso de desplazamiento a cada lado.
        mayor_m = max([c.get('max_desplazamiento_mm') or 0.0 for c in casos]) / 1000.0
        dibujado = esc * mayor_m
        tol = ref['paso'] * mayor_m / 2.0 + 1e-9
        inf.check(abs(dibujado - ref['objetivo_m']) <= tol,
                  'escala x%g * %.4f mm = %.3f m = el objetivo declarado %.3f m '
                  '(+-%.4f m del redondeo a x%g)'
                  % (esc, mayor_m * 1000.0, dibujado, ref['objetivo_m'], tol, ref['paso']),
                  'el mayor desplazamiento es del caso %s' % ref['caso'])
    return clases


# Lo que el bloque 'cargas_y_armadura' trae y el visor no lee, a
# proposito: son la ficha para quien lee el JSON, no algo que se dibuje.
#   BloqueSismo.fraccion_Q_sismica   el parametro con que se armo el peso
#                                    sismico; el panel lo muestra desde
#                                    info.parametros de los resultados
#   BloqueArmadura.as_total_cm2, n1, n2, recubrimiento
#                                    la ficha de la columna de la jaula; el
#                                    visor la dibuja con las coordenadas de
#                                    cada barra y estribo (barras,
#                                    estribo_exterior, estribo_rombo) y de
#                                    sus nodos (nodo_inferior, nodo_superior)
# Una clave NUEVA sin campo sigue siendo FALLA.
NO_VAN_AL_CSHARP_CARGAS = {('BloqueSismo', 'fraccion_Q_sismica'),
                           ('BloqueArmadura', 'as_total_cm2'), ('BloqueArmadura', 'n1'),
                           ('BloqueArmadura', 'n2'), ('BloqueArmadura', 'recubrimiento')}


def contrato_cargas_y_armadura(inf, anexo):
    """El bloque 'cargas_y_armadura' (flechas, sismo, deformadas, jaula)
    contra las clases de VisorCargasYArmadura.cs, en las dos direcciones."""
    clases = clases_de(('VisorCargasYArmadura.cs', 'ModeloEstructural.cs'), inf)
    bloque = anexo.get('cargas_y_armadura')
    if not inf.check(isinstance(bloque, dict), 'resultados.json trae el bloque cargas_y_armadura'):
        return
    objetos = objetos_por_tipo('CargasYArmadura', bloque, clases)
    comparar_clases(inf, 'cargas_y_armadura', objetos, clases, sin_campo_valido=NO_VAN_AL_CSHARP_CARGAS)
    inf.check(not arreglos_anidados(bloque), 'cargas_y_armadura: ningun arreglo dentro de otro')


# ============================================================
# CONTRATOS: LA SUPERPOSICION (bloque, /combinar, /estados)
# ============================================================
def objetos_de_casos(casos):
    return {
        'CasoLab': casos,
        'DespNodo': [d for c in casos for d in c.get('desplazamientos') or []],
        'EsfuerzosBarra': [e for c in casos for e in c.get('esfuerzos') or []],
        'Demanda': [d for c in casos for d in c.get('demandas') or []],
    }


def revisar_caso(inf, caso, que, nombre, lambdas, referencia):
    r"""Lo que el visor da por supuesto de un CasoLab de superposicion."""
    factores = [lambdas[c] for c in sp.CASOS]
    inf.check(caso.get('nombre') == nombre and caso.get('tipo') == sp.TIPO,
              '%s: nombre = %r y tipo = %r' % (que, caso.get('nombre'), caso.get('tipo')),
              'se esperaba nombre %r, tipo %r' % (nombre, sp.TIPO)
              if (caso.get('nombre'), caso.get('tipo')) != (nombre, sp.TIPO) else '')
    inf.check(caso.get('factores') == factores, '%s: factores = [G, Q, EX, EY] = %s' % (que, factores),
              'vino %s' % caso.get('factores') if caso.get('factores') != factores else '')
    inf.check(caso.get('descripcion') == sp.texto_combinacion(lambdas),
              '%s: descripcion = %r' % (que, caso.get('descripcion')))
    esf = caso.get('esfuerzos') or []
    malos = [e.get('id') for e in esf if len(e.get('f') or []) != LARGO_F]
    inf.check(not malos, '%s: f de %d en los %d esfuerzos' % (que, LARGO_F, len(esf)),
              'ids: %s' % malos[:8] if malos else '')
    malos = [e.get('id') for e in esf if len({len(e.get(k) or []) for k in ESTACIONES}) != 1]
    inf.check(not malos, '%s: %s del mismo largo en cada barra' % (que, ', '.join(ESTACIONES)),
              'ids: %s' % malos[:8] if malos else '')
    for clave, bloque in (('desplazamientos', 'nodos'), ('esfuerzos', 'barras'),
                          ('demandas', 'barras con fierro')):
        ids = [int(x['id']) for x in caso.get(clave) or []]
        quiero = referencia[clave]
        inf.check(sorted(ids) == quiero and len(set(ids)) == len(ids),
                  '%s: %s de los mismos %d %s que los casos del laboratorio, sin repetir'
                  % (que, clave, len(quiero), bloque),
                  'vinieron %d (%d distintos)' % (len(ids), len(set(ids))) if sorted(ids) != quiero else '')
    familias = {int(d.get('familia', -1)) for d in caso.get('demandas') or []}
    fuera = sorted(f for f in familias if not 0 <= f < referencia['n_familias'])
    inf.check(not fuera, '%s: toda familia citada por una demanda existe en resultados.json (%d familias)'
              % (que, referencia['n_familias']), 'fuera: %s' % fuera if fuera else '')


def revisar_equilibrio(inf, eq, que):
    if eq is None:
        inf.check(False, '%s: trae equilibrio' % que)
        return
    largos = [len(eq.get(k) or []) for k in ('aplicada_kN', 'reaccion_kN', 'error_kN')]
    inf.check(largos == [3, 3, 3] and eq.get('confiable') is True,
              '%s: equilibrio con aplicada/reaccion/error de 3 y confiable = true' % que,
              'largos %s, confiable %r' % (largos, eq.get('confiable'))
              if largos != [3, 3, 3] or eq.get('confiable') is not True else '')


def contrato_superposicion(inf, anexo, texto):
    from exportar.resultados import GENERADO_POR
    titulo('superposicion [0] el C# que lee la superposicion')
    clases, origen = {}, {}
    fuente_sup = None
    for nombre in ('VisorResultados.Superposicion.cs', 'VisorResultados.cs', 'ModeloEstructural.cs'):
        ruta, src = fuente_cs(nombre, inf)
        if ruta is None:
            continue
        propias = campos_de_clases(ruta)
        partial = set(re.findall(r'partial\s+class\s+(\w+)', src))
        repetidas = (set(propias) & set(clases)) - partial
        inf.check(not repetidas, '%s: %d clases, ninguna repite nombre con %s'
                  % (nombre, len(propias), ', '.join(sorted({os.path.basename(origen[c])
                                                             for c in repetidas})) or 'las demas'),
                  'repetidas: %s' % _lista(repetidas) if repetidas else '')
        for c in propias:
            origen.setdefault(c, ruta)
            clases.setdefault(c, propias[c])
        if nombre == 'VisorResultados.Superposicion.cs':
            fuente_sup = sin_comentarios(src)
    if fuente_sup is not None:
        # El lector tiene que usar ESTAS clases en la raiz de cada
        # respuesta: si lee con otra, esto compararia contra algo que
        # nadie usa. El bloque precalculado llega dentro de Resultados.
        for raiz in ('RespuestaCombinar', 'RespuestaEstados'):
            inf.check(re.search(r'<\s*%s\s*>' % raiz, fuente_sup) is not None,
                      'VisorResultados.Superposicion.cs deserializa con <%s>' % raiz)

    titulo('superposicion [1] PeticionCombinar = lo que lee POST /combinar')
    lee_el_servidor = {'edificio'} | set(sp.CASOS)
    if inf.check('PeticionCombinar' in clases, 'la clase PeticionCombinar existe en el C#'):
        campos = set(clases['PeticionCombinar'])
        inf.check(campos == lee_el_servidor,
                  'campos de PeticionCombinar = claves que lee el servidor (%s)'
                  % ', '.join(sorted(lee_el_servidor)),
                  'solo en C#: %s; solo en el servidor: %s'
                  % (_lista(campos - lee_el_servidor) or '-', _lista(lee_el_servidor - campos) or '-')
                  if campos != lee_el_servidor else '')

    # La referencia de ids: los casos del laboratorio del mismo archivo,
    # que es sobre los que el visor registra los casos combinados.
    c0 = anexo['casos'][0]
    referencia = {
        'desplazamientos': sorted(int(d['id']) for d in c0['desplazamientos']),
        'esfuerzos': sorted(int(e['id']) for e in anexo['elementos']),
        'demandas': sorted(int(e['id']) for e in anexo['elementos'] if e['familia'] >= 0),
        'n_familias': len(anexo['familias']),
    }
    parametros = (anexo.get('info') or {}).get('parametros')
    estados = sp.cargar_estados()
    estados_esperados = [(e['nombre'], e['descripcion'], sp.lambdas_de(e['lambdas']))
                         for e in estados['estados']]

    titulo('superposicion [2] resultados.json, bloque superposicion  ->  Superposicion')
    pre = anexo.get('superposicion')
    if inf.check(isinstance(pre, dict), 'resultados.json trae el bloque superposicion'):
        est = pre.get('estados') or []
        casos = [e.get('caso') or {} for e in est]
        objetos = {'Superposicion': [pre], 'InfoSuperposicion': [pre.get('info') or {}],
                   'EstadoSuperposicion': est, 'Lambdas': [e.get('lambdas') or {} for e in est]}
        objetos.update(objetos_de_casos(casos))
        objetos['EquilibrioCaso'] = [e.get('equilibrio') or {} for e in est]
        comparar_clases(inf, 'precalculado', objetos, clases)
        inf.check(not arreglos_anidados(pre), 'precalculado: ningun arreglo dentro de otro')
        info = pre.get('info') or {}
        inf.check(info.get('edificio') == _ed.NOMBRE and info.get('generado_por') == GENERADO_POR,
                  'info.edificio = %r, info.generado_por = %r' % (info.get('edificio'), info.get('generado_por')))
        hay = [(e.get('nombre'), e.get('descripcion'), e.get('lambdas')) for e in est]
        inf.check(hay == estados_esperados, 'estados = E1, E2, E3 de entrada/laboratorio.json, en ese orden '
                  '(nombre, descripcion, lambdas)', 'vino %s' % hay if hay != estados_esperados else '')
        for e in est:
            if e.get('lambdas') and e.get('caso'):
                revisar_caso(inf, e['caso'], 'precalculado %s' % e.get('nombre'), e.get('nombre'),
                             sp.lambdas_de(e['lambdas']), referencia)
                revisar_equilibrio(inf, e.get('equilibrio'), 'precalculado %s' % e.get('nombre'))
        inf.check(info.get('parametros') == parametros,
                  'info.parametros del bloque = info.parametros de los resultados',
                  ['bloque:     %s' % info.get('parametros'), 'resultados: %s' % parametros]
                  if info.get('parametros') != parametros else '')

    titulo('superposicion [3] POST /combinar y GET /estados (servidor con app.test_client, sin red)')
    from exportar import servidor
    servidor.ARGV_PARAMETROS[:] = []
    cliente = servidor.app.test_client()
    http = cliente.get('/estados')
    resp = http.get_json(silent=True) or {}
    inf.check(http.status_code == 200 and resp.get('ok') is True and resp.get('error') == '',
              'GET /estados: HTTP %d, ok = %r, error = %r' % (http.status_code, resp.get('ok'), resp.get('error')))
    texto_sin_no_finitos(inf, http.get_data(as_text=True), 'GET /estados')
    est = resp.get('estados') or []
    rangos = resp.get('rangos') or {}
    comparar_clases(inf, 'GET /estados', {
        'RespuestaEstados': [resp], 'EstadoSuperposicion': est,
        'Lambdas': [e.get('lambdas') or {} for e in est],
        'Rangos': [rangos], 'Rango': [rangos[c] for c in sp.CASOS if c in rangos],
    }, clases, sin_clave_valida={('EstadoSuperposicion', 'caso'), ('EstadoSuperposicion', 'equilibrio')})
    hay = [(e.get('nombre'), e.get('descripcion'), e.get('lambdas')) for e in est]
    inf.check(hay == estados_esperados, 'GET /estados: E1, E2, E3 de entrada/laboratorio.json en ese orden')
    inf.check(all('caso' not in e for e in est), 'GET /estados: los estados no traen caso')
    malos = []
    for c in sp.CASOS:
        r = rangos.get(c) or {}
        mn, mx, paso = r.get('min'), r.get('max'), r.get('paso')
        if not all(isinstance(v, (int, float)) for v in (mn, mx, paso)) or not (mn < mx and paso > 0):
            malos.append('%s: %r' % (c, r))
            continue
        pasos = (mx - mn) / paso
        if abs(pasos - round(pasos)) > 1e-9:
            malos.append('%s: (max - min) / paso = %.6f no es entero' % (c, pasos))
        for nombre, _d, lam in estados_esperados:
            k = (lam[c] - mn) / paso
            if not mn - 1e-12 <= lam[c] <= mx + 1e-12 or abs(k - round(k)) > 1e-9:
                malos.append('%s: %s = %g no cae en un paso del slider' % (nombre, c, lam[c]))
    inf.check(not malos, 'rangos de G, Q, EX, EY: min < max, paso entero, y E1..E3 caen en un paso '
              'de cada slider', malos)
    if servidor.PERMITIR_CORS:
        inf.check(http.headers.get('Access-Control-Allow-Origin') == '*',
                  'GET /estados trae Access-Control-Allow-Origin: * (build Web)')

    # Un estado con lambda negativo, uno con EY y la combinacion nula: los
    # tres caminos distintos del caso combinado.
    pedidos = [('E3', dict(estados_esperados[2][2])),
               ('0.9G - 1.0EY', {'G': 0.9, 'Q': 0.0, 'EX': 0.0, 'EY': -1.0}),
               ('nula', {'G': 0.0, 'Q': 0.0, 'EX': 0.0, 'EY': 0.0})]
    respuestas = []
    for que, lam in pedidos:
        # El cuerpo como lo arma VisorResultados.Superposicion.cs: las
        # cinco claves, numeros con '.'.
        cuerpo = json.dumps(dict(edificio=_ed.NOMBRE, **lam))
        http = cliente.post('/combinar', data=cuerpo, content_type='application/json')
        resp = http.get_json(silent=True) or {}
        ok = inf.check(http.status_code == 200 and resp.get('ok') is True and resp.get('error') == '',
                       'POST /combinar %s: HTTP %d, ok = %r' % (que, http.status_code, resp.get('ok')),
                       resp.get('error') or '')
        if not ok:
            continue
        texto_sin_no_finitos(inf, http.get_data(as_text=True), 'POST /combinar %s' % que)
        inf.check(resp.get('edificio') == _ed.NOMBRE, 'POST /combinar %s: edificio = %r'
                  % (que, resp.get('edificio')))
        inf.check(resp.get('parametros') == parametros,
                  'POST /combinar %s: parametros = info.parametros de los resultados' % que)
        revisar_caso(inf, resp.get('caso') or {}, 'POST /combinar %s' % que, sp.NOMBRE_LIBRE,
                     sp.lambdas_de(lam), referencia)
        revisar_equilibrio(inf, resp.get('equilibrio'), 'POST /combinar %s' % que)
        respuestas.append(resp)
        if que == pedidos[0][0] and servidor.PERMITIR_CORS:
            inf.check(http.headers.get('Access-Control-Allow-Origin') == '*',
                      'POST /combinar trae Access-Control-Allow-Origin: * (build Web)')
    if respuestas:
        objetos = {'RespuestaCombinar': respuestas}
        objetos.update(objetos_de_casos([r.get('caso') or {} for r in respuestas]))
        objetos['EquilibrioCaso'] = [r.get('equilibrio') or {} for r in respuestas]
        comparar_clases(inf, 'POST /combinar', objetos, clases)
        inf.check(not any(arreglos_anidados(r) for r in respuestas),
                  'POST /combinar: ningun arreglo dentro de otro')

    titulo('superposicion [4] los errores tambien son JSON {ok: false, error} (Unity lee el cuerpo)')
    malos_pedidos = [
        ('cuerpo que no es JSON', '{"edificio": "%s", "G": ' % _ed.NOMBRE, 400),
        ('cuerpo que es una lista', '[1.2, 1.0, 0, 0]', 400),
        ('edificio con ruta', json.dumps({'edificio': '../salidas/modelo', 'G': 1.0}), 400),
        ('edificio inexistente', json.dumps({'edificio': 'no_existe', 'G': 1.0}), 400),
        ('factor de texto', json.dumps({'edificio': _ed.NOMBRE, 'G': '1.2'}), 400),
        ('factor booleano', json.dumps({'edificio': _ed.NOMBRE, 'G': True}), 400),
        ('factor infinito', '{"edificio": "%s", "G": 1e999}' % _ed.NOMBRE, 400),
    ]
    for que, cuerpo, codigo in malos_pedidos:
        http = cliente.post('/combinar', data=cuerpo, content_type='application/json')
        resp = http.get_json(silent=True)
        bien = (http.status_code == codigo and isinstance(resp, dict) and resp.get('ok') is False
                and isinstance(resp.get('error'), str) and resp.get('error') != '')
        inf.check(bien, 'POST /combinar con %s: HTTP %d y {ok: false, error: "..."}' % (que, http.status_code),
                  'error: %s' % (resp or {}).get('error') if bien else 'vino %r' % (resp,))
    if 'RespuestaCombinar' in clases:
        faltan = {'ok', 'error'} - set(clases['RespuestaCombinar'])
        inf.check(not faltan, 'RespuestaCombinar tiene ok y error (lo que Unity mira en un error)',
                  'faltan: %s' % _lista(faltan) if faltan else '')


# ============================================================
# CONTRATOS: LOS JSON CHICOS
# ============================================================
def _tipo_movil(tipo, valor):
    if tipo == 'int':
        return isinstance(valor, int) and not isinstance(valor, bool)
    if tipo == 'float':
        return isinstance(valor, (int, float)) and not isinstance(valor, bool) and math.isfinite(valor)
    if tipo == 'bool':
        return isinstance(valor, bool)
    if tipo == 'string':
        return isinstance(valor, str)
    if tipo.endswith('[]'):
        return isinstance(valor, list) and all(_tipo_movil(tipo[:-2], v) for v in valor)
    if tipo.startswith('List<'):
        return isinstance(valor, list) and all(isinstance(v, dict) for v in valor)
    return isinstance(valor, dict)


def contrato_carga_movil(inf):
    titulo('carga movil [j] el JSON contra las clases C# de VisorCargaMovil.cs')
    anexo, _ = leer_json('carga_movil', inf)
    clases = clases_de(('ModeloEstructural.cs', 'VisorCargaMovil.cs'), inf)
    if anexo is None:
        return
    posiciones = anexo['posiciones']
    objetos = {
        'AnexoCargaMovil': [anexo],
        'InfoMovil': [anexo['info']],
        'RecorridoMovil': [anexo['recorrido']],
        'VerificacionMovil': anexo['info']['verificaciones'],
        'PosicionMovil': posiciones,
        'PuntoElasticaMovil': [pt for p in posiciones for pt in p['elastica']],
        'RepartoMovil': [p['reparto'] for p in posiciones],
        'ConservacionMovil': [p['conservacion'] for p in posiciones],
        'EquilibrioCaso': [p['equilibrio'] for p in posiciones],
        'DespNodo': [d for p in posiciones for d in p['desplazamientos']],
        'ReacNodo': [r for p in posiciones for r in p['reacciones']],
    }
    malos = []
    for clase, objs in objetos.items():
        campos = clases.get(clase)
        if campos is None:
            malos.append('no existe la clase C# %s' % clase)
            continue
        claves = set()
        for o in objs:
            claves |= set(o)
            for c in campos:
                if c not in o:
                    malos.append('%s.%s no viene en el JSON' % (clase, c))
                    break
        for c in sorted(claves - set(campos)):
            malos.append('clave "%s" sin campo en %s' % (c, clase))
        for o in objs[:50]:
            for c, t in campos.items():
                if c in o and not _tipo_movil(t, o[c]):
                    malos.append('%s.%s es %s y el JSON trae %r' % (clase, c, t, type(o[c]).__name__))
        # arreglos de arreglos: JsonUtility los deja vacios sin avisar
        for o in objs[:5]:
            for c, v in o.items():
                if isinstance(v, list) and v and isinstance(v[0], list):
                    malos.append('%s.%s es un arreglo de arreglos' % (clase, c))
    malos = sorted(set(malos))
    inf.check(not malos, '[j] el JSON calza con las clases C# en las dos direcciones '
              '(%d clases, %d objetos)' % (len(objetos), sum(len(v) for v in objetos.values())),
              '; '.join(malos[:8]))


def contrato_persona(inf):
    titulo('persona [4] cada clave de persona.json tiene su campo C# y al reves')
    js, _ = leer_json('persona', inf)
    ruta, _ = fuente_cs('VisorPersona.Deformada.cs', inf)
    if js is None or ruta is None:
        return
    # _U y _F son los factores de escala de los enteros: el C# los lee con
    # otro nombre ([SerializeField] en el lector), no son claves perdidas.
    contrato_simple(inf, js, campos_de_clases(ruta), CLASES_PERSONA, ignorar=('_U', '_F'))


def contrato_relieve(inf):
    titulo('relieve: cada clave de relieve.json tiene su campo C# y al reves')
    js, _ = leer_json('relieve', inf)
    ruta, _ = fuente_cs('AmbienteVisor.Relieve.cs', inf)
    ruta_m, _ = fuente_cs('ModeloEstructural.cs', inf)
    if js is None or ruta is None or ruta_m is None:
        return
    clases = campos_de_clases(ruta)
    clases.update({k: v for k, v in campos_de_clases(ruta_m).items() if k == 'VerticePlanta'})
    contrato_simple(inf, js, clases, CLASES_RELIEVE)


def contrato_personaje(inf):
    titulo('personaje: Resources/Personaje/atst.json contra VisorPersona.Personaje.cs')
    from herramientas.atst import CLASES_CS
    ruta_json = os.path.join(rutas.RESOURCES, 'Personaje', 'atst.json')
    ruta, _ = fuente_cs('VisorPersona.Personaje.cs', inf)
    if not inf.check(os.path.isfile(ruta_json), 'existe %s' % rutas.relativa(ruta_json),
                     '' if os.path.isfile(ruta_json) else 'se arma con  python sap.py atst') or ruta is None:
        return
    with io.open(ruta_json, encoding='utf-8') as f:
        js = json.load(f)
    contrato_simple(inf, js, campos_de_clases(ruta), CLASES_CS)


def _claves_agregadas(original, emulado, cuenta):
    """Cuenta, por nombre de campo, los que JsonUtility escribe con su
    valor por defecto porque el JSON no los traia ([], 0, "")."""
    if isinstance(emulado, dict):
        original = original if isinstance(original, dict) else {}
        for k, v in emulado.items():
            if k not in original:
                cuenta[k] = cuenta.get(k, 0) + 1
            else:
                _claves_agregadas(original[k], v, cuenta)
    elif isinstance(emulado, list) and isinstance(original, list):
        for x, y in zip(original, emulado):
            _claves_agregadas(x, y, cuenta)


def contrato_respuesta_analizar(inf):
    r"""
    La respuesta de POST /analizar contra las clases que la leen
    (RespuestaServidor, CasoResultado, DespNodo, ReacNodo, FuerzaElemento,
    EquilibrioCaso), resolviendo el modelo COMO LO MANDA UNITY: lo que
    deja JsonUtility.ToJson(ModeloEstructural) -- solo los campos del C#,
    float32, y listas vacias donde el JSON no traia la clave (JsonUtility
    escribe SIEMPRE todos los campos). El servidor tiene que aceptarlo.
    Se llama a la misma funcion que atiende /analizar
    (opensees.construir_y_resolver), sin el Excel que la ruta escribe en
    salidas/.
    """
    from calculo import opensees
    titulo('analizar: la respuesta de POST /analizar al modelo que manda Unity')
    modelo, _ = leer_json('modelo', inf)
    ruta, _ = fuente_cs('ModeloEstructural.cs', inf)
    if modelo is None or ruta is None:
        return
    esquema = esquema_csharp(ruta)
    clases = campos_de_clases(ruta)
    enviado = como_jsonutility(modelo, 'ModeloEstructural', esquema)
    agregadas = {}
    _claves_agregadas(modelo, enviado, agregadas)
    print('  el modelo como lo escribe JsonUtility: %d campos que el JSON no traia, escritos con '
          'su defecto (%s)' % (sum(agregadas.values()), ', '.join(
              '%s %d' % (k, n) for k, n in sorted(agregadas.items(), key=lambda x: -x[1])[:6]) or '-'))
    t0 = time.time()
    try:
        with opensees.LOCK:
            R = opensees.construir_y_resolver(copy.deepcopy(enviado))
    except Exception as e:                       # noqa: BLE001 -- se informa como falla
        inf.check(False, 'el servidor acepta el modelo como lo manda JsonUtility', str(e)[:200])
        return
    # La ruta agrega el Excel del reanalisis a la respuesta: viajan
    # siempre, aunque aca no se escriban.
    R['excel'], R['excel_error'] = '', ''
    casos = R.get('casos') or []
    inf.check([c.get('nombre') for c in casos] == ['G', 'Q', 'EX', 'EY']
              and all(c.get('ok') for c in casos),
              'el servidor acepta el modelo como lo manda JsonUtility y resuelve G, Q, EX y EY '
              '(%.0f s)' % (time.time() - t0), '%s' % [(c.get('nombre'), c.get('ok')) for c in casos])
    for c in casos:
        revisar_equilibrio(inf, c.get('equilibrio'), 'respuesta %s' % c.get('nombre'))
    objetos = {
        'RespuestaServidor': [R],
        'CasoResultado': casos,
        'DespNodo': [d for c in casos for d in c.get('desplazamientos') or []],
        'ReacNodo': [r for c in casos for r in c.get('reacciones') or []],
        'FuerzaElemento': [f for c in casos for f in c.get('fuerzas_elementos') or []],
        'EquilibrioCaso': [c['equilibrio'] for c in casos if c.get('equilibrio')],
    }
    for clase, lista in objetos.items():
        if not inf.check(clase in clases and bool(lista), '%s existe en el C# y la respuesta trae objetos'
                         % clase):
            continue
        union = set().union(*(set(o) for o in lista))
        sobran = union - set(clases[clase])
        inf.check(not sobran, 'respuesta -> %s: las %d claves tienen campo C# (%d objetos)'
                  % (clase, len(union), len(lista)), 'el C# NO tiene: %s' % _lista(sobran) if sobran else '')
    for clave in ('desplazamientos', 'reacciones', 'fuerzas_elementos'):
        inf.check(all(isinstance(c.get(clave, []), list) for c in casos), "'%s' es lista en cada caso" % clave)
    inf.check(not arreglos_anidados({k: v for k, v in R.items() if k != 'casos'})
              and not any(arreglos_anidados({k: v for k, v in c.items() if k != 'fuerzas_elementos'})
                          for c in casos),
              'la respuesta no trae arreglos dentro de arreglos (salvo f de cada barra, que es float[])')


def clases_sin_choque(inf):
    titulo('clases: ninguna choca con UnityEngine ni se declara dos veces')
    declaradas = {}
    for base in (rutas.SCRIPTS_CS, rutas.EDITOR_CS):
        for d, _, archivos in os.walk(base):
            for a in sorted(archivos):
                if not a.endswith('.cs'):
                    continue
                with io.open(os.path.join(d, a), encoding='utf-8') as f:
                    src = sin_comentarios(f.read())
                partial = set(re.findall(r'partial\s+class\s+(\w+)', src))
                for m in re.finditer(r'^([ \t]*)(?:\[[^\]]*\]\s*)*(?:public\s+|internal\s+)?'
                                     r'(?:static\s+|sealed\s+|abstract\s+)*class\s+(\w+)', src, re.M):
                    # Solo las de nivel superior: una clase anidada vive dentro
                    # de la suya y no choca con otra del mismo nombre.
                    if m.group(1) == '' and m.group(2) not in partial:
                        declaradas.setdefault(m.group(2), []).append(a)
    dups = {c: fs for c, fs in declaradas.items() if len(fs) > 1}
    inf.check(not dups, 'ninguna clase de nivel superior declarada dos veces (%d clases)' % len(declaradas),
              'duplicadas: %s' % dups if dups else '')
    choques = sorted(set(declaradas) & UNITYENGINE)
    inf.check(not choques, 'ningun nombre de clase choca con UnityEngine',
              'CHOCAN: %s -> renombralas' % choques if choques else '')


def contratos(inf):
    titulo('=== modelo.json -> ModeloEstructural (VisorEstructura) ===')
    contrato_modelo(inf)
    titulo('=== resultados.json -> Resultados (VisorResultados) ===')
    anexo, texto = leer_json('resultados', inf)
    if anexo is not None:
        contrato_resultados(inf, anexo, texto)
        titulo('cargas_y_armadura -> CargasYArmadura (VisorCargasYArmadura)')
        contrato_cargas_y_armadura(inf, anexo)
        contrato_superposicion(inf, anexo, texto)
    titulo('=== carga_movil.json, persona.json, relieve.json, atst.json ===')
    contrato_carga_movil(inf)
    contrato_persona(inf)
    contrato_relieve(inf)
    contrato_personaje(inf)
    contrato_respuesta_analizar(inf)
    clases_sin_choque(inf)


# ============================================================
# TRANSCRIPCIONES: LA CURVA DE LA DEFORMADA
# ============================================================
def _base_de(wx, wy, wz):
    return {'wx': wx, 'wy': wy, 'wz': wz}


def voladizo(direccion):
    """
    Resuelve en OpenSees un voladizo de UNA barra con carga en la punta y
    devuelve (L, EI, ui, uj, base, P) para interpolar su elastica.
    'direccion' es hacia donde corre la barra: 'x', 'y' o 'z'. La carga va
    siempre perpendicular a ella, para que la barra flecte.
    """
    import openseespy.opensees as ops
    L, E, P = 6.0, 25_000_000.0, 10.0          # m, kPa, kN
    b, h = 0.30, 0.50
    A, Iz, Iy = b * h, b * h ** 3 / 12.0, h * b ** 3 / 12.0
    J = Iy + Iz
    G = E / 2.4
    punta = {'x': (L, 0.0, 0.0), 'y': (0.0, L, 0.0), 'z': (0.0, 0.0, L)}[direccion]
    # En la barra vertical se empuja en X; en las horizontales, hacia abajo.
    carga = {'x': (0.0, 0.0, -P), 'y': (0.0, 0.0, -P), 'z': (P, 0.0, 0.0)}[direccion]
    # vecxz con la misma regla del servidor: vertical -> (1,0,0).
    vecxz = (1.0, 0.0, 0.0) if direccion == 'z' else (0.0, 0.0, 1.0)
    ops.wipe()
    ops.model('basic', '-ndm', 3, '-ndf', 6)
    ops.node(1, 0.0, 0.0, 0.0)
    ops.node(2, *punta)
    ops.fix(1, 1, 1, 1, 1, 1, 1)
    ops.geomTransf('Linear', 1, *vecxz)
    ops.element('elasticBeamColumn', 1, 1, 2, A, E, G, J, Iy, Iz, 1)
    ops.timeSeries('Linear', 1)
    ops.pattern('Plain', 1, 1)
    ops.load(2, carga[0], carga[1], carga[2], 0.0, 0.0, 0.0)
    ops.system('BandGeneral')
    ops.numberer('RCM')
    ops.constraints('Transformation')
    ops.integrator('LoadControl', 1.0)
    ops.algorithm('Linear')
    ops.analysis('Static')
    ops.analyze(1)
    ui = [ops.nodeDisp(1, i) for i in range(1, 7)]
    uj = [ops.nodeDisp(2, i) for i in range(1, 7)]
    ops.wipe()
    # Los ejes locales salen de la misma funcion con que se sellan en el
    # modelo, con el mismo vecxz que se le dio a geomTransf.
    base, _ = _ed.ejes_locales((0.0, 0.0, 0.0), punta, list(vecxz))
    # La carga va SIEMPRE a lo largo del local z: la resiste Iy (My). Con
    # vecxz = (0,0,1) el local z queda vertical y la gravedad flecta en My.
    return L, E * Iy, ui, uj, base, P


def curva_formula(inf):
    titulo('curva [1] La interpolacion = la elastica exacta del voladizo')
    for direccion in ('x', 'y', 'z'):
        L, EI, ui, uj, base, P = voladizo(direccion)
        peor, donde = 0.0, 0.0
        for k in range(11):
            x = L * k / 10.0
            # v(x) = P x^2 (3L - x) / (6 EI)
            exacta = P * x * x * (3 * L - x) / (6.0 * EI)
            d = elastica.desplazamiento_en(base, L, None, ui, uj, x)
            calc = -d[2] if direccion != 'z' else d[0]
            peor = max(peor, abs(calc - exacta))
            if abs(calc - exacta) >= peor:
                donde = x
        punta = P * L ** 3 / (3.0 * EI)
        inf.check(peor < 1e-9, 'barra en %s: 11 estaciones calzan con P x^2 (3L-x) / 6EI' % direccion,
                  'peor %.3e m en x = %.2f m; flecha de punta %.4f mm' % (peor, donde, punta * 1000))


def _cuerpo_de_curvade(src):
    """El texto del metodo CurvaDe() de VisorEstructura.cs."""
    i = src.find('Vector3[] CurvaDe(')
    if i < 0:
        return ''
    j = src.find('\n    static Vector3 EjeLocal', i)
    return src[i:j if j > 0 else len(src)]


def _expresion(cuerpo, patron, con_tipo=True):
    """La expresion C# que se le asigna a 'patron', traducida a Python: sin
    el tipo, sin los sufijos f y con Vector3.Dot(a, b) -> dot(a, b)."""
    m = re.search((r'float\s+' if con_tipo else '') + patron + r'\s*=\s*(.*?);', cuerpo, re.S)
    if not m:
        return None
    e = ' '.join(m.group(1).split())
    e = e.replace('Vector3.Dot', 'dot').replace('(float)', '')
    return re.sub(r'(\d)f\b', r'\1', e)


def _base_al_azar(rnd):
    """Tres versores ortonormales, como los localX/localY/localZ."""
    def norm(v):
        m = sum(c * c for c in v) ** 0.5
        return tuple(c / m for c in v)

    def cruz(a, b):
        return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])

    ex = norm([rnd.uniform(-1, 1) for _ in range(3)])
    t = norm([rnd.uniform(-1, 1) for _ in range(3)])
    while abs(sum(ex[c] * t[c] for c in range(3))) > 0.9:
        t = norm([rnd.uniform(-1, 1) for _ in range(3)])
    ez = norm(cruz(ex, t))
    ey = cruz(ez, ex)
    return ex, ey, ez


def curva_copia_cs(inf):
    titulo('curva [2] La formula del C# (VisorEstructura.CurvaDe) es la de elastica.py')
    _, src = fuente_cs('VisorEstructura.cs', inf)
    cuerpo = _cuerpo_de_curvade(src)
    if not inf.check(bool(cuerpo), 'VisorEstructura.cs tiene el metodo CurvaDe()'):
        return

    def dot(v, w):
        return sum(v[c] * w[c] for c in range(3))

    rnd = random.Random(SEMILLA_CURVA)
    peor, faltan, peor_tor = 0.0, [], 0.0
    for _ in range(200):
        # Una base ortonormal cualquiera y GDL cualesquiera: si un signo
        # estuviera cambiado, no se salva por casualidad.
        L = rnd.uniform(1.0, 12.0)
        ex, ey, ez = _base_al_azar(rnd)
        ti = [rnd.uniform(-0.05, 0.05) for _ in range(3)]
        tj = [rnd.uniform(-0.05, 0.05) for _ in range(3)]
        ri = [rnd.uniform(-0.01, 0.01) for _ in range(3)]
        rj = [rnd.uniform(-0.01, 0.01) for _ in range(3)]
        xi = rnd.random()
        entorno = {'dot': dot, 'ex': ex, 'ey': ey, 'ez': ez, 'L': L, 'xi': xi,
                   'ti': ti, 'tj': tj, 'ri': ri, 'rj': rj}
        for nombre in ('N1', 'N2', 'N3', 'N4', 'u', 'v', 'w'):
            e = _expresion(cuerpo, nombre)
            if e is None:
                if nombre not in faltan:
                    faltan.append(nombre)
                continue
            entorno[nombre] = eval(e, {'__builtins__': {}}, entorno)   # noqa: S307
        if faltan:
            break
        # Lo mismo con la funcion de Python: su resultado es global, asi
        # que se proyecta de vuelta sobre los ejes locales.
        g = elastica.desplazamiento_en(_base_de(ex, ey, ez), L, None,
                                       list(ti) + list(ri), list(tj) + list(rj), xi * L)
        for nombre, eje in (('u', ex), ('v', ey), ('w', ez)):
            peor = max(peor, abs(entorno[nombre] - dot(eje, g)))
        # LA TORSION: el giro sobre el propio eje, que en una barra
        # prismatica sin torque repartido va LINEAL entre sus dos nudos.
        # Lleva el factorEscala (un campo en el C#): se evalua con 1.0.
        e_tor = _expresion(cuerpo, r'torsion\[k\]', con_tipo=False)
        if e_tor is None:
            if 'torsion' not in faltan:
                faltan.append('torsion')
        else:
            entorno['factorEscala'] = 1.0
            calc = eval(e_tor, {'__builtins__': {}}, entorno)      # noqa: S307
            recta = (1 - xi) * dot(ex, ri) + xi * dot(ex, rj)
            peor_tor = max(peor_tor, abs(calc - recta))
    inf.check(not faltan, 'el C# define N1..N4, u, v y w', 'no encontre: %s' % faltan if faltan else '')
    if not faltan:
        inf.check(peor < 1e-12, '200 tiros al azar: el C# da lo mismo que elastica.desplazamiento_en',
                  'peor diferencia %.3e m' % peor)
        inf.check(peor_tor < 1e-12, 'y su torsion es la recta entre los giros axiales de los dos nudos',
                  'peor diferencia %.3e rad' % peor_tor)

    # El nombre del objeto de cada barra: resultados.json lo lleva en
    # objeto_unity y el visor lo arma con este literal. Si divergen, el
    # panel no encuentra la barra que se toco.
    literal = '"Elem_" + e.id + "_" + e.tipo'
    inf.check(literal in src, 'VisorEstructura.cs nombra cada barra %s' % literal)


def curva_datos(inf, m):
    titulo('curva [3] modelo.json trae giros y ejes locales')
    sin_giro = [n['id'] for n in m['nodos'] if 'rx' not in n or 'ry' not in n or 'rz' not in n]
    inf.check(not sin_giro, 'los %d nodos traen rx, ry, rz (la deformada precalculada de G)' % len(m['nodos']),
              'sin giros: %s' % sin_giro[:8] if sin_giro else '')
    malos, no_ortos = [], []
    for e in m['elementos']:
        ejes = [e.get('localX'), e.get('localY'), e.get('localZ')]
        if any(v is None or len(v) < 3 for v in ejes):
            malos.append(e['id'])
            continue
        for v in ejes:
            if abs(sum(c * c for c in v) ** 0.5 - 1.0) > 1e-4:
                malos.append(e['id'])
                break
        else:
            x, y, z = ejes
            if (abs(sum(x[c] * y[c] for c in range(3))) > 1e-4
                    or abs(sum(x[c] * z[c] for c in range(3))) > 1e-4
                    or abs(sum(y[c] * z[c] for c in range(3))) > 1e-4):
                no_ortos.append(e['id'])
    inf.check(not malos, 'los %d elementos traen sus 3 ejes locales unitarios' % len(m['elementos']),
              'sin ejes o no unitarios: %s' % malos[:8] if malos else '')
    inf.check(not no_ortos, 'y los tres son perpendiculares entre si',
              'no ortogonales: %s' % no_ortos[:8] if no_ortos else '')
    # Un giro cero en TODOS los nodos seria un exportador que escribe el
    # campo pero no el dato: la curva volveria a ser recta.
    giro = max((max(abs(n.get('rx', 0.0)), abs(n.get('ry', 0.0)), abs(n.get('rz', 0.0)))
                for n in m['nodos']), default=0.0)
    inf.check(giro > 1e-9, 'y algun nodo gira de verdad en G', 'mayor giro %.3e rad' % giro)


def curva_modelo(inf, m):
    titulo('curva [4] %s: la curva pasa por los nodos y la viga hace panza abajo' % _ed.NOMBRE)
    nodos = {n['id']: n for n in m['nodos']}

    def gdl(n):
        return [n.get(k, 0.0) for k in ('ux', 'uy', 'uz', 'rx', 'ry', 'rz')]

    # Si en xi = 0 y xi = 1 la interpolacion no diera EXACTAMENTE el
    # desplazamiento del nodo, dos barras seguidas se separarian en el nudo.
    peor_extremo, abajo, arriba, mayor = 0.0, 0, 0, (0.0, None)
    for e in m['elementos']:
        a, b = nodos.get(e['n1']), nodos.get(e['n2'])
        if a is None or b is None or not e.get('localX'):
            continue
        L = sum((b[c] - a[c]) ** 2 for c in 'xyz') ** 0.5
        if L < 1e-6:
            continue
        base = _base_de(tuple(e['localX']), tuple(e['localY']), tuple(e['localZ']))
        ui, uj = gdl(a), gdl(b)
        for x, esperado in ((0.0, ui), (L, uj)):
            d = elastica.desplazamiento_en(base, L, None, ui, uj, x)
            for c in range(3):
                peor_extremo = max(peor_extremo, abs(d[c] - esperado[c]))
        if not e['tipo'].startswith('viga'):
            continue
        panza = elastica.desplazamiento_en(base, L, None, ui, uj, L / 2.0)[2] - (ui[2] + uj[2]) / 2.0
        if panza < 0:
            abajo += 1
        elif panza > 0:
            arriba += 1
        if abs(panza) > abs(mayor[0]):
            mayor = (panza, e['id'])
    # La base viene REDONDEADA a 6 decimales (edificio.sellar_ejes_locales)
    # y ese redondeo es toda la diferencia: 6 * 5e-7 * |u| por componente.
    cota = 6 * 0.5e-6 * max((sum(n.get(k, 0.0) ** 2 for k in ('ux', 'uy', 'uz')) ** 0.5
                             for n in m['nodos']), default=0.0)
    inf.check(peor_extremo <= cota,
              'la curva arranca y termina en sus dos nodos, dentro del redondeo de los ejes',
              'peor diferencia %.3e m, cota por redondeo %.3e m' % (peor_extremo, cota))
    inf.check(abajo + arriba > 0, 'hay vigas con panza que medir (%d)' % (abajo + arriba))
    # La viga que mas se aparta de la recta de sus nodos tiene que colgar
    # HACIA ABAJO bajo gravedad: con el termino del giro al reves, sube.
    inf.check(mayor[0] < 0, 'la viga que mas se aparta (%s) cuelga hacia abajo bajo G' % mayor[1],
              '%.3f mm bajo la recta de sus nodos; %d vigas abajo, %d arriba'
              % (mayor[0] * 1000, abajo, arriba))


def nombres_de_objeto(inf, m):
    """objeto_unity de cada barra de resultados.json = el nombre con que
    el visor la crea ('Elem_' + id + '_' + tipo del modelo)."""
    anexo, _ = leer_json('resultados', inf)
    if anexo is None:
        return
    tipo = {e['id']: e['tipo'] for e in m['elementos']}
    malos = [e['id'] for e in anexo['elementos']
             if e.get('objeto_unity') != 'Elem_%s_%s' % (e['id'], tipo.get(e['id']))]
    inf.check(not malos, 'objeto_unity de las %d barras de resultados.json = "Elem_<id>_<tipo>" del modelo'
              % len(anexo['elementos']), 'distintos: %s' % malos[:8] if malos else '')


# ============================================================
# TRANSCRIPCIONES: LA PERSONA
# ============================================================
def _a_python(expr):
    e = ' '.join(expr.split())
    return re.sub(r'(\d)f\b', r'\1', e)


def persona_copia_cs(inf):
    titulo('persona [3] y [9] las formulas del C# (VisorPersona.Deformada.cs) = elastica.py')
    _, src = fuente_cs('VisorPersona.Deformada.cs', inf)
    if not src:
        return
    fun = {}
    for nombre in ('N1', 'N2', 'N3', 'N4'):
        m = re.search(r'static float %s\(float a\)\s*\{\s*return (.*?);\s*\}' % nombre, src, re.S)
        fun[nombre] = _a_python(m.group(1)) if m else None
    m = re.search(r'static float FormaLocal\(float xi, float alfa\)\s*\{(.*?)\n    \}', src, re.S)
    cuerpo_phi = m.group(1) if m else ''
    m_swap = re.search(r'if \(xi > alfa\) \{ xi = 1f - xi; alfa = 1f - alfa; \}', cuerpo_phi)
    m_ret = re.search(r'return (.*?);', cuerpo_phi, re.S)
    sumas = re.findall(r'Sumar\(r\.(n1|n2), GDL_(FZ|MX|MY), (.*?)\);', src)
    m_fl = re.search(r'static float UzEn\(ReceptorPersona r, DespNodo di, DespNodo dj, float xi, '
                     r'float a, float P\)\s*\{\s*return (.*?);\s*\}', src, re.S)
    ok = all(fun.values()) and m_swap and m_ret and len(sumas) == 6 and m_fl
    if not inf.check(bool(ok), '[3] el C# tiene N1..N4, FormaLocal, los seis Sumar() y UzEn',
                     'N: %s, swap %s, return %s, Sumar %d, UzEn %s'
                     % ({k: bool(v) for k, v in fun.items()}, bool(m_swap), bool(m_ret),
                        len(sumas), bool(m_fl))):
        return
    entorno = {}
    for nombre, cuerpo in fun.items():
        exec('def %s(a):\n    return %s\n' % (nombre, cuerpo), entorno)          # noqa: S102
    exec('def FormaLocal(xi, alfa):\n    if xi > alfa:\n        xi, alfa = 1 - xi, 1 - alfa\n'   # noqa: S102
         '    return %s\n' % _a_python(m_ret.group(1)), entorno)
    rnd = random.Random(SEMILLA_PERSONA)
    peor_n, peor_phi, peor_w, peor_fl = 0.0, 0.0, 0.0, 0.0
    for _ in range(300):
        a, xi = rnd.random(), rnd.random()
        ref = elastica.hermite(a)
        for i, nombre in enumerate(('N1', 'N2', 'N3', 'N4')):
            peor_n = max(peor_n, abs(entorno[nombre](a) - ref[i]))
        peor_phi = max(peor_phi, abs(entorno['FormaLocal'](xi, a) - elastica.forma_local(xi, a)))
        # forma_local es flecha_biempotrada sin unidades
        L, EI, P = 2 + 8 * rnd.random(), 1e5 * (1 + rnd.random()), 1 + 99 * rnd.random()
        fb = elastica.flecha_biempotrada(P, a * L, L, xi * L, EI)
        peor_phi = max(peor_phi, abs(fb - P * L ** 3 / EI * elastica.forma_local(xi, a)) / (P * L ** 3 / EI))
        # los seis pesos
        ang = 2 * math.pi * rnd.random()
        r = {'tipo': 'viga', 'n1': 1, 'n2': 2, 'L': L, 'dx': math.cos(ang), 'dy': math.sin(ang),
             'flex': L ** 3 / EI}
        ref_w = {(n, g): w for n, g, w in elastica.pesos(r, a, P)}
        loc = dict(entorno, a=a, P=P, r=type('R', (), {'L': L, 'dx': r['dx'], 'dy': r['dy'],
                                                       'flex': r['flex']}))
        for nodo, g, expr in sumas:
            got = eval(_a_python(expr), loc)                                        # noqa: S307
            want = ref_w[(1 if nodo == 'n1' else 2, {'FZ': 'Fz', 'MX': 'Mx', 'MY': 'My'}[g])]
            peor_w = max(peor_w, abs(got - want) / max(1.0, abs(want)))
        # la elastica que se dibuja y la flecha del panel
        ui = [rnd.uniform(-1e-3, 1e-3) for _ in range(6)]
        uj = [rnd.uniform(-1e-3, 1e-3) for _ in range(6)]
        D = type('D', (), {})
        di, dj = D(), D()
        for o, u in ((di, ui), (dj, uj)):
            o.ux, o.uy, o.uz, o.rx, o.ry, o.rz = u
        loc.update(di=di, dj=dj, xi=xi)
        got = eval(_a_python(m_fl.group(1)), loc)                                   # noqa: S307
        want = elastica.uz_en(r, ui, uj, xi, a, P)
        peor_fl = max(peor_fl, abs(got - want) / max(1e-3, abs(want)))
    # [9] el empotramiento y M(x)
    emp = re.findall(r'f\[(2|4|8|10)\] \+= (.*?);', src)
    m_my = re.search(r'static float MyEn\(float\[\] f, float x, float a, float P\)\s*\{\s*return (.*?);\s*\}',
                     src, re.S)
    m_mz = re.search(r'static float MzEn\(float\[\] f, float x\)\s*\{\s*return (.*?);\s*\}', src, re.S)
    if inf.check(len(emp) == 4 and m_my and m_mz,
                 '[9] el C# tiene las cuatro lineas del empotramiento, MyEn y MzEn',
                 'empotramiento %d lineas, MyEn %s, MzEn %s' % (len(emp), bool(m_my), bool(m_mz))):
        peor_e, peor_m = 0.0, 0.0
        for _ in range(300):
            a, P = rnd.random(), 1 + 99 * rnd.random()
            L = 2 + 8 * rnd.random()
            r = {'tipo': 'viga', 'L': L}
            loc = dict(entorno, a=a, P=P, r=type('R', (), {'L': L}))
            ref = elastica.empotramiento_local(r, a, P)
            cm = elastica.empotramiento(-P, a * L, L)
            ref_cm = {2: cm['V_i'], 4: cm['My_i'], 8: cm['V_j'], 10: cm['My_j']}
            for idx, expr in emp:
                got = eval(_a_python(expr), loc)                                    # noqa: S307
                peor_e = max(peor_e, abs(got - ref[int(idx)]) / max(1.0, abs(ref[int(idx)])),
                             abs(ref[int(idx)] - ref_cm[int(idx)]) / max(1.0, abs(ref_cm[int(idx)])))
            f = [rnd.uniform(-100, 100) for _ in range(12)]
            x = L * rnd.random()
            aa = L * a
            loc.update(f=f, x=x, a=aa)
            ex_my = _a_python(m_my.group(1)).replace('Mathf.Max', 'max')
            ex_mz = _a_python(m_mz.group(1))
            ref_s = elastica.esfuerzos_con_puntual(f, 0.0, 0.0, -P, aa, [x])
            peor_m = max(peor_m,
                         abs(eval(ex_my, loc) - ref_s['My'][0]) / max(1.0, abs(ref_s['My'][0])),  # noqa: S307
                         abs(eval(ex_mz, loc) - ref_s['Mz'][0]) / max(1.0, abs(ref_s['Mz'][0])),  # noqa: S307
                         abs(elastica.my_en(f, x, aa, P) - ref_s['My'][0]) / max(1.0, abs(ref_s['My'][0])))
        inf.check(peor_e < 1e-12 and peor_m < 1e-12,
                  '[9] el empotramiento y M(x) del C# = elastica.empotramiento y '
                  'esfuerzos_con_puntual, 300 tiros', 'peor: empotramiento %.1e, M(x) %.1e' % (peor_e, peor_m))
    inf.check(peor_n < 1e-12 and peor_phi < 1e-12 and peor_w < 1e-12 and peor_fl < 1e-12,
              '[3] la copia en C# (VisorPersona.Deformada.cs) = estas formulas, 300 tiros al azar',
              'peor: N %.1e, phi %.1e (y phi = flecha_biempotrada / (P L^3/EI)), pesos %.1e, '
              'UzEn %.1e' % (peor_n, peor_phi, peor_w, peor_fl))


def transcripciones(inf):
    curva_formula(inf)
    curva_copia_cs(inf)
    m, _ = leer_json('modelo', inf)
    if m is not None:
        curva_datos(inf, m)
        curva_modelo(inf, m)
        nombres_de_objeto(inf, m)
    persona_copia_cs(inf)


# ============================================================
# NOMBRES Y COPIAS
# ============================================================
def md5(ruta):
    h = hashlib.md5()
    with open(ruta, 'rb') as f:
        for trozo in iter(lambda: f.read(1 << 20), b''):
            h.update(trozo)
    return h.hexdigest()


def carpetas_streaming():
    """La StreamingAssets del proyecto y la de cada build que exista."""
    salida = [rutas.STREAMING]
    if os.path.isdir(rutas.BUILD):
        for d, subdirs, _ in os.walk(rutas.BUILD):
            if os.path.basename(d) == 'StreamingAssets':
                salida.append(d)
                subdirs[:] = []
    return salida


def nombres_y_copias(inf):
    titulo('nombres: las constantes del C# = calculo.rutas.NOMBRES_EN_UNITY')
    inf.check(set(ARCHIVOS_CS) == set(rutas.NOMBRES_EN_UNITY),
              'cada archivo de NOMBRES_EN_UNITY tiene su constante en el C# (%s)'
              % ', '.join(sorted(rutas.NOMBRES_EN_UNITY)),
              'sin constante: %s; constante sin nombre: %s'
              % (sorted(set(rutas.NOMBRES_EN_UNITY) - set(ARCHIVOS_CS)) or '-',
                 sorted(set(ARCHIVOS_CS) - set(rutas.NOMBRES_EN_UNITY)) or '-')
              if set(ARCHIVOS_CS) != set(rutas.NOMBRES_EN_UNITY) else '')
    for clave, (cs, constante) in sorted(ARCHIVOS_CS.items()):
        _, src = fuente_cs(cs, inf)
        m = re.search(r'const\s+string\s+%s\s*=\s*"([^"]*)"\s*;' % constante, sin_comentarios(src))
        esperado = rutas.NOMBRES_EN_UNITY.get(clave)
        inf.check(m is not None and m.group(1) == esperado,
                  '%s.%s = "%s" (rutas.NOMBRES_EN_UNITY[%r])' % (cs[:-3], constante, esperado, clave),
                  'el C# dice %r' % (m.group(1) if m else None) if not (m and m.group(1) == esperado) else '')
    # Ningun campo serializado guarda el nombre de un archivo: la escena lo
    # pisaria (la trampa del nombreArchivo que mandaba la escena).
    serializados = []
    for base in (rutas.SCRIPTS_CS,):
        for d, _, archivos in os.walk(base):
            for a in archivos:
                if a.endswith('.cs'):
                    with io.open(os.path.join(d, a), encoding='utf-8') as f:
                        src = sin_comentarios(f.read())
                    for m in re.finditer(r'public\s+string\s+(\w+)\s*=\s*"[^"]*\.(?:json|xlsx)"\s*;', src):
                        serializados.append('%s.%s' % (a[:-3], m.group(1)))
    inf.check(not serializados, 'ningun campo publico (que la escena pisaria) guarda el nombre de un archivo',
              'campos: %s' % serializados if serializados else '')

    titulo('copias: lo que lee cada Unity y la app AR es byte a byte lo de salidas/')
    ref = {}
    for clave, nombre in sorted(rutas.NOMBRES_EN_UNITY.items()):
        ruta = rutas.salida(clave)
        if inf.check(os.path.isfile(ruta), 'existe %s' % rutas.relativa(ruta),
                     '' if os.path.isfile(ruta) else 'se genera con  python sap.py preparar'):
            ref[nombre] = md5(ruta)
    for carpeta in carpetas_streaming():
        if not os.path.isdir(carpeta):
            inf.check(False, 'existe %s' % rutas.relativa(carpeta))
            continue
        distintos, faltan = [], []
        for nombre, h in sorted(ref.items()):
            ruta = os.path.join(carpeta, nombre)
            if not os.path.isfile(ruta):
                faltan.append(nombre)
            elif md5(ruta) != h:
                distintos.append(nombre)
        sobran = sorted(a for a in os.listdir(carpeta)
                        if not a.endswith('.meta') and a not in rutas.NOMBRES_EN_UNITY.values())
        inf.check(not distintos and not faltan,
                  '%s: los %d archivos = salidas/ (md5)' % (rutas.relativa(carpeta), len(ref)),
                  'distintos: %s; faltan: %s (python sap.py sincronizar)' % (distintos or '-', faltan or '-')
                  if distintos or faltan else '')
        inf.check(not sobran, '%s: no trae archivos que nadie lee' % rutas.relativa(carpeta),
                  'sobran: %s' % sobran if sobran else '')
    ar_salida = rutas.salida('ar')
    ar_web = os.path.join(rutas.AR_WEB, 'datos', 'ar.json')
    if inf.check(os.path.isfile(ar_salida) and os.path.isfile(ar_web),
                 'existen %s y %s' % (rutas.relativa(ar_salida), rutas.relativa(ar_web))):
        inf.check(md5(ar_salida) == md5(ar_web), '%s = %s (md5)'
                  % (rutas.relativa(ar_web), rutas.relativa(ar_salida)))


# ============================================================
# JSONUTILITY: LO QUE UNITY LEYO DE VERDAD
# ============================================================
REPORTE_JSONUTILITY = 'verificacion_jsonutility.json'
METODO_JSONUTILITY = 'VerificarLecturaJson.Verificar'


class Cuenta(object):
    def __init__(self):
        self.valores = 0
        self.difs = []
        self.campos_sin_clave = 0
        self.claves_sin_campo = 0


def comparar_leido(a, b, cuenta, ruta='$'):
    r"""
    a = el JSON de Python, b = lo que Unity leyo y volvio a escribir. Un
    numero calza si es el mismo o si su float32 es el mismo (JsonUtility
    guarda float de 32 bits y ToJson escribe uno de ida y vuelta); un
    entero, un texto o un bool, si es igual. Un campo C# sin clave (b sin
    a) y una clave sin campo (a sin b) se CUENTAN: el contrato los revisa.
    """
    if isinstance(b, dict):
        if not isinstance(a, dict):
            if len(cuenta.difs) < 20:
                cuenta.difs.append('%s: Unity leyo un objeto, Python escribio %s' % (ruta, type(a).__name__))
            return
        for k, v in b.items():
            if k in a:
                comparar_leido(a[k], v, cuenta, '%s.%s' % (ruta, k))
            else:
                cuenta.campos_sin_clave += 1
        cuenta.claves_sin_campo += sum(1 for k in a if k not in b)
    elif isinstance(b, list):
        if not isinstance(a, list) or len(a) != len(b):
            if len(cuenta.difs) < 20:
                cuenta.difs.append('%s: largo %s en Python, %d en Unity'
                                   % (ruta, len(a) if isinstance(a, list) else type(a).__name__, len(b)))
            return
        for i, (x, y) in enumerate(zip(a, b)):
            comparar_leido(x, y, cuenta, '%s[%d]' % (ruta, i))
    elif a is None:
        return                       # null: lo cuenta el contrato (queda en su defecto)
    elif isinstance(b, bool) or isinstance(a, bool):
        cuenta.valores += 1
        if a != b and len(cuenta.difs) < 20:
            cuenta.difs.append('%s: %r contra %r' % (ruta, a, b))
    elif isinstance(b, (int, float)) and isinstance(a, (int, float)):
        cuenta.valores += 1
        if not (a == b or f32(a) == f32(b)) and len(cuenta.difs) < 20:
            cuenta.difs.append('%s: Python %r, Unity %r' % (ruta, a, b))
    else:
        cuenta.valores += 1
        if a != b and len(cuenta.difs) < 20:
            cuenta.difs.append('%s: Python %r, Unity %r' % (ruta, str(a)[:60], str(b)[:60]))


def jsonutility(inf, reporte=None):
    titulo('jsonutility: Unity lee los cinco JSON con sus clases (VerificarLecturaJson.cs)')
    from herramientas import lanzador
    if reporte is None:
        if lanzador.unity_abierto():
            print('  Unity tiene el proyecto abierto: el batch no puede abrirlo dos veces.')
            print('  Cierralo, o corre  Laboratorio / Verificar lectura de los JSON  desde el menu')
            print('  y despues  python -m verificacion.unity jsonutility --reporte build/%s'
                  % REPORTE_JSONUTILITY)
            return 2
        fuente_cs('VerificarLecturaJson.cs', inf)
        reporte = os.path.join(rutas.BUILD, REPORTE_JSONUTILITY)
        log = os.path.join(rutas.BUILD, 'verificar_lectura_json.log')
        if os.path.exists(reporte):
            os.remove(reporte)
        codigo, _ = lanzador.correr_batch(METODO_JSONUTILITY, log, timeout=1800)
        if not inf.check(codigo == 0 and os.path.isfile(reporte),
                         'Unity corrio %s y dejo %s' % (METODO_JSONUTILITY, rutas.relativa(reporte)),
                         ['codigo %s; log %s' % (codigo, rutas.relativa(log))]
                         + lanzador.errores_del_log(log) if codigo != 0 or not os.path.isfile(reporte) else ''):
            return 1
    with io.open(reporte, encoding='utf-8') as f:
        rep = json.load(f)
    print('  reporte %s (Unity %s)' % (rutas.relativa(reporte), rep.get('unity')))
    inf.check(not rep.get('errores'), 'Unity leyo los cinco sin errores', rep.get('errores') or '')
    archivos = rep.get('archivos') or {}
    for clave in ('modelo', 'resultados', 'carga_movil', 'persona', 'relieve'):
        nombre = rutas.NOMBRES_EN_UNITY[clave]
        r = archivos.get(clave)
        if not inf.check(r is not None and r.get('leido') is not None,
                         '%s: Unity lo leyo como %s' % (nombre, (r or {}).get('clase'))):
            continue
        ruta = rutas.salida(clave)
        inf.check(r.get('md5') == md5(ruta), '%s: lo que leyo Unity es salidas/%s (md5 %s)'
                  % (nombre, nombre, (r.get('md5') or '')[:10]))
        with io.open(ruta, encoding='utf-8') as f:
            python = json.load(f)
        c = Cuenta()
        comparar_leido(python, r['leido'], c)
        inf.check(not c.difs and c.valores > 0,
                  '%s: %d valores, cada uno igual en float32 a lo que escribio Python'
                  % (nombre, c.valores), c.difs[:8])
        print('         (%d campos C# sin clave en el JSON quedaron en su defecto; %d claves sin campo; '
              'los dos los revisa contratos)' % (c.campos_sin_clave, c.claves_sin_campo))
    return None


# ============================================================
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog='python -m verificacion.unity',
                                 description='Lo que lee Unity contra lo que escribe Python.')
    ap.add_argument('bloques', nargs='*', metavar='bloque',
                    help='%s (sin nada: los cuatro)' % ', '.join(BLOQUES))
    ap.add_argument('--reporte', metavar='JSON',
                    help='jsonutility: comparar un reporte ya hecho (sin abrir Unity)')
    args = ap.parse_args(argv)
    desconocidos = [b for b in args.bloques if b not in BLOQUES]
    if desconocidos:
        ap.error('bloque desconocido %s (son: %s)' % (', '.join(desconocidos), ', '.join(BLOQUES)))
    bloques = args.bloques or list(BLOQUES)

    t0 = time.time()
    print('=' * 76)
    print('  UNITY CONTRA PYTHON   %s   (%s)' % (_ed.NOMBRE.upper(), ', '.join(bloques)))
    print('=' * 76)
    inf = Informe()
    salida = None
    for b in bloques:
        print()
        print('#' * 76)
        print('#  %s' % b.upper())
        print('#' * 76)
        if b == 'contratos':
            contratos(inf)
        elif b == 'transcripciones':
            transcripciones(inf)
        elif b == 'nombres_y_copias':
            nombres_y_copias(inf)
        elif b == 'jsonutility':
            r = jsonutility(inf, os.path.abspath(args.reporte) if args.reporte else None)
            if r == 2:
                salida = 2
    print('  (%.0f s)' % (time.time() - t0))
    codigo = inf.cerrar()
    return salida if salida is not None and codigo == 0 else codigo


if __name__ == '__main__':
    sys.exit(main())
