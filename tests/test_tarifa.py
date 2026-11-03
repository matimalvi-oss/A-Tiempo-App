import json
import unittest
from unittest.mock import patch

from bot.tarifa import (
    TarifaNoDisponibleError,
    _obtener_distancia_metros,
    consultar_tarifa,
)


class FakeCursor:
    def __init__(self, rain_active=False):
        self.rain_active = rain_active
        self.result = None

    def execute(self, query, params=None):
        if "bot_tarifas_distancia" in query:
            self.result = [
                {"limite_km": "2.8", "monto": "3000.00"},
                {"limite_km": "4.0", "monto": "3500.00"},
                {"limite_km": "5.0", "monto": "4000.00"},
                {"limite_km": "6.0", "monto": "4500.00"},
                {"limite_km": "7.0", "monto": "5000.00"},
                {"limite_km": "8.0", "monto": "5500.00"},
                {"limite_km": "9.0", "monto": "6000.00"},
            ]
        elif "bot_configuracion" in query:
            self.result = {
                "valor": "true" if self.rain_active else "false"
            }
        else:
            raise AssertionError(f"Unexpected query: {query}")

    def fetchall(self):
        return self.result

    def fetchone(self):
        return self.result


class FakeConnection:
    def __init__(self, rain_active):
        self.cursor_instance = FakeCursor(rain_active)

    def cursor(self):
        return self.cursor_instance

    def close(self):
        pass


class TarifaTests(unittest.TestCase):
    def quote(self, distance_meters, rain_active=False):
        with (
            patch(
                "bot.tarifa.get_db",
                side_effect=lambda: FakeConnection(rain_active),
            ),
            patch(
                "bot.tarifa._obtener_distancia_metros",
                return_value=distance_meters,
            ),
        ):
            return consultar_tarifa(
                "Alem 10, San Rafael",
                "Mitre 20, San Rafael",
            )

    def test_selects_rate_for_exact_upper_boundary_and_adds_rain_surcharge(self):
        result = self.quote(2800, rain_active=True)

        self.assertEqual(result["tarifa_base"], "3000.00")
        self.assertEqual(result["recargo_lluvia"], "1500.00")
        self.assertEqual(result["monto"], "4500.00")
        self.assertTrue(result["recargo_lluvia_aplicado"])
        self.assertFalse(result["provisoria"])

    def test_distance_above_boundary_uses_next_tier(self):
        result = self.quote(2801)

        self.assertEqual(result["tarifa_base"], "3500.00")
        self.assertEqual(result["monto"], "3500.00")
        self.assertEqual(result["recargo_lluvia"], "0.00")

    def test_distance_over_nine_kilometers_is_not_quoted(self):
        with self.assertRaisesRegex(TarifaNoDisponibleError, "supera los 9 km"):
            self.quote(9001)

    def test_google_routes_request_uses_commerce_origin_and_customer_coordinates(self):
        with patch.dict("os.environ", {"GOOGLE_MAPS_API_KEY": "test-key"}):
            with patch("bot.tarifa.urlopen") as mocked_urlopen:
                mocked_urlopen.return_value.__enter__.return_value.read.return_value = (
                    b'{"routes":[{"distanceMeters":4321}]}'
                )
                distance = _obtener_distancia_metros(
                    "Alem 10, San Rafael",
                    None,
                    -34.61,
                    -68.33,
                )

        self.assertEqual(distance, 4321)
        request = mocked_urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["origin"]["address"], "Alem 10, San Rafael")
        self.assertEqual(
            payload["destination"]["location"]["latLng"],
            {"latitude": -34.61, "longitude": -68.33},
        )
        self.assertEqual(payload["travelMode"], "DRIVE")


if __name__ == "__main__":
    unittest.main()
