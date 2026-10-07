# -*- coding: utf-8 -*-
r"""
================================================================
 verificacion/capturas.py  -  LO QUE LA APP REGISTRO, CONTRA PYTHON
================================================================
 La app compilada, abierta con  -capturar <modo> <carpeta>  (o con
 python sap.py capturar <modo>), saca sus fotos y deja un registro.txt
 con lineas "DATO clave = valor": los numeros que Unity CARGO, CALCULO
 y MUESTRA, escritos con G9 (el float de 32 bits exacto que tenia en
 memoria). Aca se cruzan con lo que calcula Python, en memoria (sin
 subprocesos ni archivos de evidencia):

   python -m verificacion.capturas visor      (K1)
   python -m verificacion.capturas persona    (K2)
   python -m verificacion.capturas relieve    (K3)
   python -m verificacion.capturas diagramas  (sin entrada en la suite)
   ... [--registro RUTA] [--sin-servidor]

 Los registros viven en verificacion/registros/capturas/<modo>/ (las
 fotos quedan al lado y git las ignora). Cada registro trae el md5 de
 los archivos que la app leyo: si no son los de salidas/, el registro es
 de otros datos y se dice "registro vencido: recapturar".

 visor
   [1] superposicion  E1..E3 precalculados y E3 pedido a POST /combinar
                      contra el bloque 'superposicion' de resultados.json
   [2] M1             borrar la columna de la M1 (entrada/laboratorio.json,
                      modificaciones): el modelo como lo manda Unity,
                      resuelto aca con la misma funcion que /analizar
   [3] carga movil    las posiciones registradas contra carga_movil.json
   [4] preguntas      lo que contesta el panel (donde esta, como esta
                      apoyado, que lo carga, como se deforma, que fuerzas,
                      cuanta capacidad) contra modelo.json y resultados.json
   [5] registro       fotos y su pestana, errores del log, edificio, ids de
                      control (laboratorio.json, y la regla que los elige),
                      Excel, archivos al dia
   [6] INSTANT        los sliders: lo que la app combino al moverlos contra
                      Python (superposicion.caso_combinado) y contra la
                      replica de su algoritmo en 32 bits; la version sube
                      en cada movimiento, el tipo es 'superposicion' y cada
                      combinacion cabe en un cuadro a 60 Hz (16.7 ms)
 persona
   [7] de verificacion.persona: lo que la app sumo = OpenSees directo
 relieve
   relieveEstado empieza con 'Relieve del sitio', la malla y los huecos
   que dibujo son los de relieve.json, errores del log 0
 diagramas
   los f_i / f_j que imprime el panel = resultados.json (al decimal
   impreso), el modelo calza, errores del log 0

 ----------------------------------------------------------------
 LAS TOLERANCIAS SE MIDEN CONTRA SU CAUSA
 ----------------------------------------------------------------
   f32      la separacion entre floats de 32 bits vecinos en ese valor:
            JsonUtility redondea el decimal del JSON al float mas cercano.
   impr     medio ultimo digito de un numero impreso como texto.
   M1       solo f32: el pedido se emula EXACTO -- JsonUtility.ToJson
            escribe cada float con el valor entero de su float32 (17
            cifras), no el decimal corto -- y el servidor es determinista,
            asi que lo que recibio Unity es lo que se resuelve aca, bit a
            bit. Con el decimal corto quedaba a uno o dos escalones del
            redondeo del servidor (4 decimales en kN). ent32, lo que mueve
            mandar float32 en vez de doble, se mide e informa (hasta 2e-4
            kN m en la M1 del conjunto): la comparacion distingue los dos.
   INSTANT  el redondeo del anexo (medio decimal por termino, escalado por
            su lambda) mas la aritmetica de 32 bits (K_F32 redondeos de
            2^-24 sobre la escala de cada suma); Mn, por la pendiente de
            la curva P-M.
================================================================
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import math
import os
import re
import sys
import time

import numpy as np

from calculo import edificio as _ed
from calculo import laboratorio as lab
from calculo import opensees
from calculo import rutas
from calculo import superposicion as sp
from verificacion.comun import Informe, leer_registro, medio_digito, titulo, ulp32
from verificacion.motor import borrar_elemento, como_jsonutility, esquema_csharp
from verificacion.unity import md5

BLOQUES = ('visor', 'diagramas', 'persona', 'relieve')
CARPETA = os.path.join(rutas.REGISTROS, 'capturas')

CASOS = ('G', 'Q', 'EX', 'EY')
MAGNITUDES = ('N', 'Vy', 'Vz', 'T', 'My', 'Mz')


def registro_de(modo, ruta=None):
    return os.path.abspath(ruta) if ruta else os.path.join(CARPETA, modo, 'registro.txt')


def num(texto):
    return float(texto)


def vector(texto):
    return [float(x) for x in texto.split(',')] if texto else []


# ============================================================
# TABLA
# ============================================================
class Tabla:
    """Una fila por dato: Unity, Python, |dif|, la tolerancia y su causa."""

    def __init__(self, titulo_tabla):
        self.titulo = titulo_tabla
        self.filas = []

    def numero(self, nombre, unity, python, tol, causa):
        """unity y python en las mismas unidades; ok si |dif| <= tol."""
        dif = abs(unity - python)
        ok = dif <= tol
        self.filas.append((nombre, '%.9g' % unity, '%.9g' % python, '%.2e' % dif, '%.2e' % tol, causa, ok))
        return ok

    def texto(self, nombre, unity, python, causa='igual'):
        ok = str(unity) == str(python)
        self.filas.append((nombre, str(unity), str(python), '', '', causa, ok))
        return ok

    def falta(self, nombre, que):
        self.filas.append((nombre, '(falta)', str(que), '', '', 'registro', False))

    def imprimir(self):
        print()
        print('=' * 118)
        print('  ' + self.titulo)
        print('=' * 118)
        if not self.filas:
            print('  (sin filas)')
            return 0
        print('  %-50s %-17s %-17s %-9s %-9s %-10s %s'
              % ('dato', 'Unity', 'Python', '|dif|', 'tol', 'causa', ''))
        malas = 0
        for nombre, u, p, dif, tol, causa, ok in self.filas:
            if not ok:
                malas += 1
            print('  %-50s %-17s %-17s %-9s %-9s %-10s %s'
                  % (nombre[:50], u[:17], p[:17], dif, tol, causa, 'ok' if ok else 'FALLA'))
        print('  -> %d filas, %d FALLA' % (len(self.filas), malas))
        return malas


def comparar(tabla, datos, clave, python, tol_extra=0.0, causa='f32', escala=1.0, nombre=None):
    """Una fila numerica: datos[clave]*escala contra python, tol = ulp32
    del valor de Unity (en la escala) + tol_extra."""
    nombre = nombre or clave
    if clave not in datos or datos[clave] == '':
        tabla.falta(nombre, python)
        return False
    u = num(datos[clave])
    tol = ulp32(u) * abs(escala) + tol_extra
    return tabla.numero(nombre, u * escala, float(python), tol, causa)


def comparar_texto(tabla, datos, clave, python, nombre=None):
    nombre = nombre or clave
    if clave not in datos:
        tabla.falta(nombre, python)
        return False
    return tabla.texto(nombre, datos[clave], python)


def comparar_vector(tabla, datos, clave, python, tol_extra=0.0, causa='f32', ejes=('Fx', 'Fy', 'Fz')):
    if clave not in datos:
        tabla.falta(clave, python)
        return
    u = vector(datos[clave])
    for i, eje in enumerate(ejes):
        tabla.numero('%s[%s]' % (clave, eje), u[i], python[i], ulp32(u[i]) + tol_extra, causa)


# ------------------------------------------------------------
# LA CABECERA DE CADA FOTO: DE DONDE DICE QUE SALE LO QUE SE VE
# ------------------------------------------------------------
# La cabecera del panel nombra la FUENTE de lo que se ve en 3D (anexo,
# reanalisis del servidor, carga movil) con sus numeros, y la captura la
# registra por foto. La foto de la M1 decia "Caso activo LIBRE ... 24.63
# mm" junto a un nodo que bajaba 21.60 mm: estas filas lo impiden. Un
# numero de la cabecera es TEXTO ya redondeado por C#: si el valor de
# Python +- su tolerancia cruza un limite de redondeo, valen los dos
# textos (causa 'fmt').
def textos_redondeados(valor, decimales, tol):
    """Los textos con 'decimales' que puede escribir C# para valor +- tol."""
    fmt = '%%.%df' % decimales
    return sorted({fmt % x for x in (valor - tol, valor, valor + tol)})


