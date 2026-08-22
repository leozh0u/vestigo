"""The vendors.

Two implementations cover nearly everything. Anthropic has its own message
format. Almost everyone else, Moonshot's Kimi included, along with DeepSeek,
Together, Groq, vLLM and Ollama, speaks the OpenAI chat format, so one class
with a different base URL reaches all of them.

Raw HTTP through the standard library rather than each vendor's SDK. Three
reasons, in order: the package still has no dependencies, an SDK per vendor is
three dependencies to reach two APIs, and the wire formats here are small
enough that the adapter is shorter than the integration code would be.

There is also a fake provider, which is what the tests use. Nothing in this
project's test suite is allowed to cost money or need a network.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import replace

from .llm import (
    Completion,
    Image,
    LLMError,
    Provider,
    Request,
    Text,
    Usage,
    extract_json,
)

TIMEOUT_S = 120.0


def _post(url: str, headers: dict, payload: dict) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"content-type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise LLMError(f"{exc.code} from {url}: {detail}") from None
    except urllib.error.URLError as exc:
        raise LLMError(f"could not reach {url}: {exc.reason}") from None


def _require_key(env_var: str, given: str | None) -> str:
    key = given or os.environ.get(env_var) or _from_dotenv(env_var)
    if not key:
        raise LLMError(
            f"no API key. Set {env_var} in the environment or add it to .env, "
            "which is gitignored."
        )
    return key


def _from_dotenv(name: str) -> str | None:
    """Read one key out of .env without pulling in a dotenv library.

    Last occurrence wins, which is what a shell does with a repeated export and
    what someone expects after appending a second line. The first version took
    the first match, so appending a real key below a placeholder left the
    placeholder in charge and produced a 401 that pointed nowhere near the
    cause. Quotes are stripped, since a pasted key often arrives wearing them.
    """
    import pathlib
    path = pathlib.Path(".env")
    if not path.exists():
        return None
    found = None
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("#") or not line.startswith(f"{name}="):
            continue
        value = line.split("=", 1)[1].strip().strip("'\"")
        if value:
            found = value
    return found


# --------------------------------------------------------------------------

class AnthropicProvider(Provider):
    """Claude, through the Messages API."""

    name = "anthropic"
    default_model = "claude-sonnet-5"
    base_url = "https://api.anthropic.com/v1/messages"
    api_version = "2023-06-01"

    def __init__(self, model: str = "", *, api_key: str | None = None, **kw):
        super().__init__(model, **kw)
        self._key = api_key

    def _headers(self) -> dict:
        return {"x-api-key": _require_key("ANTHROPIC_API_KEY", self._key),
                "anthropic-version": self.api_version}

    @staticmethod
    def _content(part) -> dict:
        if isinstance(part, Text):
            return {"type": "text", "text": part.text}
        if isinstance(part, Image):
            return {"type": "image",
                    "source": {"type": "base64", "media_type": part.media_type,
                               "data": part.b64}}
        raise LLMError(f"cannot send {type(part).__name__}")

    def _send(self, request: Request, model: str) -> Completion:
        payload = {
            "model": model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [{"role": str(m.role),
                          "content": [self._content(p) for p in m.content]}
                         for m in request.messages],
        }
        if request.system:
            # Marked for caching: the system prompt and tool definitions are
            # identical across every image in an eval, and a cached prefix bills
            # at about a tenth of the input rate.
            payload["system"] = [{"type": "text", "text": request.system,
                                  "cache_control": {"type": "ephemeral"}}]

        tools = list(request.tools)
        if request.schema is not None:
            # Structured output through a single forced tool, which is the
            # reliable route here and needs no separate mode.
            tools.append({"name": "answer",
                          "description": "Return the answer in this shape.",
                          "input_schema": request.schema})
            payload["tool_choice"] = {"type": "tool", "name": "answer"}
        if tools:
            payload["tools"] = tools

        data = _post(self.base_url, self._headers(), payload)
        return self._parse(data, model, request)

    def _parse(self, data: dict, model: str, request: Request) -> Completion:
        text_parts, tool_calls, structured = [], [], None
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                tool_calls.append({"name": block["name"], "input": block["input"],
                                   "id": block.get("id", "")})
                if request.schema is not None and block["name"] == "answer":
                    structured = block["input"]

        raw = data.get("usage", {})
        return Completion(
            text="\n".join(text_parts),
            model=data.get("model", model),
            usage=Usage(
                input_tokens=raw.get("input_tokens", 0)
                + raw.get("cache_read_input_tokens", 0)
                + raw.get("cache_creation_input_tokens", 0),
                output_tokens=raw.get("output_tokens", 0),
                cached_tokens=raw.get("cache_read_input_tokens", 0),
                model=model,
                batched=self.batched,
            ),
            structured=structured,
            tool_calls=tuple(tool_calls),
            stop_reason=data.get("stop_reason", ""),
        )


class OpenAICompatProvider(Provider):
    """Anything speaking the OpenAI chat format.

    Kimi, DeepSeek, Together, Groq, and a local vLLM or Ollama server. Point
    `base_url` at the vendor and set the key variable. Subclass it when a
    vendor needs a different default, which is usually all that differs.
    """

    name = "openai-compat"
    default_model = "gpt-4o-mini"
    base_url = "https://api.openai.com/v1/chat/completions"
    key_env = "OPENAI_API_KEY"

    def __init__(self, model: str = "", *, api_key: str | None = None,
                 base_url: str | None = None, key_env: str | None = None,
                 name: str | None = None, **kw):
        if base_url:
            self.base_url = base_url
        if key_env:
            self.key_env = key_env
        if name:
            self.name = name
        super().__init__(model, **kw)
        self._key = api_key

    @staticmethod
    def _content(part) -> dict:
        if isinstance(part, Text):
            return {"type": "text", "text": part.text}
        if isinstance(part, Image):
            return {"type": "image_url",
                    "image_url": {"url": f"data:{part.media_type};base64,{part.b64}"}}
        raise LLMError(f"cannot send {type(part).__name__}")

    def _send(self, request: Request, model: str) -> Completion:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages += [{"role": str(m.role),
                      "content": [self._content(p) for p in m.content]}
                     for m in request.messages]

        payload = {"model": model, "messages": messages,
                   "max_tokens": request.max_tokens,
                   "temperature": request.temperature}
        if request.tools:
            payload["tools"] = [{"type": "function",
                                 "function": {"name": t["name"],
                                              "description": t.get("description", ""),
                                              "parameters": t["input_schema"]}}
                                for t in request.tools]
        if request.schema is not None:
            # Not every compatible server implements json_schema mode, so the
            # schema also goes in the prompt and the reply is parsed either way.
            payload["response_format"] = {"type": "json_object"}
            messages.append({"role": "system",
                             "content": "Reply with one JSON object matching this "
                                        f"schema and nothing else: "
                                        f"{json.dumps(request.schema)}"})

        headers = {"authorization": f"Bearer {_require_key(self.key_env, self._key)}"}
        data = _post(self.base_url, headers, payload)
        return self._parse(data, model, request)

    def _parse(self, data: dict, model: str, request: Request) -> Completion:
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"no choices in reply from {self.name}")
        message = choices[0].get("message", {})
        text = message.get("content") or ""

        tool_calls = tuple(
            {"name": c["function"]["name"],
             "input": json.loads(c["function"].get("arguments") or "{}"),
             "id": c.get("id", "")}
            for c in message.get("tool_calls") or []
        )

        structured = None
        if request.schema is not None:
            try:
                structured = extract_json(text)
            except (ValueError, json.JSONDecodeError):
                structured = tool_calls[0]["input"] if tool_calls else None

        raw = data.get("usage", {})
        cached = (raw.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        return Completion(
            text=text,
            model=data.get("model", model),
            usage=Usage(input_tokens=raw.get("prompt_tokens", 0),
                        output_tokens=raw.get("completion_tokens", 0),
                        cached_tokens=cached,
                        model=model,
                        batched=self.batched),
            structured=structured,
            tool_calls=tool_calls,
            stop_reason=choices[0].get("finish_reason", ""),
        )


class MoonshotProvider(OpenAICompatProvider):
    """Kimi. Open weights, strong at tool use, and a fraction of the price.

    No entry in PRICING, deliberately. Their rates move and depend on which
    host you use, so putting a stale number here would make the budget confident
    and wrong. Add the current figure before running anything large.
    """

    name = "moonshot"
    default_model = "kimi-k2-0711-preview"
    base_url = "https://api.moonshot.ai/v1/chat/completions"
    key_env = "MOONSHOT_API_KEY"


class OpenRouterProvider(OpenAICompatProvider):
    """One key, most models.

    Worth more here than the price difference. The calibration thesis wants the
    same eval run against two vendors, and doing that through one endpoint makes
    the comparison a string change rather than a second integration. Model names
    carry the vendor, as in "anthropic/claude-sonnet-5" or
    "moonshotai/kimi-k2".

    Nothing is in PRICING for it, on purpose. Rates vary per underlying model
    and change, so the budget will refuse until a real figure is added, which is
    the intended behaviour.
    """

    name = "openrouter"
    default_model = "anthropic/claude-sonnet-5"
    base_url = "https://openrouter.ai/api/v1/chat/completions"
    key_env = "OPENROUTER_API_KEY"


class LocalProvider(OpenAICompatProvider):
    """A model on this machine, through Ollama or vLLM.

    The right home for the observation extractor: highest volume, most
    image-heavy, least reasoning, and here the marginal cost is zero rather
    than merely low.
    """

    name = "local"
    default_model = "qwen2.5vl:7b"
    base_url = "http://localhost:11434/v1/chat/completions"
    key_env = "LOCAL_API_KEY"

    def __init__(self, model: str = "", **kw):
        super().__init__(model, api_key=kw.pop("api_key", "not-needed"), **kw)


class FakeProvider(Provider):
    """A scripted provider, for tests and for dry runs of the agent.

    Every test in this project uses it. Nothing in the suite may cost money or
    need a network, or the suite stops being something anyone runs often.
    """

    name = "fake"
    default_model = "fake-1"

    def __init__(self, replies=None, *, model: str = "", **kw):
        super().__init__(model, **kw)
        self.replies = list(replies or [])
        self.calls: list[Request] = []

    def _send(self, request: Request, model: str) -> Completion:
        self.calls.append(request)
        reply = self.replies.pop(0) if self.replies else ""
        if isinstance(reply, Completion):
            return replace(reply, model=model)
        if isinstance(reply, dict):
            return Completion(text=json.dumps(reply), model=model, structured=reply,
                              usage=Usage(100, 50, model=model))
        if isinstance(reply, Exception):
            raise reply
        return Completion(text=str(reply), model=model, usage=Usage(100, 50, model=model))
