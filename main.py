from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
from database import get_db, init_db, row_to_dict, rows_to_list
import uvicorn
import os

app = FastAPI()

# --- MIDDLEWARE CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- SERVIDOR DE ARCHIVOS ESTÁTICOS ---
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- RUTAS PWA ---
@app.get("/", response_class=HTMLResponse)
async def root():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

@app.get("/manifest.json")
async def manifest():
    return FileResponse("static/manifest.json", media_type="application/json")

@app.get("/sw.js")
async def service_worker():
    return FileResponse("static/sw.js", media_type="application/javascript")

# --- INICIALIZAR BASE DE DATOS ---
init_db()

# --- MODELOS ---
class AssignRiderRequest(BaseModel):
    rider_id: int

class UpdateStatusRequest(BaseModel):
    nuevo_estado: str

class CreateOrderRequest(BaseModel):
    comercio_id: int
    cliente_nombre: Optional[str] = None
    cliente_telefono: Optional[str] = None
    direccion_entrega: str
    monto_a_cobrar: float = 0.0
    costo_delivery: float = 0.0
    pagado: bool = False

class CreateComercioRequest(BaseModel):
    nombre: str
    direccion: str
    telefono: str

class UpdateComercioRequest(BaseModel):
    nombre: Optional[str] = None
    direccion: Optional[str] = None
    telefono: Optional[str] = None

class CreateRiderRequest(BaseModel):
    nombre: str
    telefono: str
    vehiculo: str = "Moto"

class UpdateRiderRequest(BaseModel):
    nombre: Optional[str] = None
    telefono: Optional[str] = None
    vehiculo: Optional[str] = None
    estado: Optional[str] = None

class UpdateOrderRequest(BaseModel):
    cliente_nombre: Optional[str] = None
    cliente_telefono: Optional[str] = None
    direccion_entrega: Optional[str] = None
    monto_a_cobrar: Optional[float] = None
    costo_delivery: Optional[float] = None
    pagado: Optional[bool] = None
    estado: Optional[str] = None
    rider_id: Optional[int] = None

def sync_rider_statuses(cursor):
    cursor.execute("""
        UPDATE riders AS r
        SET estado = CASE
            WHEN active_orders.total = 0 THEN 'disponible'
            WHEN active_orders.total = 1 THEN 'en_viaje'
            ELSE 'sobrecargado'
        END
        FROM (
            SELECT r.id, COUNT(p.id) AS total
            FROM riders AS r
            LEFT JOIN pedidos AS p
                ON p.rider_id = r.id AND p.estado != 'entregado'
            GROUP BY r.id
        ) AS active_orders
        WHERE r.id = active_orders.id
    """)

# --- ENDPOINTS: DASHBOARD ---

@app.get("/api/dashboard")
def get_dashboard_data():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM comercios WHERE estado = 'activo'")
    comercios = rows_to_list(cursor.fetchall())
    
    cursor.execute("SELECT * FROM clientes")
    clientes = rows_to_list(cursor.fetchall())
    
    cursor.execute("SELECT * FROM riders")
    riders = rows_to_list(cursor.fetchall())
    
    cursor.execute("SELECT * FROM pedidos ORDER BY hora_pedido DESC LIMIT 200")
    pedidos = rows_to_list(cursor.fetchall())
    
    conn.close()
    
    return {
        "comercios": comercios,
        "clientes": clientes,
        "riders": riders,
        "pedidos": pedidos
    }

# --- ENDPOINTS: PEDIDOS ---