def foto_que_contiene(datos, trozo):
    """El nombre de la foto cuyo nombre contiene 'trozo', o None."""
    for k in datos:
        m = re.match(r'foto\.(.+)\.cabecera\.fuente$', k)
        if m and trozo in m.group(1):
            return m.group(1)
    return None


def filas_cabecera(tabla, datos, trozo, fuente, piezas):
    """fuente: texto igual. piezas: [(etiqueta, [textos validos])], cada una
    tiene que estar en el texto de la cabecera (basta uno de sus textos)."""
    foto = foto_que_contiene(datos, trozo)
    if foto is None:
        tabla.falta('cabecera de la foto *%s*' % trozo, fuente)
        return
    n = foto.split('_')[0]
    comparar_texto(tabla, datos, 'foto.%s.cabecera.fuente' % foto, fuente,
                   nombre='cabecera foto %s fuente' % n)
    texto = datos.get('foto.%s.cabecera.texto' % foto, '')
    for etiqueta, validos in piezas:
        hallado = next((v for v in validos if v in texto), None)
        tabla.texto('cabecera foto %s "%s"' % (n, etiqueta), hallado or texto, hallado or validos[0],
                    'fmt' if len(validos) > 1 else 'contiene')


# ------------------------------------------------------------
# EL REGISTRO ES DE ESTOS DATOS
# ------------------------------------------------------------
def archivos_al_dia(tabla, datos):
    """El md5 de cada archivo que la app leyo = el de salidas/. Si no, el
    registro es de otros datos: hay que volver a capturar."""
    for clave, nombre in sorted(rutas.NOMBRES_EN_UNITY.items()):
        k = 'archivos.%s.md5' % clave
        ruta = rutas.salida(clave)
        if k not in datos:
            tabla.falta(k, 'el md5 de salidas/%s' % nombre)
            continue
        h = md5(ruta) if os.path.isfile(ruta) else '(no existe)'
        tabla.texto('%s (%s)' % (k, nombre), datos[k], h,
                    'al dia' if datos[k] == h else 'registro vencido: recapturar')


def leer_salida(clave):
    with io.open(rutas.salida(clave), encoding='utf-8') as f:
        return json.load(f)


# ============================================================
# [1] SUPERPOSICION
# ============================================================
def control_por_regla(anexo):
    r"""
    Los elementos de control con la regla de entrada/laboratorio.json
    (superposicion.control.reglas), rehecha aca: si el edificio cambia y la
    regla da otro id, se dice en vez de comparar contra un elemento que ya
    no es el representativo.
    """
    info = anexo['info']
    e1 = next(e for e in anexo['superposicion']['estados'] if e['nombre'] == 'E1')['caso']
    tipo = {int(e['id']): e.get('tipo', '') for e in anexo['elementos']}
    viga = max((s for s in e1['esfuerzos'] if tipo.get(int(s['id']), '').startswith('viga')),
               key=lambda s: (max(abs(v) for v in s['My']), -int(s['id'])))
    nodo = max(e1['desplazamientos'],
               key=lambda d: (math.sqrt(d['ux'] ** 2 + d['uy'] ** 2 + d['uz'] ** 2), -int(d['id'])))
    return {'columna': int(info['columna_demo']), 'muro': int(info['muro_demo']),
            'viga': int(viga['id']), 'nodo': int(nodo['id'])}


def bloque_superposicion(datos, anexo, control, exigir_libre):
    tabla = Tabla('[1] SUPERPOSICION: Unity contra el bloque superposicion de resultados.json')
    pre = {e['nombre']: e for e in anexo['superposicion']['estados']}
    origenes = [('pre', None)]
    ref_libre = datos.get('sup.libre.estado_de_referencia', 'E3')
    if datos.get('sup.libre.hecho') == 'True':
        origenes.append(('libre', ref_libre))
    elif exigir_libre:
        tabla.falta('sup.libre.hecho', 'True (E3 por POST /combinar)')
    for origen, solo in origenes:
        for estado in sorted(pre):
            if solo and estado != solo:
                continue
            p = 'sup.%s.%s' % (origen, estado)
            caso = pre[estado]['caso']
            v = caso['max_desplazamiento_mm']
            comparar(tabla, datos, p + '.max_desplazamiento_mm', v)
            # La cabecera de su foto sigue diciendo el caso del anexo.
            trozo = '_superposicion_%s_%s' % (estado, 'precalculado' if origen == 'pre' else 'LIBRE')
            filas_cabecera(tabla, datos, trozo, 'anexo',
                           [('Desp. max', ['Desp. max %s mm' % t
                                           for t in textos_redondeados(v, 2, ulp32(v))])])
            dem = {int(d['id']): d for d in caso['demandas']}
            no_pasa = sorted(i for i, d in dem.items() if not d['pasa'])
            comparar_texto(tabla, datos, p + '.no_pasan', str(len(no_pasa)))
            comparar_texto(tabla, datos, p + '.con_fierro', str(len(dem)))
            for k in ('columna', 'muro'):
                eid = control[k]
                d = dem.get(eid)
                if d is None:
                    tabla.falta('%s %s %d' % (p, k, eid), 'una demanda en el JSON')
                    continue
                for mag in ('P', 'M', 'Mn', 'u'):
                    comparar(tabla, datos, '%s.elem.%d.%s' % (p, eid, mag), d[mag])
                comparar_texto(tabla, datos, '%s.elem.%d.extremo' % (p, eid), d['extremo'])
                comparar_texto(tabla, datos, '%s.elem.%d.pasa' % (p, eid), str(d['pasa']))
            s = next(x for x in caso['esfuerzos'] if int(x['id']) == control['viga'])
            k = max(range(len(s['My'])), key=lambda i: (abs(s['My'][i]), -i))
            q = '%s.elem.%d' % (p, control['viga'])
            comparar(tabla, datos, q + '.My_i', s['My'][0])
            comparar(tabla, datos, q + '.My_j', s['My'][-1])
            comparar(tabla, datos, q + '.My_max_abs_valor', s['My'][k])
            comparar(tabla, datos, q + '.My_max_abs_x', s['x'][k])
            d = next(x for x in caso['desplazamientos'] if int(x['id']) == control['nodo'])
            for comp in ('ux', 'uy', 'uz'):
                comparar(tabla, datos, '%s.nodo.%d.%s_m' % (p, control['nodo'], comp), d[comp])
            for eid in no_pasa:
                comparar(tabla, datos, '%s.no_pasa.%d.u' % (p, eid), dem[eid]['u'])
            if p + '.no_pasa.ids' in datos:
                tabla.texto(p + '.no_pasa.ids', datos[p + '.no_pasa.ids'], ','.join(map(str, no_pasa)))
            else:
                tabla.falta(p + '.no_pasa.ids', no_pasa)
            # El equilibrio que el panel muestra, contra el JSON que lo trae.
            eq = pre[estado].get('equilibrio') or {}
            for kk in ('aplicada_kN', 'reaccion_kN', 'error_kN'):
                comparar_vector(tabla, datos, '%s.equilibrio.%s' % (p, kk), eq.get(kk) or [0.0] * 3)
    return tabla.imprimir()


