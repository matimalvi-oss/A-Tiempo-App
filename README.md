# Asistente de WhatsApp

Prototipo conversacional para los comercios de A Tiempo. El webhook valida la firma de Meta, guarda y deduplica cada mensaje, y un worker agrupa mensajes por conversación antes de llamar a Gemini. El precio de envío es fijo y provisorio; no se consulta Google Maps.

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

2. Copiar `.env.example` a `.env` y completar PostgreSQL, Meta, Gemini y WhatsApp. `TARIFA_PROVISORIA` es obligatorio y no tiene un precio de respaldo. No subir `.env` al repositorio. Los teléfonos deben cargarse en formato internacional, solo dígitos y separados por coma.
3. Ejecutar una vez la migración contra la misma base PostgreSQL configurada en `DATABASE_URL`:

   ```powershell
   psql $env:DATABASE_URL -f migrations\001_whatsapp_assistant.sql
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
2. Ejecutar `migrations/001_whatsapp_assistant.sql` una sola vez en la base vinculada antes de habilitar el webhook.
3. Cargar en Railway las variables de `.env.example`, incluyendo secretos solo en el panel de variables. `NUMEROS_PRUEBA` limita los remitentes a los que el bot procesa y responde; `NUMEROS_STAFF` es opcional, pero las alertas siempre quedan guardadas y consultables en `GET /api/bot/alertas`.
4. Registrar los comercios y teléfonos permitidos en `contactos_whatsapp`. Mantener una sola instancia de la app para este prototipo, ya que el worker y los recordatorios corren dentro del proceso web.

`RECORDATORIO_BORRADOR_MINUTOS` controla el primer recordatorio (15 por defecto); `ESCALAMIENTO_RECORDATORIO_MINUTOS` controla cuánto esperar después antes de pasar la conversación a una persona (15 por defecto). La respuesta inicial usa solo texto y debe enviarse dentro de la ventana permitida por Meta; no se implementan plantillas fuera de esa ventana.

El prompt editable está en `bot/system_prompt.md` y las respuestas frecuentes en `bot/preguntas_frecuentes.md`.
