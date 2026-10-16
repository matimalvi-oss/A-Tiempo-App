import os
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor

# Crear un pool de conexiones (mínimo 1, máximo 10 conexiones simultáneas)
db_pool = pool.SimpleConnectionPool(
    1, 10,
    os.environ.get("DATABASE_URL")
)

def get_db():
    # Obtiene una conexión del pool
    return db_pool.getconn()

def release_db(conn):
    # Devuelve la conexión al pool en lugar de cerrarla
    db_pool.putconn(conn)

def init_db():
    """Crea las tablas si no existen"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # ... (MANTÉN TODOS TUS CREATE TABLE IGUAL QUE ANTES) ...
        cursor.execute("""CREATE TABLE IF NOT EXISTS comercios (id SERIAL PRIMARY KEY, nombre VARCHAR(100) NOT NULL, direccion VARCHAR(200), telefono VARCHAR(50), estado VARCHAR(20) DEFAULT 'activo')""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS clientes (id SERIAL PRIMARY KEY, nombre VARCHAR(100) NOT NULL, telefono VARCHAR(50) UNIQUE NOT NULL)""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS riders (id SERIAL PRIMARY KEY, nombre VARCHAR(100) NOT NULL, telefono VARCHAR(50), vehiculo VARCHAR(50), estado VARCHAR(20) DEFAULT 'disponible')""")
        cursor.execute("""CREATE TABLE IF NOT EXISTS pedidos (id SERIAL PRIMARY KEY, comercio_id INT REFERENCES comercios(id), cliente_id INT REFERENCES clientes(id), rider_id INT REFERENCES riders(id), direccion_recogida VARCHAR(200), direccion_entrega VARCHAR(200), estado VARCHAR(50) DEFAULT 'pendiente', monto_a_cobrar DECIMAL(10,2) DEFAULT 0.0, costo_delivery DECIMAL(10,2) DEFAULT 0.0, pagado BOOLEAN DEFAULT FALSE, hora_pedido TIMESTAMP DEFAULT CURRENT_TIMESTAMP, hora_estimada_retiro TIMESTAMP, hora_real_retiro TIMESTAMP, hora_entrega TIMESTAMP)""")
        
        conn.commit()
        print("✅ Base de datos PostgreSQL inicializada correctamente.")
    except Exception as e:
        print(f"❌ Error al inicializar la base de datos: {e}")
        conn.rollback()
    finally:
        release_db(conn) # <-- USAR RELEASE EN LUGAR DE CLOSE

# Como RealDictCursor ya devuelve diccionarios, estas funciones son redundantes,
# pero las dejamos por compatibilidad con tu main.py
def row_to_dict(row):
    return dict(row) if row else None

def rows_to_list(rows):
    return [dict(row) for row in rows]