# ============================================================
# [2] M1
# ============================================================
def resolver(modelo):
    """La respuesta de /analizar para este modelo: la misma funcion que
    atiende la ruta (sin el Excel que la ruta escribe en salidas/)."""
    with opensees.LOCK:
        return opensees.construir_y_resolver(copy.deepcopy(modelo))


def float32_exacto(valor):
    r"""
    Cada float del modelo emulado, llevado al valor EXACTO de su float de
    32 bits. JsonUtility.ToJson escribe el float32 entero, con 17 cifras
    (8.02 -> 8.020000457763672: se ve en el reporte de la verificacion
    jsonutility), no el decimal mas corto que vuelve a el. Con el decimal
    corto el servidor resuelve otros numeros: la M1 del conjunto quedaba a
    uno o dos escalones del redondeo del servidor de lo que recibio Unity;
    con el exacto, a cero (medido barra por barra). Los enteros, textos y
    bools no cambian; el modelo no tiene campos double.
    # MOVER A verificacion/motor.py (_float32 de como_jsonutility)
    """
    if isinstance(valor, dict):
        return {k: float32_exacto(v) for k, v in valor.items()}
    if isinstance(valor, list):
        return [float32_exacto(v) for v in valor]
    if isinstance(valor, float):
        return float(np.float32(valor))
    return valor


def como_lo_manda_unity(modelo, esquema):
    """El modelo como lo escribe JsonUtility.ToJson(ModeloEstructural):
    solo los campos del C#, defaults donde no habia clave, float32 exacto."""
    return float32_exacto(como_jsonutility(modelo, 'ModeloEstructural', esquema))


def bloque_m1(datos, modelo, exigir):
    m1 = lab.bloque('modificaciones')['M1']
    col, nodo, barra = int(m1['borrar_elemento']), int(m1['nodo']), int(m1['elemento'])
    tabla = Tabla('[2] M1 (borrar la columna %d): Unity + POST /analizar contra el mismo pedido resuelto aca'
                  % col)
    if datos.get('m1.hecho') != 'True':
        if exigir:
            tabla.falta('m1.hecho', 'True')
            return tabla.imprimir()
        print('\n  [2] M1 no se hizo en la captura (sin servidor): no se compara.')
        return 0
    for clave, valor in (('m1.columna', col), ('m1.nodo', nodo), ('m1.barra_extra', barra)):
        comparar_texto(tabla, datos, clave, str(valor))

    # El pedido es el mismo que mando la app (el modelo como lo escribe
    # JsonUtility, antes y despues de EditorEstructura.BorrarElemento), y la
    # funcion es la de /analizar: el servidor es determinista, asi que la
    # unica causa que queda es f32 (Unity guarda la respuesta en float).
    # ent32 -- lo que mueve mandar float32 en vez de doble -- se mide y se
    # informa: muestra que la comparacion distingue los dos pedidos.
    esquema = esquema_csharp()
    despues = copy.deepcopy(modelo)
    borrar_elemento(despues, col)
    t0 = time.time()
    r = {}
    for fase, m in (('antes', modelo), ('despues', despues)):
        r[fase] = (resolver(como_lo_manda_unity(m, esquema)), resolver(m))
    print()
    print('  referencia: opensees.construir_y_resolver (la funcion de /analizar) sobre el modelo como lo')
    print('  manda JsonUtility (float32 exacto) y, para medir ent32, sobre el mismo en doble: 4 corridas en %.0f s'
          % (time.time() - t0))

    for clave in ('m1.antes.ok', 'm1.despues.ok', 'm1.borrado', 'm1.anexo_desactualizado', 'm1.excel_existe'):
        comparar_texto(tabla, datos, clave, 'True')
    comparar_texto(tabla, datos, 'm1.existe_columna', 'False')
    comparar_texto(tabla, datos, 'm1.motivo', 'borrar elemento %d' % col)
    comparar_texto(tabla, datos, 'm1.elementos_despues', str(len(modelo['elementos']) - 1))

    ent32 = [0.0, '']

    def medir(a32, a64, que):
        if abs(a32 - a64) > ent32[0]:
            ent32[0], ent32[1] = abs(a32 - a64), que

    for fase in ('antes', 'despues'):
        r32, r64 = r[fase]
        barras = sorted({int(e['id']) for e in (modelo if fase == 'antes' else despues)['elementos']
                         if nodo in (int(e['n1']), int(e['n2'])) and int(e['id']) != col} | {barra})
        for c32, c64 in zip(r32['casos'], r64['casos']):
            caso = c32['nombre']
            p = 'm1.%s.%s' % (fase, caso)
            comparar_texto(tabla, datos, p + '.ok', str(bool(c32['ok'])))
            comparar(tabla, datos, p + '.max_desplazamiento_m', c32['max_desplazamiento'])
            d32 = next(x for x in c32['desplazamientos'] if int(x['id']) == nodo)
            d64 = next(x for x in c64['desplazamientos'] if int(x['id']) == nodo)
            for comp in ('ux', 'uy', 'uz'):
                comparar(tabla, datos, '%s.nodo.%d.%s_m' % (p, nodo, comp), d32[comp])
                medir(d32[comp], d64[comp], '%s nodo %d %s (m)' % (p, nodo, comp))
            e32 = c32['equilibrio']
            for k in ('aplicada_kN', 'reaccion_kN', 'error_kN'):
                comparar_vector(tabla, datos, '%s.equilibrio.%s' % (p, k), e32[k])
            comparar_texto(tabla, datos, p + '.equilibrio.confiable', str(bool(e32['confiable'])))
            comparar_texto(tabla, datos, p + '.equilibrio.nodos_en_diafragma', str(e32['nodos_en_diafragma']))
            if caso != 'G':
                continue
            f32_por_id = {int(x['id']): x['f'] for x in c32['fuerzas_elementos']}
            f64_por_id = {int(x['id']): x['f'] for x in c64['fuerzas_elementos']}
            for eid in barras:
                if eid not in f32_por_id:
                    continue
                for nombre, i in (('N_i', 0), ('Vz_i', 2), ('My_i', 4), ('My_j', 10)):
                    comparar(tabla, datos, '%s.elem.%d.%s' % (p, eid, nombre), f32_por_id[eid][i])
                    medir(f32_por_id[eid][i], f64_por_id[eid][i], '%s barra %d %s (kN, kN m)' % (p, eid, nombre))
    print('  ent32: mandar el modelo en float32 en vez de doble mueve hasta %.1e (%s); la tolerancia de'
          % (ent32[0], ent32[1] or '-'))
    print('  cada fila es solo f32: el pedido emulado es el que mando la app')

    # La cabecera de las fotos de la M1 dice que lo que se ve es el
    # reanalisis del servidor en G, con SU maximo (la mayor componente), y
    # que la D/C no se recalculo.
    g32 = next(c for c in r['despues'][0]['casos'] if c['nombre'] == 'G')
    mm = g32['max_desplazamiento'] * 1000.0
    piezas = [('caso', ['(modelo editado) \u00b7 caso G \u00b7']),
              ('Max. componente', ['Max. componente %s mm' % t for t in textos_redondeados(mm, 2, ulp32(mm))]),
              ('D/C', ['D/C: sin recalcular (anexo del modelo original)'])]
    for trozo in ('_M1_sin_columna_', '_M1_nodo_'):
        filas_cabecera(tabla, datos, trozo, 'reanalisis', piezas)
    return tabla.imprimir()


