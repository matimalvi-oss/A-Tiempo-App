# database.py
import sqlite3
from datetime import datetime, timedelta

DATABASE = 'delivery.db'

def get_db():
    """Obtener conexión a la base de datos"""
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row  # Para acceder a las columnas por nombre
    return conn

def init_db():
    """Inicializar la base de datos con las tablas y datos de prueba"""
    conn = get_db()
    cursor = conn.cursor()
    
    # Crear tablas
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS comercios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre VARCHAR(150) NOT NULL,
            direccion VARCHAR(255) NOT NULL,
            telefono VARCHAR(30) NOT NULL,
            estado VARCHAR(20) DEFAULT 'activo',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS riders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre VARCHAR(100) NOT NULL,
            telefono VARCHAR(30) NOT NULL,
            vehiculo VARCHAR(30) DEFAULT 'Moto',
            estado VARCHAR(30) DEFAULT 'disponible',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS clientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre VARCHAR(100) NOT NULL,
            telefono VARCHAR(30) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pedidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            comercio_id INTEGER NOT NULL,
            cliente_id INTEGER NOT NULL,
            rider_id INTEGER,
            direccion_recogida VARCHAR(255) NOT NULL,
            direccion_entrega VARCHAR(255) NOT NULL,
            estado VARCHAR(30) DEFAULT 'pendiente',
            monto_a_cobrar DECIMAL(10, 2) DEFAULT 0.00,
            costo_delivery DECIMAL(10, 2) NOT NULL,
            pagado BOOLEAN DEFAULT 0,
            hora_pedido TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            hora_estimada_retiro TIMESTAMP,
            hora_real_retiro TIMESTAMP,
            hora_entrega TIMESTAMP,
            FOREIGN KEY (comercio_id) REFERENCES comercios(id),
            FOREIGN KEY (cliente_id) REFERENCES clientes(id),
            FOREIGN KEY (rider_id) REFERENCES riders(id)
        );
    ''')
    
    # Verificar si ya hay datos (para no duplicar)
    cursor.execute("SELECT COUNT(*) FROM comercios")
    if cursor.fetchone()[0] == 0:
        # Insertar datos de prueba
        cursor.executescript('''
            INSERT INTO comercios (nombre, direccion, telefono) VALUES
            ('Pizzería Don Pepe', 'Av. Siempre Viva 123', '555-1001'),
            ('Sushi Master', 'Calle Falsa 456', '555-1002');

            INSERT INTO clientes (nombre, telefono) VALUES
            ('Juan Pérez', '555-0101'),
            ('María Gómez', '555-0102');

            INSERT INTO riders (nombre, telefono, vehiculo, estado) VALUES
            ('Carlos M.', '555-0201', 'Moto', 'disponible'),
            ('Ana T.', '555-0202', 'Bicicleta', 'en_viaje');

            INSERT INTO pedidos (comercio_id, cliente_id, rider_id, direccion_recogida, direccion_entrega, estado, monto_a_cobrar, costo_delivery, pagado, hora_pedido, hora_estimada_retiro) VALUES
            (1, 1, NULL, 'Av. Siempre Viva 123', 'Calle 1 234', 'pendiente', 5000.00, 1500.00, 0, datetime('now', '-15 minutes'), datetime('now', '-5 minutes')),
            (2, 2, 2, 'Calle Falsa 456', 'Blvd. Central 789', 'en_camino_comercio', 0.00, 2000.00, 1, datetime('now', '-30 minutes'), datetime('now', '-10 minutes'));
        ''')
    
    conn.commit()
    conn.close()

def row_to_dict(row):
    """Convertir una fila de SQLite a diccionario"""
    if row is None:
        return None
    return dict(row)

def rows_to_list(rows):
    """Convertir múltiples filas a lista de diccionarios"""
    return [dict(row) for row in rows]