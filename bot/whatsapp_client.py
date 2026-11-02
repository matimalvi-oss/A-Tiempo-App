import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class WhatsAppDeliveryError(RuntimeError):
    pass


def enviar_texto(destinatario: str, texto: str) -> str:
    access_token = os.environ.get("WHATSAPP_TOKEN")
    phone_number_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
    api_version = os.environ.get("META_GRAPH_API_VERSION", "v22.0")
    if not access_token or not phone_number_id:
        raise WhatsAppDeliveryError(
            "Faltan WHATSAPP_TOKEN o WHATSAPP_PHONE_NUMBER_ID."
        )

    request = Request(
        f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages",
        data=json.dumps(
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": destinatario,
                "type": "text",
                "text": {"preview_url": False, "body": texto},
            },
            ensure_ascii=False,
        ).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            response_body = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        try:
            error_body = json.loads(error.read(4096).decode("utf-8"))
            provider_error = error_body.get("error", {})
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            provider_error = {}
        if not isinstance(provider_error, dict):
            provider_error = {}
        provider_message = str(provider_error.get("message", ""))
        provider_message = (
            provider_message.replace(access_token, "[REDACTED]")
            .replace(destinatario, "[REDACTED]")
            .replace(phone_number_id, "[REDACTED]")[:300]
        )
        provider_code = provider_error.get("code", "unknown")
        provider_type = provider_error.get("type", "unknown")
        raise WhatsAppDeliveryError(
            f"WhatsApp Cloud API rechazó el envío (HTTP {error.code}, "
            f"code={provider_code}, type={provider_type}): "
            f"{provider_message or 'Meta no devolvió detalle del error.'}"
        ) from error
    except (TimeoutError, OSError, URLError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise WhatsAppDeliveryError(
            f"No se pudo completar el envío por WhatsApp ({type(error).__name__})."
        ) from error

    messages = response_body.get("messages", []) if isinstance(response_body, dict) else []
    if not messages or not isinstance(messages[0], dict) or not messages[0].get("id"):
        raise WhatsAppDeliveryError("WhatsApp no devolvió el id del mensaje enviado.")
    return messages[0]["id"]