@app.post("/api/pedidos")
def crear_pedido(req: CreateOrderRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cliente_nombre = (req.cliente_nombre or "").strip()
        cliente_telefono = (req.cliente_telefono or "").strip() or None
        cliente_id = None

        if cliente_telefono:
            cursor.execute("SELECT id FROM clientes WHERE telefono = %s", (cliente_telefono,))
            cliente = cursor.fetchone()
            if cliente:
                cliente_id = cliente['id']

        if cliente_id is None and (cliente_nombre or cliente_telefono):
            cursor.execute(
                "INSERT INTO clientes (nombre, telefono) VALUES (%s, %s) RETURNING id",
                (cliente_nombre or "Sin nombre", cliente_telefono)
            )
            cliente_id = cursor.fetchone()['id']
        
        # 2. Obtener dirección del comercio
        cursor.execute("SELECT direccion FROM comercios WHERE id = %s", (req.comercio_id,))
        comercio = cursor.fetchone()
        
        if not comercio:
            raise HTTPException(404, "Comercio no encontrado")
        
        ahora = datetime.now()
        hora_estimada = ahora + timedelta(minutes=20)
        
        # 3. Crear el pedido
        cursor.execute('''
            INSERT INTO pedidos 
            (comercio_id, cliente_id, rider_id, direccion_recogida, direccion_entrega, estado, 
             monto_a_cobrar, costo_delivery, pagado, hora_pedido, hora_estimada_retiro)
            VALUES (%s, %s, NULL, %s, %s, 'pendiente', %s, %s, %s, %s, %s)
            RETURNING id
        ''', (req.comercio_id, cliente_id, comercio['direccion'], req.direccion_entrega,
              req.monto_a_cobrar, req.costo_delivery, req.pagado, ahora, hora_estimada))
        
        pedido_id = cursor.fetchone()['id']
        conn.commit()
        
        print(f"✅ Pedido creado con ID: {pedido_id}")
        return {"message": "Pedido creado", "pedido_id": pedido_id}
        
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        print(f"❌ Error al crear pedido: {e}")
        raise HTTPException(500, f"Error al crear pedido: {str(e)}")
    finally:
        conn.close()

@app.post("/api/pedidos/{pedido_id}/asignar")
def asignar_rider(pedido_id: int, req: AssignRiderRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM pedidos WHERE id = %s", (pedido_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "Pedido no encontrado")
    
    cursor.execute("SELECT id FROM riders WHERE id = %s", (req.rider_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "Rider no encontrado")
    
    cursor.execute("UPDATE pedidos SET rider_id = %s, estado = 'asignado' WHERE id = %s", 
                  (req.rider_id, pedido_id))
    sync_rider_statuses(cursor)
    
    conn.commit()
    conn.close()
    
    return {"message": "Rider asignado"}

@app.post("/api/pedidos/{pedido_id}/estado")
def actualizar_estado(pedido_id: int, req: UpdateStatusRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    estados_validos = ["pendiente", "asignado", "en_camino_comercio", "retirado", "en_camino_cliente", "entregado"]
    if req.nuevo_estado not in estados_validos:
        conn.close()
        raise HTTPException(400, "Estado inválido")
    
    ahora = datetime.now()
    
    if req.nuevo_estado == "retirado":
        cursor.execute("UPDATE pedidos SET estado = %s, hora_real_retiro = %s WHERE id = %s",
                      (req.nuevo_estado, ahora, pedido_id))
    elif req.nuevo_estado == "entregado":
        cursor.execute("UPDATE pedidos SET estado = %s, hora_entrega = %s WHERE id = %s",
                      (req.nuevo_estado, ahora, pedido_id))
    else:
        cursor.execute("UPDATE pedidos SET estado = %s WHERE id = %s",
                      (req.nuevo_estado, pedido_id))
    
    sync_rider_statuses(cursor)
    conn.commit()
    conn.close()
    
    return {"message": "Estado actualizado"}

# --- ENDPOINTS: COMERCIOS ---

@app.post("/api/comercios")
def crear_comercio(req: CreateComercioRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO comercios (nombre, direccion, telefono) VALUES (%s, %s, %s) RETURNING id",
            (req.nombre, req.direccion, req.telefono)
        )
        result = cursor.fetchone()  # Guardamos el resultado PRIMERO
        conn.commit()
        
        if result:
            comercio_id = result['id']
            print(f"✅ Comercio creado con ID: {comercio_id}")
            return {"message": "Comercio creado", "comercio_id": comercio_id}
        else:
            print("❌ No se obtuvo ID del comercio")
            raise HTTPException(500, "No se pudo obtener el ID del comercio")
    except Exception as e:
        conn.rollback()
        print(f" Error al crear comercio: {e}")
        raise HTTPException(500, f"Error al crear comercio: {str(e)}")
    finally:
        conn.close()

@app.put("/api/comercios/{comercio_id}")
def actualizar_comercio(comercio_id: int, req: UpdateComercioRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM comercios WHERE id = %s", (comercio_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "Comercio no encontrado")
    
    updates = []
    params = []
    
    if req.nombre is not None:
        updates.append("nombre = %s")
        params.append(req.nombre)
    if req.direccion is not None:
        updates.append("direccion = %s")
        params.append(req.direccion)
    if req.telefono is not None:
        updates.append("telefono = %s")
        params.append(req.telefono)
    
    if updates:
        params.append(comercio_id)
        cursor.execute(f"UPDATE comercios SET {', '.join(updates)} WHERE id = %s", params)
        conn.commit()
    
    conn.close()
    return {"message": "Comercio actualizado"}

@app.delete("/api/comercios/{comercio_id}")
def eliminar_comercio(comercio_id: int):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM comercios WHERE id = %s", (comercio_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "Comercio no encontrado")
    
    cursor.execute("SELECT id FROM pedidos WHERE comercio_id = %s AND estado != 'entregado'", (comercio_id,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(400, "No se puede eliminar: tiene pedidos activos")
    
    cursor.execute("UPDATE comercios SET estado = 'inactivo' WHERE id = %s", (comercio_id,))
    conn.commit()
    conn.close()
    
    return {"message": "Comercio eliminado"}

# --- ENDPOINTS: RIDERS ---

@app.post("/api/riders")
def crear_rider(req: CreateRiderRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO riders (nombre, telefono, vehiculo, estado) VALUES (%s, %s, %s, 'disponible') RETURNING id",
            (req.nombre, req.telefono, req.vehiculo)
        )
        result = cursor.fetchone()
        conn.commit()
        
        if result:
            rider_id = result['id']
            print(f"✅ Rider creado con ID: {rider_id}")
            return {"message": "Rider creado", "rider_id": rider_id}
        else:
            print("❌ No se obtuvo ID del rider")
            raise HTTPException(500, "No se pudo obtener el ID del rider")
    except Exception as e:
        conn.rollback()
        print(f"❌ Error al crear rider: {e}")
        raise HTTPException(500, f"Error al crear rider: {str(e)}")
    finally:
        conn.close()

@app.put("/api/riders/{rider_id}")
def actualizar_rider(rider_id: int, req: UpdateRiderRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM riders WHERE id = %s", (rider_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "Rider no encontrado")
    
    updates = []
    params = []
    
    if req.nombre is not None:
        updates.append("nombre = %s")
        params.append(req.nombre)
    if req.telefono is not None:
        updates.append("telefono = %s")
        params.append(req.telefono)
    if req.vehiculo is not None:
        updates.append("vehiculo = %s")
        params.append(req.vehiculo)
    if req.estado is not None:
        updates.append("estado = %s")
        params.append(req.estado)
    
    if updates:
        params.append(rider_id)
        cursor.execute(f"UPDATE riders SET {', '.join(updates)} WHERE id = %s", params)
        conn.commit()
    
    conn.close()
    return {"message": "Rider actualizado"}

@app.delete("/api/riders/{rider_id}")
def eliminar_rider(rider_id: int):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM riders WHERE id = %s", (rider_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "Rider no encontrado")
    
    cursor.execute("SELECT id FROM pedidos WHERE rider_id = %s AND estado != 'entregado'", (rider_id,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(400, "No se puede eliminar: tiene pedidos activos asignados")
    
    cursor.execute("DELETE FROM riders WHERE id = %s", (rider_id,))
    conn.commit()
    conn.close()
    
    return {"message": "Rider eliminado"}

@app.put("/api/pedidos/{pedido_id}")
def actualizar_pedido(pedido_id: int, req: UpdateOrderRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM pedidos WHERE id = %s", (pedido_id,))
    pedido = cursor.fetchone()
    if not pedido:
        conn.close()
        raise HTTPException(404, "Pedido no encontrado")
    
    updates = []
    params = []
    
    if req.cliente_nombre is not None or req.cliente_telefono is not None:
        cliente_nombre = (req.cliente_nombre or "").strip()
        cliente_telefono = (req.cliente_telefono or "").strip() or None

        if pedido['cliente_id'] is None:
            cliente = None
            if cliente_telefono:
                cursor.execute("SELECT id FROM clientes WHERE telefono = %s", (cliente_telefono,))
                cliente = cursor.fetchone()

            if cliente:
                cliente_id = cliente['id']
            elif cliente_nombre or cliente_telefono:
                cursor.execute(
                    "INSERT INTO clientes (nombre, telefono) VALUES (%s, %s) RETURNING id",
                    (cliente_nombre or "Sin nombre", cliente_telefono)
                )
                cliente_id = cursor.fetchone()['id']
            else:
                cliente_id = None

            if cliente_id is not None:
                cursor.execute("UPDATE pedidos SET cliente_id = %s WHERE id = %s", (cliente_id, pedido_id))
        else:
            cursor.execute(
                "UPDATE clientes SET nombre = COALESCE(NULLIF(%s, ''), nombre), telefono = %s WHERE id = %s",
                (cliente_nombre, cliente_telefono, pedido['cliente_id'])
            )
    
    if req.direccion_entrega is not None:
        updates.append("direccion_entrega = %s")
        params.append(req.direccion_entrega)
    if req.monto_a_cobrar is not None:
        updates.append("monto_a_cobrar = %s")
        params.append(req.monto_a_cobrar)
    if req.costo_delivery is not None:
        updates.append("costo_delivery = %s")
        params.append(req.costo_delivery)
    if req.pagado is not None:
        updates.append("pagado = %s")
        params.append(req.pagado)
    if req.rider_id is not None or 'rider_id' in req.__fields_set__:
        updates.append("rider_id = %s")
        params.append(req.rider_id)
        
    if req.estado is not None:
        updates.append("estado = %s")
        params.append(req.estado)
        
        ahora = datetime.now()
        if req.estado == 'retirado' and not pedido['hora_real_retiro']:
            updates.append("hora_real_retiro = %s")
            params.append(ahora)
        elif req.estado == 'entregado' and not pedido['hora_entrega']:
            updates.append("hora_entrega = %s")
            params.append(ahora)
    
    if updates:
        params.append(pedido_id)
        cursor.execute(f"UPDATE pedidos SET {', '.join(updates)} WHERE id = %s", params)
    
    sync_rider_statuses(cursor)
    conn.commit()
    conn.close()
    return {"message": "Pedido actualizado"}

# --- ENDPOINTS: ELIMINAR PEDIDOS ---

@app.delete("/api/pedidos/limpiar-entregados")
def limpiar_pedidos_entregados():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pedidos WHERE estado = 'entregado'")
    sync_rider_statuses(cursor)
    conn.commit()
    conn.close()
    return {"message": "Pedidos entregados eliminados"}

@app.delete("/api/pedidos/{pedido_id}")
def eliminar_pedido(pedido_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pedidos WHERE id = %s", (pedido_id,))
    sync_rider_statuses(cursor)
    conn.commit()
    conn.close()
    return {"message": "Pedido eliminado"}

# ==========================================
# ENDPOINTS: LIQUIDACIONES DE RIDERS
# ==========================================

@app.get("/api/liquidaciones/resumen")
def resumen_liquidaciones(desde: str, hasta: str):
    conn = get_db()
    cursor = conn.cursor()
    
    # Convertimos las fechas a formato timestamp para PostgreSQL
    fecha_desde = f"{desde} 00:00:00"
    fecha_hasta = f"{hasta} 23:59:59"
    
    query = """
        SELECT 
            r.id as rider_id,
            r.nombre as rider_nombre,
            COUNT(p.id) as viajes,
            COALESCE(SUM(p.monto_a_cobrar), 0) as total_efectivo,
            COALESCE(SUM(p.costo_delivery), 0) as total_delivery
        FROM riders r
        LEFT JOIN pedidos p ON r.id = p.rider_id 
            AND p.estado = 'entregado' 
            AND p.hora_entrega >= %s::timestamp 
            AND p.hora_entrega <= %s::timestamp
        GROUP BY r.id, r.nombre
        ORDER BY r.nombre
    """
    cursor.execute(query, (fecha_desde, fecha_hasta))
    resumen = rows_to_list(cursor.fetchall())
    conn.close()
    
    # Calculamos el saldo neto en Python
    for r in resumen:
        ef = float(r['total_efectivo'] or 0)
        dl = float(r['total_delivery'] or 0)
        r['saldo'] = dl - ef
        
    return {"riders": resumen}


@app.get("/api/riders/{rider_id}/liquidacion")
def detalle_liquidacion(rider_id: int, desde: str, hasta: str):
    conn = get_db()
    cursor = conn.cursor()
    
    fecha_desde = f"{desde} 00:00:00"
    fecha_hasta = f"{hasta} 23:59:59"
    
    query = """
        SELECT 
            p.id,
            p.hora_entrega,
            p.monto_a_cobrar,
            p.costo_delivery,
            c.id as comercio_id,
            c.nombre as comercio_nombre
        FROM pedidos p
        JOIN comercios c ON p.comercio_id = c.id
        WHERE p.rider_id = %s
          AND p.estado = 'entregado'
          AND p.hora_entrega >= %s::timestamp
          AND p.hora_entrega <= %s::timestamp
        ORDER BY c.nombre, p.hora_entrega DESC
    """
    cursor.execute(query, (rider_id, fecha_desde, fecha_hasta))
    pedidos = rows_to_list(cursor.fetchall())
    conn.close()
    
    # Agrupar pedidos por comercio
    agrupado = {}
    total_efectivo = 0.0
    total_delivery = 0.0
    
    for p in pedidos:
        cid = p['comercio_id']
        if cid not in agrupado:
            agrupado[cid] = {
                "comercio_id": cid,
                "comercio_nombre": p['comercio_nombre'],
                "viajes": 0,
                "subtotal_efectivo": 0.0,
                "subtotal_delivery": 0.0,
                "pedidos": []
            }
        
        ef = float(p['monto_a_cobrar'] or 0)
        dl = float(p['costo_delivery'] or 0)
        
        agrupado[cid]['viajes'] += 1
        agrupado[cid]['subtotal_efectivo'] += ef
        agrupado[cid]['subtotal_delivery'] += dl
        agrupado[cid]['pedidos'].append({
            "id": p['id'],
            "hora_entrega": p['hora_entrega'].strftime('%d/%m %H:%M') if p['hora_entrega'] else 'N/A',
            "efectivo": ef,
            "delivery": dl
        })
        
        total_efectivo += ef
        total_delivery += dl
        
    return {
        "comercios": list(agrupado.values()),
        "totales": {
            "viajes": len(pedidos),
            "efectivo": total_efectivo,
            "delivery": total_delivery,
            "saldo": total_delivery - total_efectivo
        }
    }

@app.get("/api/liquidaciones/locales")
def resumen_liquidaciones_locales(desde: str, hasta: str):
    conn = get_db()
    cursor = conn.cursor()
    
    fecha_desde = f"{desde} 00:00:00"
    fecha_hasta = f"{hasta} 23:59:59"
    
    query = """
        SELECT 
            c.id as comercio_id,
            c.nombre as comercio_nombre,
            COUNT(p.id) as pedidos,
            COALESCE(SUM(p.monto_a_cobrar), 0) as total_efectivo_cobrado,
            COALESCE(SUM(p.costo_delivery), 0) as total_costo_delivery
        FROM comercios c
        LEFT JOIN pedidos p ON c.id = p.comercio_id 
            AND p.estado = 'entregado' 
            AND p.hora_entrega >= %s::timestamp 
            AND p.hora_entrega <= %s::timestamp
        WHERE c.estado = 'activo'
        GROUP BY c.id, c.nombre
        ORDER BY c.nombre
    """
    cursor.execute(query, (fecha_desde, fecha_hasta))
    locales = rows_to_list(cursor.fetchall())
    conn.close()
    
    # Calculamos el saldo a liquidar para cada local
    for loc in locales:
        ef = float(loc['total_efectivo_cobrado'] or 0)
        dl = float(loc['total_costo_delivery'] or 0)
        # Lo que se le debe liquidar al local = efectivo cobrado - costo delivery
        loc['saldo_liquidar'] = ef - dl
        
    return {"locales": locales}

# --- EJECUCIÓN LOCAL ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)