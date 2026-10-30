import os
from decimal import Decimal, InvalidOperation
from typing import Optional


def consultar_tarifa(
    direccion: Optional[str] = None,
    latitud: Optional[float] = None,
    longitud: Optional[float] = None,
) -> dict:
    if not direccion and (latitud is None or longitud is None):
        raise ValueError("Indicá una dirección o una ubicación completa.")

    raw_amount = os.environ.get("TARIFA_PROVISORIA")
    if not raw_amount:
        raise RuntimeError("Falta configurar TARIFA_PROVISORIA.")
    try:
        amount = Decimal(raw_amount)
    except InvalidOperation as error:
        raise RuntimeError("TARIFA_PROVISORIA debe ser un monto numérico.") from error
    if not amount.is_finite() or amount < 0 or amount > Decimal("99999999.99"):
        raise RuntimeError(
            "TARIFA_PROVISORIA debe estar entre 0 y 99999999.99."
        )

    return {"monto": str(amount.quantize(Decimal("0.01"))), "provisoria": True}
