// ================================================================
//  semana06_lab/web/ar.js  —  LA APP DE REALIDAD AUMENTADA
// ================================================================
//  Lo que corre en el TELEFONO. No calcula nada estructural: todos los
//  numeros (esfuerzos, desplazamientos, P-M, demandas) vienen de
//  datos/ar.json, que escribio Python con los resultados de OpenSees
//  (semana06_lab/exportar_ar.py). Aca solo se:
//
//    1. inicia la sesion AR (camara) y se busca la imagen de referencia
//       (MindAR: image tracking con targets.mind);
//    2. toma la POSE de la imagen respecto de la camara (matriz del anchor);
//    3. TRANSFORMA las coordenadas del modelo, en metros de OpenSees, al
//       sistema del anchor (matrizModeloAAnchor): una rotacion, una
//       traslacion y una escala, las tres sacadas del JSON;
//    4. dibuja el sector con los MISMOS tags de OpenSees y sus resultados.
//
//  CADENA DE COORDENADAS (la explicacion completa en ../COORDENADAS.md)
//    OpenSees  x, y horizontales, z arriba, metros, sistema derecho.
//    marcador  x = derecha de la imagen, y = arriba de la imagen, z = sale
//              de la imagen hacia quien la mira; origen en su centro; m.
//              q = R^T (p - c), R = [ejes.x ejes.y ejes.z] (en OpenSees).
//    anchor    lo mismo en "anchos de imagen": a = q * escala / ancho_m.
//              MindAR pone el anchor en el centro de la imagen, con x, y en
//              el plano de la imagen y 1 unidad = el ancho de la imagen.
//    camara    la matriz del anchor (pose) la estima MindAR en cada cuadro.
// ================================================================
import * as THREE from 'three';
import { MindARThree } from './vendor/mindar/mindar-image-three.prod.js';

const Q = new URLSearchParams(location.search);
const PRUEBA = Q.get('prueba') === '1';
const log = (etiqueta, obj) => console.log(etiqueta + ' ' + JSON.stringify(obj));

const D = await (await fetch('datos/ar.json', { cache: 'no-store' })).json();
const NODOS = new Map(D.nodos.map(n => [n.id, n]));
const ELEM = new Map(D.elementos.map(e => [e.id, e]));
const CASOS = new Map(D.casos.map(c => [c.nombre, c]));

// ---------------------------------------------------------------
// 3. LA TRANSFORMACION  modelo (OpenSees, m)  ->  anchor (anchos de imagen)
// ---------------------------------------------------------------
//  M = S(k) · R^T · T(-c),  k = escala / ancho_m
//  Filas de R^T = los ejes del marcador expresados en OpenSees.
export function matrizModeloAAnchor(pose, escala, anchoM) {
  const k = escala / anchoM;
  const { x: ex, y: ey, z: ez } = pose.ejes;
  const c = pose.centro;
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  return new THREE.Matrix4().set(
    k * ex[0], k * ex[1], k * ex[2], -k * dot(ex, c),
    k * ey[0], k * ey[1], k * ey[2], -k * dot(ey, c),
    k * ez[0], k * ez[1], k * ez[2], -k * dot(ez, c),
    0, 0, 0, 1);
}
const poseDe = (modo) => (modo === 'maqueta' ? D.marcador.maqueta : D.marcador);

// ---------------------------------------------------------------
// ESTADO
// ---------------------------------------------------------------
const estado = {
  modo: Q.get('modo') || D.info.modo_por_defecto || 'maqueta',
  caso: D.info.caso_por_defecto && CASOS.has(D.info.caso_por_defecto) ? D.info.caso_por_defecto : D.casos[0].nombre,
  magnitud: 'Mz',
  seleccion: D.objetivo,
  deformada: false,
  tributarias: false,
  etiquetas: true,
};