# ============================================================
# [3] CARGA MOVIL
# ============================================================
CAMPOS_POSICION = ('xL', 'a_m', 'L_m', 's_m', 'x', 'y', 'z', 'Pz_local_kN', 'max_desplazamiento_mm',
                   'uz_min_mm', 'uz_bajo_carga_mm', 'M_bajo_carga_kNm')
ENTEROS_POSICION = ('indice', 'elemento', 'nodo_max_desplazamiento', 'nodo_uz_min')
CAMPOS_REPARTO = ('V_i_kN', 'V_j_kN', 'porcentaje_i', 'porcentaje_j', 'palanca_i_kN', 'palanca_j_kN',
                  'My_i_kNm', 'My_j_kNm', 'momentos_sobre_L_kN')
CAMPOS_CONSERVACION = ('P_kN', 'suma_Rz_kN', 'error_kN', 'cota_kN', 'suma_Rx_kN', 'suma_Ry_kN')


def bloque_carga_movil(datos, movil):
    tabla = Tabla('[3] CARGA MOVIL: Unity contra salidas/carga_movil.json')
    indices = sorted({int(m.group(1)) for k in datos for m in [re.match(r'movil\.p(\d+)\.indice$', k)] if m})
    comparar_texto(tabla, datos, 'movil.hecho', 'True')
    comparar_texto(tabla, datos, 'movil.posiciones', str(len(movil['posiciones'])))
    comparar(tabla, datos, 'movil.P_kN', movil['P_kN'])
    if not indices:
        tabla.falta('movil.p<i>', 'al menos una posicion')
    for i in indices:
        pe = movil['posiciones'][i]
        p = 'movil.p%d' % i
        for k in ENTEROS_POSICION:
            comparar_texto(tabla, datos, '%s.%s' % (p, k), str(pe[k]))
        comparar_texto(tabla, datos, p + '.indice_mostrado', str(i))
        for k in CAMPOS_POSICION:
            comparar(tabla, datos, '%s.%s' % (p, k), pe[k])
        comparar_vector(tabla, datos, p + '.u_carga_m', pe['u_carga_m'], ejes=('ux', 'uy', 'uz'))
        for k in ('nodo_i', 'nodo_j'):
            comparar_texto(tabla, datos, '%s.reparto.%s' % (p, k), str(pe['reparto'][k]))
        for k in CAMPOS_REPARTO:
            comparar(tabla, datos, '%s.reparto.%s' % (p, k), pe['reparto'][k])
        for k in CAMPOS_CONSERVACION:
            comparar(tabla, datos, '%s.conservacion.%s' % (p, k), pe['conservacion'][k])
        comparar_texto(tabla, datos, p + '.conservacion.cumple', str(pe['conservacion']['cumple']))
        # Lo que muestra el panel tiene que cerrar con su propia cota:
        # |suma Rz - P| <= cota, con los numeros que tenia Unity.
        try:
            srz = num(datos[p + '.conservacion.suma_Rz_kN'])
            pk = num(datos[p + '.conservacion.P_kN'])
            cota = num(datos[p + '.conservacion.cota_kN'])
            tabla.numero(p + ' |suma Rz - P| <= cota', abs(srz - pk), 0.0,
                         cota + ulp32(srz) + ulp32(pk), 'cota JSON')
        except KeyError as e:
            tabla.falta(p + ' conservacion', str(e))
        # La deformada que puso el visor es la de esta posicion: el uz del
        # nodo que mas baja, en la lista aplicada, contra el resumen (4 dec.).
        clave = p + '.desplazamiento_nodo_uz_min.uz_m'
        comparar(tabla, datos, clave, pe['uz_min_mm'], medio_digito('%.4f' % pe['uz_min_mm']),
                 'f32+impr', 1000.0, nombre=clave + ' (mm)')
        comparar_texto(tabla, datos, p + '.hay_deformada', 'True')
        # La cabecera de su foto dice "Carga movil" con los numeros de esta
        # posicion, no el caso del anexo.
        P = ('%.2f' % movil['P_kN']).rstrip('0').rstrip('.')
        filas_cabecera(tabla, datos, '_carga_movil_posicion_%d_' % i, 'carga_movil', [
            ('posicion', ['Carga movil · posicion %d/%d' % (i + 1, len(movil['posiciones']))]),
            ('x', ['x = %s m' % t for t in textos_redondeados(pe['x'], 2, ulp32(pe['x']))]),
            ('P', ['P = %s kN' % P]),
            ('UZ max', ['UZ max %s mm (nodo %d)' % (t, pe['nodo_uz_min'])
                        for t in textos_redondeados(pe['uz_min_mm'], 3, ulp32(pe['uz_min_mm']))]),
            ('D/C', ['D/C: no se calcula para la carga movil'])])
    return tabla.imprimir()


