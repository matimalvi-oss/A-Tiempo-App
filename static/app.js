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
    const fechaRetiro = pedido.hora_estimada_retiro ? new Date(pedido.hora_estimada_retiro + 'Z') : new Date();
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