// ---------------------------------------------------------------
// 4. EL MODELO, EN METROS DE OPENSEES (el grupo lleva la matriz M)
// ---------------------------------------------------------------
const COLOR = { objetivo: 0xc8641e, columna: 0x9aa4b2, viga: 0x6f8fb8, muro: 0x2e7d4f, sel: 0x00d0ff };
const modelo = new THREE.Group();
modelo.matrixAutoUpdate = false;
const capas = { barras: new THREE.Group(), diagramas: new THREE.Group(), deformada: new THREE.Group(),
                tributarias: new THREE.Group(), etiquetas: new THREE.Group() };
Object.values(capas).forEach(g => modelo.add(g));
const mallas = [];

const v3 = (a) => new THREE.Vector3(a[0], a[1], a[2]);
const pos = (id) => { const n = NODOS.get(id); return new THREE.Vector3(n.x, n.y, n.z); };

function ejes(e) {
  const a = pos(e.n1), b = pos(e.n2);
  const X = new THREE.Vector3().subVectors(b, a);
  const L = X.length(); X.normalize();
  let Y = e.localY ? v3(e.localY) : new THREE.Vector3(0, 0, 1);
  let Z = e.localZ ? v3(e.localZ) : new THREE.Vector3().crossVectors(X, Y);
  if (Math.abs(X.dot(Y)) > 1e-3 || Math.abs(X.dot(Z)) > 1e-3) {       // por si acaso: base ortonormal
    Z = new THREE.Vector3().crossVectors(X, Math.abs(X.z) > 0.9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 0, 1)).normalize();
    Y = new THREE.Vector3().crossVectors(Z, X).normalize();
  }
  return { a, b, X, Y, Z, L };
}

function colorDe(e) {
  if (e.id === D.objetivo) return COLOR.objetivo;
  if (e.tipo.startsWith('viga')) return COLOR.viga;
  if (e.tipo === 'muro') return COLOR.muro;
  return COLOR.columna;
}

function construirBarras() {
  for (const e of D.elementos) {
    const { a, b, X, Y, Z, L } = ejes(e);
    // Caja de L x b x h: h a lo largo del eje local z (en una viga, el
    // alto), b del y. La misma convencion que usa exportar_ar.py.
    const geo = new THREE.BoxGeometry(L, e.b || 0.3, e.h || 0.3);
    const mat = new THREE.MeshBasicMaterial({ color: colorDe(e), transparent: true,
      opacity: e.id === D.objetivo ? 0.75 : 0.35, depthWrite: false });
    const malla = new THREE.Mesh(geo, mat);
    malla.matrixAutoUpdate = false;
    malla.matrix.makeBasis(X, Y, Z).setPosition(new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5));
    malla.userData.id = e.id;
    const bordes = new THREE.LineSegments(new THREE.EdgesGeometry(geo),
      new THREE.LineBasicMaterial({ color: e.id === D.objetivo ? 0xffb070 : 0xffffff }));
    malla.add(bordes);
    capas.barras.add(malla);
    mallas.push(malla);
  }
}

// Diagramas: la convencion de dibujo del anexo (info.convencion):
// My en +My*z_local, Mz en -Mz*y_local, Vz en +z, Vy en +y, N y T en +z.
const DIRECCION = { My: ['Z', 1], Mz: ['Y', -1], Vz: ['Z', 1], Vy: ['Y', 1], N: ['Z', 1], T: ['Z', 1] };
const ALTO_DIAGRAMA_M = 0.9;