# ============================================================
# [4] LAS PREGUNTAS: contra los JSON que Unity leyo
# ============================================================
def bloque_preguntas(datos, modelo, anexo):
    tabla = Tabla('[4] PREGUNTAS DEL VISOR: lo que contesta el panel contra modelo.json y resultados.json')
    casos = {c['nombre']: c for c in anexo['casos']}
    nodos = {n['id']: n for n in modelo['nodos']}

    # Donde esta y como esta apoyado.
    col = anexo['info']['columna_demo']
    elem = next(e for e in modelo['elementos'] if e['id'] == col)
    comparar_texto(tabla, datos, 'ux.donde.seleccion', 'elemento %d' % col)
    comparar_texto(tabla, datos, 'ux.donde.seccion', elem['seccion'])
    for lado in ('n1', 'n2'):
        n = nodos[elem[lado]]
        comparar_texto(tabla, datos, 'ux.donde.%s.id' % lado, str(n['id']))
        comparar_vector(tabla, datos, 'ux.donde.%s.xyz_m' % lado, [n['x'], n['y'], n['z']], ejes=('x', 'y', 'z'))
    apoyo = min((nodos[elem['n1']], nodos[elem['n2']]), key=lambda n: n['z'])
    comparar_texto(tabla, datos, 'ux.apoyo.nodo', str(apoyo['id']))
    comparar_texto(tabla, datos, 'ux.apoyo.restricciones', ','.join(str(r) for r in apoyo['restricciones']))
    comparar_texto(tabla, datos, 'ux.apoyo.fijo', str(bool(apoyo.get('fijo'))))

    # Que lo carga: w es SOLO la losa; w_peso_propio y w_total_G (la w que
    # recibe OpenSees en G) vienen en las entradas que los traen.
    if 'ux.carga.viga' in datos:
        viga = int(datos['ux.carga.viga'])
        trib = [t for t in modelo.get('areas_tributarias', []) if t['elemento'] == viga]
        comparar_texto(tabla, datos, 'ux.carga.entradas', str(len(trib)))
        for i, t in enumerate(trib):
            for k, clave in (('area', 'area_m2'), ('qG', 'qG_kN_m2'), ('carga_total', 'carga_total_kN'),
                             ('w', 'w_kN_m'), ('luz', 'luz_m'),
                             ('w_peso_propio', 'w_peso_propio_kN_m'), ('w_total_G', 'w_total_G_kN_m')):
                if k in t:
                    comparar(tabla, datos, 'ux.carga.trib%d.%s' % (i, clave), t[k])
        for c in modelo['casos_de_carga']:
            for q in c.get('cargas_distribuidas') or []:
                if int(q['elemento']) != viga:
                    continue
                comparar_vector(tabla, datos, 'ux.carga.distribuida.' + c['nombre'],
                                [q.get('wx', 0.0), q.get('wy', 0.0), q.get('wz', 0.0)], ejes=('wx', 'wy', 'wz'))
    else:
        tabla.falta('ux.carga.viga', 'una viga con area tributaria')

    # Como se deforma.
    if 'ux.deforma.caso' in datos and 'ux.deforma.nodo' in datos:
        caso = casos[datos['ux.deforma.caso']]
        nodo = int(datos['ux.deforma.nodo'])
        d = next(x for x in caso['desplazamientos'] if x['id'] == nodo)
        comparar(tabla, datos, 'ux.deforma.max_desplazamiento_mm', caso['max_desplazamiento_mm'])
        for k in ('ux', 'uy', 'uz'):
            comparar(tabla, datos, 'ux.deforma.%s_m' % k, d[k])
        comparar_texto(tabla, datos, 'ux.deforma.hay_deformada', 'True')
    else:
        tabla.falta('ux.deforma', 'caso y nodo')

    # Que fuerzas tiene.
    if 'ux.fuerzas.caso' in datos and 'ux.fuerzas.viga' in datos:
        caso = casos[datos['ux.fuerzas.caso']]
        viga = int(datos['ux.fuerzas.viga'])
        s = next(x for x in caso['esfuerzos'] if x['id'] == viga)
        comparar_texto(tabla, datos, 'ux.fuerzas.estaciones', str(len(s['x'])))
        for k in MAGNITUDES:
            comparar(tabla, datos, 'ux.fuerzas.%s_i' % k, s[k][0])
            comparar(tabla, datos, 'ux.fuerzas.%s_j' % k, s[k][-1])
        comparar_texto(tabla, datos, 'ux.fuerzas.motivo_sin_diagrama', '')
    else:
        tabla.falta('ux.fuerzas', 'caso y viga')

    # Cuanta capacidad tiene: el caso con mas NO PASA con la regla del
    # visor (el primero de los casos del anexo con mas pasa = false; los
    # E1..E3 van despues en la lista).
    orden = list(anexo['casos']) + [e['caso'] for e in anexo['superposicion']['estados']]
    mejor, mayor = None, -1
    for c in orden:
        n = sum(1 for d in c.get('demandas') or [] if not d['pasa'])
        if n > mayor:
            mejor, mayor = c['nombre'], n
    comparar_texto(tabla, datos, 'ux.capacidad.caso_con_mas_no_pasa', mejor)
    caso = casos.get(mejor) or next(c for c in orden if c['nombre'] == mejor)
    comparar_texto(tabla, datos, 'ux.capacidad.no_pasan', str(mayor))
    comparar_texto(tabla, datos, 'ux.capacidad.fuera_de_curva',
                   str(sum(1 for d in caso['demandas'] if d['u'] >= 9999)))
    comparar_texto(tabla, datos, 'ux.capacidad.con_fierro', str(len(caso['demandas'])))
    dm = next((d for d in caso['demandas'] if d['id'] == col), None)
    if dm:
        for k in ('P', 'M', 'Mn', 'u'):
            comparar(tabla, datos, 'ux.capacidad.elem.%d.%s' % (col, k), dm[k])
        comparar_texto(tabla, datos, 'ux.capacidad.elem.%d.pasa' % col, str(dm['pasa']))
        comparar_texto(tabla, datos, 'ux.capacidad.elem.%d.extremo' % col, dm['extremo'])
    comparar_texto(tabla, datos, 'ux.capacidad.no_pasa.ids',
                   ','.join(str(d['id']) for d in caso['demandas'] if not d['pasa']))
    comparar_texto(tabla, datos, 'ux.capacidad.mapa_activo', 'True')
    return tabla.imprimir()


# ============================================================
# [5] EL REGISTRO MISMO
# ============================================================
POR_NOMBRE = {'_panel_vista': 'Vista', '_panel_capas': 'Capas', '_panel_caso': 'Caso',
              '_panel_elemento': 'Elemento', '_panel_modificar': 'Modificar',
              '_panel_carga_movil': 'Carga movil', '_superposicion_': 'Caso', '_carga_movil_': 'Carga movil',
              '_M1_': 'Modificar', '_donde_esta_': 'Elemento', '_como_esta_apoyado_': 'Elemento',
              '_que_lo_carga_': 'Elemento', '_como_se_deforma_': 'Elemento', '_que_fuerzas_': 'Elemento',
              '_capacidad_': 'Elemento', '_mapa_DC_leyenda': 'Caso', '_vista_general_': 'Vista'}


