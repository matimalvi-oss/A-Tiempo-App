// static/app.js
let data = { pedidos: [], riders: [], comercios: [], clientes: [] };
let filtroComercio = 'todos';
let dashboardFetchPromise = null;
let orderSearchQuery = '';
const orderCardExpanded = new Map();

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
    mostrarVista('liquidaciones');
    establecerPeriodoLiquidacion('hoy');
    try {
        await fetchData();
        renderKanbanColumns();
        renderSidebar();
        setupListeners();
        startDashboardPolling();
        console.log('Aplicación lista. Botones activos.');
    } catch (error) {
        console.error('Error fatal al iniciar:', error);
    }
});

async function fetchData() {
    if (dashboardFetchPromise) return dashboardFetchPromise;

    dashboardFetchPromise = (async () => {
        try {
            const res = await fetch('/api/dashboard', { cache: 'no-store' });
            if (!res.ok) throw new Error('Error en la API');

            const previousData = JSON.stringify(data);
            data = await res.json();
            updateMetrics();
            populateComercioFilter();
            updateLastUpdated();
            return previousData !== JSON.stringify(data);
        } catch (error) {
            console.error('Error al cargar datos:', error);
            const lastUpdated = document.getElementById('last-updated');
            if (lastUpdated) lastUpdated.textContent = 'No se pudo actualizar';
            return false;
        }
    })();

    try {
        return await dashboardFetchPromise;
    } finally {
        dashboardFetchPromise = null;
    }
}

function startDashboardPolling() {
    window.setInterval(async () => {
        if (document.hidden) return;

        const existingPendingIds = new Set(
            data.pedidos.filter(pedido => pedido.estado === 'pendiente').map(pedido => pedido.id)
        );
        const dataChanged = await fetchData();
        if (!dataChanged) return;

        const newPendingOrders = data.pedidos.filter(
            pedido => pedido.estado === 'pendiente' && !existingPendingIds.has(pedido.id)
        );
        if (newPendingOrders.length) {
            showOrderToast(newPendingOrders.length);
        }

        const board = document.getElementById('kanban-board');
        const scrollLeft = board ? board.scrollLeft : 0;
        const scrollTop = board ? board.scrollTop : 0;
        const columnScrollPositions = new Map(
            Array.from(document.querySelectorAll('.kanban-column')).map((column, index) => [
                index,
                column.querySelector('.column-cards')?.scrollTop || 0
            ])
        );
        renderKanbanColumns();
        if (board) {
            board.scrollLeft = scrollLeft;
            board.scrollTop = scrollTop;
        }
        document.querySelectorAll('.kanban-column').forEach((column, index) => {
            const cards = column.querySelector('.column-cards');
            if (cards) cards.scrollTop = columnScrollPositions.get(index) || 0;
        });
        renderSidebar();
    }, 5000);
}

function updateLastUpdated() {
    const lastUpdated = document.getElementById('last-updated');
    if (lastUpdated) {
        lastUpdated.textContent = `Actualizado ${new Intl.DateTimeFormat('es', {
            hour: '2-digit',
            minute: '2-digit'
        }).format(new Date())}`;
    }
}

function showOrderToast(count) {
    const toast = document.getElementById('new-order-toast');
    if (!toast) return;

    toast.textContent = count === 1 ? 'Llegó un pedido nuevo' : `Llegaron ${count} pedidos nuevos`;
    toast.classList.add('visible');
    window.clearTimeout(showOrderToast.timeoutId);
    showOrderToast.timeoutId = window.setTimeout(() => toast.classList.remove('visible'), 4500);
}

function updateMetrics() {
    const activos = data.pedidos.filter(p => p.estado !== 'entregado').length;
    const pendientes = data.pedidos.filter(p => p.estado === 'pendiente').length;
    document.getElementById('metric-activos').innerText = activos;
    document.getElementById('metric-pendientes').innerText = pendientes;
}

