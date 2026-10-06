# El AT-ST de la pestaña Persona

`at-st_tom_meyer.obj` y `materials.mtl` son el modelo **"AT-ST"** de
**Tom Meyer** ("Star Wars AT-ST, first try at modeling something in
Blocks", 2017), descargado de Poly Pizza el 05-10-2026 sin cambios:

- Página: https://poly.pizza/m/6jqEk8QiL0m (viene de Google Poly / Blocks)
- Licencia: **Creative Commons Attribution 3.0** (CC BY 3.0),
  https://creativecommons.org/licenses/by/3.0/
- Atribución: "AT-ST" by Tom Meyer, CC BY 3.0, via Poly Pizza.

**Cambios** (los hace `herramientas/atst.py`, con `python sap.py atst`; el
OBJ queda como vino): separado en cuerpo y dos piernas, pasado a los ejes de Unity,
reorientado para mirar hacia +z y escalado a 2.8 m. El resultado es
`unity/Assets/Resources/Personaje/atst.json`, que lleva la misma
atribución en `info.atribucion`; la app la muestra en la pestaña Persona.

El AT-ST es un diseño de Star Wars (Lucasfilm). Esto es un modelo hecho
por un fan y se usa en un trabajo de curso, sin fines comerciales.

Se descartaron otros dos que se encontraron:
- "Star Wars AT-ST-2" (Free3D 99916): su licencia es "personal use or
  education", y solo se pudo leer en un espejo, sin confirmarla en la
  fuente.
- Los "AT-ST" de Printables derivados de "SW ATST": su OBJ trae la ruta
  `SWBF3 Model Pack 2\Models\ATST.fbx`, o sea que están extraídos de un
  videojuego.