def bloque_registro(datos, avisos, carpeta, modelo, anexo, control, exigir_servidor):
    tabla = Tabla('[5] REGISTRO: fotos, log, ids de control, Excel, edificio, archivos al dia')
    fotos = sorted(f for f in os.listdir(carpeta) if f.lower().endswith(('.jpg', '.png')))
    if fotos:
        comparar_texto(tabla, datos, 'fotos', str(len(fotos)))
    else:
        print('  [--  ] las fotos no estan en %s (git las ignora): no se cuentan' % rutas.relativa(carpeta))
    comparar_texto(tabla, datos, 'salida', '0')
    comparar_texto(tabla, datos, 'log.errores', '0')
    tabla.texto('lineas AVISO/ERROR en registro.txt', len(avisos), 0)
    comparar_texto(tabla, datos, 'edificio', _ed.NOMBRE)
    comparar_texto(tabla, datos, 'anexo.edificio', _ed.NOMBRE)
    comparar_texto(tabla, datos, 'anexo.calza', 'True')
    comparar_texto(tabla, datos, 'anexo.aviso', '')
    comparar_texto(tabla, datos, 'anexo.casos', str(len(anexo['casos']) + len(anexo['superposicion']['estados'])))
    comparar_texto(tabla, datos, 'excel.existe', 'True')
    comparar_texto(tabla, datos, 'superposicion.aviso', '')
    comparar_texto(tabla, datos, 'superposicion.nombres', ','.join(
        '%s(precalculado)' % e['nombre'] for e in anexo['superposicion']['estados']))
    comparar_texto(tabla, datos, 'modelo.nodos', str(len(modelo['nodos'])))
    comparar_texto(tabla, datos, 'modelo.elementos', str(len(modelo['elementos'])))
    cota = (modelo.get('info') or {}).get('cota_terreno')
    if cota is not None:
        comparar(tabla, datos, 'modelo.cota_terreno', cota)
    if exigir_servidor:
        comparar_texto(tabla, datos, 'servidor.responde', 'True')
    # Los ids de control: los de entrada/laboratorio.json, que tienen que
    # ser los que da la regla con los datos de hoy.
    esperados = lab.bloque('superposicion')['control']['esperados']
    for k in ('columna', 'muro', 'viga', 'nodo'):
        tabla.texto('regla de control: %s' % k, control[k], esperados.get(k), 'regla')
        comparar_texto(tabla, datos, 'control.' + k, str(esperados.get(k)))
    # Cada foto salio con la pestana que dice su nombre.
    for k in sorted(d for d in datos if d.endswith('.pestana') and d.startswith('foto.')):
        base = k[len('foto.'):-len('.pestana')]
        esperada = next((v for t, v in POR_NOMBRE.items() if t in base), None)
        if esperada:
            comparar_texto(tabla, datos, k, esperada)
    archivos_al_dia(tabla, datos)
    for a in avisos[:10]:
        print('  registro: ' + a)
    return tabla.imprimir()


# ============================================================
# [6] LOS SLIDERS INSTANTANEOS (lo que la app combino en C#)
# ============================================================
# La replica del algoritmo de VisorResultados.Instantanea.cs (retabular a
# la malla comun POR FRACCION DE INDICE, escalar y sumar en float32,
# rehacer la demanda) y las cotas de cada termino son UNA, la de la
# verificacion de los resultados (R5, sobre 10 juegos de lambdas). Aca se
# usa para cruzar lo que la APP escribio al mover los sliders.
from verificacion.resultados import (EPS, MS_INSTANTANEO, R_DESPL, R_FUERZA,  # noqa: E402
                                     combinar_como_unity, comparar_demandas, conteos, cota_f32,
                                     norma_maxima_mm, preparar)
from verificacion.resultados import PeorMargen as Peor  # noqa: E402