function construirDiagramas() {
  capas.diagramas.clear();
  const mag = estado.magnitud;
  if (!mag) return;
  const caso = CASOS.get(estado.caso);
  let maximo = 0;
  for (const s of Object.values(caso.esfuerzos)) for (const v of s[mag]) maximo = Math.max(maximo, Math.abs(v));
  if (maximo < 1e-9) return;
  const k = ALTO_DIAGRAMA_M / maximo;              // solo para dibujar: el valor sale en el panel
  const [eje, signo] = DIRECCION[mag];
  for (const e of D.elementos) {
    const s = caso.esfuerzos[e.id];
    if (!s) continue;
    const ej = ejes(e);
    const dir = ej[eje].clone().multiplyScalar(signo * k);
    const base = [], punta = [];
    s.x.forEach((x, i) => {
      const p = ej.a.clone().addScaledVector(ej.X, x);
      base.push(p);
      punta.push(p.clone().addScaledVector(dir, s[mag][i]));
    });
    const vert = [];
    for (let i = 0; i + 1 < base.length; i++) {
      vert.push(...base[i].toArray(), ...punta[i].toArray(), ...punta[i + 1].toArray(),
                ...base[i].toArray(), ...punta[i + 1].toArray(), ...base[i + 1].toArray());
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(vert, 3));
    const color = e.id === estado.seleccion ? 0xff3b30 : 0xe0492f;
    capas.diagramas.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide,
      transparent: true, opacity: e.id === estado.seleccion ? 0.8 : 0.45, depthWrite: false })));
    capas.diagramas.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(punta),
      new THREE.LineBasicMaterial({ color: 0xffffff })));
  }
}

function construirDeformada() {
  capas.deformada.clear();
  if (!estado.deformada) return;
  const caso = CASOS.get(estado.caso);
  const f = D.info.escala_deformada || 50;           // la que calculo Python para todo el modelo
  const desplazado = (id) => {
    const u = caso.desplazamientos[id] || [0, 0, 0];
    return pos(id).add(new THREE.Vector3(u[0], u[1], u[2]).multiplyScalar(f));
  };
  for (const e of D.elementos) {
    capas.deformada.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([desplazado(e.n1), desplazado(e.n2)]),
      new THREE.LineBasicMaterial({ color: 0xffe14d })));
  }
}

function construirTributarias() {
  capas.tributarias.clear();
  if (!estado.tributarias) return;
  for (const t of D.tributarias) {
    const sel = t.elemento === estado.seleccion;
    // Los vertices vienen de todos los poligonos seguidos; 'tamanos' dice cuantos tiene cada uno.
    let i0 = 0;
    for (const n of (t.tamanos || [t.vertices.length])) {
      const pts = t.vertices.slice(i0, i0 + n).map(v => new THREE.Vector2(v.x, v.y));
      i0 += n;
      const tris = THREE.ShapeUtils.triangulateShape(pts, []);
      const vert = [];
      for (const tri of tris) for (const j of tri) vert.push(pts[j].x, pts[j].y, t.z + 0.02);
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.Float32BufferAttribute(vert, 3));
      capas.tributarias.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: sel ? 0x33ff88 : 0x2e7d4f,
        transparent: true, opacity: sel ? 0.55 : 0.22, side: THREE.DoubleSide, depthWrite: false })));
    }
  }
}

function etiqueta(texto, alto, color = '#ffffff', fondo = 'rgba(0,0,0,0.65)') {
  const cv = document.createElement('canvas');
  const ctx = cv.getContext('2d');
  ctx.font = 'bold 44px system-ui, sans-serif';
  cv.width = Math.ceil(ctx.measureText(texto).width) + 28; cv.height = 64;
  ctx.font = 'bold 44px system-ui, sans-serif';
  ctx.fillStyle = fondo; ctx.fillRect(0, 0, cv.width, cv.height);
  ctx.fillStyle = color; ctx.textBaseline = 'middle'; ctx.fillText(texto, 14, 34);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(cv), depthTest: false }));
  sp.scale.set(alto * cv.width / cv.height, alto, 1);
  return sp;
}

