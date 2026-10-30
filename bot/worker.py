import asyncio
import json
import os
import time
from datetime import datetime
from typing import Any

from psycopg2.extras import Json

from database import get_db

from .agent import ConversationAgent
from .tools import BotTools, PostgresBotRepository
from .whatsapp_client import WhatsAppDeliveryError, enviar_texto


SUPPORTED_TYPES = {"text", "location", "contacts", "interactive"}


def _render_message(message: dict) -> str:
    content = message.get("contenido") or {}
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            content = {}
    if not isinstance(content, dict):
        content = {}

    message_type = message.get("tipo", "")
    if message_type == "text":
        value = content.get("text", {})
        text = value.get("body", "") if isinstance(value, dict) else ""
    elif message_type == "location":
        value = content.get("location", {})
        if not isinstance(value, dict):
            value = {}
        text = (
            "Ubicación compartida: "
            f"latitud={value.get('latitude')}, longitud={value.get('longitude')}, "
            f"nombre={value.get('name') or ''}, dirección={value.get('address') or ''}"
        )
    elif message_type == "contacts":
        contacts = content.get("contacts", [])
        parsed = []
        if isinstance(contacts, list):
            for contact in contacts:
                if not isinstance(contact, dict):
                    continue
                name = contact.get("name", {})
                formatted_name = (
                    name.get("formatted_name", "")
                    if isinstance(name, dict)
                    else ""
                )
                phones = contact.get("phones", [])
                numbers = [
                    phone.get("phone", "")
                    for phone in phones
                    if isinstance(phone, dict)
                ] if isinstance(phones, list) else []
                parsed.append(
                    f"{formatted_name} {' '.join(number for number in numbers if number)}"
                )
        text = "Contacto compartido: " + "; ".join(parsed)
    elif message_type == "interactive":
        interactive = content.get("interactive", {})
        if not isinstance(interactive, dict):
            interactive = {}
        reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
        text = (
            f"Respuesta interactiva: {reply.get('title') or reply.get('id') or ''}"
            if isinstance(reply, dict)
            else "Respuesta interactiva recibida."
        )
    else:
        text = f"Mensaje de tipo {message_type} que el asistente todavía no puede leer."

    context_id = message.get("context_wa_message_id")
    context_order_id = message.get("context_pedido_id")
    message_id = message.get("wa_message_id")
    prefix = f"[mensaje {message_id or 'sin id'}]"
    if context_id:
        prefix += f" [responde a {context_id}]"
    if context_order_id:
        prefix += f" [pedido asociado #{context_order_id}]"
    return f"{prefix} {text}".strip()


def _history(conversation_id: int) -> list[dict]:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT m.wa_message_id, m.direccion, m.tipo, m.contenido,
                   m.context_wa_message_id, referenciado.pedido_id AS context_pedido_id
            FROM mensajes m
            LEFT JOIN mensajes referenciado
              ON referenciado.wa_message_id = m.context_wa_message_id
            WHERE m.conversacion_id = %s
            ORDER BY m.id DESC
            LIMIT 20
            """,
            (conversation_id,),
        )
        rows = [dict(row) for row in cursor.fetchall()]
        rows.reverse()
        return [
            {
                "role": "user" if row["direccion"] == "entrada" else "model",
                "text": _render_message(row),
            }
            for row in rows
        ]
    finally:
        conn.close()


def _conversation_context(conversation_id: int) -> dict:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT c.id, c.comercio_id, c.modo, c.bienvenida_enviada,
                   co.nombre AS comercio, ct.numero AS telefono
            FROM conversaciones c
            JOIN comercios co ON co.id = c.comercio_id
            JOIN contactos_whatsapp ct ON ct.id = c.contacto_whatsapp_id
            WHERE c.id = %s
            """,
            (conversation_id,),
        )
        result = cursor.fetchone()
        if not result:
            raise RuntimeError(f"No existe la conversación {conversation_id}.")
        return dict(result)
    finally:
        conn.close()


