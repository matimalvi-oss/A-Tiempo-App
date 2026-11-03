-- Distance-based delivery tariffs and manually controlled rain surcharge.
-- Apply once after 001_whatsapp_assistant.sql.

CREATE TABLE IF NOT EXISTS bot_tarifas_distancia (
    limite_km NUMERIC(5, 1) PRIMARY KEY CHECK (limite_km > 0),
    monto NUMERIC(12, 2) NOT NULL CHECK (monto >= 0)
);

INSERT INTO bot_tarifas_distancia (limite_km, monto)
VALUES
    (2.8, 3000),
    (4.0, 3500),
    (5.0, 4000),
    (6.0, 4500),
    (7.0, 5000),
    (8.0, 5500),
    (9.0, 6000)
ON CONFLICT (limite_km) DO NOTHING;

CREATE TABLE IF NOT EXISTS bot_configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

INSERT INTO bot_configuracion (clave, valor)
VALUES ('recargo_lluvia_activo', 'false')
ON CONFLICT (clave) DO NOTHING;
