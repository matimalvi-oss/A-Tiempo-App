import os
import psycopg2
from psycopg2.extras import RealDictCursor

def get_db():
    # Obtiene la URL de la variable de entorno de Railway
    database_url = os.environ.get("DATABASE_URL")
    
    # Conecta a PostgreSQL usando un cursor que devuelve diccionarios
    conn = psycopg2.connect(
        database_url,
        cursor_factory=RealDictCursor
    )
    return conn

def init_db():
    """Crea las tablas si no existen"""
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS comercios (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                direccion VARCHAR(200),
                telefono VARCHAR(50),
                estado VARCHAR(20) DEFAULT 'activo'
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clientes (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                telefono VARCHAR(50) UNIQUE
            )
        """)
        cursor.execute("ALTER TABLE clientes ALTER COLUMN telefono DROP NOT NULL")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS riders (
                id SERIAL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                telefono VARCHAR(50),
                vehiculo VARCHAR(50),
                estado VARCHAR(20) DEFAULT 'disponible'
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pedidos (
                id SERIAL PRIMARY KEY,
                comercio_id INT REFERENCES comercios(id),
                cliente_id INT REFERENCES clientes(id),
                rider_id INT REFERENCES riders(id),
                direccion_recogida VARCHAR(200),
                direccion_entrega VARCHAR(200),
                estado VARCHAR(50) DEFAULT 'pendiente',
                monto_a_cobrar DECIMAL(10,2) DEFAULT 0.0,
                costo_delivery DECIMAL(10,2) DEFAULT 0.0,
                pagado BOOLEAN DEFAULT FALSE,
                hora_pedido TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hora_estimada_retiro TIMESTAMP,
                hora_real_retiro TIMESTAMP,
                hora_entrega TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS whatsapp_messages (
                message_id TEXT PRIMARY KEY,
                sender_wa_id TEXT NOT NULL,
                phone_number_id TEXT,
                message_type TEXT NOT NULL,
                message_timestamp TEXT,
                text_body TEXT,
                message_data JSONB NOT NULL,
                received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        print("✅ Base de datos PostgreSQL inicializada correctamente.")
        
    except Exception as e:
        print(f"❌ Error al inicializar la base de datos: {e}")
        conn.rollback()
    finally:
        conn.close()

# Como RealDictCursor ya devuelve diccionarios, estas funciones son compatibles
def row_to_dict(row):
    return dict(row) if row else None

def rows_to_list(rows):
    return [dict(row) for row in rows]