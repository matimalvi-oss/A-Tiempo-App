import os
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from zoneinfo import ZoneInfo

from database import get_db

from .tarifa import consultar_tarifa
from .whatsapp_client import WhatsAppDeliveryError, enviar_texto


MENDOZA = ZoneInfo("America/Argentina/Mendoza")


class ToolValidationError(ValueError):
    pass


TOOL_DECLARATIONS = [
    {
        "name": "guardar_borrador_pedido",
        "description": "Crea un borrador de pedido o actualiza el borrador indicado. Si pedido_id es null, crea un pedido nuevo.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "pedido_id": {"type": "INTEGER", "nullable": True},
                "direccion_entrega": {"type": "STRING", "nullable": True},
                "latitud": {"type": "NUMBER", "nullable": True},
                "longitud": {"type": "NUMBER", "nullable": True},
                "cliente_nombre": {"type": "STRING", "nullable": True},
                "cliente_telefono": {"type": "STRING", "nullable": True},
                "referencia": {"type": "STRING", "nullable": True},
                "hora_entrega_solicitada": {"type": "STRING", "nullable": True},
                "entrega_en_minutos": {"type": "INTEGER", "nullable": True},
                "forma_pago": {
                    "type": "STRING",
                    "enum": ["efectivo", "transferencia", "pagado"],
                    "nullable": True,
                },
                "monto_a_cobrar": {"type": "NUMBER", "nullable": True},
                "paga_con": {"type": "NUMBER", "nullable": True},
                "pagado": {"type": "BOOLEAN", "nullable": True},
                "notas": {"type": "STRING", "nullable": True},
            },
        },
    },
    {
        "name": "confirmar_pedido",
        "description": "Confirma un borrador completo después de que el local respondió que está de acuerdo con el resumen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"pedido_id": {"type": "INTEGER"}},
            "required": ["pedido_id"],
        },
    },
    {
        "name": "consultar_tarifa",
        "description": "Consulta la tarifa provisoria fija usando una dirección o coordenadas.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "direccion": {"type": "STRING", "nullable": True},
                "latitud": {"type": "NUMBER", "nullable": True},
                "longitud": {"type": "NUMBER", "nullable": True},
            },
        },
    },
    {
        "name": "consultar_estado_pedido",
        "description": "Consulta el estado y horarios de un pedido de este comercio.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"pedido_id": {"type": "INTEGER"}},
            "required": ["pedido_id"],
        },
    },
    {
        "name": "cancelar_pedido",
        "description": "Cancela un pedido de este comercio que todavía no está en curso.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"pedido_id": {"type": "INTEGER"}},
            "required": ["pedido_id"],
        },
    },
    {
        "name": "pasar_a_humano",
        "description": "Pasa la conversación a una persona y registra/notifica la alerta.",
        "parameters": {
            "type": "OBJECT",
            "properties": {"motivo": {"type": "STRING"}},
            "required": ["motivo"],
        },
    },
]


