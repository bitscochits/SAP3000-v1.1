# -*- coding: utf-8 -*-
r"""
================================================================
 calculo/rutas.py  -  DONDE ESTA CADA COSA
================================================================
 Un solo archivo sabe como esta ordenado el proyecto. Todos los
 demas se lo preguntan a el.

     entrada/       lo que se edita a mano: el edificio, lo que pide
                    el laboratorio y el sitio (relieve)
     calculo/       Python + OpenSees: lo unico que calcula
     exportar/      arma cada archivo de salidas/ (uno por archivo)
     salidas/       GENERADO: lo que leen Unity, la AR y Excel
     unity/         el visor (StreamingAssets recibe COPIAS de salidas/)
     ar/            la app de realidad aumentada (web/datos recibe ar.json)
     verificacion/  la suite: compara, no escribe salidas
     herramientas/  abrir y compilar Unity, regenerar assets

 La raiz se busca SUBIENDO hasta la marca (setup.ps1 junto a sap.py),
 nunca contando `os.path.dirname`: contar funciona hasta que un archivo
 cambia de carpeta, y entonces escribe en el lugar equivocado sin
 fallar (CLAUDE.md, convencion "Rutas").
================================================================
"""
from __future__ import annotations

import os

# La marca de la raiz: las dos juntas. setup.ps1 solo no basta: una copia
# de v1.0 tambien lo tiene, y v1.1 no debe leer ni escribir la de v1.0.
MARCAS = ('setup.ps1', 'sap.py')


def _subir_hasta_la_raiz(desde: str) -> str:
    d = os.path.dirname(os.path.abspath(desde))
    while True:
        if all(os.path.isfile(os.path.join(d, m)) for m in MARCAS):
            return d
        padre = os.path.dirname(d)
        if padre == d:
            raise RuntimeError(
                'no encuentro la raiz del proyecto (una carpeta con %s) subiendo '
                'desde %s' % (' y '.join(MARCAS), desde))
        d = padre


RAIZ = _subir_hasta_la_raiz(__file__)

# --- entrada: lo que se edita a mano ---
ENTRADA = os.path.join(RAIZ, 'entrada')
EDIFICIO = os.path.join(ENTRADA, 'edificio.json')
LABORATORIO = os.path.join(ENTRADA, 'laboratorio.json')
SITIO = os.path.join(ENTRADA, 'sitio')

# --- salidas: lo que se genera ---
SALIDAS = os.path.join(RAIZ, 'salidas')
CAPTURAS = os.path.join(SALIDAS, 'capturas')
EVIDENCIA = os.path.join(SALIDAS, 'evidencia')
FIGURAS = os.path.join(SALIDAS, 'figuras')

# Cada archivo de salidas/ con el nombre con que lo lee su consumidor.
# Los de Unity tienen que llamarse igual que la constante ARCHIVO de su
# lector C#: la verificacion "nombres y copias" compara las dos listas.
NOMBRES_EN_UNITY = {
    'modelo': 'modelo.json',
    'resultados': 'resultados.json',
    'carga_movil': 'carga_movil.json',
    'persona': 'persona.json',
    'relieve': 'relieve.json',
    'excel': 'resultados.xlsx',
}
OTRAS_SALIDAS = {
    'casos_del_modelo': 'casos_del_modelo.json',
    'ar': 'ar.json',
    'reanalisis': 'reanalisis.xlsx',
}

# --- codigo y proyectos ---
CALCULO = os.path.join(RAIZ, 'calculo')
UNITY_PROYECTO = os.path.join(RAIZ, 'unity')
ASSETS = os.path.join(UNITY_PROYECTO, 'Assets')
STREAMING = os.path.join(ASSETS, 'StreamingAssets')
SCRIPTS_CS = os.path.join(ASSETS, 'Scripts')
EDITOR_CS = os.path.join(ASSETS, 'Editor')
ESCENA = os.path.join(ASSETS, 'Scenes', 'SampleScene.unity')
RESOURCES = os.path.join(ASSETS, 'Resources')
BUILD = os.path.join(RAIZ, 'build')
AR = os.path.join(RAIZ, 'ar')
AR_WEB = os.path.join(AR, 'web')


def salida(nombre: str) -> str:
    """salidas/<archivo> de una salida por su nombre corto ('modelo', 'ar', ...)."""
    if nombre in NOMBRES_EN_UNITY:
        return os.path.join(SALIDAS, NOMBRES_EN_UNITY[nombre])
    if nombre in OTRAS_SALIDAS:
        return os.path.join(SALIDAS, OTRAS_SALIDAS[nombre])
    raise KeyError('no hay una salida llamada %r (son: %s)'
                   % (nombre, ', '.join(sorted(NOMBRES_EN_UNITY) + sorted(OTRAS_SALIDAS))))


def cs(nombre: str) -> str:
    """
    La ruta de un .cs del visor por su nombre ('VisorEstructura.cs'). Las
    verificaciones que LEEN el C# lo buscan aca, asi un .cs que cambia de
    carpeta no deja a su guardia leyendo la nada: si no aparece, o aparece
    dos veces, es un error y no un "PEND".
    """
    hallados = []
    for base in (SCRIPTS_CS, EDITOR_CS):
        for d, _, archivos in os.walk(base):
            if nombre in archivos:
                hallados.append(os.path.join(d, nombre))
    if len(hallados) != 1:
        raise FileNotFoundError('%s: %d copias bajo unity/Assets (tiene que haber una)'
                                % (nombre, len(hallados)))
    return hallados[0]


def asegurar(ruta: str) -> str:
    """Crea la carpeta que contiene `ruta` si no existe. Devuelve `ruta`."""
    carpeta = os.path.dirname(ruta)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    return ruta


def escribir_atomico(ruta: str, datos: bytes) -> str:
    """
    Escribe `datos` en `ruta` de una vez: a un temporal en la misma carpeta y
    despues os.replace. Quien lee nunca ve un archivo a medias (Unity abierto
    leyendo StreamingAssets, un Excel que se reescribe). Si el destino esta
    tomado (un libro abierto en Excel), el error lo dice.
    """
    asegurar(ruta)
    tmp = ruta + '.tmp%d' % os.getpid()
    with open(tmp, 'wb') as f:
        f.write(datos)
    try:
        os.replace(tmp, ruta)
    except PermissionError:
        os.remove(tmp)
        raise PermissionError(
            'no puedo reemplazar %s: esta abierto en otro programa (Excel, Unity). '
            'Cerralo y volve a correr.' % ruta)
    return ruta


def relativa(ruta: str) -> str:
    """La ruta relativa a la raiz, para los mensajes."""
    try:
        return os.path.relpath(ruta, RAIZ)
    except ValueError:
        return ruta


if __name__ == '__main__':
    print('%-14s %s' % ('RAIZ', RAIZ))
    for n in ('ENTRADA', 'EDIFICIO', 'LABORATORIO', 'SITIO', 'SALIDAS', 'STREAMING',
              'SCRIPTS_CS', 'ESCENA', 'BUILD', 'AR_WEB'):
        v = globals()[n]
        print('%-14s %s   %s' % (n, relativa(v), '' if os.path.exists(v) else '(no existe aun)'))
