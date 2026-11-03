# Asistente de WhatsApp

Prototipo conversacional para los comercios de A Tiempo. El webhook valida la firma de Meta, guarda y deduplica cada mensaje, y un worker agrupa mensajes por conversación antes de llamar a Gemini. La tarifa se calcula con el recorrido en auto de Google Maps y una tabla de distancias configurable en PostgreSQL.

Las horas de entrega sin fecha se interpretan en `America/Argentina/Mendoza`: si la hora todavía no pasó, se agenda para hoy; si ya pasó, para el día siguiente. El asistente recibe la fecha y hora local actual y debe enviar una hora simple como `23:00` sin inventar una fecha.

La tarifa se calcula con el recorrido en auto de Google Maps desde `comercios.direccion` hasta la dirección o ubicación del cliente. La tabla común inicial es: hasta 2,8 km $3.000; más de 2,8 y hasta 4 km $3.500; y luego tramos hasta 9 km que suben $500 por km, hasta $6.000. Más de 9 km o una ruta no disponible se deriva a una persona sin cotizar. El recargo por lluvia agrega 50% y queda apagado hasta activarlo manualmente en PostgreSQL. Las zonas de cobertura siguen pendientes de definir.

## Local

1. Crear un entorno virtual e instalar dependencias:

   ```powershell
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

   Si preferís activarlo en PowerShell y la ejecución de scripts está bloqueada, podés habilitarla solo para esa sesión (no cambia la política permanente del equipo) y activar el entorno:

   ```powershell
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .venv\Scripts\Activate.ps1
   ```

2. Copiar `.env.example` a `.env` y completar PostgreSQL, Meta, Gemini, Google Maps y WhatsApp. No subir `.env` al repositorio. Los teléfonos deben cargarse en formato internacional, solo dígitos y separados por coma.
3. Ejecutar las migraciones, en orden, una vez contra la misma base PostgreSQL configurada en `DATABASE_URL`:

   ```powershell
   psql $env:DATABASE_URL -f migrations\001_whatsapp_assistant.sql
   psql $env:DATABASE_URL -f migrations\002_delivery_tariffs.sql
   ```

   La migración convierte los timestamps preexistentes sin zona interpretándolos como UTC. La app fija la zona de sesión PostgreSQL en `America/Argentina/Mendoza`.
4. Cargar cada número de comercio habilitado en `contactos_whatsapp` y agregarlo también a `NUMEROS_PRUEBA`. Por ejemplo, en una consola SQL:

   ```sql
   INSERT INTO contactos_whatsapp (numero, comercio_id, nombre)
   VALUES ('5492604000000', 1, 'Local de prueba');
   ```

5. Iniciar el servicio:

   ```powershell
   .venv\Scripts\python.exe -m uvicorn main:app --reload
   ```

## Pruebas

Las pruebas usan un simulador del ciclo de Gemini y no llaman a Meta, WhatsApp ni Gemini:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Configurar el webhook de Meta en `/webhooks/meta/whatsapp`, usando `META_WEBHOOK_VERIFY_TOKEN` y `META_APP_SECRET`. El endpoint responde después de persistir los mensajes; el worker los procesa cuando transcurre `DEBOUNCE_SEGUNDOS`.

## Railway

1. Desplegar el servicio con el `Procfile` existente y vincular Railway PostgreSQL.
2. Ejecutar `migrations/001_whatsapp_assistant.sql` y `migrations/002_delivery_tariffs.sql`, en ese orden, una sola vez en la base vinculada antes de habilitar el webhook.
3. Cargar en Railway las variables de `.env.example`, incluyendo secretos solo en el panel de variables. `GOOGLE_MAPS_API_KEY` debe tener habilitada Google Routes API y facturación. `NUMEROS_PRUEBA` limita los remitentes a los que el bot procesa y responde; `NUMEROS_STAFF` es opcional, pero las alertas siempre quedan guardadas y consultables en `GET /api/bot/alertas`.
4. Registrar los comercios y teléfonos permitidos en `contactos_whatsapp`. Mantener una sola instancia de la app para este prototipo, ya que el worker y los recordatorios corren dentro del proceso web.

`RECORDATORIO_BORRADOR_MINUTOS` controla el primer recordatorio (15 por defecto); `ESCALAMIENTO_RECORDATORIO_MINUTOS` controla cuánto esperar después antes de pasar la conversación a una persona (15 por defecto). La respuesta inicial usa solo texto y debe enviarse dentro de la ventana permitida por Meta; no se implementan plantillas fuera de esa ventana.

Para activar manualmente el recargo del 50% por lluvia, ejecutar en PostgreSQL:

```sql
UPDATE bot_configuracion
SET valor = 'true'
WHERE clave = 'recargo_lluvia_activo';
```

Para desactivarlo, cambiar el valor a `'false'`. El cambio se aplica a nuevas cotizaciones y confirmaciones, sin reiniciar Railway; los pedidos ya confirmados no se recalculan. El origen de cada recorrido se toma de `comercios.direccion`, por lo que esa dirección debe estar completa y ser ubicable en Google Maps.

El prompt editable está en `bot/system_prompt.md` y las respuestas frecuentes en `bot/preguntas_frecuentes.md`.