def bloque_instantaneo(reg, ruta, anexo, inf):
    """Los numeros que la app escribio al mover los sliders, contra Python
    (superposicion.caso_combinado) y contra la replica de su algoritmo."""
    titulo('[6] INSTANT: lo que la app combino al mover los sliders, contra Python')
    juegos = [k for k in ('E1', 'E2', 'E3', 'feo') if ('ins.%s.lambdas' % k) in reg]
    if not inf.check(bool(juegos), 'el registro %s trae los sliders instantaneos (ins.*)' % rutas.relativa(ruta),
                     () if juegos else 'no hay lineas "ins.*": vuelve a capturar con  python sap.py capturar visor'):
        return
    ids = [int(reg[k]) for k in ('control.columna', 'control.muro', 'control.viga') if k in reg]
    nodo = int(reg['control.nodo']) if 'control.nodo' in reg else None
    print('  barras de control %s, nodo %s, juegos %s' % (ids, nodo, juegos))

    # --- la version: cada juego tiene que haber REEMPLAZADO el caso ---
    antes = int(reg.get('ins.version_antes', '0'))
    versiones = [int(reg['ins.%s.version' % k]) for k in juegos]
    inf.check(versiones == [antes + i + 1 for i in range(len(juegos))],
              'la version sube 1 en cada juego: %s -> %s (el segundo movimiento del slider tambien reemplaza)'
              % (antes, versiones))
    if 'ins.version_despues' in reg and 'ins.combinaciones_pedidas' in reg:
        inf.check(int(reg['ins.version_despues']) - antes == int(reg['ins.combinaciones_pedidas']),
                  'se combino exactamente %s veces' % reg['ins.combinaciones_pedidas'])
    for k in juegos:
        inf.check(reg.get('ins.%s.caso_activo' % k) == 'INSTANT' and reg.get('ins.%s.tipo' % k) == sp.TIPO,
                  '%s: el caso activo es INSTANT y su tipo "%s" (activo %s, tipo %s)'
                  % (k, sp.TIPO, reg.get('ins.%s.caso_activo' % k), reg.get('ins.%s.tipo' % k)))
    origenes_mal = [k for k in juegos if 'Unity' not in reg.get('ins.%s.origen' % k, '')]
    inf.check(not origenes_mal, 'el panel dice que INSTANT se combino en Unity, no en Python',
              ['%s: %s' % (k, reg.get('ins.%s.origen' % k, '')[:100]) for k in origenes_mal])

    # --- instantaneo: dentro de un cuadro ---
    ms = [float(reg['ins.%s.ms' % k]) for k in juegos]
    inf.check(max(ms) <= MS_INSTANTANEO, 'cada combinacion cabe en un cuadro a 60 Hz: %s ms (tope %.1f)'
              % (', '.join('%.2f' % v for v in ms), MS_INSTANTANEO))

    # --- la base de Python: los cuatro casos resueltos en OpenSees ---
    b = sp.base([], silenciar=True)
    print('  base de Python: %d barras en %.1f s' % (len(b['largos']), b['segundos']))
    inf.check(sp.parametros_de(b) == anexo['info']['parametros'],
              'la base usa los mismos parametros que el resultados.json que lee Unity')
    prep = preparar(anexo)

    peor_replica = 0.0
    for k in juegos:
        lam = tuple(float(v) for v in reg['ins.%s.lambdas' % k].split(','))
        etiqueta = 'registro %s l = (%s)' % (k, ', '.join('%g' % v for v in lam))
        caso, _ = sp.caso_combinado(b, dict(zip(CASOS, lam)))
        replica = combinar_como_unity(prep, lam)
        esc = replica['escala']
        suma = sum(abs(v) for v in lam)
        cota_u = R_DESPL * (suma + 1.0)
        cota_f = R_FUERZA * (suma + 1.0)
        p = 'ins.%s' % k

        # desplazamiento maximo (la norma, como la cabecera del anexo)
        u_max_py = norma_maxima_mm(caso['desplazamientos'])
        u_max_un = float(reg[p + '.max_desplazamiento_mm'])
        esc_max = max(sum(e.values()) for e in esc['u'].values()) * 1000.0
        tope = cota_u * 1000.0 + cota_f32(esc_max) + EPS
        inf.check(abs(u_max_un - u_max_py) <= tope, '%s: desplazamiento maximo %.4f mm (Python %.4f, cota %.1e)'
                  % (etiqueta, u_max_un, u_max_py, tope))

        # el nodo de control
        if nodo is not None:
            py_u = {int(d['id']): d for d in caso['desplazamientos']}[nodo]
            re_u = {int(d['id']): d for d in replica['desplazamientos']}[nodo]
            peor = Peor()
            for g in ('ux', 'uy', 'uz'):
                v = float(reg['%s.nodo.%d.%s_m' % (p, nodo, g)])
                peor.ver(abs(v - float(py_u[g])), cota_u + cota_f32(esc['u'][nodo][g]) + EPS, g)
                peor_replica = max(peor_replica, abs(v - float(re_u[g])) / max(abs(v), 1e-12))
            inf.check(peor.ok, '%s: nodo %d ux, uy, uz (%s)' % (etiqueta, nodo, peor))

        # los extremos de las barras de control
        py_e = {int(s['id']): s for s in caso['esfuerzos']}
        re_e = {int(s['id']): s for s in replica['esfuerzos']}
        peor = Peor()
        for eid in ids:
            if ('%s.elem.%d.N_i' % (p, eid)) not in reg:
                continue
            for m in MAGNITUDES:
                for lado, i in (('i', 0), ('j', -1)):
                    v = float(reg['%s.elem.%d.%s_%s' % (p, eid, m, lado)])
                    peor.ver(abs(v - float(py_e[eid][m][i])), cota_f + cota_f32(esc['m'][eid][m][i]) + EPS,
                             'elem %d %s_%s' % (eid, m, lado))
                    peor_replica = max(peor_replica, abs(v - float(re_e[eid][m][i])) / max(abs(v), 1e-6))
        inf.check(peor.ok, '%s: extremos N..Mz de las barras %s (%s)' % (etiqueta, ids, peor))

        # las demandas de las barras de control
        dem = []
        for eid in ids:
            if ('%s.elem.%d.P' % (p, eid)) not in reg:
                continue
            dem.append({'id': eid, 'P': float(reg['%s.elem.%d.P' % (p, eid)]),
                        'M': float(reg['%s.elem.%d.M' % (p, eid)]),
                        'Mn': float(reg['%s.elem.%d.Mn' % (p, eid)]),
                        'u': float(reg['%s.elem.%d.u' % (p, eid)]),
                        'extremo': reg['%s.elem.%d.extremo' % (p, eid)],
                        'pasa': reg['%s.elem.%d.pasa' % (p, eid)] == 'True'})
        if dem:
            comparar_demandas(dem, caso['demandas'], esc['f'], cota_f, inf, etiqueta)

        # los conteos de la cabecera
        np_py, fu_py, tot_py = conteos(caso['demandas'])
        np_un = int(reg[p + '.no_pasan'])
        fu_un = int(reg[p + '.fuera_de_curva'])
        tot_un = int(reg[p + '.con_fierro'])
        inf.check((np_un, fu_un, tot_un) == (np_py, fu_py, tot_py),
                  '%s: la cabecera cuenta NO PASA %d/%d (%d fuera de curva); Python %d/%d (%d)'
                  % (etiqueta, np_un, tot_un, fu_un, np_py, tot_py, fu_py))
    print('  la replica de Python y el registro de Unity difieren a lo mas %.1e relativo' % peor_replica
          + ' (la aritmetica de 32 bits esta bien emulada si es ~1e-7)')


# ============================================================
# LOS MODOS
# ============================================================
def visor(inf, ruta, sin_servidor):
    datos, avisos = leer_registro(ruta)
    exigir = not sin_servidor
    print('  registro %s: edificio %s; %d datos; equipo %s | %s | %s | RAM %s MB | pantalla %s a %s dpi'
          % (rutas.relativa(ruta), datos.get('edificio', '?'), len(datos), datos.get('equipo.cpu', '?'),
             datos.get('equipo.so', '?'), datos.get('equipo.gpu', '?'), datos.get('equipo.ram_mb', '?'),
             datos.get('pantalla', '?'), datos.get('pantalla.dpi', '?')))
    print('  tolerancia por fila = suma de sus causas (f32, impr): ver el encabezado')
    modelo = leer_salida('modelo')
    anexo = leer_salida('resultados')
    movil = leer_salida('carga_movil')
    control = control_por_regla(anexo)
    malas = bloque_superposicion(datos, anexo, control, exigir)
    inf.check(malas == 0, '[1] superposicion: E1..E3 y LIBRE = el bloque de resultados.json (%d FALLA)' % malas)
    malas = bloque_m1(datos, modelo, exigir)
    inf.check(malas == 0, '[2] M1: Unity + /analizar = el mismo pedido resuelto aca (%d FALLA)' % malas)
    malas = bloque_carga_movil(datos, movil)
    inf.check(malas == 0, '[3] carga movil = carga_movil.json (%d FALLA)' % malas)
    malas = bloque_preguntas(datos, modelo, anexo)
    inf.check(malas == 0, '[4] preguntas del visor = modelo.json y resultados.json (%d FALLA)' % malas)
    malas = bloque_registro(datos, avisos, os.path.dirname(ruta), modelo, anexo, control, exigir)
    inf.check(malas == 0, '[5] registro: fotos, log.errores = 0, control, archivos al dia (%d FALLA)' % malas)
    bloque_instantaneo(datos, ruta, anexo, inf)


def errores_y_al_dia(inf, datos, avisos, modo):
    tabla = Tabla('%s: la captura termino bien y es de los datos de hoy' % modo)
    comparar_texto(tabla, datos, 'salida', '0')
    comparar_texto(tabla, datos, 'log.errores', '0')
    tabla.texto('lineas AVISO/ERROR en registro.txt', len(avisos), 0)
    archivos_al_dia(tabla, datos)
    malas = tabla.imprimir()
    inf.check(malas == 0, '%s: salida 0, log.errores = 0 y archivos al dia (%d FALLA)' % (modo, malas))


