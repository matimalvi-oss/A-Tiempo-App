// static/app.js
let data = { pedidos: [], riders: [], comercios: [], clientes: [] };
let filtroComercio = 'todos';

const ESTADOS_KANBAN = [
    { id: 'pendiente', titulo: 'Pedidos nuevos' },
    { id: 'en_curso', titulo: 'En curso' },
    { id: 'entregado', titulo: 'Entregados' }
];

function getColumnIdForEstado(estado) {
    if (estado === 'pendiente') return 'pendiente';
    if (estado === 'entregado') return 'entregado';
    return 'en_curso'; // Agrupa: asignado, en_camino_comercio, retirado, en_camino_cliente
}

document.addEventListener('DOMContentLoaded', async () => {
    console.log('Iniciando aplicación...');
    try {
        await fetchData();
        renderKanbanColumns();
        renderSidebar();
        setupListeners();
        console.log('Aplicación lista. Botones activos.');
    } catch (error) {
        console.error('Error fatal al iniciar:', error);
    }
});

async function fetchData() {
    try {
        const res = await fetch('/api/dashboard');
        if (!res.ok) throw new Error('Error en la API');
        data = await res.json();
        updateMetrics();
        populateComercioFilter();
    } catch (error) {
        console.error('Error al cargar datos:', error);
    }
}

function updateMetrics() {
    const activos = data.pedidos.filter(p => p.estado !== 'entregado').length;
    const pendientes = data.pedidos.filter(p => p.estado === 'pendiente').length;
    document.getElementById('metric-activos').innerText = activos;
    document.getElementById('metric-pendientes').innerText = pendientes;
}

function populateComercioFilter() {
    const select = document.getElementById('filter-comercio');
    if (!select) return;
    while (select.options.length > 1) select.remove(1);
    data.comercios.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.id;
        opt.innerText = c.nombre;
        select.appendChild(opt);
    });
    
    const formSelect = document.getElementById('form-comercio-pedido');
    if (formSelect) {
        while (formSelect.options.length > 0) formSelect.remove(0);
        data.comercios.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.innerText = c.nombre;
            formSelect.appendChild(opt);
        });
    }
}