def _save_outgoing(
    conversation_id: int,
    phone: str,
    message: str,
    welcome_pending: bool,
    order_id: int = None,
) -> str:
    whatsapp_id = enviar_texto(phone, message)
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO mensajes (
                conversacion_id, wa_message_id, direccion, tipo, contenido, pedido_id
            )
            VALUES (%s, %s, 'salida', 'text', %s, %s)
            ON CONFLICT (wa_message_id) DO NOTHING
            """,
            (
                conversation_id,
                whatsapp_id,
                Json({"text": {"body": message}}),
                order_id,
            ),
        )
        if welcome_pending:
            cursor.execute(
                "UPDATE conversaciones SET bienvenida_enviada = TRUE WHERE id = %s",
                (conversation_id,),
            )
        conn.commit()
        return whatsapp_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _finish_messages(message_ids: list[int], outgoing_id: str = "") -> None:
    if not message_ids:
        return
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE mensajes
            SET procesado_at = CURRENT_TIMESTAMP, procesando_at = NULL
            WHERE id = ANY(%s)
            """,
            (message_ids,),
        )
        cursor.execute(
            """
            UPDATE whatsapp_messages
            SET auto_reply_status = %s,
                auto_reply_message_id = %s,
                auto_reply_updated_at = CURRENT_TIMESTAMP
            WHERE message_id IN (
                SELECT wa_message_id FROM mensajes WHERE id = ANY(%s)
            )
            """,
            ("sent" if outgoing_id else "failed", outgoing_id or None, message_ids),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _write_log(
    conversation_id: int,
    received: list[dict],
    tools: list[dict],
    response: str,
    duration_ms: int,
    error: str = "",
) -> None:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO bot_logs (
                conversacion_id, mensajes_recibidos, herramientas,
                respuesta_enviada, duracion_ms, error
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                conversation_id,
                Json(received),
                Json(tools),
                response or None,
                duration_ms,
                error or None,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _claim_ready_conversations(debounce_seconds: int) -> list[dict]:
    conn = get_db()
    claims = []
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT c.id
            FROM conversaciones c
            WHERE c.modo = 'bot'
              AND c.ultimo_mensaje_at <= CURRENT_TIMESTAMP
                  - (%s * INTERVAL '1 second')
              AND EXISTS (
                  SELECT 1 FROM mensajes m
                  WHERE m.conversacion_id = c.id
                    AND m.direccion = 'entrada'
                    AND m.procesado_at IS NULL
                    AND (
                        m.procesando_at IS NULL OR
                        m.procesando_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'
                    )
              )
            ORDER BY c.ultimo_mensaje_at
            LIMIT 10
            FOR UPDATE SKIP LOCKED
            """,
            (debounce_seconds,),
        )
        conversation_ids = [row["id"] for row in cursor.fetchall()]
        for conversation_id in conversation_ids:
            cursor.execute(
                """
                UPDATE mensajes
                SET procesando_at = CURRENT_TIMESTAMP
                WHERE conversacion_id = %s AND direccion = 'entrada'
                  AND procesado_at IS NULL
                  AND (
                      procesando_at IS NULL OR
                      procesando_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes'
                  )
                RETURNING id, wa_message_id, tipo, contenido,
                          context_wa_message_id
                """,
                (conversation_id,),
            )
            messages = [dict(row) for row in cursor.fetchall()]
            if messages:
                claims.append(
                    {
                        "conversation_id": conversation_id,
                        "messages": messages,
                        "message_ids": [row["id"] for row in messages],
                    }
                )
        conn.commit()
        return claims
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _process_claim(claim: dict) -> None:
    conversation_id = claim["conversation_id"]
    messages = claim["messages"]
    message_ids = claim["message_ids"]
    started = time.monotonic()
    outgoing_id = ""
    response_text = ""
    tool_calls: list[dict] = []
    try:
        context = _conversation_context(conversation_id)
        if context["modo"] != "bot":
            _finish_messages(message_ids)
            return
        history = _history(conversation_id)
        original = "\n".join(_render_message(message) for message in messages)
        bot_tools = BotTools(
            context["comercio_id"],
            conversation_id,
            mensaje_original=original,
        )
        unsupported = [
            message for message in messages if message["tipo"] not in SUPPORTED_TYPES
        ]
        if unsupported:
            tool_result = bot_tools.execute(
                "pasar_a_humano",
                {
                    "motivo": (
                        "El local envió contenido que el asistente todavía no puede leer."
                    )
                },
            )
            tool_calls.append(
                {
                    "nombre": "pasar_a_humano",
                    "argumentos": {"motivo": "contenido no compatible"},
                    "resultado": tool_result,
                }
            )
            greeting = (
                "Hola, soy el asistente automático de la empresa de delivery. "
                "Una persona supervisa y puede intervenir. "
                if not context["bienvenida_enviada"]
                else ""
            )
            response_text = (
                greeting
                + "Todavía no puedo leer fotos, audios u otros archivos. "
                "Pasame los datos en texto y dejo el caso para que lo revise una persona."
            )
        else:
            repository = bot_tools.repository
            open_orders = repository.open_orders(context["comercio_id"])
            agent = ConversationAgent(tools=bot_tools)
            result = agent.run(
                history=history,
                commerce_name=context["comercio"],
                open_orders=open_orders,
                welcome_pending=not context["bienvenida_enviada"],
            )
            response_text = result["respuesta"]
            tool_calls.extend(result["herramientas"])

        related_order_ids = {
            call["resultado"]["pedido_id"]
            for call in tool_calls
            if call["nombre"] in {"guardar_borrador_pedido", "confirmar_pedido"}
            and isinstance(call.get("resultado"), dict)
            and isinstance(call["resultado"].get("pedido_id"), int)
        }
        outgoing_id = _save_outgoing(
            conversation_id,
            context["telefono"],
            response_text,
            not context["bienvenida_enviada"],
            next(iter(related_order_ids)) if len(related_order_ids) == 1 else None,
        )
        _finish_messages(message_ids, outgoing_id)
        _write_log(
            conversation_id,
            messages,
            tool_calls,
            response_text,
            int((time.monotonic() - started) * 1000),
        )
    except Exception as error:
        error_text = f"{type(error).__name__}: {error}"
        print(
            f"BOT_WORKER conversation_id={conversation_id} error={error_text}",
            flush=True,
        )
        try:
            context = _conversation_context(conversation_id)
            fallback_tools = BotTools(context["comercio_id"], conversation_id)
            handoff = fallback_tools.execute(
                "pasar_a_humano",
                {"motivo": "El asistente tuvo un error al procesar el mensaje."},
            )
            tool_calls.append(
                {
                    "nombre": "pasar_a_humano",
                    "argumentos": {"motivo": "error del asistente"},
                    "resultado": handoff,
                }
            )
            response_text = (
                "Hola, soy el asistente automático de la empresa de delivery. "
                "Una persona supervisa y puede intervenir. "
                "Se me complicó revisar esto; dejo el caso para que una persona lo vea."
                if not context["bienvenida_enviada"]
                else "Se me complicó revisar esto; dejo el caso para que una persona lo vea."
            )
            outgoing_id = _save_outgoing(
                conversation_id,
                context["telefono"],
                response_text,
                not context["bienvenida_enviada"],
            )
        except Exception as fallback_error:
            print(
                f"BOT_WORKER fallback_failed conversation_id={conversation_id} "
                f"type={type(fallback_error).__name__}: {fallback_error}",
                flush=True,
            )
        _finish_messages(message_ids, outgoing_id)
        _write_log(
            conversation_id,
            messages,
            tool_calls,
            response_text,
            int((time.monotonic() - started) * 1000),
            error_text,
        )


def _reminder_intervals() -> tuple[int, int]:
    reminder_minutes = int(os.environ.get("RECORDATORIO_BORRADOR_MINUTOS", "15"))
    escalation_minutes = int(
        os.environ.get("ESCALAMIENTO_RECORDATORIO_MINUTOS", "15")
    )
    if reminder_minutes < 1 or escalation_minutes < 1:
        raise ValueError("Los intervalos de recordatorio deben ser positivos.")
    return reminder_minutes, escalation_minutes


def _process_draft_reminders() -> None:
    reminder_minutes, escalation_minutes = _reminder_intervals()
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT p.id, p.comercio_id, p.bot_conversacion_id,
                   p.bot_recordatorio_enviado_at, c.modo,
                   ct.numero AS telefono
            FROM pedidos p
            JOIN conversaciones c ON c.id = p.bot_conversacion_id
            JOIN contactos_whatsapp ct ON ct.id = c.contacto_whatsapp_id
            WHERE p.estado = 'borrador' AND c.modo = 'bot'
              AND (
                  (p.bot_recordatorio_enviado_at IS NULL
                   AND p.bot_ultimo_movimiento_at <= CURRENT_TIMESTAMP
                       - (%s * INTERVAL '1 minute'))
                  OR
                  (p.bot_recordatorio_enviado_at IS NOT NULL
                   AND p.bot_alerta_enviada_at IS NULL
                   AND p.bot_recordatorio_enviado_at <= CURRENT_TIMESTAMP
                       - (%s * INTERVAL '1 minute'))
              )
            ORDER BY p.bot_ultimo_movimiento_at
            LIMIT 20
            """,
            (reminder_minutes, escalation_minutes),
        )
        due_orders = [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

    for order in due_orders:
        try:
            if order["bot_recordatorio_enviado_at"] is None:
                message = (
                    f"Te quedó abierto el pedido #{order['id']}. "
                    "Cuando puedas, mandame los datos que faltan y lo seguimos."
                )
                _save_outgoing(
                    order["bot_conversacion_id"],
                    order["telefono"],
                    message,
                    False,
                    order["id"],
                )
                _write_log(
                    order["bot_conversacion_id"],
                    [],
                    [],
                    message,
                    0,
                )
                update_column = "bot_recordatorio_enviado_at"
            else:
                bot_tools = BotTools(
                    order["comercio_id"], order["bot_conversacion_id"]
                )
                bot_tools.execute(
                    "pasar_a_humano",
                    {
                        "motivo": (
                            f"El borrador #{order['id']} quedó sin respuesta después "
                            "del recordatorio."
                        )
                    },
                )
                update_column = "bot_alerta_enviada_at"
            update_conn = get_db()
            try:
                update_cursor = update_conn.cursor()
                update_cursor.execute(
                    f"UPDATE pedidos SET {update_column} = CURRENT_TIMESTAMP WHERE id = %s",
                    (order["id"],),
                )
                update_conn.commit()
            except Exception:
                update_conn.rollback()
                raise
            finally:
                update_conn.close()
        except (WhatsAppDeliveryError, ValueError, RuntimeError) as error:
            print(
                f"BOT_REMINDER order_id={order['id']} "
                f"type={type(error).__name__}: {error}",
                flush=True,
            )


def process_ready_conversations() -> int:
    debounce_seconds = int(os.environ.get("DEBOUNCE_SEGUNDOS", "10"))
    if debounce_seconds < 0:
        raise ValueError("DEBOUNCE_SEGUNDOS no puede ser negativo.")
    claims = _claim_ready_conversations(debounce_seconds)
    for claim in claims:
        _process_claim(claim)
    _process_draft_reminders()
    return len(claims)


async def run_worker() -> None:
    while True:
        try:
            await asyncio.to_thread(process_ready_conversations)
        except Exception as error:
            print(
                f"BOT_WORKER loop_error type={type(error).__name__}: {error}",
                flush=True,
            )
        await asyncio.sleep(1)