function populateComercioFilter() {
    const select = document.getElementById('filter-comercio');
    const filterValue = select ? select.value : 'todos';
    if (select) {
        while (select.options.length > 1) select.remove(1);
        data.comercios.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.innerText = c.nombre;
            select.appendChild(opt);
        });
        select.value = Array.from(select.options).some(option => option.value === filterValue)
            ? filterValue
            : 'todos';
        filtroComercio = select.value;
    }
    
    const formSelect = document.getElementById('form-comercio-pedido');
    if (formSelect) {
        const selectedComercio = formSelect.value;
        while (formSelect.options.length > 0) formSelect.remove(0);
        data.comercios.forEach(c => {
            const opt = document.createElement('option');
            opt.value = c.id;
            opt.innerText = c.nombre;
            formSelect.appendChild(opt);
        });
        if (Array.from(formSelect.options).some(option => option.value === selectedComercio)) {
            formSelect.value = selectedComercio;
        }
    }
}

function renderKanbanColumns() {
    const board = document.getElementById('kanban-board');
    if (!board) return;
    board.innerHTML = '';

    ESTADOS_KANBAN.forEach(col => {
        // Filtrar pedidos que pertenecen a esta columna agrupada
        let pedidosCol = data.pedidos.filter(p => {
            if (getColumnIdForEstado(p.estado) !== col.id) return false;

            const comercio = data.comercios.find(item => item.id === p.comercio_id);
            const cliente = data.clientes.find(item => item.id === p.cliente_id);
            const rider = data.riders.find(item => item.id === p.rider_id);
            const searchableText = [
                p.id,
                p.direccion_entrega,
                comercio?.nombre,
                cliente?.nombre,
                cliente?.telefono,
                rider?.nombre
            ].join(' ').toLocaleLowerCase();

            return searchableText.includes(orderSearchQuery);
        });
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
        if (pedidosCol.length === 0) {
            const emptyMessage = document.createElement('p');
            emptyMessage.className = 'empty-column';
            emptyMessage.textContent = orderSearchQuery ? 'No hay pedidos que coincidan.' : 'No hay pedidos.';
            cardsContainer.appendChild(emptyMessage);
        }
    });
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function createOrderCard(pedido) {
    const comercio = data.comercios.find(c => c.id === pedido.comercio_id);
    const cliente = data.clientes.find(c => c.id === pedido.cliente_id);
    const rider = pedido.rider_id ? data.riders.find(r => r.id === pedido.rider_id) : null;

    if (!comercio) return document.createElement('div');

    const card = document.createElement('div');
    const collapsedByDefault = window.innerWidth <= 768 || pedido.estado === 'entregado';
    const collapsed = orderCardExpanded.has(pedido.id)
        ? !orderCardExpanded.get(pedido.id)
        : collapsedByDefault;
    card.className = collapsed ? 'order-card collapsed' : 'order-card';
    card.dataset.orderId = pedido.id;
    const estadoTexto = (pedido.estado || 'pendiente').replace(/_/g, ' ');
    
    const headerHtml = `
        <div class="card-header" role="button" tabindex="0" aria-expanded="${!collapsed}" onclick="window.toggleOrderCard(this, ${pedido.id})" onkeydown="if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); window.toggleOrderCard(this, ${pedido.id}); }">
            <div>
                <div class="card-title-row">
                    <span class="comercio-name">${comercio.nombre}</span>
                    <span class="card-time">#${pedido.id}</span>
                    <span class="order-state">${estadoTexto}</span>
                </div>
                <span class="card-summary">${cliente?.nombre || 'Sin nombre'} · ${pedido.direccion_entrega || 'Sin dirección'}</span>
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
            <div class="card-row"><span>${cliente?.nombre || 'Sin nombre'}</span> <span>${cliente?.telefono ? `<a href="tel:${cliente.telefono}">${cliente.telefono}</a>` : 'Sin teléfono'}</span></div>
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

window.toggleOrderCard = function(header, pedidoId) {
    const card = header.parentElement;
    const expanded = card.classList.contains('collapsed');
    card.classList.toggle('collapsed', !expanded);
    header.setAttribute('aria-expanded', String(expanded));
    orderCardExpanded.set(pedidoId, expanded);
};

function renderSidebar() {
    const ridersList = document.getElementById('riders-list');
    if (ridersList) {
        ridersList.innerHTML = data.riders.map(r => {
            const pedidosActivos = data.pedidos.filter(p => p.rider_id === r.id && p.estado !== 'entregado').length;
            const estado = pedidosActivos > 1 ? 'sobrecargado' : pedidosActivos === 1 ? 'en_viaje' : 'disponible';
            const estadoTexto = pedidosActivos === 0 ? 'Libre' : pedidosActivos === 1 ? '1 pedido activo' : `${pedidosActivos} pedidos activos`;
            return `
                <div class="rider-card">
                    <div class="rider-header">
                        <span class="rider-name">${r.nombre}</span>
                        <span class="rider-status status-${estado}" title="${estadoTexto}"></span>
                    </div>
                    <div class="rider-details">${r.vehiculo} | <span class="rider-workload status-text-${estado}">${estadoTexto}</span></div>
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

    const orderSearch = document.getElementById('search-orders');
    if (orderSearch) {
        orderSearch.addEventListener('input', () => {
            orderSearchQuery = orderSearch.value.trim().toLocaleLowerCase();
            renderKanbanColumns();
        });
    }

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
    const asignables = data.riders.filter(r => r.estado !== 'fuera_de_servicio');
    const body = document.getElementById('modal-body');
    body.innerHTML = asignables.length === 0
        ? '<p>No hay riders disponibles para asignar.</p>'
        : asignables.map(r => {
            const pedidosActivos = data.pedidos.filter(p => p.rider_id === r.id && p.estado !== 'entregado').length;
            const estado = pedidosActivos > 1 ? 'sobrecargado' : pedidosActivos === 1 ? 'en_viaje' : 'disponible';
            const estadoTexto = pedidosActivos === 0 ? 'Libre' : pedidosActivos === 1 ? '1 pedido activo' : `${pedidosActivos} pedidos activos`;
            return `
            <button class="rider-option" onclick="window.assignRider(${pedidoId}, ${r.id})">
                <strong>${r.nombre}</strong> (${r.vehiculo}) <span class="rider-option-status status-text-${estado}">${estadoTexto}</span>
            </button>
        `}).join('');
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
    if (!pedido) return;
    const cliente = data.clientes.find(c => c.id === pedido.cliente_id);

    document.getElementById('edit-pedido-id').innerText = pedido.id;
    document.getElementById('edit-pedido-id-input').value = pedido.id;
    document.getElementById('edit-estado').value = pedido.estado;
    document.getElementById('edit-cliente-nombre').value = cliente?.nombre || '';
    document.getElementById('edit-cliente-telefono').value = cliente?.telefono || '';
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
    if (!confirm('¿Estás seguro de eliminar TODOS los pedidos entregados?\n\nEsta acción no se puede deshacer.')) return;
    
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
            alert('Pedidos entregados eliminados correctamente');
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
    const boardTools = document.getElementById('board-tools');
    const btnPedidos = document.getElementById('btn-vista-pedidos');
    const btnLiquidaciones = document.getElementById('btn-vista-liquidaciones');

    console.log(`Cambiando a vista: ${vista}`); // DEBUG

        if (vista === 'pedidos') {
        if (kanban) kanban.style.display = 'flex';
        if (liquidaciones) liquidaciones.style.display = 'none';
            if (boardTools) boardTools.style.display = 'flex';
        
        // Pedidos activo (azul)
        if (btnPedidos) {
            btnPedidos.style.background = '#3b82f6';
            btnPedidos.style.color = 'white';
        }
        
        // Liquidaciones inactivo (blanco)
        if (btnLiquidaciones) {
            btnLiquidaciones.style.background = 'white';
            btnLiquidaciones.style.color = '#374151';
        }
        
    } else if (vista === 'liquidaciones') {
        if (kanban) kanban.style.display = 'none';
        if (liquidaciones) liquidaciones.style.display = 'block';
        if (boardTools) boardTools.style.display = 'none';
        
        // Pedidos inactivo (blanco)
        if (btnPedidos) {
            btnPedidos.style.background = 'white';
            btnPedidos.style.color = '#374151';
        }
        
        // Liquidaciones activo (azul)
        if (btnLiquidaciones) {
            btnLiquidaciones.style.background = '#3b82f6';
            btnLiquidaciones.style.color = 'white';
        }
        
        console.log('Vista liquidaciones activada'); // DEBUG
    }

    if (typeof lucide !== 'undefined') lucide.createIcons();
}

function formatearMoneda(valor) {
    return '$ ' + Number(valor || 0).toLocaleString('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: 0 });
}

function fechaLocalISO(fecha) {
    const anio = fecha.getFullYear();
    const mes = String(fecha.getMonth() + 1).padStart(2, '0');
    const dia = String(fecha.getDate()).padStart(2, '0');
    return `${anio}-${mes}-${dia}`;
}

const HORA_CORTE_LIQUIDACION = '06:00';

function obtenerFechaOperativaActual(ahora = new Date()) {
    const fecha = new Date(ahora.getFullYear(), ahora.getMonth(), ahora.getDate());
    if (ahora.getHours() < 6) fecha.setDate(fecha.getDate() - 1);
    return fecha;
}

function limpiarPeriodoLiquidacionSeleccionado() {
    document.querySelectorAll('[data-liquidation-period]').forEach(button => {
        button.classList.remove('is-selected');
        button.setAttribute('aria-pressed', 'false');
    });
}

function establecerPeriodoLiquidacion(periodo, consultar = true) {
    const fechaOperativa = obtenerFechaOperativaActual();
    const desde = new Date(fechaOperativa);
    const hasta = new Date(fechaOperativa);

    if (periodo === 'ayer') {
        desde.setDate(desde.getDate() - 1);
        hasta.setDate(hasta.getDate() - 1);
    } else if (periodo === '7dias') desde.setDate(desde.getDate() - 6);
    else if (periodo === 'mes') desde.setDate(1);
    else if (periodo !== 'hoy') desde.setDate(desde.getDate() - (periodo === '30dias' ? 29 : 30));

    document.getElementById('liq-desde').value = fechaLocalISO(desde);
    document.getElementById('liq-hasta').value = fechaLocalISO(hasta);
    document.querySelectorAll('[data-liquidation-period]').forEach(button => {
        const seleccionado = button.dataset.liquidationPeriod === periodo;
        button.classList.toggle('is-selected', seleccionado);
        button.setAttribute('aria-pressed', String(seleccionado));
    });
    if (consultar) cargarResumenLiquidaciones();
}

async function cargarResumenLiquidaciones() {
    const desde = document.getElementById('liq-desde').value;
    const hasta = document.getElementById('liq-hasta').value;
    if (!desde || !hasta) { alert('Seleccioná un rango de fechas válido.'); return; }
    if (desde > hasta) { alert('La fecha "Desde" no puede ser posterior a "Hasta".'); return; }

    const contenedor = document.getElementById('grid-resumen-riders');
    contenedor.innerHTML = '<p style="grid-column: 1 / -1; text-align: center; color: #6b7280; padding: 32px 0;">Cargando datos...</p>';

    try {
        const res = await fetch(`/api/liquidaciones/resumen?desde=${desde}&hasta=${hasta}&hora_corte=${HORA_CORTE_LIQUIDACION}`);
        const dataLiq = await res.json();
        
        const ridersConSaldo = (dataLiq.riders || []).filter(r => Math.abs(Number(r.saldo || 0)) > 0.000001);
        if (ridersConSaldo.length === 0) {
            contenedor.innerHTML = '<p style="grid-column: 1 / -1; text-align: center; color: #6b7280; padding: 32px 0;">No hay riders con saldo pendiente en este período.</p>';
            await cargarResumenLocales(desde, hasta);
            return;
        }

        contenedor.innerHTML = ridersConSaldo.map(r => {
            const saldoColor = r.saldo >= 0 ? '#16a34a' : '#dc2626';
            const saldoBg = r.saldo >= 0 ? '#f0fdf4' : '#fef2f2';
            const saldoBorder = r.saldo >= 0 ? '#bbf7d0' : '#fecaca';
            const saldoLabel = r.saldo >= 0 ? 'A favor del rider' : 'Debe entregar';
            
            return `
                <article class="settlement-card">
                    <div class="settlement-card-heading">
                        <div class="settlement-avatar"><i data-lucide="user-round" aria-hidden="true"></i></div>
                        <div>
                            <h3>${r.rider_nombre}</h3>
                            <p>ID: #${r.rider_id}</p>
                        </div>
                    </div>
                    <div class="settlement-card-metrics">
                        <div class="settlement-metric">
                            <span>Viajes</span>
                            <strong>${r.viajes}</strong>
                        </div>
                        <div class="settlement-metric settlement-metric--cash">
                            <span>Efectivo</span>
                            <strong>${formatearMoneda(r.total_efectivo)}</strong>
                        </div>
                        <div class="settlement-metric settlement-metric--delivery">
                            <span>Delivery</span>
                            <strong>${formatearMoneda(r.total_delivery)}</strong>
                        </div>
                    </div>
                    <div class="settlement-card-balance" style="--balance-color: ${saldoColor}; --balance-bg: ${saldoBg}; --balance-border: ${saldoBorder};">
                        <span>Saldo neto · ${saldoLabel}</span>
                        <strong>${formatearMoneda(Math.abs(r.saldo))}</strong>
                    </div>
                    <button class="settlement-detail-button" onclick="verDetalleLiquidacion(${r.rider_id}, '${r.rider_nombre.replace(/'/g, "\\'")}', '${desde}', '${hasta}')">
                        <i data-lucide="eye" aria-hidden="true"></i> Ver Detalle por Local
                    </button>
                </article>
            `;
        }).join('');
        if (typeof lucide !== 'undefined') lucide.createIcons();
    await cargarResumenLocales(desde, hasta);
    } catch (err) {
        console.error(err);
        contenedor.innerHTML = '<p style="grid-column: 1 / -1; text-align: center; color: #dc2626; padding: 32px 0;">Error al cargar los datos.</p>';
    }
}

async function verDetalleLiquidacion(riderId, riderNombre, desde, hasta) {
    const modal = document.getElementById('modal-liquidacion');
    const body = document.getElementById('modal-liq-body');
    
    document.getElementById('modal-liq-titulo').innerHTML = `<i data-lucide="user-round" aria-hidden="true"></i> Liquidación: ${riderNombre}`;
    document.getElementById('modal-liq-periodo').innerHTML = `<i data-lucide="calendar-days" aria-hidden="true"></i> Período: ${desde} al ${hasta}`;
    body.innerHTML = '<p style="color: #6b7280; text-align: center; padding: 32px 0;">Cargando detalle...</p>';
    modal.style.display = 'flex';
    if (typeof lucide !== 'undefined') lucide.createIcons();

    try {
        const res = await fetch(`/api/riders/${riderId}/liquidacion?desde=${desde}&hasta=${hasta}&hora_corte=${HORA_CORTE_LIQUIDACION}`);
        const dataLiq = await res.json();

        if (!dataLiq.comercios || dataLiq.comercios.length === 0) {
            body.innerHTML = '<p style="color: #6b7280; text-align: center; padding: 32px 0;">No hay viajes entregados en este período.</p>';
        } else {
            body.innerHTML = dataLiq.comercios.map(c => `
                <section class="settlement-store-details">
                    <h3><i data-lucide="store" aria-hidden="true"></i> ${c.comercio_nombre} <span>(${c.viajes} viajes)</span></h3>
                    <div class="settlement-order-list">
                        ${c.pedidos.map(p => `
                            <article class="settlement-order">
                                <div class="settlement-order-heading">
                                    <strong>Pedido #${p.id}</strong>
                                    <time>${p.hora_entrega}</time>
                                </div>
                                <div class="settlement-order-values">
                                    <div><span><i data-lucide="banknote" aria-hidden="true"></i> Efectivo</span><strong>${formatearMoneda(p.efectivo)}</strong></div>
                                    <div><span><i data-lucide="bike" aria-hidden="true"></i> Delivery</span><strong>${formatearMoneda(p.delivery)}</strong></div>
                                </div>
                            </article>
                        `).join('')}
                    </div>
                    <div class="settlement-store-subtotal">
                        <span>Subtotal</span>
                        <strong>Efectivo: ${formatearMoneda(c.subtotal_efectivo)}</strong>
                        <strong>Delivery: ${formatearMoneda(c.subtotal_delivery)}</strong>
                    </div>
                </section>
            `).join('');
        }
        if (typeof lucide !== 'undefined') lucide.createIcons();

        document.getElementById('liq-total-efectivo').textContent = formatearMoneda(dataLiq.totales.efectivo);
        document.getElementById('liq-total-delivery').textContent = formatearMoneda(dataLiq.totales.delivery);
        const saldoEl = document.getElementById('liq-total-saldo');
        const saldo = dataLiq.totales.saldo;
        saldoEl.textContent = (saldo < 0 ? '- ' : '+ ') + formatearMoneda(Math.abs(saldo));
        saldoEl.style.color = saldo > 0 ? '#166534' : saldo < 0 ? '#991b1b' : '#374151';

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
        const res = await fetch(`/api/liquidaciones/locales?desde=${desde}&hasta=${hasta}&hora_corte=${HORA_CORTE_LIQUIDACION}`);
        const dataLoc = await res.json();
        
        const localesConSaldo = (dataLoc.locales || []).filter(loc => Math.abs(Number(loc.saldo_liquidar || 0)) > 0.000001);
        if (localesConSaldo.length === 0) {
            contenedor.innerHTML = '<p style="grid-column: 1 / -1; text-align: center; color: #6b7280; padding: 32px 0;">No hay locales con saldo pendiente en este período.</p>';
            return;
        }

        contenedor.innerHTML = localesConSaldo.map(loc => {
            const ef = parseFloat(loc.total_efectivo_cobrado || 0);
            const dl = parseFloat(loc.total_costo_delivery || 0);
            const saldo = parseFloat(loc.saldo_liquidar || 0);
            
            const estadoSaldo = saldo > 0
                ? { clase: 'collect-store', etiqueta: 'Nosotros debemos al local' }
                : saldo < 0
                    ? { clase: 'pay-store', etiqueta: 'El local nos debe pagar' }
                    : { clase: 'settled', etiqueta: 'Sin saldo pendiente' };
            
            return `
                <article class="settlement-card">
                    <div class="settlement-card-heading">
                        <div class="settlement-avatar settlement-avatar--store"><i data-lucide="store" aria-hidden="true"></i></div>
                        <div>
                            <h3>${loc.comercio_nombre}</h3>
                            <p>${loc.pedidos} pedidos entregados</p>
                        </div>
                    </div>
                    <div class="settlement-card-metrics">
                        <div class="settlement-metric settlement-metric--cash">
                            <span>Efectivo cobrado</span>
                            <strong>${formatearMoneda(ef)}</strong>
                        </div>
                        <div class="settlement-metric settlement-metric--delivery">
                            <span>Costo Delivery</span>
                            <strong>${formatearMoneda(dl)}</strong>
                        </div>
                    </div>
                    <div class="store-balance store-balance--${estadoSaldo.clase}">
                        <span class="store-balance-label">${estadoSaldo.etiqueta}</span>
                        <strong>${formatearMoneda(Math.abs(saldo))}</strong>
                    </div>
                </article>
            `;
        }).join('');
        if (typeof lucide !== 'undefined') lucide.createIcons();
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
    const overlay = document.getElementById('sidebar-overlay');
    const btn = document.getElementById('btn-toggle-sidebar');
    const btnClose = document.querySelector('.btn-close-sidebar');
    
    if (!sidebar || !btn) return;
    
    const isMobile = window.innerWidth <= 768;

    if (isMobile) {
        // Comportamiento movil: drawer lateral
        sidebar.classList.toggle('visible');
        overlay.style.display = sidebar.classList.contains('visible') ? 'block' : 'none';
        if (btnClose) btnClose.style.display = sidebar.classList.contains('visible') ? 'block' : 'none';
    } else {
        // Comportamiento escritorio: ocultar/mostrar
        if(sidebar.style.display === 'none') {
            sidebar.style.display = 'block';
            btn.innerHTML = '<i data-lucide="panel-right-close" style="width: 18px; height: 18px;"></i>';
            localStorage.setItem('sidebarVisible', 'true');
        } else {
        // Ocultar sidebar
        sidebar.style.display = 'none';
        btn.innerHTML = '<i data-lucide="panel-right-open" style="width: 18px; height: 18px;"></i>';
        localStorage.setItem('sidebarVisible', 'false');
        }
    }
    
    if (typeof lucide !== 'undefined') lucide.createIcons();
}

// Restaurar estado del sidebar al cargar la página
document.addEventListener('DOMContentLoaded', () => {
    const sidebarVisible = localStorage.getItem('sidebarVisible');
    if (sidebarVisible === 'false') {
        const sidebar = document.getElementById('sidebar');
        const btn = document.getElementById('btn-toggle-sidebar');
        if (sidebar) sidebar.style.display = 'none';
        if (btn) {
            btn.innerHTML = '<i data-lucide="panel-right-open" style="width: 18px; height: 18px;"></i>';
            if (typeof lucide !== 'undefined') lucide.createIcons();
        }
    }
});
