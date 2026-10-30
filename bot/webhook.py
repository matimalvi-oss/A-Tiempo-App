import asyncio
import hashlib
import hmac
import json
import os
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from psycopg2.extras import Json

from database import get_db


router = APIRouter()


def _normalize_number(value: str) -> str:
    return re.sub(r"\D", "", value)


def _extract_messages(payload: dict) -> list[dict]:
    if payload.get("object") != "whatsapp_business_account":
        return []
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        raise HTTPException(400, "Formato de entradas del webhook inválido")

    inbound = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise HTTPException(400, "Formato de entrada del webhook inválido")
        changes = entry.get("changes", [])
        if not isinstance(changes, list):
            raise HTTPException(400, "Formato de cambios del webhook inválido")
        for change in changes:
            if not isinstance(change, dict):
                raise HTTPException(400, "Formato de cambio del webhook inválido")
            value = change.get("value", {})
            if not isinstance(value, dict):
                raise HTTPException(400, "Formato de valor del webhook inválido")
            messages = value.get("messages", [])
            if not isinstance(messages, list):
                raise HTTPException(400, "Formato de mensajes del webhook inválido")
            if not messages:
                continue
            metadata = value.get("metadata", {})
            phone_number_id = metadata.get("phone_number_id") if isinstance(metadata, dict) else None
            if not isinstance(phone_number_id, str) or not phone_number_id.isdigit():
                raise HTTPException(400, "Falta un phone_number_id válido")
            for message in messages:
                if not isinstance(message, dict):
                    raise HTTPException(400, "Formato de mensaje del webhook inválido")
                message_id = message.get("id")
                sender = message.get("from")
                message_type = message.get("type")
                if not all(
                    isinstance(item, str) and item
                    for item in (message_id, sender, message_type)
                ):
                    raise HTTPException(400, "Faltan datos obligatorios del mensaje")
                timestamp = message.get("timestamp")
                if timestamp is not None and not isinstance(timestamp, str):
                    raise HTTPException(400, "Formato de timestamp del mensaje inválido")
                context = message.get("context", {})
                context_id: Optional[str] = None
                if isinstance(context, dict) and isinstance(context.get("id"), str):
                    context_id = context["id"]
                inbound.append(
                    {
                        "message_id": message_id,
                        "sender": _normalize_number(sender),
                        "phone_number_id": phone_number_id,
                        "type": message_type,
                        "timestamp": timestamp,
                        "context_id": context_id,
                        "message": message,
                    }
                )
    return inbound


def enqueue_inbound_messages(messages: list[dict]) -> int:
    if not messages:
        return 0
    test_numbers = {
        _normalize_number(number.strip())
        for number in os.environ.get("NUMEROS_PRUEBA", "").split(",")
        if number.strip()
    }
    conn = get_db()
    queued = 0
    try:
        cursor = conn.cursor()
        for item in messages:
            cursor.execute(
                """
                INSERT INTO whatsapp_messages (
                    message_id, sender_wa_id, phone_number_id, message_type,
                    message_timestamp, text_body, message_data
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_id) DO NOTHING
                RETURNING message_id
                """,
                (
                    item["message_id"],
                    item["sender"],
                    item["phone_number_id"],
                    item["type"],
                    item["timestamp"],
                    item["message"].get("text", {}).get("body")
                    if isinstance(item["message"].get("text"), dict)
                    else None,
                    Json(item["message"]),
                ),
            )
            if not cursor.fetchone():
                continue

            sender = item["sender"]
            if not sender:
                print(
                    f"BOT_INBOUND ignored message_id={item['message_id']} reason=invalid_sender",
                    flush=True,
                )
                continue
            cursor.execute(
                """
                SELECT id, comercio_id
                FROM contactos_whatsapp
                WHERE numero = %s
                """,
                (sender,),
            )
            contact = cursor.fetchone()
            if not contact:
                print(
                    f"BOT_INBOUND ignored message_id={item['message_id']} reason=unknown_contact",
                    flush=True,
                )
                continue
            if sender not in test_numbers:
                print(
                    f"BOT_INBOUND ignored message_id={item['message_id']} reason=outside_test_list",
                    flush=True,
                )
                continue

            cursor.execute(
                """
                INSERT INTO conversaciones (
                    comercio_id, contacto_whatsapp_id, ultimo_mensaje_at
                )
                VALUES (%s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (contacto_whatsapp_id)
                DO UPDATE SET ultimo_mensaje_at = CURRENT_TIMESTAMP
                RETURNING id, modo
                """,
                (contact["comercio_id"], contact["id"]),
            )
            conversation = cursor.fetchone()
            cursor.execute(
                """
                INSERT INTO mensajes (
                    conversacion_id, wa_message_id, direccion, tipo,
                    contenido, context_wa_message_id
                )
                VALUES (%s, %s, 'entrada', %s, %s, %s)
                ON CONFLICT (wa_message_id) DO NOTHING
                """,
                (
                    conversation["id"],
                    item["message_id"],
                    item["type"],
                    Json(item["message"]),
                    item["context_id"],
                ),
            )
            if cursor.rowcount:
                queued += 1
            if conversation["modo"] == "humano":
                print(
                    f"BOT_INBOUND stored message_id={item['message_id']} "
                    f"conversation_id={conversation['id']} mode=human",
                    flush=True,
                )
            else:
                cursor.execute(
                    """
                    UPDATE pedidos
                    SET bot_ultimo_movimiento_at = CURRENT_TIMESTAMP,
                        bot_recordatorio_enviado_at = NULL,
                        bot_alerta_enviada_at = NULL
                    WHERE bot_conversacion_id = %s AND estado = 'borrador'
                    """,
                    (conversation["id"],),
                )
        conn.commit()
        return queued
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@router.get("/webhooks/meta/whatsapp")
async def verificar_webhook_whatsapp(request: Request):
    verify_token = os.environ.get("META_WEBHOOK_VERIFY_TOKEN")
    if not verify_token:
        raise HTTPException(503, "Falta configurar META_WEBHOOK_VERIFY_TOKEN")
    params = request.query_params
    if params.get("hub.mode") != "subscribe" or not hmac.compare_digest(
        params.get("hub.verify_token", "").encode("utf-8"),
        verify_token.encode("utf-8"),
    ):
        raise HTTPException(403, "Verificación de webhook rechazada")
    challenge = params.get("hub.challenge")
    if challenge is None:
        raise HTTPException(400, "Falta el parámetro hub.challenge")
    return PlainTextResponse(challenge)


@router.post("/webhooks/meta/whatsapp")
async def recibir_webhook_whatsapp(request: Request):
    app_secret = os.environ.get("META_APP_SECRET")
    if not app_secret:
        raise HTTPException(503, "Falta configurar META_APP_SECRET")

    body = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")
    expected_signature = "sha256=" + hmac.new(
        app_secret.encode("utf-8"), body, digestmod=hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise HTTPException(401, "Firma de webhook inválida")

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise HTTPException(400, "El cuerpo del webhook no es JSON válido") from error
    if not isinstance(payload, dict):
        raise HTTPException(400, "El cuerpo del webhook debe ser un objeto JSON")
    if payload.get("object") != "whatsapp_business_account":
        print("WHATSAPP_WEBHOOK ignored unsupported object", flush=True)
        return {"status": "ignored"}

    inbound = _extract_messages(payload)
    queued = await asyncio.to_thread(enqueue_inbound_messages, inbound)
    return {"status": "received", "queued": queued}
