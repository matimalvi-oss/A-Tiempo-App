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

# --- RUTAS PWA (Manifest y Service Worker en la raíz) ---
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
    cliente_nombre: str
    cliente_telefono: str
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
    
    cursor.execute("SELECT * FROM pedidos ORDER BY hora_pedido DESC")
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
    
    cursor.execute("SELECT id FROM clientes WHERE telefono = ?", (req.cliente_telefono,))
    cliente = cursor.fetchone()
    
    if cliente:
        cliente_id = cliente['id']
    else:
        cursor.execute("INSERT INTO clientes (nombre, telefono) VALUES (?, ?)", 
                      (req.cliente_nombre, req.cliente_telefono))
        cliente_id = cursor.lastrowid
    
    cursor.execute("SELECT direccion FROM comercios WHERE id = ?", (req.comercio_id,))
    comercio = cursor.fetchone()
    
    if not comercio:
        conn.close()
        raise HTTPException(404, "Comercio no encontrado")
    
    ahora = datetime.now()
    hora_estimada = ahora + timedelta(minutes=20)
    
    cursor.execute('''
        INSERT INTO pedidos 
        (comercio_id, cliente_id, rider_id, direccion_recogida, direccion_entrega, estado, 
         monto_a_cobrar, costo_delivery, pagado, hora_pedido, hora_estimada_retiro)
        VALUES (?, ?, NULL, ?, ?, 'pendiente', ?, ?, ?, ?, ?)
    ''', (req.comercio_id, cliente_id, comercio['direccion'], req.direccion_entrega,
          req.monto_a_cobrar, req.costo_delivery, int(req.pagado), ahora, hora_estimada))
    
    conn.commit()
    pedido_id = cursor.lastrowid
    conn.close()
    
    return {"message": "Pedido creado", "pedido_id": pedido_id}