function construirEtiquetas() {
  capas.etiquetas.clear();
  if (!estado.etiquetas) return;
  // Alto de la etiqueta en m de OpenSees: 0.30 m a 1:50 son 6 mm sobre la
  // mesa; en sitio, 0.12 m. Grande solo la del elemento del marcador y la
  // del seleccionado; las demas, solo en maqueta.
  const alto = estado.modo === 'maqueta' ? 0.30 : 0.12;
  for (const e of D.elementos) {
    const esObjetivo = e.id === D.objetivo, esSel = e.id === estado.seleccion;
    if (!esObjetivo && !esSel && estado.modo === 'sitio') continue;
    const { a, b, Z } = ejes(e);
    const sp = etiqueta(String(e.id), esObjetivo || esSel ? alto * 2 : alto, esObjetivo ? '#ffb070' : esSel ? '#7fe6ff' : '#ffffff');
    const p = new THREE.Vector3().addVectors(a, b).multiplyScalar(0.5);
    if (e.tipo === 'columna') p.z = Math.max(a.z, b.z) + alto * 1.2;
    else p.addScaledVector(new THREE.Vector3(0, 0, 1), alto * 1.1);
    sp.position.copy(p);
    capas.etiquetas.add(sp);
  }
}

function resaltarSeleccion() {
  for (const m of mallas) {
    const e = ELEM.get(m.userData.id);
    m.material.color.setHex(m.userData.id === estado.seleccion && e.id !== D.objetivo ? COLOR.sel : colorDe(e));
    m.material.opacity = m.userData.id === estado.seleccion || e.id === D.objetivo ? 0.75 : 0.35;
  }
}

function aplicarModo() {
  const esc = D.modos[estado.modo].escala;
  modelo.matrix.copy(matrizModeloAAnchor(poseDe(estado.modo), esc, D.marcador.ancho_m));
  modelo.matrixWorldNeedsUpdate = true;
  construirEtiquetas();
}

function redibujar() {
  construirDiagramas(); construirDeformada(); construirTributarias(); construirEtiquetas();
  resaltarSeleccion(); actualizarPanel();
}

// ---------------------------------------------------------------
// EL PANEL: los numeros, tal como los calculo OpenSees
// ---------------------------------------------------------------
const $ = (id) => document.getElementById(id);
const f1 = (v, d = 1) => (v === undefined || v === null ? '—' : Number(v).toFixed(d));

function actualizarPanel() {
  const e = ELEM.get(estado.seleccion);
  const caso = CASOS.get(estado.caso);
  const s = caso.esfuerzos[e.id];
  $('titulo').textContent = `elementTag ${e.id} · ${e.tipo} ${e.seccion}`;
  const filas = ['N', 'Vy', 'Vz', 'T', 'My', 'Mz'].map(m => {
    const u = m.startsWith('M') || m === 'T' ? 'kN·m' : 'kN';
    return `<tr><td>${m} [${u}]</td><td>${f1(s[m][0])}</td><td>${f1(s[m][s[m].length - 1])}</td></tr>`;
  }).join('');
  const d1 = caso.desplazamientos[e.n1] || [0, 0, 0], d2 = caso.desplazamientos[e.n2] || [0, 0, 0];
  const mm = (u) => `${f1(u[0] * 1000, 2)} / ${f1(u[1] * 1000, 2)} / ${f1(u[2] * 1000, 2)}`;
  let html = `<table><tr><th>${caso.nombre}</th><th>extremo i</th><th>extremo j</th></tr>${filas}
    <tr><td>u<sub>x</sub>/u<sub>y</sub>/u<sub>z</sub> [mm]</td><td>${mm(d1)}</td><td>${mm(d2)}</td></tr></table>`;
  const dem = caso.demandas[e.id];
  if (dem) {
    html += `<table><tr><td>Demanda (extremo ${dem.extremo})</td><td>P ${f1(dem.P)} kN</td><td>M ${f1(dem.M)} kN·m</td></tr>
      <tr><td>Capacidad</td><td>Mn(P) ${f1(dem.Mn)} kN·m</td><td>u = M/Mn ${f1(dem.u, 3)}
      <span class="${dem.pasa ? 'pasa' : 'nopasa'}">${dem.pasa ? 'PASA' : 'NO PASA'}</span></td></tr></table>`;
  }
  const trib = D.tributarias.find(t => t.elemento === e.id);
  if (trib) html += `<table><tr><td>Área tributaria</td><td colspan="2">${f1(trib.area, 2)} m² en z = ${f1(trib.z, 2)} m (${trib.forma})</td></tr></table>`;
  html += `<div class="tag">${e.tag_opensees || ''}</div>`;
  $('datos').innerHTML = html;
  dibujarPM(e, dem);
  $('origen').textContent = `Números de OpenSees (${D.info.resultados_de}); el teléfono solo los dibuja. Modo ${estado.modo}, escala 1:${Math.round(1 / D.modos[estado.modo].escala)}.`;
}

