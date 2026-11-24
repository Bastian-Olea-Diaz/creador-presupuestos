'use strict';

/* =====================================================================
   Utilidades
   ===================================================================== */
const $ = (selector) => document.querySelector(selector);

/** Crea un elemento: el('div', {class: 'x', onclick: fn}, 'texto', otroElemento) */
function el(etiqueta, atributos = {}, ...hijos) {
  const nodo = document.createElement(etiqueta);
  for (const [clave, valor] of Object.entries(atributos)) {
    if (valor === undefined || valor === null || valor === false) continue;
    if (clave.startsWith('on')) nodo.addEventListener(clave.slice(2), valor);
    else if (clave === 'class') nodo.className = valor;
    else if (clave === 'value') nodo.value = valor;
    else nodo.setAttribute(clave, valor === true ? '' : valor);
  }
  for (const hijo of hijos.flat()) {
    if (hijo !== null && hijo !== undefined) nodo.append(hijo);
  }
  return nodo;
}

const miles = (n) => String(Math.round(n || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
const pesos = (n) => '$' + miles(n);

/** "3.190", "$3190", "3190,50" → 3190 */
function leerPesos(texto) {
  const digitos = String(texto ?? '').split(',')[0].replace(/\D/g, '');
  return digitos ? parseInt(digitos, 10) : 0;
}

/** "2", "1,5", "1.5", "1.000" → número */
function leerCantidad(texto) {
  let s = String(texto ?? '').trim().replace(/\s/g, '');
  if (!s) return 0;
  if (s.includes(',')) s = s.replace(/\./g, '').replace(',', '.');
  else if (/^\d{1,3}(\.\d{3})+$/.test(s)) s = s.replace(/\./g, '');
  const n = parseFloat(s.replace(/[^\d.]/g, ''));
  return Number.isFinite(n) && n > 0 ? Math.round(n * 1000) / 1000 : 0;
}

function mostrarCantidad(n) {
  if (!n) return '';
  const [entero, decimales] = String(n).split('.');
  return miles(parseInt(entero, 10)) + (decimales ? ',' + decimales : '');
}

function fechaHoy() {
  const d = new Date();
  const dos = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${dos(d.getMonth() + 1)}-${dos(d.getDate())}`;
}

function fechaBonita(iso) {
  const [a, m, d] = String(iso || '').split('-').map(Number);
  if (!a || !m || !d) return iso || '';
  return new Date(a, m - 1, d).toLocaleDateString('es-CL', { day: 'numeric', month: 'long', year: 'numeric' });
}

const sinTildes = (s) => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();

let contadorUid = 0;
const nuevoUid = () => 'f' + (++contadorUid);

/* =====================================================================
   Comunicación con el programa
   ===================================================================== */
async function api(metodo, url, cuerpo) {
  let respuesta;
  try {
    respuesta = await fetch(url, {
      method: metodo,
      headers: cuerpo ? { 'Content-Type': 'application/json' } : {},
      body: cuerpo ? JSON.stringify(cuerpo) : undefined,
    });
  } catch {
    throw new Error('No se pudo conectar con el programa. Cierre esta pestaña y vuelva a abrirlo ' +
                    'con doble clic en «Iniciar Creador de presupuestos».');
  }
  let datos = {};
  try { datos = await respuesta.json(); } catch { /* respuesta vacía */ }
  if (!respuesta.ok) throw new Error(datos.error || 'Ocurrió un problema inesperado. Intente de nuevo.');
  return datos;
}

/* =====================================================================
   Mensajes (avisos que aparecen abajo)
   ===================================================================== */
function aviso(texto, tipo = 'info', { accion, alHacer, duracion } = {}) {
  const contenedor = $('#avisos');
  while (contenedor.children.length >= 3) contenedor.firstElementChild.remove();
  const iconos = { exito: '✓', error: '⚠', info: 'ℹ' };
  const cerrar = () => nodo.remove();
  const nodo = el('div', { class: `aviso ${tipo}`, role: tipo === 'error' ? 'alert' : 'status' },
    el('span', { class: 'aviso-icono', 'aria-hidden': 'true' }, iconos[tipo] || ''),
    el('span', { class: 'aviso-texto' }, texto),
    accion && el('button', { type: 'button', class: 'boton', onclick: () => { cerrar(); alHacer(); } }, accion),
    el('button', { type: 'button', class: 'aviso-cerrar', 'aria-label': 'Cerrar mensaje', onclick: cerrar }, '×'),
  );
  contenedor.append(nodo);
  setTimeout(cerrar, duracion || (tipo === 'error' ? 12000 : accion ? 9000 : 6000));
}

/* =====================================================================
   Ventana de confirmación
   botones: [{texto, valor, clase}] — el último es la opción destacada
   ===================================================================== */
function preguntar({ titulo, texto, botones, enfocar }) {
  return new Promise((resolver) => {
    const fondo = $('#modal');
    const contenedor = $('#modal-botones');
    const anterior = document.activeElement;
    $('#modal-titulo').textContent = titulo;
    $('#modal-texto').textContent = texto;
    contenedor.innerHTML = '';

    const terminar = (valor) => {
      fondo.hidden = true;
      document.removeEventListener('keydown', teclas, true);
      if (anterior && anterior.focus) anterior.focus();
      resolver(valor);
    };
    const teclas = (e) => {
      if (e.key === 'Escape') { e.preventDefault(); terminar(null); }
    };

    const nodos = botones.map((b) =>
      el('button', { type: 'button', class: `boton ${b.clase || 'boton-secundario'}`, onclick: () => terminar(b.valor) }, b.texto));
    contenedor.append(...nodos);
    fondo.onclick = (e) => { if (e.target === fondo) terminar(null); };
    document.addEventListener('keydown', teclas, true);
    fondo.hidden = false;
    nodos[enfocar ?? nodos.length - 1].focus();
  });
}

/* =====================================================================
   Navegación entre pantallas
   ===================================================================== */
let vista = null;
let hashActual = location.hash;
let ignorarCambioHash = false;

function rutear() {
  const h = location.hash;
  if (h.startsWith('#/presupuesto/')) abrirEditor(decodeURIComponent(h.slice('#/presupuesto/'.length)));
  else if (h === '#/nuevo') abrirEditor(null);
  else mostrarInicio();
}

function irA(hash) {
  hashActual = hash;
  if (location.hash !== hash) {
    ignorarCambioHash = true;
    location.hash = hash;
  }
  rutear();
}

window.addEventListener('hashchange', async () => {
  if (ignorarCambioHash) { ignorarCambioHash = false; return; }
  const destino = location.hash;
  if (vista === 'editor' && hayCambios()) {
    // Botón «atrás» del navegador con cambios sin guardar: primero preguntar.
    ignorarCambioHash = true;
    location.hash = hashActual;
    if (await confirmarSalida()) irA(destino);
    return;
  }
  hashActual = destino;
  rutear();
});

window.addEventListener('beforeunload', (e) => {
  if (vista === 'editor' && hayCambios()) { e.preventDefault(); e.returnValue = ''; }
});

function mostrarVista(nombre) {
  // Los mensajes de error de una pantalla no tienen sentido en la otra.
  if (vista !== nombre) document.querySelectorAll('.aviso.error').forEach((n) => n.remove());
  vista = nombre;
  $('#vista-inicio').hidden = nombre !== 'inicio';
  $('#vista-editor').hidden = nombre !== 'editor';
  window.scrollTo(0, 0);
}

/* =====================================================================
   Pantalla principal
   ===================================================================== */
let lista = [];

async function mostrarInicio() {
  mostrarVista('inicio');
  document.title = 'Creador de presupuestos';
  const cuadricula = $('#cuadricula');
  cuadricula.replaceChildren(el('p', { class: 'cargando' }, 'Cargando sus presupuestos…'));
  try {
    lista = (await api('GET', '/api/presupuestos')).presupuestos;
  } catch (e) {
    lista = [];
    aviso(e.message, 'error');
  }
  $('#buscador').hidden = lista.length < 2;
  dibujarLista();
}

function dibujarLista() {
  const busqueda = sinTildes($('#buscar').value.trim());
  const visibles = busqueda
    ? lista.filter((p) => sinTildes(`${p.cliente} ${p.proyecto}`).includes(busqueda))
    : lista;

  const nuevo = el('button', { type: 'button', class: 'cuadro cuadro-nuevo', onclick: () => irA('#/nuevo') },
    el('span', { class: 'mas', 'aria-hidden': 'true' }, '+'),
    el('strong', {}, 'Crear nuevo presupuesto'));

  $('#cuadricula').replaceChildren(nuevo, ...visibles.map(tarjetaPresupuesto));

  const vacio = $('#mensaje-vacio');
  if (!lista.length) {
    vacio.textContent = 'Todavía no tiene presupuestos guardados. Para empezar, haga clic en «Crear nuevo presupuesto».';
    vacio.hidden = false;
  } else if (!visibles.length) {
    vacio.textContent = `No se encontró ningún presupuesto con «${$('#buscar').value.trim()}».`;
    vacio.hidden = false;
  } else {
    vacio.hidden = true;
  }
}

function tarjetaPresupuesto(p) {
  const abrir = () => irA('#/presupuesto/' + encodeURIComponent(p.id));
  return el('article', {
    class: 'cuadro', tabindex: '0', role: 'button',
    'aria-label': `Abrir presupuesto ${p.proyecto}, cliente ${p.cliente}`,
    onclick: abrir,
    onkeydown: (e) => { if (e.key === 'Enter' && e.target === e.currentTarget) abrir(); },
  },
    el('div', { class: 'cuadro-fecha' }, fechaBonita(p.fecha)),
    el('h3', { class: 'cuadro-proyecto', title: p.proyecto }, p.proyecto || 'Sin nombre'),
    el('div', { class: 'cuadro-cliente', title: p.cliente }, 'Cliente: ', el('strong', {}, p.cliente)),
    el('div', { class: 'cuadro-montos' },
      el('div', {}, el('span', {}, `Materiales (${p.cantidad_materiales})`), el('strong', {}, pesos(p.total_materiales))),
      el('div', {}, el('span', {}, 'Mano de obra'), el('strong', {}, pesos(p.mano_de_obra)))),
    el('div', { class: 'cuadro-botones' },
      el('button', { type: 'button', class: 'boton boton-principal', onclick: (e) => { e.stopPropagation(); abrir(); } },
        'Abrir'),
      el('button', {
        type: 'button', class: 'boton boton-eliminar', title: 'Eliminar este presupuesto',
        onclick: (e) => { e.stopPropagation(); eliminarPresupuesto(p); },
      }, 'Eliminar')),
  );
}

async function eliminarPresupuesto(p) {
  const respuesta = await preguntar({
    titulo: '¿Eliminar este presupuesto?',
    texto: `Se quitará «${p.proyecto}» (cliente: ${p.cliente}) de su lista.\n` +
           'Los PDF que ya creó no se borran.',
    botones: [
      { texto: 'No, conservarlo', valor: false },
      { texto: 'Sí, eliminar', valor: true, clase: 'boton-peligro' },
    ],
    enfocar: 0,
  });
  if (!respuesta) return;
  try {
    await api('DELETE', '/api/presupuestos/' + encodeURIComponent(p.id));
    aviso(`Se eliminó el presupuesto «${p.proyecto}».`, 'exito');
    mostrarInicio();
  } catch (e) {
    aviso(e.message, 'error');
  }
}

$('#buscar').addEventListener('input', dibujarLista);
$('#btn-carpeta-pdf').addEventListener('click', () =>
  api('POST', '/api/abrir-carpeta', { carpeta: 'pdf' }).catch((e) => aviso(e.message, 'error')));

/* =====================================================================
   Formulario del presupuesto
   ===================================================================== */
let estado = null;          // datos que se están editando
let guardadoComo = '';      // copia de lo último guardado, para saber si hay cambios
let ocupado = false;
const celdasTotal = new Map();  // uid → celda «Total» de esa fila

const campoCliente = $('#campo-cliente');
const campoFecha = $('#campo-fecha');
const campoProyecto = $('#campo-proyecto');
const campoMano = $('#campo-mano');

function filaVacia(f) {
  return f.tipo === 'titulo' ? !f.texto.trim() : !f.nombre.trim() && !f.precio;
}

function datosParaEnviar() {
  return {
    id: estado.id,
    cliente: estado.cliente.trim(),
    fecha: estado.fecha,
    proyecto: estado.proyecto.trim(),
    filas: estado.filas.filter((f) => !filaVacia(f)).map((f) => f.tipo === 'titulo'
      ? { tipo: 'titulo', texto: f.texto.trim() }
      : { tipo: 'material', nombre: f.nombre.trim(), precio: f.precio, cantidad: f.cantidad }),
    mano_de_obra: estado.mano_de_obra,
  };
}

const huella = () => JSON.stringify(datosParaEnviar());
const hayCambios = () => !!estado && huella() !== guardadoComo;

async function abrirEditor(id) {
  let datos;
  if (id) {
    try {
      datos = await api('GET', '/api/presupuestos/' + encodeURIComponent(id));
    } catch (e) {
      aviso(e.message, 'error');
      irA('#/');
      return;
    }
  } else {
    datos = { fecha: fechaHoy(), filas: [], mano_de_obra: 0 };
  }

  estado = {
    id: datos.id || null,
    cliente: datos.cliente || '',
    fecha: datos.fecha || fechaHoy(),
    proyecto: datos.proyecto || '',
    mano_de_obra: datos.mano_de_obra || 0,
    filas: (datos.filas || []).map((f) => f.tipo === 'titulo'
      ? { uid: nuevoUid(), tipo: 'titulo', texto: f.texto || '' }
      : { uid: nuevoUid(), tipo: 'material', nombre: f.nombre || '', precio: f.precio || 0, cantidad: f.cantidad || 0 }),
  };
  if (!estado.filas.some((f) => f.tipo === 'material')) estado.filas.push(materialNuevo());

  campoCliente.value = estado.cliente;
  campoFecha.value = estado.fecha;
  campoProyecto.value = estado.proyecto;
  campoMano.value = estado.mano_de_obra ? miles(estado.mano_de_obra) : '';
  document.querySelectorAll('.con-error').forEach((n) => n.classList.remove('con-error'));

  // Un presupuesto nuevo cuenta como «sin cambios» hasta que se escriba algo.
  guardadoComo = huella();
  mostrarVista('editor');
  dibujarFilas();
  actualizarEncabezado();
  if (!id) campoCliente.focus();
}

function materialNuevo() {
  return { uid: nuevoUid(), tipo: 'material', nombre: '', precio: 0, cantidad: 1 };
}

function actualizarEncabezado() {
  const titulo = estado.id ? (estado.proyecto.trim() || 'Presupuesto sin nombre') : 'Nuevo presupuesto';
  $('#titulo-editor').textContent = titulo;
  document.title = `${titulo} · Creador de presupuestos`;
  const marca = $('#estado-guardado');
  if (hayCambios()) {
    marca.textContent = '● Hay cambios sin guardar';
    marca.className = 'estado-guardado sin-guardar';
  } else if (estado.id) {
    marca.textContent = '✓ Todo está guardado';
    marca.className = 'estado-guardado guardado';
  } else {
    marca.textContent = '';
    marca.className = 'estado-guardado';
  }
}

function recalcular() {
  let total = 0;
  for (const f of estado.filas) {
    if (f.tipo !== 'material') continue;
    const subtotal = Math.round(f.precio * f.cantidad);
    total += subtotal;
    const celda = celdasTotal.get(f.uid);
    if (celda) celda.textContent = pesos(subtotal);
  }
  $('#total-materiales').textContent = pesos(total);
  actualizarEncabezado();
}

/* --------------------------------------------------- tabla de materiales */
function dibujarFilas() {
  const cuerpo = $('#filas');
  celdasTotal.clear();
  let numero = 0;
  const ultima = estado.filas.length - 1;

  const filas = estado.filas.map((f, i) => {
    const acciones = el('td', {},
      el('div', { class: 'acciones-fila' },
        el('button', { type: 'button', class: 'boton-icono', title: 'Subir esta fila', 'aria-label': 'Subir esta fila',
          disabled: i === 0, onclick: () => moverFila(i, -1) }, '↑'),
        el('button', { type: 'button', class: 'boton-icono', title: 'Bajar esta fila', 'aria-label': 'Bajar esta fila',
          disabled: i === ultima, onclick: () => moverFila(i, 1) }, '↓'),
        el('button', { type: 'button', class: 'boton-icono quitar', title: 'Quitar esta fila', 'aria-label': 'Quitar esta fila',
          onclick: () => quitarFila(i) }, '✕')));

    if (f.tipo === 'titulo') {
      return el('tr', { class: 'fila-titulo', 'data-uid': f.uid },
        el('td', { class: 'num' }),
        el('td', { colspan: '4' },
          el('input', {
            type: 'text', class: 'entrada-nombre', value: f.texto, autocomplete: 'off',
            placeholder: 'Escriba el subtítulo (por ejemplo: Baño, Cocina, Llave de jardín…)',
            'aria-label': 'Subtítulo',
            oninput: (e) => { f.texto = e.target.value; actualizarEncabezado(); },
            onkeydown: (e) => alPresionarEnter(e, i),
          })),
        acciones);
    }

    numero += 1;
    const total = el('td', { class: 'total' }, pesos(Math.round(f.precio * f.cantidad)));
    celdasTotal.set(f.uid, total);
    return el('tr', { 'data-uid': f.uid },
      el('td', { class: 'num' }, String(numero)),
      el('td', {},
        el('input', {
          type: 'text', class: 'entrada-nombre', value: f.nombre, autocomplete: 'off',
          placeholder: 'Por ejemplo: Codo de cobre ½"', 'aria-label': `Nombre del material ${numero}`,
          oninput: (e) => { f.nombre = e.target.value; e.target.classList.remove('con-error'); actualizarEncabezado(); },
          onkeydown: (e) => alPresionarEnter(e, i),
        })),
      el('td', {},
        el('span', { class: 'entrada-pesos' },
          el('span', { class: 'signo', 'aria-hidden': 'true' }, '$'),
          el('input', {
            type: 'text', class: 'numero', inputmode: 'numeric', placeholder: '0', autocomplete: 'off',
            value: f.precio ? miles(f.precio) : '', 'aria-label': `Precio unitario del material ${numero}`,
            oninput: (e) => { f.precio = leerPesos(e.target.value); recalcular(); },
            onblur: (e) => { e.target.value = f.precio ? miles(f.precio) : ''; },
            onkeydown: (e) => alPresionarEnter(e, i),
          }))),
      el('td', {},
        el('input', {
          type: 'text', class: 'cantidad', inputmode: 'decimal', placeholder: '0', autocomplete: 'off',
          value: mostrarCantidad(f.cantidad), 'aria-label': `Cantidad del material ${numero}`,
          oninput: (e) => { f.cantidad = leerCantidad(e.target.value); recalcular(); },
          onblur: (e) => { e.target.value = mostrarCantidad(f.cantidad); },
          onkeydown: (e) => alPresionarEnter(e, i),
        })),
      total,
      acciones);
  });

  if (!filas.length) {
    filas.push(el('tr', {}, el('td', { colspan: '6', class: 'cargando', style: 'text-align:center;padding:18px' },
      'No hay materiales. Use el botón «Agregar otro material».')));
  }
  cuerpo.replaceChildren(...filas);
  recalcular();
}

/** Enter: pasa a la fila siguiente; en la última fila, agrega un material nuevo. */
function alPresionarEnter(e, i) {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  if (i === estado.filas.length - 1) agregarMaterial();
  else enfocarFila(i + 1);
}

function enfocarFila(i) {
  const fila = estado.filas[i];
  const entrada = fila && document.querySelector(`tr[data-uid="${fila.uid}"] .entrada-nombre`);
  if (entrada) { entrada.focus(); entrada.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
}

function agregarMaterial() {
  estado.filas.push(materialNuevo());
  dibujarFilas();
  enfocarFila(estado.filas.length - 1);
}

function agregarTitulo() {
  estado.filas.push({ uid: nuevoUid(), tipo: 'titulo', texto: '' });
  dibujarFilas();
  enfocarFila(estado.filas.length - 1);
}

function quitarFila(i) {
  const [quitada] = estado.filas.splice(i, 1);
  dibujarFilas();
  if (filaVacia(quitada)) return;
  const nombre = quitada.tipo === 'titulo' ? `el subtítulo «${quitada.texto}»` : `el material «${quitada.nombre || 'sin nombre'}»`;
  aviso(`Se quitó ${nombre}.`, 'info', {
    accion: 'Deshacer',
    alHacer: () => {
      if (!estado) return;
      estado.filas.splice(Math.min(i, estado.filas.length), 0, quitada);
      dibujarFilas();
    },
  });
}

function moverFila(i, direccion) {
  const j = i + direccion;
  if (j < 0 || j >= estado.filas.length) return;
  [estado.filas[i], estado.filas[j]] = [estado.filas[j], estado.filas[i]];
  dibujarFilas();
  const boton = document.querySelector(`tr[data-uid="${estado.filas[j].uid}"] .boton-icono:nth-child(${direccion < 0 ? 1 : 2})`);
  if (boton && !boton.disabled) boton.focus();
}

$('#btn-agregar-material').addEventListener('click', agregarMaterial);
$('#btn-agregar-titulo').addEventListener('click', agregarTitulo);

campoCliente.addEventListener('input', () => { estado.cliente = campoCliente.value; campoCliente.classList.remove('con-error'); actualizarEncabezado(); });
campoProyecto.addEventListener('input', () => { estado.proyecto = campoProyecto.value; campoProyecto.classList.remove('con-error'); actualizarEncabezado(); });
campoFecha.addEventListener('change', () => { estado.fecha = campoFecha.value || fechaHoy(); actualizarEncabezado(); });
campoFecha.addEventListener('blur', () => { if (!campoFecha.value) campoFecha.value = estado.fecha; });
campoMano.addEventListener('input', () => { estado.mano_de_obra = leerPesos(campoMano.value); actualizarEncabezado(); });
campoMano.addEventListener('blur', () => { campoMano.value = estado.mano_de_obra ? miles(estado.mano_de_obra) : ''; });

/* --------------------------------------------------- revisar antes de guardar */
function marcarError(campo, mensaje) {
  campo.classList.add('con-error');
  campo.scrollIntoView({ block: 'center', behavior: 'smooth' });
  campo.focus({ preventScroll: true });
  aviso(mensaje, 'error');
  return false;
}

function revisar() {
  if (!estado.cliente.trim()) return marcarError(campoCliente, 'Falta escribir el nombre del cliente.');
  if (!estado.proyecto.trim()) return marcarError(campoProyecto, 'Falta escribir el nombre del proyecto o trabajo.');
  let numero = 0;
  for (const f of estado.filas) {
    if (f.tipo !== 'material') continue;
    numero += 1;
    if (!f.nombre.trim() && f.precio) {
      const entrada = document.querySelector(`tr[data-uid="${f.uid}"] .entrada-nombre`);
      return marcarError(entrada, `El material n.º ${numero} tiene precio pero no tiene nombre. Escriba el nombre o quite esa fila.`);
    }
  }
  return true;
}

/* --------------------------------------------------- guardar y crear PDF */
function marcarOcupado(si, texto) {
  ocupado = si;
  for (const id of ['#btn-guardar', '#btn-pdf', '#btn-guardar-pdf']) $(id).disabled = si;
  document.body.style.cursor = si ? 'progress' : '';
  if (si && texto) aviso(texto, 'info', { duracion: 2500 });
}

async function guardar({ silencioso = false } = {}) {
  if (!revisar()) return false;
  try {
    const guardado = await api('POST', '/api/presupuestos', datosParaEnviar());
    const eraNuevo = !estado.id;
    estado.id = guardado.id;
    guardadoComo = huella();
    hashActual = '#/presupuesto/' + encodeURIComponent(guardado.id);
    history.replaceState(null, '', hashActual);
    actualizarEncabezado();
    if (!silencioso) {
      aviso(eraNuevo
        ? 'Presupuesto guardado. Lo encontrará en la pantalla principal.'
        : 'Cambios guardados.', 'exito');
    }
    return true;
  } catch (e) {
    aviso(e.message, 'error');
    return false;
  }
}

async function crearPdf(cuerpo) {
  const resultado = await api('POST', '/api/pdf', cuerpo);
  const donde = 'Está en la carpeta «Presupuestos en PDF».';
  aviso(resultado.abierto
    ? `PDF creado y abierto. ${donde}`
    : `PDF creado: ${resultado.archivo}. ${donde}`, 'exito', {
    accion: 'Mostrar en la carpeta',
    alHacer: () => api('POST', '/api/abrir-carpeta', { carpeta: 'pdf', seleccionar: resultado.archivo })
      .catch((e) => aviso(e.message, 'error')),
    duracion: 12000,
  });
}

async function accionGuardar() {
  if (ocupado) return;
  marcarOcupado(true);
  await guardar();
  marcarOcupado(false);
}

async function accionGuardarYPdf() {
  if (ocupado) return;
  marcarOcupado(true);
  try {
    if (await guardar({ silencioso: true })) {
      aviso('Presupuesto guardado. Creando el PDF…', 'exito', { duracion: 3000 });
      await crearPdf({ id: estado.id });
    }
  } catch (e) {
    aviso(e.message, 'error');
  } finally {
    marcarOcupado(false);
  }
}

async function accionPdf() {
  if (ocupado || !revisar()) return;
  if (hayCambios()) {
    const opcion = await preguntar({
      titulo: estado.id ? 'Hay cambios sin guardar' : 'Este presupuesto todavía no está guardado',
      texto: 'El PDF se creará con lo que ve en pantalla.\n¿Quiere guardar también el presupuesto para poder abrirlo después?',
      botones: [
        { texto: 'Cancelar', valor: null },
        { texto: 'Crear PDF sin guardar', valor: 'solo-pdf' },
        { texto: 'Guardar y crear PDF', valor: 'ambos', clase: 'boton-principal' },
      ],
    });
    if (!opcion) return;
    if (opcion === 'ambos') return accionGuardarYPdf();
  }
  marcarOcupado(true, 'Creando el PDF…');
  try {
    // Si no hay cambios, el PDF se crea exactamente desde el archivo guardado.
    await crearPdf(hayCambios() || !estado.id ? { datos: datosParaEnviar() } : { id: estado.id });
  } catch (e) {
    aviso(e.message, 'error');
  } finally {
    marcarOcupado(false);
  }
}

$('#btn-guardar').addEventListener('click', accionGuardar);
$('#btn-pdf').addEventListener('click', accionPdf);
$('#btn-guardar-pdf').addEventListener('click', accionGuardarYPdf);

document.addEventListener('keydown', (e) => {
  if (vista === 'editor' && (e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') {
    e.preventDefault();
    accionGuardar();
  }
});

/* --------------------------------------------------- salir del formulario */
async function confirmarSalida() {
  if (!hayCambios()) return true;
  const opcion = await preguntar({
    titulo: '¿Salir sin guardar?',
    texto: 'Hay cambios en este presupuesto que todavía no se guardaron. Si sale ahora, se perderán.',
    botones: [
      { texto: 'Seguir editando', valor: null },
      { texto: 'Salir sin guardar', valor: 'descartar', clase: 'boton-peligro' },
      { texto: 'Guardar y salir', valor: 'guardar', clase: 'boton-principal' },
    ],
  });
  if (opcion === 'descartar') { guardadoComo = huella(); return true; }
  if (opcion === 'guardar') return guardar();
  return false;
}

$('#btn-volver').addEventListener('click', async () => {
  if (await confirmarSalida()) irA('#/');
});

/* =====================================================================
   Inicio
   ===================================================================== */
rutear();