@app.post("/api/pedidos/{pedido_id}/asignar")
def asignar_rider(pedido_id: int, req: AssignRiderRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM pedidos WHERE id = ?", (pedido_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "Pedido no encontrado")
    
    cursor.execute("SELECT id FROM riders WHERE id = ?", (req.rider_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "Rider no encontrado")
    
    cursor.execute("UPDATE pedidos SET rider_id = ?, estado = 'asignado' WHERE id = ?", 
                  (req.rider_id, pedido_id))
    cursor.execute("UPDATE riders SET estado = 'en_viaje' WHERE id = ?", (req.rider_id,))
    
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
        cursor.execute("UPDATE pedidos SET estado = ?, hora_real_retiro = ? WHERE id = ?",
                      (req.nuevo_estado, ahora, pedido_id))
    elif req.nuevo_estado == "entregado":
        cursor.execute("UPDATE pedidos SET estado = ?, hora_entrega = ? WHERE id = ?",
                      (req.nuevo_estado, ahora, pedido_id))
        cursor.execute("SELECT rider_id FROM pedidos WHERE id = ?", (pedido_id,))
        pedido = cursor.fetchone()
        if pedido and pedido['rider_id']:
            cursor.execute("UPDATE riders SET estado = 'disponible' WHERE id = ?", (pedido['rider_id'],))
    else:
        cursor.execute("UPDATE pedidos SET estado = ? WHERE id = ?",
                      (req.nuevo_estado, pedido_id))
    
    conn.commit()
    conn.close()
    
    return {"message": "Estado actualizado"}

# --- ENDPOINTS: COMERCIOS ---

@app.post("/api/comercios")
def crear_comercio(req: CreateComercioRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("INSERT INTO comercios (nombre, direccion, telefono) VALUES (?, ?, ?)",
                  (req.nombre, req.direccion, req.telefono))
    
    conn.commit()
    comercio_id = cursor.lastrowid
    conn.close()
    
    return {"message": "Comercio creado", "comercio_id": comercio_id}

@app.put("/api/comercios/{comercio_id}")
def actualizar_comercio(comercio_id: int, req: UpdateComercioRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM comercios WHERE id = ?", (comercio_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "Comercio no encontrado")
    
    updates = []
    params = []
    
    if req.nombre is not None:
        updates.append("nombre = ?")
        params.append(req.nombre)
    if req.direccion is not None:
        updates.append("direccion = ?")
        params.append(req.direccion)
    if req.telefono is not None:
        updates.append("telefono = ?")
        params.append(req.telefono)
    
    if updates:
        params.append(comercio_id)
        cursor.execute(f"UPDATE comercios SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    
    conn.close()
    return {"message": "Comercio actualizado"}

@app.delete("/api/comercios/{comercio_id}")
def eliminar_comercio(comercio_id: int):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM comercios WHERE id = ?", (comercio_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "Comercio no encontrado")
    
    cursor.execute("SELECT id FROM pedidos WHERE comercio_id = ? AND estado != 'entregado'", (comercio_id,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(400, "No se puede eliminar: tiene pedidos activos")
    
    cursor.execute("UPDATE comercios SET estado = 'inactivo' WHERE id = ?", (comercio_id,))
    conn.commit()
    conn.close()
    
    return {"message": "Comercio eliminado"}

# --- ENDPOINTS: RIDERS ---

@app.post("/api/riders")
def crear_rider(req: CreateRiderRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("INSERT INTO riders (nombre, telefono, vehiculo, estado) VALUES (?, ?, ?, 'disponible')",
                  (req.nombre, req.telefono, req.vehiculo))
    
    conn.commit()
    rider_id = cursor.lastrowid
    conn.close()
    
    return {"message": "Rider creado", "rider_id": rider_id}

@app.put("/api/riders/{rider_id}")
def actualizar_rider(rider_id: int, req: UpdateRiderRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM riders WHERE id = ?", (rider_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "Rider no encontrado")
    
    updates = []
    params = []
    
    if req.nombre is not None:
        updates.append("nombre = ?")
        params.append(req.nombre)
    if req.telefono is not None:
        updates.append("telefono = ?")
        params.append(req.telefono)
    if req.vehiculo is not None:
        updates.append("vehiculo = ?")
        params.append(req.vehiculo)
    if req.estado is not None:
        updates.append("estado = ?")
        params.append(req.estado)
    
    if updates:
        params.append(rider_id)
        cursor.execute(f"UPDATE riders SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    
    conn.close()
    return {"message": "Rider actualizado"}

@app.delete("/api/riders/{rider_id}")
def eliminar_rider(rider_id: int):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM riders WHERE id = ?", (rider_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(404, "Rider no encontrado")
    
    cursor.execute("SELECT id FROM pedidos WHERE rider_id = ? AND estado != 'entregado'", (rider_id,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(400, "No se puede eliminar: tiene pedidos activos asignados")
    
    cursor.execute("DELETE FROM riders WHERE id = ?", (rider_id,))
    conn.commit()
    conn.close()
    
    return {"message": "Rider eliminado"}

@app.put("/api/pedidos/{pedido_id}")
def actualizar_pedido(pedido_id: int, req: UpdateOrderRequest):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM pedidos WHERE id = ?", (pedido_id,))
    pedido = cursor.fetchone()
    if not pedido:
        conn.close()
        raise HTTPException(404, "Pedido no encontrado")
    
    updates = []
    params = []
    
    if req.cliente_nombre is not None or req.cliente_telefono is not None:
        cursor.execute("UPDATE clientes SET nombre = COALESCE(?, nombre), telefono = COALESCE(?, telefono) WHERE id = ?", 
                      (req.cliente_nombre, req.cliente_telefono, pedido['cliente_id']))
    
    if req.direccion_entrega is not None:
        updates.append("direccion_entrega = ?")
        params.append(req.direccion_entrega)
    if req.monto_a_cobrar is not None:
        updates.append("monto_a_cobrar = ?")
        params.append(req.monto_a_cobrar)
    if req.costo_delivery is not None:
        updates.append("costo_delivery = ?")
        params.append(req.costo_delivery)
    if req.pagado is not None:
        updates.append("pagado = ?")
        params.append(int(req.pagado))
    if req.rider_id is not None:
        updates.append("rider_id = ?")
        params.append(req.rider_id)
        
    if req.estado is not None:
        updates.append("estado = ?")
        params.append(req.estado)
        
        if req.estado == 'entregado' or req.rider_id is None:
            if pedido['rider_id']:
                cursor.execute("UPDATE riders SET estado = 'disponible' WHERE id = ?", (pedido['rider_id'],))
        
        ahora = datetime.now()
        if req.estado == 'retirado' and not pedido['hora_real_retiro']:
            updates.append("hora_real_retiro = ?")
            params.append(ahora)
        elif req.estado == 'entregado' and not pedido['hora_entrega']:
            updates.append("hora_entrega = ?")
            params.append(ahora)
    
    if updates:
        params.append(pedido_id)
        cursor.execute(f"UPDATE pedidos SET {', '.join(updates)} WHERE id = ?", params)
    
    conn.commit()
    conn.close()
    return {"message": "Pedido actualizado"}

# --- ENDPOINTS: ELIMINAR PEDIDOS ---

@app.delete("/api/pedidos/limpiar-entregados")
def limpiar_pedidos_entregados():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pedidos WHERE estado = 'entregado'")
    conn.commit()
    conn.close()
    return {"message": "Pedidos entregados eliminados"}

@app.delete("/api/pedidos/{pedido_id}")
def eliminar_pedido(pedido_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM pedidos WHERE id = ?", (pedido_id,))
    conn.commit()
    conn.close()
    return {"message": "Pedido eliminado"}

# --- EJECUCIÓN LOCAL (no se usa en Railway) ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    uvicorn.run(app, host="0.0.0.0", port=port)
