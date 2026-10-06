# -*- coding: utf-8 -*-
r"""
================================================================
 verificacion/comun.py  -  LO QUE COMPARTEN LAS VERIFICACIONES
================================================================
 Una sola definicion de cada herramienta de comprobar:

   Informe, titulo          cada comprobacion imprime UNA linea [OK]/[FALLA]
   f32, ulp32, medio_digito lo que Unity guarda en float32 y el medio ultimo
                            digito de un numero impreso (cotas MEDIDAS, no a ojo)
   campos_de_clases         los campos publicos de las clases de un .cs, con su
                            tipo: JsonUtility ignora EN SILENCIO una clave del
                            JSON que no tiene campo (CLAUDE.md, trampas)
   tipo_calza,              si JsonUtility puede volcar un valor en un campo de
   arreglos_anidados        ese tipo; y donde hay arreglos dentro de arreglos,
                            que JsonUtility no lee
   leer_registro            las lineas 'DATO clave = valor' que escribe la app
                            al capturar (verificacion/registros/capturas/...)
   comparar_json            dos JSON por OBJETOS, con tolerancia y exclusiones

 Ninguna verificacion escribe en salidas/: compara.
================================================================
"""
from __future__ import annotations

import io
import math
import re
import struct

import numpy as np

# int de C# es de 32 bits y float de 32: un valor fuera de rango no da
# error en JsonUtility, da basura.
INT32 = (-2 ** 31, 2 ** 31 - 1)
FLOAT32_MAX = 3.4028234663852886e38


# ============================================================
# INFORME
# ============================================================
class Informe(object):
    """Junta lo que no calza y lo pendiente; cada comprobacion imprime una linea."""

    def __init__(self):
        self.fallas = []
        self.pendientes = []

    def check(self, ok, que, detalle=()):
        print('  [%s] %s' % ('OK  ' if ok else 'FALLA', que))
        for linea in ([detalle] if isinstance(detalle, str) else detalle):
            if linea:
                print('         %s' % linea)
        if not ok:
            self.fallas.append(que)
        return ok

    def pendiente(self, que):
        print('  [PEND] %s' % que)
        self.pendientes.append(que)

    def cerrar(self, mensaje_ok='TODO OK'):
        """La ultima linea y el codigo de salida: 0 si no hubo fallas."""
        print()
        if self.fallas:
            print('  %d FALLA(S):' % len(self.fallas))
            for f in self.fallas:
                print('    - %s' % f)
            return 1
        print('  ' + mensaje_ok)
        return 0


def titulo(texto):
    print()
    print(texto)
    print('-' * min(len(texto), 78))


# ============================================================
# FLOAT32 Y DIGITOS IMPRESOS
# ============================================================
def f32(x):
    """El float de 32 bits mas cercano: lo que Unity tiene en memoria."""
    return struct.unpack('<f', struct.pack('<f', float(x)))[0]


def ulp32(v):
    """Separacion entre floats de 32 bits vecinos en |v|."""
    return float(np.spacing(np.float32(abs(v))))


def medio_digito(texto):
    """Medio ultimo digito de un numero impreso: '-3.64515' -> 5e-6,
    '2.0e-04' -> 5e-6, '34148' -> 0.5."""
    t = texto.strip().lower()
    m = re.fullmatch(r'[-+]?\d*(?:\.(\d*))?(?:e([-+]?\d+))?', t)
    if not m:
        return 0.0
    dec = len(m.group(1) or '')
    exp = int(m.group(2) or 0)
    return 0.5 * 10.0 ** (exp - dec)


# ============================================================
# EL C#: CAMPOS PUBLICOS Y SU TIPO
# ============================================================
def campos_de_clases(ruta):
    r"""
    {clase: {campo: tipo}} de un .cs. Fuera los comentarios (un ejemplo en
    una nota no es codigo); la clase se recorta hasta su llave de cierre por
    profundidad; cuenta 'public <tipo> a, b;' (las propiedades con get
    quedan fuera, como para JsonUtility).
    """
    with io.open(ruta, encoding='utf-8') as f:
        src = f.read()
    src = re.sub(r'/\*.*?\*/', '', src, flags=re.S)
    src = re.sub(r'//[^\n]*', '', src)

    clases = {}
    for m in re.finditer(r'class\s+(\w+)\s*\{', src):
        i = m.end() - 1
        prof, j = 0, i
        while j < len(src):
            if src[j] == '{':
                prof += 1
            elif src[j] == '}':
                prof -= 1
                if prof == 0:
                    break
            j += 1
        campos = {}
        for d in re.finditer(
                r'public\s+([\w<>\[\]\.]+)\s+([\w\s,]+?)\s*(?:=[^;]*)?;', src[i:j]):
            if '(' in d.group(2):
                continue
            for nom in d.group(2).split(','):
                nom = nom.strip()
                if nom and re.fullmatch(r'\w+', nom):
                    campos[nom] = d.group(1)
        clases[m.group(1)] = campos
    return clases


