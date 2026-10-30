import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .tools import BotTools, TOOL_DECLARATIONS, ToolValidationError


class GeminiAgentError(RuntimeError):
    pass


class GeminiClient:
    def generate(
        self,
        model: str,
        system_instruction: str,
        contents: list[dict],
        tools: list[dict],
    ) -> dict:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise GeminiAgentError("Falta configurar GEMINI_API_KEY.")
        if not model:
            raise GeminiAgentError("Falta configurar GEMINI_MODEL.")

        payload = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": contents,
            "tools": [{"functionDeclarations": tools}],
            "toolConfig": {
                "functionCallingConfig": {"mode": "AUTO"}
            },
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 1200,
            },
        }
        request = Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except HTTPError as error:
            raise GeminiAgentError(
                f"Gemini rechazó la solicitud (HTTP {error.code})."
            ) from error
        except (TimeoutError, OSError, URLError, UnicodeDecodeError) as error:
            raise GeminiAgentError(
                f"No se pudo completar la solicitud a Gemini ({type(error).__name__})."
            ) from error
        try:
            result = json.loads(body)
        except json.JSONDecodeError as error:
            raise GeminiAgentError("Gemini devolvió JSON inválido.") from error
        if not isinstance(result, dict):
            raise GeminiAgentError("Gemini devolvió una respuesta inválida.")
        return result


class ConversationAgent:
    def __init__(self, client: Any = None, tools: BotTools = None):
        self.client = client or GeminiClient()
        self.tools = tools

    def _system_instruction(
        self, commerce_name: str, open_orders: list[dict], welcome_pending: bool
    ) -> str:
        root = Path(__file__).parent
        system_prompt = (root / "system_prompt.md").read_text(encoding="utf-8")
        frequently_asked_questions = (root / "preguntas_frecuentes.md").read_text(
            encoding="utf-8"
        )
        extra_context = [
            f"Comercio actual: {commerce_name}.",
            "Pedidos abiertos de este comercio (no uses pedidos de otros comercios): "
            + json.dumps(open_orders, ensure_ascii=False, default=str),
        ]
        if welcome_pending:
            extra_context.append(
                "Todavía no se envió el saludo inicial de esta conversación."
            )
        return (
            f"{system_prompt}\n\n"
            f"Preguntas frecuentes:\n{frequently_asked_questions}\n\n"
            f"Contexto de esta conversación:\n- "
            + "\n- ".join(extra_context)
        )

    def run(
        self,
        history: list[dict],
        commerce_name: str,
        open_orders: list[dict],
        welcome_pending: bool,
    ) -> dict:
        model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
        contents = [
            {"role": item["role"], "parts": [{"text": item["text"]}]}
            for item in history
        ]
        if not contents:
            raise GeminiAgentError("No hay mensajes para procesar.")
        system_instruction = self._system_instruction(
            commerce_name, open_orders, welcome_pending
        )
        tool_calls = []

        for iteration in range(5):
            response = self.client.generate(
                model=model,
                system_instruction=system_instruction,
                contents=contents,
                tools=TOOL_DECLARATIONS,
            )
            parts = self._parts(response)
            function_calls = [
                part.get("functionCall", part.get("function_call"))
                for part in parts
                if isinstance(part, dict)
                and (
                    "functionCall" in part
                    or "function_call" in part
                )
            ]
            if not function_calls:
                answer = " ".join(
                    part["text"].strip()
                    for part in parts
                    if isinstance(part, dict)
                    and isinstance(part.get("text"), str)
                    and part["text"].strip()
                ).strip()
                if not answer:
                    raise GeminiAgentError("Gemini no devolvió una respuesta de texto.")
                return {"respuesta": answer, "herramientas": tool_calls}

            contents.append({"role": "model", "parts": parts})
            for function_call in function_calls:
                if not isinstance(function_call, dict):
                    raise GeminiAgentError("Gemini devolvió una herramienta inválida.")
                name = function_call.get("name")
                arguments = function_call.get("args", function_call.get("arguments", {}))
                if not isinstance(name, str) or not name:
                    raise GeminiAgentError("Gemini devolvió una herramienta sin nombre.")
                try:
                    result = self.tools.execute(name, arguments)
                except ToolValidationError as error:
                    result = {"error": str(error)}
                tool_calls.append(
                    {"nombre": name, "argumentos": arguments, "resultado": result}
                )
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": name,
                                    "response": result,
                                }
                            }
                        ],
                    }
                )
            if iteration == 4:
                raise GeminiAgentError(
                    "Gemini superó el máximo de cinco iteraciones con herramientas."
                )
        raise GeminiAgentError("El ciclo de Gemini terminó sin respuesta.")

    @staticmethod
    def _parts(response: dict) -> list:
        candidates = response.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise GeminiAgentError("Gemini no devolvió candidatos.")
        content = candidates[0].get("content", {})
        parts = content.get("parts", []) if isinstance(content, dict) else []
        if not isinstance(parts, list):
            raise GeminiAgentError("Gemini devolvió partes inválidas.")
        return parts
