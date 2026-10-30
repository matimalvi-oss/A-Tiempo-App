-- WhatsApp assistant schema. Run once against the existing PostgreSQL database.
-- Existing TIMESTAMP values are interpreted as UTC (Railway's default).

CREATE TABLE IF NOT EXISTS contactos_whatsapp (
    id BIGSERIAL PRIMARY KEY,
    numero TEXT NOT NULL UNIQUE,
    comercio_id INTEGER NOT NULL REFERENCES comercios(id),
    nombre TEXT,
    creado_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversaciones (
    id BIGSERIAL PRIMARY KEY,
    comercio_id INTEGER NOT NULL REFERENCES comercios(id),
    contacto_whatsapp_id BIGINT NOT NULL UNIQUE
        REFERENCES contactos_whatsapp(id),
    modo TEXT NOT NULL DEFAULT 'bot'
        CHECK (modo IN ('bot', 'humano')),
    ultimo_mensaje_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    bienvenida_enviada BOOLEAN NOT NULL DEFAULT FALSE,
    creada_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mensajes (
    id BIGSERIAL PRIMARY KEY,
    conversacion_id BIGINT NOT NULL REFERENCES conversaciones(id),
    wa_message_id TEXT NOT NULL UNIQUE,
    direccion TEXT NOT NULL CHECK (direccion IN ('entrada', 'salida')),
    tipo TEXT NOT NULL,
    contenido JSONB NOT NULL,
    context_wa_message_id TEXT,
    creado_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    procesado_at TIMESTAMPTZ,
    procesando_at TIMESTAMPTZ,
    pedido_id BIGINT REFERENCES pedidos(id)
);

CREATE TABLE IF NOT EXISTS bot_logs (
    id BIGSERIAL PRIMARY KEY,
    conversacion_id BIGINT NOT NULL REFERENCES conversaciones(id),
    mensajes_recibidos JSONB NOT NULL DEFAULT '[]'::jsonb,
    herramientas JSONB NOT NULL DEFAULT '[]'::jsonb,
    respuesta_enviada TEXT,
    duracion_ms BIGINT,
    error TEXT,
    creado_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bot_alertas (
    id BIGSERIAL PRIMARY KEY,
    conversacion_id BIGINT REFERENCES conversaciones(id),
    comercio_id INTEGER REFERENCES comercios(id),
    motivo TEXT NOT NULL,
    notificada BOOLEAN NOT NULL DEFAULT FALSE,
    notificada_at TIMESTAMPTZ,
    creada_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE pedidos
    ADD COLUMN IF NOT EXISTS referencia TEXT,
    ADD COLUMN IF NOT EXISTS ubicacion_url TEXT,
    ADD COLUMN IF NOT EXISTS latitud NUMERIC(10, 7),
    ADD COLUMN IF NOT EXISTS longitud NUMERIC(10, 7),
    ADD COLUMN IF NOT EXISTS hora_entrega_solicitada TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS forma_pago TEXT,
    ADD COLUMN IF NOT EXISTS paga_con NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS notas TEXT,
    ADD COLUMN IF NOT EXISTS mensaje_original TEXT,
    ADD COLUMN IF NOT EXISTS bot_conversacion_id BIGINT
        REFERENCES conversaciones(id),
    ADD COLUMN IF NOT EXISTS bot_ultimo_movimiento_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS bot_recordatorio_enviado_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS bot_alerta_enviada_at TIMESTAMPTZ;

DO $$
DECLARE
    columna RECORD;
BEGIN
    FOR columna IN
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'pedidos'
          AND data_type = 'timestamp without time zone'
          AND column_name IN (
              'hora_pedido',
              'hora_estimada_retiro',
              'hora_real_retiro',
              'hora_entrega'
          )
    LOOP
        EXECUTE format(
            'ALTER TABLE pedidos ALTER COLUMN %I TYPE TIMESTAMPTZ USING %I AT TIME ZONE %L',
            columna.column_name,
            columna.column_name,
            'UTC'
        );
    END LOOP;
END $$;

CREATE INDEX IF NOT EXISTS idx_conversaciones_debounce
    ON conversaciones (ultimo_mensaje_at)
    WHERE modo = 'bot';

CREATE INDEX IF NOT EXISTS idx_mensajes_pendientes
    ON mensajes (conversacion_id, creado_at)
    WHERE direccion = 'entrada' AND procesado_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_pedidos_borradores_bot
    ON pedidos (comercio_id, hora_pedido)
    WHERE estado = 'borrador';

CREATE INDEX IF NOT EXISTS idx_bot_alertas_creada_at
    ON bot_alertas (creada_at DESC);
