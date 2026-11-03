import json
import os
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from database import get_db


CENTAVO = Decimal("0.01")


class TarifaNoDisponibleError(RuntimeError):
    pass


def _obtener_distancia_metros(
    origen: str,
    direccion: Optional[str],
    latitud: Optional[float],
    longitud: Optional[float],
) -> int:
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise TarifaNoDisponibleError(
            "Falta configurar GOOGLE_MAPS_API_KEY."
        )
    if not origen.strip():
        raise TarifaNoDisponibleError(
            "El comercio no tiene una dirección de origen configurada."
        )
    if not direccion and (latitud is None or longitud is None):
        raise TarifaNoDisponibleError(
            "Falta la dirección o ubicación de destino."
        )

    destination = (
        {"location": {"latLng": {"latitude": latitud, "longitude": longitud}}}
        if latitud is not None and longitud is not None
        else {"address": direccion}
    )
    payload = {
        "origin": {"address": origen},
        "destination": destination,
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_UNAWARE",
    }
    request = Request(
        "https://routes.googleapis.com/directions/v2:computeRoutes",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "routes.distanceMeters",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise TarifaNoDisponibleError(
            f"Google Maps rechazó la cotización (HTTP {error.code})."
        ) from error
    except (TimeoutError, OSError, URLError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TarifaNoDisponibleError(
            f"No se pudo calcular el recorrido ({type(error).__name__})."
        ) from error

    routes = result.get("routes") if isinstance(result, dict) else None
    if (
        not isinstance(routes, list)
        or not routes
        or not isinstance(routes[0], dict)
    ):
        raise TarifaNoDisponibleError(
            "Google Maps no encontró un recorrido para esas direcciones."
        )
    distance_meters = routes[0].get("distanceMeters")
    if (
        isinstance(distance_meters, bool)
        or not isinstance(distance_meters, int)
        or distance_meters < 0
    ):
        raise TarifaNoDisponibleError(
            "Google Maps devolvió una distancia inválida."
        )
    return distance_meters


def _tarifa_base(distancia_km: Decimal) -> Decimal:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT limite_km, monto
            FROM bot_tarifas_distancia
            ORDER BY limite_km
            """
        )
        rows = cursor.fetchall()
    finally:
        conn.close()

    for row in rows:
        limit = Decimal(str(row["limite_km"]))
        if distancia_km <= limit:
            return Decimal(str(row["monto"])).quantize(CENTAVO)
    raise TarifaNoDisponibleError(
        "El recorrido supera los 9 km y no tiene una tarifa configurada."
    )


def _recargo_lluvia_activo() -> bool:
    conn = get_db()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT valor FROM bot_configuracion WHERE clave = %s",
            ("recargo_lluvia_activo",),
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if not row:
        raise TarifaNoDisponibleError(
            "No está configurada la activación del recargo por lluvia."
        )
    value = str(row["valor"]).strip().lower()
    if value not in {"true", "false"}:
        raise TarifaNoDisponibleError(
            "La configuración del recargo por lluvia debe ser true o false."
        )
    return value == "true"


def consultar_tarifa(
    origen: str,
    direccion: Optional[str] = None,
    latitud: Optional[float] = None,
    longitud: Optional[float] = None,
) -> dict:
    distance_meters = _obtener_distancia_metros(
        origen, direccion, latitud, longitud
    )
    distance_km = Decimal(distance_meters) / Decimal("1000")
    base = _tarifa_base(distance_km)
    rain_active = _recargo_lluvia_activo()
    surcharge = (
        (base * Decimal("0.50")).quantize(CENTAVO, rounding=ROUND_HALF_UP)
        if rain_active
        else Decimal("0.00")
    )
    total = base + surcharge

    return {
        "distancia_km": str(distance_km.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "tarifa_base": str(base),
        "recargo_lluvia": str(surcharge),
        "recargo_lluvia_aplicado": rain_active,
        "monto": str(total.quantize(CENTAVO)),
        "provisoria": False,
    }
