import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from bot.tools import BotTools, ToolValidationError


class FakeRepository:
    def __init__(self):
        self.saved = []
        self.scoped_commerce_ids = []

    def save_draft(self, commerce_id, conversation_id, values):
        self.scoped_commerce_ids.append(commerce_id)
        self.saved.append((conversation_id, values))
        missing = []
        if not values["direccion_entrega"] and values["latitud"] is None:
            missing.append("dirección o ubicación")
        if not values["cliente_nombre"] and not values["cliente_telefono"]:
            missing.append("nombre o teléfono del cliente")
        if not values["hora_entrega_solicitada"]:
            missing.append("para cuándo")
        if not values["forma_pago"]:
            missing.append("forma de cobro")
        return {"pedido_id": 14, "faltan": missing, "pedido": values}

    def order_status(self, commerce_id, order_id):
        self.scoped_commerce_ids.append(commerce_id)
        return {
            "pedido_id": order_id,
            "pedido": {
                "direccion_entrega": "Alem 10",
                "latitud": None,
                "longitud": None,
                "cliente_nombre": "Ana",
                "cliente_telefono": "2604000000",
                "hora_entrega_solicitada": "2026-10-30T12:00:00-03:00",
                "forma_pago": "efectivo",
            },
        }

    def confirm_order(self, commerce_id, order_id, fee):
        self.scoped_commerce_ids.append(commerce_id)
        return {"pedido_id": order_id, "pedido": {"costo_delivery": str(fee)}}

    def cancel_order(self, commerce_id, order_id):
        self.scoped_commerce_ids.append(commerce_id)
        return {"pedido_id": order_id, "estado": "cancelado"}

    def create_handoff_alert(self, conversation_id, commerce_id, reason):
        self.scoped_commerce_ids.append(commerce_id)
        return {"alerta_id": 3, "comercio": "Local"}

    def mark_alert_notified(self, alert_id):
        pass


class BotToolsTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()
        self.tools = BotTools(7, 101, repository=self.repository)

    def test_complete_draft_validates_and_returns_no_missing_fields(self):
        result = self.tools.execute(
            "guardar_borrador_pedido",
            {
                "pedido_id": None,
                "direccion_entrega": "Alem 10",
                "cliente_nombre": "Ana",
                "entrega_en_minutos": 30,
                "forma_pago": "efectivo",
                "monto_a_cobrar": 1500,
            },
        )
        self.assertEqual(result["faltan"], [])
        self.assertEqual(result["pedido_id"], 14)
        self.assertEqual(self.repository.scoped_commerce_ids, [7])
        requested = self.repository.saved[0][1]["hora_entrega_solicitada"]
        self.assertIsInstance(requested, datetime)
        self.assertEqual(requested.tzinfo, ZoneInfo("America/Argentina/Mendoza"))

    def test_incomplete_draft_returns_all_missing_requirements(self):
        result = self.tools.execute(
            "guardar_borrador_pedido",
            {"pedido_id": None, "direccion_entrega": "Alem 10"},
        )
        self.assertEqual(
            result["faltan"],
            [
                "nombre o teléfono del cliente",
                "para cuándo",
                "forma de cobro",
            ],
        )

    def test_location_coordinates_are_validated_as_a_pair(self):
        with self.assertRaisesRegex(ToolValidationError, "requiere latitud"):
            self.tools.execute(
                "guardar_borrador_pedido",
                {"pedido_id": None, "latitud": -34.6},
            )

    def test_out_of_range_location_is_rejected(self):
        with self.assertRaisesRegex(ToolValidationError, "fuera de rango"):
            self.tools.execute(
                "guardar_borrador_pedido",
                {"pedido_id": None, "latitud": 91, "longitud": -68},
            )

    def test_payment_method_is_allowlisted(self):
        with self.assertRaisesRegex(ToolValidationError, "forma_pago"):
            self.tools.execute(
                "guardar_borrador_pedido",
                {"pedido_id": None, "forma_pago": "cheque"},
            )

    def test_paga_con_is_only_allowed_for_cash(self):
        with self.assertRaisesRegex(ToolValidationError, "solo corresponde"):
            self.tools.execute(
                "guardar_borrador_pedido",
                {"pedido_id": None, "forma_pago": "transferencia", "paga_con": 5000},
            )

    def test_confirm_calculates_a_provisional_tariff_for_the_same_commerce(self):
        with patch.dict("os.environ", {"TARIFA_PROVISORIA": "1500"}):
            result = self.tools.execute("confirmar_pedido", {"pedido_id": 14})
        self.assertTrue(result["tarifa_provisoria"])
        self.assertEqual(self.repository.scoped_commerce_ids, [7, 7])

    def test_handoff_always_registers_an_alert_without_staff_configuration(self):
        with patch.dict("os.environ", {"NUMEROS_STAFF": ""}):
            result = self.tools.execute(
                "pasar_a_humano", {"motivo": "Consulta de prueba."}
            )
        self.assertEqual(result["alerta_id"], 3)
        self.assertFalse(result["notificada"])
        self.assertEqual(self.repository.scoped_commerce_ids, [7])

    def test_order_status_and_cancel_are_scoped_to_commerce(self):
        status = self.tools.execute("consultar_estado_pedido", {"pedido_id": 14})
        cancelled = self.tools.execute("cancelar_pedido", {"pedido_id": 14})
        self.assertEqual(status["pedido_id"], 14)
        self.assertEqual(cancelled["estado"], "cancelado")
        self.assertEqual(self.repository.scoped_commerce_ids, [7, 7])

    def test_unknown_tool_fields_are_rejected(self):
        with self.assertRaisesRegex(ToolValidationError, "Campos no permitidos"):
            self.tools.execute(
                "guardar_borrador_pedido",
                {"pedido_id": None, "comercio_id": 999},
            )


if __name__ == "__main__":
    unittest.main()