function renderKanbanColumns() {
    const board = document.getElementById('kanban-board');
    if (!board) return;
    board.innerHTML = '';

    ESTADOS_KANBAN.forEach(col => {
        // Filtrar pedidos que pertenecen a esta columna agrupada
        let pedidosCol = data.pedidos.filter(p => getColumnIdForEstado(p.estado) === col.id);
        if (filtroComercio !== 'todos') {
            pedidosCol = pedidosCol.filter(p => p.comercio_id == filtroComercio);
        }

        const colEl = document.createElement('div');
        colEl.className = 'kanban-column';
        colEl.innerHTML = `
            <div class="column-header">
                <span class="column-title">${col.titulo}</span>
                <span class="column-count">${pedidosCol.length}</span>
            </div>
            <div class="column-cards"></div>
        `;
        board.appendChild(colEl);

        const cardsContainer = colEl.querySelector('.column-cards');
        pedidosCol.forEach(p => cardsContainer.appendChild(createOrderCard(p)));
    });
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function createOrderCard(pedido) {
    const comercio = data.comercios.find(c => c.id === pedido.comercio_id);
    const cliente = data.clientes.find(c => c.id === pedido.cliente_id);
    const rider = pedido.rider_id ? data.riders.find(r => r.id === pedido.rider_id) : null;

    if (!comercio || !cliente) return document.createElement('div');

    const card = document.createElement('div');
    // CAMBIO 1: Si está entregado, agregamos la clase 'collapsed' por defecto
    card.className = pedido.estado === 'entregado' ? 'order-card collapsed' : 'order-card';
    
    const headerHtml = `
        <div class="card-header" onclick="this.parentElement.classList.toggle('collapsed')">
            <div>
                <span class="comercio-name">${comercio.nombre}</span>
                <span class="card-time" style="margin-left: 8px;">#${pedido.id}</span>
            </div>
            <div style="display: flex; align-items: center; gap: 8px;">
                ${rider ? `<span style="font-size: 0.8rem; color: var(--primary); font-weight: 500;"><i data-lucide="bike" size="14"></i> ${rider.nombre}</span>` : '<span style="font-size: 0.8rem; color: var(--text-muted);">Sin rider</span>'}
                <i data-lucide="chevron-down" class="toggle-icon" size="18"></i>
            </div>
        </div>
    `;

    const ahora = new Date();
    const fechaRetiro = pedido.hora_estimada_retiro ? new Date(pedido.hora_estimada_retiro) : new Date();
    const esDemorado = (pedido.estado === 'pendiente') && ahora > fechaRetiro;
    if (esDemorado) card.classList.add('alerta-demora');

    let actionsHtml = `
        <button class="btn-sm btn-edit" onclick="event.stopPropagation(); window.openEditOrderModal(${pedido.id})">
            <i data-lucide="edit-3" size="14"></i> Editar
        </button>
    `;

    if (pedido.estado === 'pendiente') {
        actionsHtml += `
            <button class="btn-sm btn-primary" onclick="event.stopPropagation(); window.openAssignModal(${pedido.id})">
                <i data-lucide="user-plus" size="14"></i> Asignar
            </button>
        `;
    }

    if (pedido.estado !== 'pendiente' && pedido.estado !== 'entregado') {
        actionsHtml += `
            <button class="btn-sm btn-success" onclick="event.stopPropagation(); window.updateStatus(${pedido.id}, 'entregado')">
                <i data-lucide="check-circle" size="14"></i> Entregar
            </button>
        `;
    }

    // CAMBIO 2: Agregamos el botón de eliminar a TODAS las tarjetas
    actionsHtml += `
        <button class="btn-sm btn-danger" onclick="event.stopPropagation(); window.deleteOrder(${pedido.id})">
            <i data-lucide="trash-2" size="14"></i> Eliminar
        </button>
    `;
    
    const detailsHtml = `
        <div class="card-section">
            <div class="card-section-title"><i data-lucide="user" size="12"></i> Cliente</div>
            <div class="card-row"><span>${cliente.nombre}</span> <span><a href="tel:${cliente.telefono}">${cliente.telefono}</a></span></div>
        </div>
        <div class="card-section">
            <div class="card-section-title"><i data-lucide="banknote" size="12"></i> Finanzas</div>
            <div class="card-row"><span>A cobrar:</span> <span>$${pedido.monto_a_cobrar}</span></div>
            <div class="card-row"><span>Delivery:</span> <span>$${pedido.costo_delivery}</span></div>
        </div>
        <div class="card-actions">
            ${actionsHtml}
        </div>
    `;

    card.innerHTML = headerHtml + detailsHtml;
    return card;
}

function renderSidebar() {
    const ridersList = document.getElementById('riders-list');
    if (ridersList) {
        ridersList.innerHTML = data.riders.map(r => {
            const pedidosActivos = data.pedidos.filter(p => p.rider_id === r.id && p.estado !== 'entregado').length;
            return `
                <div class="rider-card">
                    <div class="rider-header">
                        <span class="rider-name">${r.nombre}</span>
                        <span class="rider-status status-${r.estado}"></span>
                    </div>
                    <div class="rider-details">${r.vehiculo} | ${pedidosActivos} pedidos activos</div>
                    <div class="rider-actions">
                        <button class="btn-tiny btn-tiny-primary" onclick="window.editRider(${r.id})"><i data-lucide="edit" size="12"></i></button>
                        <button class="btn-tiny btn-tiny-danger" onclick="window.deleteRider(${r.id})"><i data-lucide="trash-2" size="12"></i></button>
                    </div>
                </div>
            `;
        }).join('');
    }

    const comerciosList = document.getElementById('comercios-list');
    if (comerciosList) {
        comerciosList.innerHTML = data.comercios.map(c => {
            const pedidosActivos = data.pedidos.filter(p => p.comercio_id === c.id && p.estado !== 'entregado').length;
            return `
                <div class="comercio-card">
                    <div class="comercio-name">${c.nombre}</div>
                    <div class="comercio-details">${c.direccion} | ${c.telefono}</div>
                    <div class="comercio-details" style="margin-top: 0.25rem;">${pedidosActivos} pedidos activos</div>
                    <div class="comercio-actions">
                        <button class="btn-tiny btn-tiny-primary" onclick="window.editComercio(${c.id})"><i data-lucide="edit" size="12"></i></button>
                        <button class="btn-tiny btn-tiny-danger" onclick="window.deleteComercio(${c.id})"><i data-lucide="trash-2" size="12"></i></button>
                    </div>
                </div>
            `;
        }).join('');
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function setupListeners() {
    const filterSelect = document.getElementById('filter-comercio');
    if (filterSelect) filterSelect.addEventListener('change', (e) => {
        filtroComercio = e.target.value;
        renderKanbanColumns();
    });

    const closeBtns = [
        { id: 'close-modal', modal: 'modal-overlay' },
        { id: 'close-new-order', modal: 'modal-new-order' },
        { id: 'close-comercio', modal: 'modal-comercio' },
        { id: 'close-rider', modal: 'modal-rider' }
    ];
    
    closeBtns.forEach(btn => {
        const el = document.getElementById(btn.id);
        if (el) el.addEventListener('click', () => document.getElementById(btn.modal).classList.remove('active'));
    });

    const btnNewOrder = document.getElementById('btn-new-order');
    if (btnNewOrder) btnNewOrder.addEventListener('click', () => document.getElementById('modal-new-order').classList.add('active'));

    const btnAddComercio = document.getElementById('btn-add-comercio');
    if (btnAddComercio) btnAddComercio.addEventListener('click', () => window.openComercioModal());

    const btnAddRider = document.getElementById('btn-add-rider');
    if (btnAddRider) btnAddRider.addEventListener('click', () => window.openRiderModal());

    const formNewOrder = document.getElementById('form-new-order');
    if (formNewOrder) {
        formNewOrder.addEventListener('submit', async (e) => {
            e.preventDefault();
            const body = {
                comercio_id: parseInt(document.getElementById('form-comercio-pedido').value),
                cliente_nombre: document.getElementById('form-cliente-nombre').value,
                cliente_telefono: document.getElementById('form-cliente-telefono').value,
                direccion_entrega: document.getElementById('form-direccion').value,
                monto_a_cobrar: parseFloat(document.getElementById('form-monto').value) || 0,
                costo_delivery: parseFloat(document.getElementById('form-delivery').value) || 0,
                pagado: document.getElementById('form-pagado').checked
            };
            
            try {
                const res = await fetch('/api/pedidos', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (res.ok) {
                    document.getElementById('modal-new-order').classList.remove('active');
                    formNewOrder.reset();
                    await fetchData();
                    renderKanbanColumns();
                    renderSidebar();
                } else {
                    const err = await res.json();
                    alert(err.detail || 'Error al guardar');
                }
            } catch (error) {
                console.error('Error:', error);
            }
        });
    }

    const formComercio = document.getElementById('form-nuevo-comercio');
    if (formComercio) {
        formComercio.addEventListener('submit', async (e) => {
            e.preventDefault();
            const comercioId = document.getElementById('comercio-id').value;
            const comercioData = {
                nombre: document.getElementById('comercio-nombre').value,
                direccion: document.getElementById('comercio-direccion').value,
                telefono: document.getElementById('comercio-telefono').value
            };
            
            try {
                const url = comercioId ? `/api/comercios/${comercioId}` : '/api/comercios';
                const method = comercioId ? 'PUT' : 'POST';
                
                const res = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(comercioData)
                });
                
                if (res.ok) {
                    document.getElementById('modal-comercio').classList.remove('active');
                    formComercio.reset();
                    document.getElementById('comercio-id').value = '';
                    await fetchData();
                    renderKanbanColumns();
                    renderSidebar();
                } else {
                    const err = await res.json();
                    alert(err.detail || 'Error al guardar');
                }
            } catch (error) {
                console.error('Error:', error);
            }
        });
    }

    const formRider = document.getElementById('form-rider');
    if (formRider) {
        formRider.addEventListener('submit', async (e) => {
            e.preventDefault();
            const riderId = document.getElementById('rider-id').value;
            const riderData = {
                nombre: document.getElementById('rider-nombre').value,
                telefono: document.getElementById('rider-telefono').value,
                vehiculo: document.getElementById('rider-vehiculo').value
            };
            
            try {
                const url = riderId ? `/api/riders/${riderId}` : '/api/riders';
                const method = riderId ? 'PUT' : 'POST';
                
                const res = await fetch(url, {
                    method: method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(riderData)
                });
                
                if (res.ok) {
                    document.getElementById('modal-rider').classList.remove('active');
                    formRider.reset();
                    document.getElementById('rider-id').value = '';
                    await fetchData();
                    renderKanbanColumns();
                    renderSidebar();
                } else {
                    const err = await res.json();
                    alert(err.detail || 'Error al guardar');
                }
            } catch (error) {
                console.error('Error:', error);
            }
        });
    }

    const formEditOrder = document.getElementById('form-edit-order');
    if (formEditOrder) {
        formEditOrder.addEventListener('submit', async (e) => {
            e.preventDefault();
            const pedidoId = document.getElementById('edit-pedido-id-input').value;
            
            const riderSelect = document.getElementById('edit-rider');
            const riderId = riderSelect.value === "" ? null : parseInt(riderSelect.value);

            const body = {
                cliente_nombre: document.getElementById('edit-cliente-nombre').value,
                cliente_telefono: document.getElementById('edit-cliente-telefono').value,
                direccion_entrega: document.getElementById('edit-direccion').value,
                monto_a_cobrar: parseFloat(document.getElementById('edit-monto').value) || 0,
                costo_delivery: parseFloat(document.getElementById('edit-delivery').value) || 0,
                pagado: document.getElementById('edit-pagado').checked,
                estado: document.getElementById('edit-estado').value,
                rider_id: riderId
            };

            try {
                const res = await fetch(`/api/pedidos/${pedidoId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });
                if (res.ok) {
                    document.getElementById('modal-edit-order').classList.remove('active');
                    await fetchData();
                    renderKanbanColumns();
                    renderSidebar();
                } else {
                    const err = await res.json();
                    alert(err.detail || 'Error al actualizar');
                }
            } catch (error) {
                console.error('Error:', error);
            }
        });
    }

    const btnClearDelivered = document.getElementById('btn-clear-delivered');
    if (btnClearDelivered) {
        btnClearDelivered.addEventListener('click', window.deleteAllDelivered);
    }
}

// --- FUNCIONES GLOBALES ---

window.updateStatus = async function(pedidoId, nuevoEstado) {
    try {
        await fetch(`/api/pedidos/${pedidoId}/estado`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nuevo_estado: nuevoEstado })
        });
        await fetchData();
        renderKanbanColumns();
        renderSidebar();
    } catch (error) {
        console.error('Error:', error);
    }
};

window.openAssignModal = function(pedidoId) {
    const disponibles = data.riders.filter(r => r.estado === 'disponible');
    const body = document.getElementById('modal-body');
    body.innerHTML = disponibles.length === 0 
        ? '<p>No hay riders disponibles.</p>'
        : disponibles.map(r => `
            <button class="rider-option" onclick="window.assignRider(${pedidoId}, ${r.id})">
                <strong>${r.nombre}</strong> (${r.vehiculo})
            </button>
        `).join('');
    document.getElementById('modal-overlay').classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
};

window.assignRider = async function(pedidoId, riderId) {
    await fetch(`/api/pedidos/${pedidoId}/asignar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rider_id: riderId })
    });
    document.getElementById('modal-overlay').classList.remove('active');
    await fetchData();
    renderKanbanColumns();
    renderSidebar();
};

window.openEditOrderModal = function(pedidoId) {
    const pedido = data.pedidos.find(p => p.id === pedidoId);
    const cliente = data.clientes.find(c => c.id === pedido.cliente_id);
    if (!pedido || !cliente) return;

    document.getElementById('edit-pedido-id').innerText = pedido.id;
    document.getElementById('edit-pedido-id-input').value = pedido.id;
    document.getElementById('edit-estado').value = pedido.estado;
    document.getElementById('edit-cliente-nombre').value = cliente.nombre;
    document.getElementById('edit-cliente-telefono').value = cliente.telefono;
    document.getElementById('edit-direccion').value = pedido.direccion_entrega;
    document.getElementById('edit-monto').value = pedido.monto_a_cobrar;
    document.getElementById('edit-delivery').value = pedido.costo_delivery;
    document.getElementById('edit-pagado').checked = pedido.pagado;

    // Poblar select de riders
    const riderSelect = document.getElementById('edit-rider');
    riderSelect.innerHTML = '<option value="">-- Sin asignar --</option>';
    data.riders.forEach(r => {
        const opt = document.createElement('option');
        opt.value = r.id;
        opt.innerText = `${r.nombre} (${r.estado})`;
        if (pedido.rider_id === r.id) opt.selected = true;
        riderSelect.appendChild(opt);
    });

    document.getElementById('modal-edit-order').classList.add('active');
    if (typeof lucide !== 'undefined') lucide.createIcons();
};

window.openComercioModal = function(comercio = null) {
    document.getElementById('comercio-modal-title').innerText = comercio ? 'Editar Comercio' : 'Nuevo Comercio';
    document.getElementById('comercio-id').value = comercio ? comercio.id : '';
    document.getElementById('comercio-nombre').value = comercio ? comercio.nombre : '';
    document.getElementById('comercio-direccion').value = comercio ? comercio.direccion : '';
    document.getElementById('comercio-telefono').value = comercio ? comercio.telefono : '';
    document.getElementById('modal-comercio').classList.add('active');
};

window.editComercio = function(comercioId) {
    const comercio = data.comercios.find(c => c.id === comercioId);
    if (comercio) window.openComercioModal(comercio);
};

window.deleteComercio = async function(comercioId) {
    if (!confirm('¿Eliminar comercio?')) return;
    try {
        const res = await fetch(`/api/comercios/${comercioId}`, { method: 'DELETE' });
        if (res.ok) {
            await fetchData();
            renderKanbanColumns();
            renderSidebar();
        } else {
            const err = await res.json();
            alert(err.detail || 'Error al eliminar');
        }
    } catch (error) {
        console.error('Error:', error);
    }
};

window.openRiderModal = function(rider = null) {
    document.getElementById('rider-modal-title').innerText = rider ? 'Editar Rider' : 'Nuevo Rider';
    document.getElementById('rider-id').value = rider ? rider.id : '';
    document.getElementById('rider-nombre').value = rider ? rider.nombre : '';
    document.getElementById('rider-telefono').value = rider ? rider.telefono : '';
    document.getElementById('rider-vehiculo').value = rider ? rider.vehiculo : 'Moto';
    document.getElementById('modal-rider').classList.add('active');
};

window.editRider = function(riderId) {
    const rider = data.riders.find(r => r.id === riderId);
    if (rider) window.openRiderModal(rider);
};

window.deleteRider = async function(riderId) {
    if (!confirm('¿Eliminar rider?')) return;
    try {
        const res = await fetch(`/api/riders/${riderId}`, { method: 'DELETE' });
        if (res.ok) {
            await fetchData();
            renderKanbanColumns();
            renderSidebar();
        } else {
            const err = await res.json();
            alert(err.detail || 'Error al eliminar');
        }
    } catch (error) {
        console.error('Error:', error);
    }
};

window.deleteOrder = async function(pedidoId) {
    if (!confirm('¿Estás seguro de eliminar este pedido permanentemente?')) return;
    try {
        const res = await fetch(`/api/pedidos/${pedidoId}`, { method: 'DELETE' });
        if (res.ok) {
            await fetchData();
            renderKanbanColumns();
            renderSidebar();
        } else {
            const err = await res.json();
            alert(err.detail || 'Error al eliminar');
        }
    } catch (error) {
        console.error('Error:', error);
    }
};

window.deleteAllDelivered = async function() {
    if (!confirm('⚠️ ¿Estás seguro de eliminar TODOS los pedidos entregados?\n\nEsta acción no se puede deshacer.')) return;
    
    try {
        const res = await fetch('/api/pedidos/limpiar-entregados', { 
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' }
        });
        
        console.log('Respuesta del servidor:', res.status);
        
        if (res.ok) {
            await fetchData();
            renderKanbanColumns();
            renderSidebar();
            alert('✅ Pedidos entregados eliminados correctamente');
        } else {
            // Intentar obtener el mensaje de error
            let errorMsg = 'Error al limpiar pedidos';
            try {
                const err = await res.json();
                errorMsg = err.detail || JSON.stringify(err);
            } catch (e) {
                errorMsg = `Error ${res.status}: ${res.statusText}`;
            }
            alert(errorMsg);
        }
    } catch (error) {
        console.error('Error en la petición:', error);
        alert('Error de conexión con el servidor');
    }
};

// ==========================================
// NAVEGACIÓN DE VISTAS Y LIQUIDACIONES
// ==========================================

function mostrarVista(vista) {
    const kanban = document.getElementById('kanban-board');
    const liquidaciones = document.getElementById('vista-liquidaciones');
    const btnPedidos = document.getElementById('btn-vista-pedidos');
    const btnLiquidaciones = document.getElementById('btn-vista-liquidaciones');

    if (vista === 'pedidos') {
        kanban.style.display = 'block';
        liquidaciones.style.display = 'none';
        btnPedidos.style.background = '#3b82f6';
        btnPedidos.style.color = 'white';
        btnLiquidaciones.style.background = 'white';
        btnLiquidaciones.style.color = '#374151';
    } else if (vista === 'liquidaciones') {
        kanban.style.display = 'none';
        liquidaciones.style.display = 'block';
        btnPedidos.style.background = 'white';
        btnPedidos.style.color = '#374151';
        btnLiquidaciones.style.background = '#3b82f6';
        btnLiquidaciones.style.color = 'white';
        
        // Inicializar fechas por defecto (últimos 30 días)
        const hoy = new Date();
        const hace30 = new Date();
        hace30.setDate(hoy.getDate() - 30);
        document.getElementById('liq-hasta').value = hoy.toISOString().split('T')[0];
        document.getElementById('liq-desde').value = hace30.toISOString().split('T')[0];
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function formatearMoneda(valor) {
    return '$ ' + Number(valor || 0).toLocaleString('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

async function cargarResumenLiquidaciones() {
    const desde = document.getElementById('liq-desde').value;
    const hasta = document.getElementById('liq-hasta').value;
    if (!desde || !hasta) { alert('Seleccioná un rango de fechas válido.'); return; }

    const contenedor = document.getElementById('grid-resumen-riders');
    contenedor.innerHTML = '<p style="grid-column: 1 / -1; text-align: center; color: #6b7280; padding: 32px 0;">Cargando datos...</p>';

    try {
        const res = await fetch(`/api/liquidaciones/resumen?desde=${desde}&hasta=${hasta}`);
        const dataLiq = await res.json();
        
        if (!dataLiq.riders || dataLiq.riders.length === 0) {
            contenedor.innerHTML = '<p style="grid-column: 1 / -1; text-align: center; color: #6b7280; padding: 32px 0;">No hay datos para este período.</p>';
            return;
        }

        contenedor.innerHTML = dataLiq.riders.map(r => {
            const saldoColor = r.saldo >= 0 ? '#16a34a' : '#dc2626';
            const saldoBg = r.saldo >= 0 ? '#f0fdf4' : '#fef2f2';
            const saldoBorder = r.saldo >= 0 ? '#bbf7d0' : '#fecaca';
            const saldoLabel = r.saldo >= 0 ? 'A favor del rider' : 'Debe entregar';
            
            return `
                <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <div style="display: flex; align-items: center; margin-bottom: 12px;">
                        <div style="width: 40px; height: 40px; background: #dbeafe; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-right: 12px;">👤</div>
                        <div>
                            <h3 style="margin: 0; font-weight: bold; color: #1f2937;">${r.rider_nombre}</h3>
                            <p style="margin: 0; font-size: 0.75rem; color: #6b7280;">ID: #${r.rider_id}</p>
                        </div>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; font-size: 0.875rem;">
                        <div style="background: #f9fafb; padding: 8px; border-radius: 4px; text-align: center;">
                            <p style="margin: 0; font-size: 0.75rem; color: #6b7280;">Viajes</p>
                            <p style="margin: 0; font-weight: bold; font-size: 1.125rem;">${r.viajes}</p>
                        </div>
                        <div style="background: #fef2f2; padding: 8px; border-radius: 4px; text-align: center;">
                            <p style="margin: 0; font-size: 0.75rem; color: #dc2626;">Debe (Ef.)</p>
                            <p style="margin: 0; font-weight: bold; color: #dc2626;">${formatearMoneda(r.total_efectivo)}</p>
                        </div>
                        <div style="background: #f0fdf4; padding: 8px; border-radius: 4px; text-align: center; grid-column: 1 / -1;">
                            <p style="margin: 0; font-size: 0.75rem; color: #16a34a;">A favor (Delivery)</p>
                            <p style="margin: 0; font-weight: bold; color: #16a34a;">${formatearMoneda(r.total_delivery)}</p>
                        </div>
                    </div>
                    <div style="border-top: 1px solid #e5e7eb; padding-top: 12px; margin-bottom: 12px; background: ${saldoBg}; border: 1px solid ${saldoBorder}; border-radius: 6px; padding: 12px; text-align: center;">
                        <p style="margin: 0 0 4px 0; font-size: 0.75rem; color: #4b5563;">Saldo Neto: <span style="font-weight: 600;">${saldoLabel}</span></p>
                        <p style="margin: 0; font-size: 1.25rem; font-weight: bold; color: ${saldoColor};">${formatearMoneda(Math.abs(r.saldo))}</p>
                    </div>
                    <button onclick="verDetalleLiquidacion(${r.rider_id}, '${r.rider_nombre.replace(/'/g, "\\'")}', '${desde}', '${hasta}')" style="width: 100%; padding: 8px; background: #2563eb; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 500; display: flex; align-items: center; justify-content: center;">
                        👁️ Ver Detalle por Local
                    </button>
                </div>
            `;
        }).join('');
    await cargarResumenLocales(desde, hasta);
    } catch (err) {
        console.error(err);
        contenedor.innerHTML = '<p style="grid-column: 1 / -1; text-align: center; color: #dc2626; padding: 32px 0;">Error al cargar los datos.</p>';
    }
}

async function verDetalleLiquidacion(riderId, riderNombre, desde, hasta) {
    const modal = document.getElementById('modal-liquidacion');
    const body = document.getElementById('modal-liq-body');
    
    document.getElementById('modal-liq-titulo').innerHTML = `👤 Liquidación: ${riderNombre}`;
    document.getElementById('modal-liq-periodo').innerHTML = `📅 Período: ${desde} al ${hasta}`;
    body.innerHTML = '<p style="color: #6b7280; text-align: center; padding: 32px 0;">Cargando detalle...</p>';
    modal.style.display = 'flex';

    try {
        const res = await fetch(`/api/riders/${riderId}/liquidacion?desde=${desde}&hasta=${hasta}`);
        const dataLiq = await res.json();

        if (!dataLiq.comercios || dataLiq.comercios.length === 0) {
            body.innerHTML = '<p style="color: #6b7280; text-align: center; padding: 32px 0;">No hay viajes entregados en este período.</p>';
        } else {
            body.innerHTML = dataLiq.comercios.map(c => `
                <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; background: #f9fafb; margin-bottom: 16px;">
                    <h3 style="margin: 0 0 12px 0; font-weight: 600; color: #374151; display: flex; align-items: center;">
                        🏪 ${c.comercio_nombre} <span style="font-size: 0.875rem; font-weight: normal; color: #6b7280; margin-left: 8px;">(${c.viajes} viajes)</span>
                    </h3>
                    <div style="overflow-x: auto;">
                        <table style="width: 100%; font-size: 0.875rem; text-align: left; color: #4b5563; border-collapse: collapse;">
                            <thead style="font-size: 0.75rem; text-transform: uppercase; color: #374151; background: #e5e7eb;">
                                <tr>
                                    <th style="padding: 8px 12px;">ID Pedido</th>
                                    <th style="padding: 8px 12px;">Fecha/Hora</th>
                                    <th style="padding: 8px 12px; text-align: right;">💵 Efectivo</th>
                                    <th style="padding: 8px 12px; text-align: right;">🚴 Delivery</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${c.pedidos.map(p => `
                                    <tr style="background: white; border-bottom: 1px solid #e5e7eb;">
                                        <td style="padding: 8px 12px; font-weight: 500;">#${p.id}</td>
                                        <td style="padding: 8px 12px;">${p.hora_entrega}</td>
                                        <td style="padding: 8px 12px; text-align: right; color: #dc2626; font-weight: 500;">${formatearMoneda(p.efectivo)}</td>
                                        <td style="padding: 8px 12px; text-align: right; color: #16a34a; font-weight: 500;">${formatearMoneda(p.delivery)}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                    <div style="margin-top: 12px; padding-top: 12px; border-top: 1px solid #d1d5db; font-size: 0.875rem; display: flex; justify-content: flex-end; gap: 24px;">
                        <span style="color: #4b5563; font-weight: 500;">Subtotal:</span>
                        <span style="color: #dc2626; font-weight: 600;">Ef: ${formatearMoneda(c.subtotal_efectivo)}</span>
                        <span style="color: #16a34a; font-weight: 600;">Del: ${formatearMoneda(c.subtotal_delivery)}</span>
                    </div>
                </div>
            `).join('');
        }

        document.getElementById('liq-total-efectivo').textContent = formatearMoneda(dataLiq.totales.efectivo);
        document.getElementById('liq-total-delivery').textContent = formatearMoneda(dataLiq.totales.delivery);
        const saldoEl = document.getElementById('liq-total-saldo');
        const saldo = dataLiq.totales.saldo;
        saldoEl.textContent = (saldo < 0 ? '- ' : '+ ') + formatearMoneda(Math.abs(saldo));
        saldoEl.style.color = saldo >= 0 ? '#166534' : '#991b1b';

    } catch (err) {
        console.error(err);
        body.innerHTML = '<p style="color: #dc2626; text-align: center; padding: 32px 0;">Error al cargar el detalle.</p>';
    }
}

function cerrarModalLiquidacion() {
    document.getElementById('modal-liquidacion').style.display = 'none';
}

// ==========================================
// LIQUIDACIÓN POR LOCAL (COMERCIO)
// ==========================================

async function cargarResumenLocales(desde, hasta) {
    const contenedor = document.getElementById('grid-resumen-locales');
    contenedor.innerHTML = '<p style="grid-column: 1 / -1; text-align: center; color: #6b7280; padding: 32px 0;">Cargando datos...</p>';

    try {
        const res = await fetch(`/api/liquidaciones/locales?desde=${desde}&hasta=${hasta}`);
        const dataLoc = await res.json();
        
        if (!dataLoc.locales || dataLoc.locales.length === 0) {
            contenedor.innerHTML = '<p style="grid-column: 1 / -1; text-align: center; color: #6b7280; padding: 32px 0;">No hay locales con pedidos en este período.</p>';
            return;
        }

        contenedor.innerHTML = dataLoc.locales.map(loc => {
            const ef = parseFloat(loc.total_efectivo_cobrado || 0);
            const dl = parseFloat(loc.total_costo_delivery || 0);
            const saldo = parseFloat(loc.saldo_liquidar || 0);
            
            // Color del saldo: verde si el local recibe plata, rojo si debe
            const saldoColor = saldo >= 0 ? '#16a34a' : '#dc2626';
            const saldoBg = saldo >= 0 ? '#f0fdf4' : '#fef2f2';
            const saldoBorder = saldo >= 0 ? '#bbf7d0' : '#fecaca';
            const saldoLabel = saldo >= 0 ? 'A favor del local' : 'Local debe diferencia';
            
            return `
                <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
                    <div style="display: flex; align-items: center; margin-bottom: 12px;">
                        <div style="width: 40px; height: 40px; background: #fef3c7; border-radius: 50%; display: flex; align-items: center; justify-content: center; margin-right: 12px; font-size: 1.25rem;">🏪</div>
                        <div>
                            <h3 style="margin: 0; font-weight: bold; color: #1f2937;">${loc.comercio_nombre}</h3>
                            <p style="margin: 0; font-size: 0.75rem; color: #6b7280;">${loc.pedidos} pedidos entregados</p>
                        </div>
                    </div>
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 12px; font-size: 0.875rem;">
                        <div style="background: #fef2f2; padding: 8px; border-radius: 4px; text-align: center;">
                            <p style="margin: 0; font-size: 0.75rem; color: #dc2626;">Efectivo cobrado</p>
                            <p style="margin: 0; font-weight: bold; color: #dc2626;">${formatearMoneda(ef)}</p>
                        </div>
                        <div style="background: #eff6ff; padding: 8px; border-radius: 4px; text-align: center;">
                            <p style="margin: 0; font-size: 0.75rem; color: #2563eb;">Costo Delivery</p>
                            <p style="margin: 0; font-weight: bold; color: #2563eb;">${formatearMoneda(dl)}</p>
                        </div>
                    </div>
                    <div style="border-top: 1px solid #e5e7eb; padding-top: 12px; background: ${saldoBg}; border: 1px solid ${saldoBorder}; border-radius: 6px; padding: 12px; text-align: center;">
                        <p style="margin: 0 0 4px 0; font-size: 0.75rem; color: #4b5563;">💰 Se le debe liquidar al local</p>
                        <p style="margin: 0; font-size: 1.25rem; font-weight: bold; color: ${saldoColor};">${formatearMoneda(Math.abs(saldo))}</p>
                        <p style="margin: 4px 0 0 0; font-size: 0.7rem; color: #6b7280;">${saldoLabel}</p>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error(err);
        contenedor.innerHTML = '<p style="grid-column: 1 / -1; text-align: center; color: #dc2626; padding: 32px 0;">Error al cargar los datos de locales.</p>';
    }
}

// ==========================================
// TOGGLE SIDEBAR
// ==========================================

function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const btn = document.getElementById('btn-toggle-sidebar');
    const container = document.querySelector('.container');
    
    if (sidebar.style.display === 'none') {
        // Mostrar sidebar
        sidebar.style.display = 'block';
        btn.innerHTML = '◀';
        btn.style.right = '20px';
        container.style.marginRight = '0';
        localStorage.setItem('sidebarVisible', 'true');
    } else {
        // Ocultar sidebar
        sidebar.style.display = 'none';
        btn.innerHTML = '▶';
        btn.style.right = '20px';
        container.style.marginRight = '0';
        localStorage.setItem('sidebarVisible', 'false');
    }
}

// Restaurar estado del sidebar al cargar la página
document.addEventListener('DOMContentLoaded', () => {
    const sidebarVisible = localStorage.getItem('sidebarVisible');
    if (sidebarVisible === 'false') {
        const sidebar = document.getElementById('sidebar');
        const btn = document.getElementById('btn-toggle-sidebar');
        if (sidebar) sidebar.style.display = 'none';
        if (btn) {
            btn.innerHTML = '▶';
        }
    }
});