def _decimal(value: Any, field: str) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ToolValidationError(f"{field} debe ser un monto o número válido.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ToolValidationError(f"{field} debe ser un monto o número válido.")
    if not result.is_finite():
        raise ToolValidationError(f"{field} debe ser un monto o número válido.")
    return result


def _text(value: Any, field: str, max_length: int = 500) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ToolValidationError(f"{field} debe ser texto.")
    value = value.strip()
    if len(value) > max_length:
        raise ToolValidationError(f"{field} supera el largo permitido.")
    return value or None


def _pedido_id(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ToolValidationError("pedido_id debe ser un número de pedido válido.")
    return value


def _validate_keys(arguments: dict, allowed: set[str]) -> None:
    unknown = set(arguments) - allowed
    if unknown:
        raise ToolValidationError(
            f"Campos no permitidos: {', '.join(sorted(unknown))}."
        )


def _requested_time(absolute: Any, minutes: Any) -> Optional[datetime]:
    if absolute is not None and minutes is not None:
        raise ToolValidationError(
            "Indicá hora_entrega_solicitada o entrega_en_minutos, no ambos."
        )
    if minutes is not None:
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 1440:
            raise ToolValidationError("entrega_en_minutos debe estar entre 1 y 1440.")
        return datetime.now(MENDOZA).replace(microsecond=0) + timedelta(
            minutes=minutes
        )
    if absolute is None:
        return None
    if not isinstance(absolute, str):
        raise ToolValidationError("hora_entrega_solicitada debe ser una fecha ISO.")
    try:
        value = datetime.fromisoformat(absolute)
    except ValueError as error:
        raise ToolValidationError(
            "hora_entrega_solicitada debe ser una fecha ISO válida."
        ) from error
    if value.tzinfo is None:
        value = value.replace(tzinfo=MENDOZA)
    value = value.astimezone(MENDOZA)
    if value < datetime.now(MENDOZA):
        raise ToolValidationError("La hora de entrega no puede estar en el pasado.")
    return value


def _missing_fields(order: dict) -> list[str]:
    missing = []
    if not order.get("direccion_entrega") and not (
        order.get("latitud") is not None and order.get("longitud") is not None
    ):
        missing.append("dirección o ubicación")
    if not order.get("cliente_nombre") and not order.get("cliente_telefono"):
        missing.append("nombre o teléfono del cliente")
    if not order.get("hora_entrega_solicitada"):
        missing.append("para cuándo")
    if order.get("forma_pago") not in {"efectivo", "transferencia", "pagado"}:
        missing.append("forma de cobro")
    return missing


class PostgresBotRepository:
    def open_orders(self, comercio_id: int) -> list[dict]:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT p.id, p.estado, p.direccion_entrega, p.latitud, p.longitud,
                       p.referencia, p.hora_entrega_solicitada, p.forma_pago,
                       p.monto_a_cobrar, p.costo_delivery, p.pagado,
                       cl.nombre AS cliente_nombre, cl.telefono AS cliente_telefono
                FROM pedidos p
                LEFT JOIN clientes cl ON cl.id = p.cliente_id
                WHERE p.comercio_id = %s AND p.estado IN ('borrador', 'pendiente')
                ORDER BY p.hora_pedido DESC
                LIMIT 20
                """,
                (comercio_id,),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    def save_draft(
        self, comercio_id: int, conversacion_id: int, values: dict
    ) -> dict:
        conn = get_db()
        try:
            cursor = conn.cursor()
            order_id = values["pedido_id"]
            order = None
            client_id = None
            old_client_name = None
            old_client_phone = None
            if order_id is not None:
                cursor.execute(
                    """
                    SELECT p.*, cl.nombre AS cliente_nombre,
                           cl.telefono AS cliente_telefono
                    FROM pedidos p
                    LEFT JOIN clientes cl ON cl.id = p.cliente_id
                    WHERE p.id = %s AND p.comercio_id = %s
                      AND p.estado = 'borrador'
                    FOR UPDATE OF p
                    """,
                    (order_id, comercio_id),
                )
                order = cursor.fetchone()
                if not order:
                    raise ToolValidationError(
                        f"No encontré el borrador #{order_id} de este comercio."
                    )
                client_id = order["cliente_id"]
                old_client_name = order.get("cliente_nombre")
                old_client_phone = order.get("cliente_telefono")

            name = values["cliente_nombre"] or old_client_name
            phone = values["cliente_telefono"] or old_client_phone
            if phone:
                cursor.execute("SELECT id FROM clientes WHERE telefono = %s", (phone,))
                matched_client = cursor.fetchone()
                if matched_client:
                    client_id = matched_client["id"]
                    cursor.execute(
                        """
                        UPDATE clientes
                        SET nombre = COALESCE(NULLIF(%s, ''), nombre)
                        WHERE id = %s
                        """,
                        (name or "", client_id),
                    )
                elif client_id is not None:
                    cursor.execute(
                        "UPDATE clientes SET nombre = %s, telefono = %s WHERE id = %s",
                        (name or "Sin nombre", phone, client_id),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO clientes (nombre, telefono)
                        VALUES (%s, %s)
                        RETURNING id
                        """,
                        (name or "Sin nombre", phone),
                    )
                    client_id = cursor.fetchone()["id"]
            elif name and client_id is not None:
                cursor.execute(
                    "UPDATE clientes SET nombre = %s WHERE id = %s",
                    (name, client_id),
                )
            elif name:
                cursor.execute(
                    "INSERT INTO clientes (nombre) VALUES (%s) RETURNING id",
                    (name,),
                )
                client_id = cursor.fetchone()["id"]

            address = values["direccion_entrega"]
            if not address and values["latitud"] is not None:
                address = "Ubicación compartida"
            timestamp = datetime.now(MENDOZA)
            if order is None:
                cursor.execute(
                    """
                    SELECT direccion FROM comercios WHERE id = %s
                    """,
                    (comercio_id,),
                )
                commerce = cursor.fetchone()
                if not commerce:
                    raise ToolValidationError("El comercio ya no existe.")
                cursor.execute(
                    """
                    INSERT INTO pedidos (
                        comercio_id, cliente_id, rider_id, direccion_recogida,
                        direccion_entrega, estado, monto_a_cobrar, costo_delivery,
                        pagado, hora_pedido, bot_conversacion_id,
                        bot_ultimo_movimiento_at
                    )
                    VALUES (%s, %s, NULL, %s, %s, 'borrador', 0, 0,
                            FALSE, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        comercio_id,
                        client_id,
                        commerce["direccion"],
                        address,
                        timestamp,
                        conversacion_id,
                        timestamp,
                    ),
                )
                order_id = cursor.fetchone()["id"]

            updates = {
                "cliente_id": client_id,
                "direccion_entrega": address,
                "referencia": values["referencia"],
                "latitud": values["latitud"],
                "longitud": values["longitud"],
                "hora_entrega_solicitada": values["hora_entrega_solicitada"],
                "forma_pago": values["forma_pago"],
                "monto_a_cobrar": values["monto_a_cobrar"],
                "paga_con": values["paga_con"],
                "pagado": values["pagado"],
                "notas": values["notas"],
                "mensaje_original": values["mensaje_original"],
                "bot_conversacion_id": conversacion_id,
                "bot_ultimo_movimiento_at": timestamp,
            }
            if values["latitud"] is not None and values["longitud"] is not None:
                updates["ubicacion_url"] = (
                    "https://maps.google.com/?q="
                    f"{values['latitud']},{values['longitud']}"
                )
            set_parts = []
            params = []
            for column, value in updates.items():
                if value is not None:
                    set_parts.append(f"{column} = %s")
                    params.append(value)
            params.append(order_id)
            cursor.execute(
                f"UPDATE pedidos SET {', '.join(set_parts)} WHERE id = %s",
                params,
            )
            cursor.execute(
                """
                SELECT p.id, p.direccion_entrega, p.latitud, p.longitud,
                       p.hora_entrega_solicitada, p.forma_pago,
                       cl.nombre AS cliente_nombre, cl.telefono AS cliente_telefono
                FROM pedidos p
                LEFT JOIN clientes cl ON cl.id = p.cliente_id
                WHERE p.id = %s AND p.comercio_id = %s
                """,
                (order_id, comercio_id),
            )
            saved = dict(cursor.fetchone())
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

        missing = _missing_fields(saved)
        return {
            "pedido_id": order_id,
            "faltan": missing,
            "pedido": _json_safe(saved),
        }

    def confirm_order(self, comercio_id: int, order_id: int, fee: Decimal) -> dict:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT p.*, cl.nombre AS cliente_nombre,
                       cl.telefono AS cliente_telefono
                FROM pedidos p
                LEFT JOIN clientes cl ON cl.id = p.cliente_id
                WHERE p.id = %s AND p.comercio_id = %s
                  AND p.estado = 'borrador'
                FOR UPDATE OF p
                """,
                (order_id, comercio_id),
            )
            order = cursor.fetchone()
            if not order:
                raise ToolValidationError(
                    f"No encontré el borrador #{order_id} de este comercio."
                )
            order = dict(order)
            missing = _missing_fields(order)
            if missing:
                return {"pedido_id": order_id, "faltan": missing}
            now = datetime.now(MENDOZA)
            cursor.execute(
                """
                UPDATE pedidos
                SET estado = 'pendiente', costo_delivery = %s,
                    bot_ultimo_movimiento_at = %s
                WHERE id = %s AND comercio_id = %s
                RETURNING id, direccion_entrega, referencia,
                          hora_entrega_solicitada, forma_pago, monto_a_cobrar,
                          costo_delivery, pagado, latitud, longitud
                """,
                (fee, now, order_id, comercio_id),
            )
            result = dict(cursor.fetchone())
            result["cliente_nombre"] = order.get("cliente_nombre")
            result["cliente_telefono"] = order.get("cliente_telefono")
            conn.commit()
            return {
                "pedido_id": order_id,
                "estado": "pendiente",
                "pedido": _json_safe(result),
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def order_status(self, comercio_id: int, order_id: int) -> dict:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT p.id, p.estado, p.hora_pedido, p.hora_estimada_retiro,
                       p.hora_real_retiro, p.hora_entrega,
                       p.hora_entrega_solicitada, p.direccion_entrega,
                       p.latitud, p.longitud, p.forma_pago,
                       cl.nombre AS cliente_nombre, cl.telefono AS cliente_telefono
                FROM pedidos p
                LEFT JOIN clientes cl ON cl.id = p.cliente_id
                WHERE p.id = %s AND p.comercio_id = %s
                """,
                (order_id, comercio_id),
            )
            result = cursor.fetchone()
            if not result:
                raise ToolValidationError(
                    f"No encontré el pedido #{order_id} de este comercio."
                )
            return {"pedido_id": order_id, "pedido": _json_safe(dict(result))}
        finally:
            conn.close()

    def cancel_order(self, comercio_id: int, order_id: int) -> dict:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT estado FROM pedidos
                WHERE id = %s AND comercio_id = %s
                FOR UPDATE
                """,
                (order_id, comercio_id),
            )
            result = cursor.fetchone()
            if not result:
                raise ToolValidationError(
                    f"No encontré el pedido #{order_id} de este comercio."
                )
            if result["estado"] not in {"borrador", "pendiente"}:
                raise ToolValidationError(
                    f"El pedido #{order_id} ya está en curso y no se puede cancelar desde acá."
                )
            cursor.execute(
                """
                UPDATE pedidos SET estado = 'cancelado'
                WHERE id = %s AND comercio_id = %s
                """,
                (order_id, comercio_id),
            )
            conn.commit()
            return {"pedido_id": order_id, "estado": "cancelado"}
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_handoff_alert(
        self, conversacion_id: int, comercio_id: int, motivo: str
    ) -> dict:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE conversaciones SET modo = 'humano' WHERE id = %s AND comercio_id = %s",
                (conversacion_id, comercio_id),
            )
            if cursor.rowcount == 0:
                raise ToolValidationError("No encontré la conversación de este comercio.")
            cursor.execute(
                """
                INSERT INTO bot_alertas (conversacion_id, comercio_id, motivo)
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (conversacion_id, comercio_id, motivo),
            )
            alert_id = cursor.fetchone()["id"]
            cursor.execute(
                "SELECT nombre FROM comercios WHERE id = %s",
                (comercio_id,),
            )
            commerce = cursor.fetchone()
            conn.commit()
            return {
                "alerta_id": alert_id,
                "comercio": commerce["nombre"] if commerce else str(comercio_id),
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def mark_alert_notified(self, alert_id: int) -> None:
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE bot_alertas SET notificada = TRUE,
                    notificada_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (alert_id,),
            )
            conn.commit()
        finally:
            conn.close()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, Decimal)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    return value


class BotTools:
    def __init__(
        self,
        comercio_id: int,
        conversacion_id: int,
        repository: Optional[PostgresBotRepository] = None,
        mensaje_original: Optional[str] = None,
    ):
        self.comercio_id = comercio_id
        self.conversacion_id = conversacion_id
        self.repository = repository or PostgresBotRepository()
        self.mensaje_original = mensaje_original

    def execute(self, name: str, arguments: dict) -> dict:
        if not isinstance(arguments, dict):
            raise ToolValidationError("Los argumentos de la herramienta no son válidos.")
        if name == "guardar_borrador_pedido":
            return self._save_draft(arguments)
        if name == "confirmar_pedido":
            _validate_keys(arguments, {"pedido_id"})
            order_id = _pedido_id(arguments.get("pedido_id"))
            if order_id is None:
                raise ToolValidationError("Falta pedido_id.")
            existing = self.repository.order_status(self.comercio_id, order_id)
            order = existing["pedido"]
            missing = _missing_fields(order)
            if missing:
                return {"pedido_id": order_id, "faltan": missing}
            quote = consultar_tarifa(
                order.get("direccion_entrega"),
                order.get("latitud"),
                order.get("longitud"),
            )
            confirmed = self.repository.confirm_order(
                self.comercio_id, order_id, Decimal(quote["monto"])
            )
            if confirmed.get("faltan"):
                return confirmed
            confirmed["tarifa_provisoria"] = quote["provisoria"]
            return confirmed
        if name == "consultar_tarifa":
            _validate_keys(arguments, {"direccion", "latitud", "longitud"})
            address = _text(arguments.get("direccion"), "direccion", 300)
            latitude = _decimal(arguments.get("latitud"), "latitud")
            longitude = _decimal(arguments.get("longitud"), "longitud")
            if (latitude is None) != (longitude is None):
                raise ToolValidationError(
                    "Para consultar por ubicación necesito latitud y longitud."
                )
            if latitude is not None and not (
                Decimal("-90") <= latitude <= Decimal("90")
                and Decimal("-180") <= longitude <= Decimal("180")
            ):
                raise ToolValidationError("La ubicación está fuera de rango.")
            if not address and latitude is None:
                raise ToolValidationError(
                    "Indicá una dirección o compartí una ubicación para consultar la tarifa."
                )
            return consultar_tarifa(
                address,
                float(latitude) if latitude is not None else None,
                float(longitude) if longitude is not None else None,
            )
        if name == "consultar_estado_pedido":
            _validate_keys(arguments, {"pedido_id"})
            order_id = _pedido_id(arguments.get("pedido_id"))
            if order_id is None:
                raise ToolValidationError("Falta pedido_id.")
            return self.repository.order_status(self.comercio_id, order_id)
        if name == "cancelar_pedido":
            _validate_keys(arguments, {"pedido_id"})
            order_id = _pedido_id(arguments.get("pedido_id"))
            if order_id is None:
                raise ToolValidationError("Falta pedido_id.")
            return self.repository.cancel_order(self.comercio_id, order_id)
        if name == "pasar_a_humano":
            _validate_keys(arguments, {"motivo"})
            reason = _text(arguments.get("motivo"), "motivo", 1000)
            if not reason:
                raise ToolValidationError("Indicá el motivo para pasar a una persona.")
            alert = self.repository.create_handoff_alert(
                self.conversacion_id, self.comercio_id, reason
            )
            staff_numbers = []
            for number in os.environ.get("NUMEROS_STAFF", "").split(","):
                normalized = "".join(
                    character for character in number if character.isdigit()
                )
                if normalized:
                    staff_numbers.append(normalized)
            sent_count = 0
            for number in staff_numbers:
                try:
                    enviar_texto(
                        number,
                        f"Alerta de WhatsApp para {alert['comercio']}: {reason}",
                    )
                    sent_count += 1
                except WhatsAppDeliveryError as error:
                    print(
                        f"BOT_ALERT staff_notification_failed alert_id={alert['alerta_id']} "
                        f"type={type(error).__name__}: {error}",
                        flush=True,
                    )
            if sent_count:
                self.repository.mark_alert_notified(alert["alerta_id"])
            return {
                **alert,
                "notificada": sent_count > 0,
            }
        raise ToolValidationError(f"Herramienta desconocida: {name}.")

    def _save_draft(self, arguments: dict) -> dict:
        allowed = {
            "pedido_id",
            "direccion_entrega",
            "latitud",
            "longitud",
            "cliente_nombre",
            "cliente_telefono",
            "referencia",
            "hora_entrega_solicitada",
            "entrega_en_minutos",
            "forma_pago",
            "monto_a_cobrar",
            "paga_con",
            "pagado",
            "notas",
        }
        _validate_keys(arguments, allowed)
        latitude = _decimal(arguments.get("latitud"), "latitud")
        longitude = _decimal(arguments.get("longitud"), "longitud")
        if (latitude is None) != (longitude is None):
            raise ToolValidationError("La ubicación requiere latitud y longitud.")
        if latitude is not None and not (
            Decimal("-90") <= latitude <= Decimal("90")
            and Decimal("-180") <= longitude <= Decimal("180")
        ):
            raise ToolValidationError("La ubicación está fuera de rango.")
        payment_method = _text(arguments.get("forma_pago"), "forma_pago", 30)
        if payment_method not in {None, "efectivo", "transferencia", "pagado"}:
            raise ToolValidationError(
                "forma_pago debe ser efectivo, transferencia o pagado."
            )
        paid = arguments.get("pagado")
        if paid is not None and not isinstance(paid, bool):
            raise ToolValidationError("pagado debe ser verdadero o falso.")
        if paid is True and payment_method not in {None, "pagado"}:
            raise ToolValidationError("Un pedido pagado debe tener forma_pago=pagado.")
        if payment_method == "pagado" and paid is False:
            raise ToolValidationError("forma_pago=pagado no puede tener pagado=falso.")
        if payment_method == "pagado":
            paid = True
        if paid is True:
            payment_method = "pagado"
        elif payment_method and paid is None:
            paid = False

        amount = _decimal(arguments.get("monto_a_cobrar"), "monto_a_cobrar")
        cash_amount = _decimal(arguments.get("paga_con"), "paga_con")
        for field, value in (
            ("monto_a_cobrar", amount),
            ("paga_con", cash_amount),
        ):
            if value is not None and value < 0:
                raise ToolValidationError(f"{field} no puede ser negativo.")
        if amount is not None and amount > Decimal("99999999.99"):
            raise ToolValidationError("monto_a_cobrar supera el máximo permitido.")
        if cash_amount is not None and cash_amount > Decimal("9999999999.99"):
            raise ToolValidationError("paga_con supera el máximo permitido.")
        if cash_amount is not None and payment_method != "efectivo":
            raise ToolValidationError("paga_con solo corresponde a pagos en efectivo.")
        if (
            cash_amount is not None
            and amount is not None
            and cash_amount < amount
        ):
            raise ToolValidationError("paga_con no puede ser menor a monto_a_cobrar.")

        minutes = arguments.get("entrega_en_minutos")
        if minutes is not None and (
            isinstance(minutes, bool) or not isinstance(minutes, int)
        ):
            raise ToolValidationError("entrega_en_minutos debe ser un número entero.")
        original_time = arguments.get("hora_entrega_solicitada")
        requested_time = _requested_time(original_time, minutes)

        return self.repository.save_draft(
            self.comercio_id,
            self.conversacion_id,
            {
                "pedido_id": _pedido_id(arguments.get("pedido_id")),
                "direccion_entrega": _text(
                    arguments.get("direccion_entrega"), "direccion_entrega", 300
                ),
                "latitud": latitude,
                "longitud": longitude,
                "cliente_nombre": _text(
                    arguments.get("cliente_nombre"), "cliente_nombre", 100
                ),
                "cliente_telefono": _text(
                    arguments.get("cliente_telefono"), "cliente_telefono", 50
                ),
                "referencia": _text(arguments.get("referencia"), "referencia", 300),
                "hora_entrega_solicitada": requested_time,
                "forma_pago": payment_method,
                "monto_a_cobrar": amount,
                "paga_con": cash_amount,
                "pagado": paid,
                "notas": _text(arguments.get("notas"), "notas", 2000),
                "mensaje_original": self.mensaje_original,
            },
        )