def persona(inf, ruta):
    datos, avisos = leer_registro(ruta)
    errores_y_al_dia(inf, datos, avisos, 'persona')
    titulo('[7] lo que la app sumo, contra OpenSees directo (verificacion.persona registro)')
    from verificacion import persona as ver_persona
    codigo = ver_persona.main(['registro', '--registro', ruta])
    inf.check(codigo == 0, '[7] verificacion.persona registro: lo que la app sumo = OpenSees (codigo %s)' % codigo)


def relieve(inf, ruta):
    datos, avisos = leer_registro(ruta)
    errores_y_al_dia(inf, datos, avisos, 'relieve')
    titulo('relieve: lo que dibujo la app')
    with io.open(ruta, encoding='utf-8') as f:
        lineas = [l.rstrip('\r\n') for l in f]
    estado = next((l[len('relieveEstado: '):] for l in lineas if l.startswith('relieveEstado: ')), None)
    inf.check(estado is not None and estado.startswith('Relieve del sitio'),
              "relieveEstado empieza con 'Relieve del sitio'", (estado or '(no hay linea relieveEstado)')[:160])
    js = leer_salida('relieve')
    m = next((re.search(r'relieve del sitio de (\d+) x (\d+) nodos cada ([\d.]+) m, (\d+) huecos', l)
              for l in lineas if 'relieve del sitio de' in l), None)
    hay = (int(m.group(1)), int(m.group(2)), float(m.group(3)), int(m.group(4))) if m else None
    quiero = (js['nx'], js['ny'], float(js['paso']), len(js['huecos']))
    inf.check(hay == quiero, 'la malla que dibujo (%s x %s cada %s m, %s huecos) es la de relieve.json'
              % quiero, 'la app dice %s' % (hay,) if hay != quiero else '')
    if estado is not None:
        info = js['info']
        for etiqueta, valor in (('desfase', info['desfase_vertical_m']), ('residuo rms', info['residuo_rms_m'])):
            mm = re.search(r'%s ([\d.]+) m' % etiqueta, estado)
            inf.check(mm is not None and abs(float(mm.group(1)) - valor) <= medio_digito(mm.group(1)),
                      'relieveEstado dice %s %s m = relieve.json %s' % (etiqueta, mm.group(1) if mm else '?', valor))
    errores = next((l for l in lineas if l.startswith('errores del log: ')), None)
    inf.check(errores == 'errores del log: 0', 'errores del log: 0',
              '' if errores == 'errores del log: 0' else (errores or '(no hay linea)'))


def diagramas(inf, ruta):
    datos, avisos = leer_registro(ruta)
    errores_y_al_dia(inf, datos, avisos, 'diagramas')
    titulo('diagramas: los f_i / f_j que imprime el panel = resultados.json')
    with io.open(ruta, encoding='utf-8') as f:
        lineas = [l.rstrip('\r\n') for l in f]
    anexo = leer_salida('resultados')
    casos = {c['nombre']: {int(s['id']): s for s in c['esfuerzos']} for c in anexo['casos']}
    revisados, malos = 0, []
    for i, l in enumerate(lineas):
        m = re.search(r'casos\[(.+?)\]\.esfuerzos\[id=(\d+)\]\.f', l)
        if not m:
            continue
        s = casos.get(m.group(1), {}).get(int(m.group(2)))
        fi = next((x for x in lineas[i + 1:i + 5] if x.strip().startswith('f_i [')), None)
        fj = next((x for x in lineas[i + 1:i + 5] if x.strip().startswith('f_j [')), None)
        if s is None or fi is None or fj is None:
            malos.append('%s %s: sin f_i/f_j o sin el esfuerzo en resultados.json' % (m.group(1), m.group(2)))
            continue
        impresos = (fi.split('[', 1)[1].rstrip(']').split() + fj.split('[', 1)[1].rstrip(']').split())
        for k, t in enumerate(impresos):
            revisados += 1
            ref = s['f'][k]
            if abs(float(t) - ref) > medio_digito(t) + ulp32(ref):
                malos.append('%s %s f[%d]: impreso %s, resultados.json %r' % (m.group(1), m.group(2), k, t, ref))
    inf.check(revisados > 0 and not malos, 'los %d valores de f impresos = resultados.json al decimal impreso'
              % revisados, malos[:6])
    calzan = [l for l in lineas if l.startswith('aviso del anexo:')]
    inf.check(bool(calzan) and all('calza con el modelo: True' in l for l in calzan),
              'el panel dice que resultados.json calza con el modelo', calzan[:1])
    modelo_ok = [l for l in lineas if l.strip().startswith('Modelo ')]
    inf.check(bool(modelo_ok) and all(l.rstrip().endswith('OK') for l in modelo_ok),
              'en cada barra revisada, nodos y seccion del anexo calzan con el modelo del visor (%d)' % len(modelo_ok))


# ============================================================
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog='python -m verificacion.capturas',
                                 description='Lo que la app registro al capturar, contra Python.')
    ap.add_argument('modos', nargs='*', metavar='modo', help='%s (sin nada: todos)' % ', '.join(BLOQUES))
    ap.add_argument('--registro', metavar='REGISTRO_TXT',
                    help='otro registro.txt (con un solo modo); por defecto %s'
                    % rutas.relativa(os.path.join(CARPETA, '<modo>', 'registro.txt')))
    ap.add_argument('--sin-servidor', action='store_true',
                    help='la captura del visor se hizo sin servidor: no exigir LIBRE ni M1')
    args = ap.parse_args(argv)
    desconocidos = [m for m in args.modos if m not in BLOQUES]
    if desconocidos:
        ap.error('modo desconocido %s (son: %s)' % (', '.join(desconocidos), ', '.join(BLOQUES)))
    modos = args.modos or list(BLOQUES)
    if args.registro and len(modos) != 1:
        ap.error('--registro va con un solo modo')

    t0 = time.time()
    print('=' * 118)
    print('  LO QUE LA APP REGISTRO, CONTRA PYTHON   %s   (%s)' % (_ed.NOMBRE.upper(), ', '.join(modos)))
    print('=' * 118)
    inf = Informe()
    for modo in modos:
        ruta = registro_de(modo, args.registro)
        print()
        print('#' * 118)
        print('#  %s   %s' % (modo.upper(), rutas.relativa(ruta)))
        print('#' * 118)
        if not inf.check(os.path.isfile(ruta), 'existe %s' % rutas.relativa(ruta),
                         '' if os.path.isfile(ruta) else 'se hace con  python sap.py capturar %s' % modo):
            continue
        if modo == 'visor':
            visor(inf, ruta, args.sin_servidor)
        elif modo == 'persona':
            persona(inf, ruta)
        elif modo == 'relieve':
            relieve(inf, ruta)
        elif modo == 'diagramas':
            diagramas(inf, ruta)
    print('  (%.0f s)' % (time.time() - t0))
    return inf.cerrar()


if __name__ == '__main__':
    sys.exit(main())
