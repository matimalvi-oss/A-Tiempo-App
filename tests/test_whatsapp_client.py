import io
import json
import unittest
from unittest.mock import patch

from bot.whatsapp_client import WhatsAppDeliveryError, enviar_texto


class WhatsAppClientTests(unittest.TestCase):
    @patch.dict(
        "os.environ",
        {
            "WHATSAPP_TOKEN": "test-access-token",
            "WHATSAPP_PHONE_NUMBER_ID": "123456789",
            "META_GRAPH_API_VERSION": "v22.0",
        },
    )
    @patch("bot.whatsapp_client.urlopen")
    def test_sends_bearer_token_to_configured_phone_number(self, urlopen_mock):
        response = io.BytesIO(
            json.dumps({"messages": [{"id": "wamid.sent"}]}).encode("utf-8")
        )
        response.__enter__ = lambda self: self
        response.__exit__ = lambda self, *args: None
        urlopen_mock.return_value = response

        message_id = enviar_texto("5492604000000", "Hola")

        self.assertEqual(message_id, "wamid.sent")
        request = urlopen_mock.call_args.args[0]
        self.assertEqual(
            request.get_header("Authorization"),
            "Bearer test-access-token",
        )
        self.assertIn("/123456789/messages", request.full_url)

    @patch.dict(
        "os.environ",
        {
            "WHATSAPP_TOKEN": "test-access-token",
            "WHATSAPP_PHONE_NUMBER_ID": "123456789",
        },
    )
    @patch("bot.whatsapp_client.urlopen")
    def test_exposes_meta_error_code_and_message_without_token(self, urlopen_mock):
        error_body = json.dumps(
            {
                "error": {
                    "message": "Invalid recipient for token test-access-token",
                    "type": "OAuthException",
                    "code": 100,
                }
            }
        ).encode("utf-8")
        urlopen_mock.side_effect = __import__("urllib.error").error.HTTPError(
            url="https://graph.facebook.com/test",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(error_body),
        )

        with self.assertRaises(WhatsAppDeliveryError) as raised:
            enviar_texto("5492604000000", "Hola")

        message = str(raised.exception)
        self.assertIn("HTTP 400", message)
        self.assertIn("code=100", message)
        self.assertIn("Invalid recipient", message)
        self.assertNotIn("test-access-token", message)


if __name__ == "__main__":
    unittest.main()