function dibujarPM(e, dem) {
  const cv = $('pm'), ctx = cv.getContext('2d');
  ctx.clearRect(0, 0, cv.width, cv.height);
  const fam = e.familia >= 0 ? D.familias[e.familia] : null;
  cv.style.display = fam ? '' : 'none';
  if (!fam) return;
  const P = fam.P, Mn = fam.Mn;
  const mMax = Math.max(...Mn, dem ? dem.M : 0) * 1.15, pMin = Math.min(...P, dem ? dem.P : 0), pMax = Math.max(...P, dem ? dem.P : 0);
  const X = (m) => 50 + (m / mMax) * (cv.width - 70);
  const Y = (p) => cv.height - 30 - ((p - pMin) / (pMax - pMin)) * (cv.height - 50);
  ctx.strokeStyle = '#999'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(X(0), Y(pMin)); ctx.lineTo(X(0), Y(pMax)); ctx.moveTo(X(0), Y(0)); ctx.lineTo(X(mMax), Y(0)); ctx.stroke();
  ctx.strokeStyle = '#1f3a5f'; ctx.lineWidth = 3; ctx.beginPath();
  P.forEach((p, i) => (i ? ctx.lineTo(X(Mn[i]), Y(p)) : ctx.moveTo(X(Mn[i]), Y(p))));
  ctx.stroke();
  ctx.fillStyle = '#222'; ctx.font = '20px system-ui';
  ctx.fillText('P [kN] (compresión +)', 56, 20);
  ctx.fillText('M [kN·m]', cv.width - 110, cv.height - 8);
  ctx.fillText(`${f1(pMax, 0)}`, 2, Y(pMax) + 6); ctx.fillText(`${f1(pMin, 0)}`, 2, Y(pMin));
  if (dem) {
    ctx.fillStyle = dem.pasa ? '#2e7d4f' : '#d62828';
    ctx.beginPath(); ctx.arc(X(dem.M), Y(dem.P), 9, 0, Math.PI * 2); ctx.fill();
    ctx.fillText(`${estado.caso}: P ${f1(dem.P, 0)}, M ${f1(dem.M, 0)}`, X(dem.M) + 12, Y(dem.P) - 10);
  }
}

// ---------------------------------------------------------------
// CONTROLES
// ---------------------------------------------------------------
for (const c of D.casos) $('caso').add(new Option(`${c.nombre}`, c.nombre));
$('caso').value = estado.caso;
$('caso').onchange = (ev) => { estado.caso = ev.target.value; redibujar(); };
$('magnitud').value = estado.magnitud;
$('magnitud').onchange = (ev) => { estado.magnitud = ev.target.value; construirDiagramas(); };
$('deformada').onchange = (ev) => { estado.deformada = ev.target.checked; construirDeformada(); };
$('tributarias').onchange = (ev) => { estado.tributarias = ev.target.checked; construirTributarias(); };
$('etiquetas').onchange = (ev) => { estado.etiquetas = ev.target.checked; construirEtiquetas(); };
$('plegar').onclick = () => { $('panel').classList.toggle('plegado'); $('plegar').textContent = $('panel').classList.contains('plegado') ? '▴' : '▾'; };
const objetivo = ELEM.get(D.objetivo);
$('resumen').textContent = `${D.info.edificio}: elemento ${objetivo.id} (${objetivo.tipo} ${objetivo.seccion}), ` +
  `${D.elementos.length} elementos del sector, ${D.casos.length} casos de OpenSees.`;