def campos_publicos(ruta):
    """{clase: set de campos} (sin el tipo)."""
    return {c: set(v) for c, v in campos_de_clases(ruta).items()}


def tipo_calza(tipo, valor, clases):
    """
    None si JsonUtility puede volcar 'valor' en un campo C# de 'tipo'; si
    no, el motivo. Tipos del contrato: int, long, float, double, string,
    bool, T[] y List<T>, y las clases del propio contrato.
    """
    if valor is None:
        return 'null (JsonUtility lo deja en su valor por defecto)'
    m = re.fullmatch(r'List<(\w+)>', tipo) or re.fullmatch(r'(\w+)\[\]', tipo)
    if m:
        if not isinstance(valor, list):
            return 'se esperaba un arreglo'
        for v in valor:
            motivo = tipo_calza(m.group(1), v, clases)
            if motivo:
                return 'elemento del arreglo: ' + motivo
        return None
    if tipo in ('int', 'long'):
        if isinstance(valor, bool) or not isinstance(valor, int):
            return 'se esperaba un entero, vino %r' % (valor,)
        if tipo == 'int' and not INT32[0] <= valor <= INT32[1]:
            return 'fuera del rango de int32: %d' % valor
        return None
    if tipo in ('float', 'double'):
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            return 'se esperaba un numero, vino %r' % (valor,)
        if tipo == 'float' and abs(valor) > FLOAT32_MAX:
            return 'fuera del rango de float32: %r' % valor
        return None
    if tipo == 'string':
        return None if isinstance(valor, str) else 'se esperaba texto, vino %r' % (valor,)
    if tipo == 'bool':
        return None if isinstance(valor, bool) else 'se esperaba true/false, vino %r' % (valor,)
    if tipo in clases:
        return None if isinstance(valor, dict) else 'se esperaba un objeto %s' % tipo
    return 'tipo C# %r que el contrato no conoce' % tipo


def arreglos_anidados(valor, ruta='$', salida=None, tope=5):
    """Rutas donde hay un arreglo dentro de otro: JsonUtility no los lee."""
    salida = [] if salida is None else salida
    if len(salida) >= tope:
        return salida
    if isinstance(valor, dict):
        for k, v in valor.items():
            arreglos_anidados(v, '%s.%s' % (ruta, k), salida, tope)
    elif isinstance(valor, list):
        for i, v in enumerate(valor):
            if isinstance(v, list):
                salida.append('%s[%d]' % (ruta, i))
            else:
                arreglos_anidados(v, '%s[%d]' % (ruta, i), salida, tope)
    return salida


# ============================================================
# LOS REGISTROS DE LA APP
# ============================================================
_DATO = re.compile(r'^DATO (\S+) = (.*)$')


def leer_registro(ruta):
    """
    ({clave: texto} de las lineas 'DATO clave = valor', [lineas de AVISO y
    ERROR]) del registro.txt que deja la app al capturar.
    """
    datos, avisos = {}, []
    with io.open(ruta, encoding='utf-8') as fh:
        for linea in fh:
            linea = linea.rstrip('\r\n')
            m = _DATO.match(linea)
            if m:
                datos[m.group(1)] = m.group(2)
            elif linea.startswith(('AVISO', 'ERROR')):
                avisos.append(linea)
    return datos, avisos


# ============================================================
# COMPARAR JSON POR OBJETOS
# ============================================================
def comparar_json(a, b, ignorar=(), tol=0.0, ruta='$', difs=None, limite=40):
    """
    Las diferencias entre dos objetos JSON ya cargados (el orden de las
    claves y el formato no cuentan). Una clave en `ignorar` se salta en
    cualquier nivel. Devuelve la lista de diferencias (vacia si son iguales).
    """
    difs = [] if difs is None else difs
    if len(difs) >= limite:
        return difs
    if isinstance(a, dict) and isinstance(b, dict):
        ka = {k for k in a if k not in ignorar}
        kb = {k for k in b if k not in ignorar}
        for k in sorted(ka - kb):
            difs.append('%s.%s: falta' % (ruta, k))
        for k in sorted(kb - ka):
            difs.append('%s.%s: sobra' % (ruta, k))
        for k in sorted(ka & kb):
            comparar_json(a[k], b[k], ignorar, tol, '%s.%s' % (ruta, k), difs, limite)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            difs.append('%s: largo %d contra %d' % (ruta, len(a), len(b)))
            return difs
        for i, (x, y) in enumerate(zip(a, b)):
            comparar_json(x, y, ignorar, tol, '%s[%d]' % (ruta, i), difs, limite)
    elif isinstance(a, bool) or isinstance(b, bool):
        if a != b:
            difs.append('%s: %r contra %r' % (ruta, a, b))
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not (isinstance(a, float) and math.isnan(a) and isinstance(b, float) and math.isnan(b)):
            if abs(a - b) > tol:
                difs.append('%s: %r contra %r' % (ruta, a, b))
    elif a != b:
        difs.append('%s: %s contra %s' % (ruta, repr(a)[:100], repr(b)[:100]))
    return difs