construirBarras();
redibujar();

// ---------------------------------------------------------------
// PRUEBA: la transformacion, para verificar_ar.py (sin camara)
// ---------------------------------------------------------------
if (PRUEBA) {
  const salida = {};
  for (const modo of ['sitio', 'maqueta']) {
    const M = matrizModeloAAnchor(poseDe(modo), D.modos[modo].escala, D.marcador.ancho_m);
    const puntos = {};
    for (const n of D.nodos) puntos[n.id] = new THREE.Vector3(n.x, n.y, n.z).applyMatrix4(M).toArray();
    puntos.centro_marcador = v3(poseDe(modo).centro).applyMatrix4(M).toArray();
    salida[modo] = { matriz: M.elements, puntos };
  }
  log('AR_TRANSFORM', salida);
  log('AR_PANEL', { titulo: $('titulo').textContent, datos: $('datos').innerText });
}

// ---------------------------------------------------------------
// 1-2. SESION AR, IMAGE TRACKING Y POSE
// ---------------------------------------------------------------
async function iniciar(modo) {
  estado.modo = modo;
  $('inicio').hidden = true;
  $('panel').hidden = false;
  aplicarModo();
  actualizarPanel();
  const mindar = new MindARThree({
    container: $('ar'), imageTargetSrc: 'targets.mind', maxTrack: 1,
    uiLoading: 'yes', uiScanning: 'no', uiError: 'yes',
    filterMinCF: 0.0001, filterBeta: 0.001,        // suaviza la pose sin retrasarla mucho
  });
  const { renderer, scene, camera } = mindar;
  const anchor = mindar.addAnchor(0);               // el ANCHOR: el sistema de la imagen
  anchor.group.add(modelo);
  anchor.onTargetFound = () => { $('estado').textContent = 'imagen detectada'; $('estado').className = 'ok'; };
  anchor.onTargetLost = () => { $('estado').textContent = 'buscando la imagen…'; $('estado').className = ''; $('pose').textContent = ''; };

  // Tocar una barra la selecciona.
  const ray = new THREE.Raycaster(), puntero = new THREE.Vector2();
  $('ar').addEventListener('pointerup', (ev) => {
    const r = renderer.domElement.getBoundingClientRect();
    puntero.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(puntero, camera);
    const hit = ray.intersectObjects(mallas, false)[0];
    if (hit) { estado.seleccion = hit.object.userData.id; redibujar(); }
  });

  await mindar.start();
  let ultimo = 0;
  renderer.setAnimationLoop((t) => {
    if (anchor.group.visible) {
      // La pose: la matriz del anchor respecto de la camara, en pixeles de la
      // imagen (su escala es el ancho en pixeles). Pasada a metros:
      const m = anchor.group.matrix, e = m.elements;
      const anchoPx = new THREE.Vector3(e[0], e[1], e[2]).length();
      const t3 = new THREE.Vector3(e[12], e[13], e[14]);
      const dist = t3.length() / anchoPx * D.marcador.ancho_m;
      const normal = new THREE.Vector3(e[8], e[9], e[10]).normalize();
      const giro = THREE.MathUtils.radToDeg(Math.acos(Math.min(1, Math.abs(normal.z))));
      $('pose').textContent = `pose: ${dist.toFixed(2)} m, inclinación ${giro.toFixed(0)}°`;
      if (PRUEBA && t - ultimo > 500) { ultimo = t; log('AR_POSE', { m: Array.from(e), dist_m: dist, giro_deg: giro }); }
    }
    renderer.render(scene, camera);
  });
}

for (const b of document.querySelectorAll('button.modo')) b.onclick = () => iniciar(b.dataset.modo);
if (PRUEBA && Q.get('plegado')) $('plegar').onclick();
if (PRUEBA && Q.get('iniciar')) iniciar(Q.get('iniciar'));
window.AR = { D, estado, matrizModeloAAnchor, iniciar };
