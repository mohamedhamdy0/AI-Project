"""
AI Client - supports Ollama, OpenAI-compatible local providers
(LM Studio, Jan, AnythingLLM, Llamafile) and built-in llama-cpp-python.
"""
import json
import os
import requests
from pathlib import Path
from typing import Callable, List, Dict, Optional, Tuple

# Built-in model directory (inside project)
MODELS_DIR = Path(__file__).parent.parent / "models"


PROVIDERS = {
    "Ollama": {
        "base_url": "http://localhost:11434",
        "models_ep": "/api/tags",
        "chat_ep": "/api/chat",
        "type": "ollama",
    },
    "LM Studio": {
        "base_url": "http://localhost:1234",
        "models_ep": "/v1/models",
        "chat_ep": "/v1/chat/completions",
        "type": "openai",
    },
    "Jan": {
        "base_url": "http://localhost:1337",
        "models_ep": "/v1/models",
        "chat_ep": "/v1/chat/completions",
        "type": "openai",
    },
    "AnythingLLM": {
        "base_url": "http://localhost:3001",
        "models_ep": "/v1/models",
        "chat_ep": "/v1/chat/completions",
        "type": "openai",
    },
    "Llamafile": {
        "base_url": "http://localhost:8080",
        "models_ep": "/v1/models",
        "chat_ep": "/v1/chat/completions",
        "type": "openai",
    },
    "Custom": {
        "base_url": "http://localhost:11434",
        "models_ep": "/api/tags",
        "chat_ep": "/api/chat",
        "type": "ollama",
    },
    "Built-in (GGUF)": {
        "base_url": "",
        "models_ep": "",
        "chat_ep": "",
        "type": "builtin",
    },
}


# ── Built-in llama-cpp-python engine ─────────────────────────────────────── #

def _builtin_available() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except ImportError:
        return False


def _list_gguf_models() -> List[str]:
    MODELS_DIR.mkdir(exist_ok=True)
    return [f.name for f in MODELS_DIR.glob("*.gguf")]


def _run_builtin(model_name: str, messages: List[Dict],
                 on_token: Optional[Callable[[str], None]],
                 temperature: float) -> str:
    from llama_cpp import Llama
    model_path = str(MODELS_DIR / model_name)
    llm = Llama(model_path=model_path, n_ctx=4096, n_threads=4,
                n_gpu_layers=-1, verbose=False)
    full = ""
    if on_token:
        stream = llm.create_chat_completion(
            messages=messages, temperature=temperature, stream=True, max_tokens=2048)
        for chunk in stream:
            tok = chunk["choices"][0]["delta"].get("content", "")
            if tok:
                full += tok
                on_token(tok)
    else:
        resp = llm.create_chat_completion(
            messages=messages, temperature=temperature, max_tokens=2048)
        full = resp["choices"][0]["message"]["content"]
    return full


class AIClient:
    def __init__(self, provider: str, base_url: str = "", api_key: str = ""):
        cfg = PROVIDERS.get(provider, PROVIDERS["Ollama"])
        self.api_type  = cfg["type"]
        self.models_ep = cfg["models_ep"]
        self.chat_ep   = cfg["chat_ep"]
        self.base_url  = (base_url.strip().rstrip("/") or cfg["base_url"])
        self.api_key   = api_key.strip()

    @property
    def _headers(self) -> Dict:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def test_connection(self) -> Tuple[bool, str]:
        if self.api_type == "builtin":
            if not _builtin_available():
                return False, "❌ llama-cpp-python not installed (pip install llama-cpp-python)"
            models = _list_gguf_models()
            if not models:
                return False, "❌ No .gguf files found in models/ folder"
            return True, f"✅ Built-in engine ready ({len(models)} model(s))"
        try:
            r = requests.get(f"{self.base_url}{self.models_ep}", timeout=5, headers=self._headers)
            if r.status_code == 200:
                return True, "✅ Connected"
            return False, f"❌ HTTP {r.status_code}"
        except requests.ConnectionError:
            return False, "❌ Connection refused — is the service running?"
        except requests.Timeout:
            return False, "❌ Timed out"
        except Exception as e:
            return False, f"❌ {e}"

    def list_models(self) -> List[str]:
        if self.api_type == "builtin":
            return _list_gguf_models()
        try:
            r = requests.get(f"{self.base_url}{self.models_ep}", timeout=10, headers=self._headers)
            r.raise_for_status()
            data = r.json()
            if self.api_type == "ollama":
                return [m["name"] for m in data.get("models", [])]
            else:
                return [m["id"] for m in data.get("data", [])]
        except Exception:
            return []

    def chat(
        self,
        model: str,
        messages: List[Dict],
        on_token: Optional[Callable[[str], None]] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        if self.api_type == "builtin":
            return _run_builtin(model, messages, on_token, temperature)
        if self.api_type == "ollama":
            return self._chat_ollama(model, messages, on_token, temperature, max_tokens)
        return self._chat_openai(model, messages, on_token, temperature, max_tokens)

    # ------------------------------------------------------------------ #
    def _chat_ollama(self, model, messages, on_token, temperature, max_tokens) -> str:
        url     = f"{self.base_url}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": bool(on_token),
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        full = ""
        if on_token:
            with requests.post(url, json=payload, stream=True,
                               headers=self._headers, timeout=600) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(d, dict) and d.get("error"):
                        raise RuntimeError(f"Ollama error: {d['error']}")
                    tok = d.get("message", {}).get("content", "")
                    if tok:
                        full += tok
                        on_token(tok)
                    if d.get("done"):
                        break
        else:
            payload["stream"] = False
            r = requests.post(url, json=payload, headers=self._headers, timeout=600)
            r.raise_for_status()
            j = r.json()
            if isinstance(j, dict) and j.get("error"):
                raise RuntimeError(f"Ollama error: {j['error']}")
            full = j.get("message", {}).get("content", "")
        return full

    def _chat_openai(self, model, messages, on_token, temperature, max_tokens) -> str:
        url     = f"{self.base_url}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": messages,
            "stream": bool(on_token),
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if on_token:
            content_buf, reasoning_buf, in_reasoning = "", "", False
            current_event = "message"  # default SSE event
            with requests.post(url, json=payload, stream=True,
                               headers=self._headers, timeout=600) as r:
                if r.status_code != 200:
                    raise RuntimeError(
                        f"HTTP {r.status_code} from {self.base_url}: {r.text[:500]}")
                for raw in r.iter_lines():
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
                    # Track SSE event: lines (LM Studio uses `event: error` for failures)
                    if line.startswith("event: "):
                        current_event = line[7:].strip()
                        continue
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        obj = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    # Inline error payload (LM Studio sends `event: error` then a data
                    # line containing `{"error": {"message": ...}}`)
                    err = obj.get("error") if isinstance(obj, dict) else None
                    if current_event == "error" or err:
                        msg = (err.get("message") if isinstance(err, dict)
                               else (obj.get("message") or str(err) if err
                                     else "Unknown upstream error"))
                        raise RuntimeError(f"Upstream provider error: {msg}")
                    try:
                        delta = obj["choices"][0].get("delta", {}) or {}
                    except (KeyError, IndexError):
                        continue
                    rtok = delta.get("reasoning_content") or ""
                    ctok = delta.get("content") or ""
                    if rtok:
                        if not in_reasoning:
                            in_reasoning = True
                            on_token("💭 [thinking] ")
                        reasoning_buf += rtok
                        on_token(rtok)
                    if ctok:
                        if in_reasoning:
                            in_reasoning = False
                            on_token("\n\n💡 [answer]\n")
                        content_buf += ctok
                        on_token(ctok)
            # Reasoning models may exhaust max_tokens before producing content.
            # In that case surface the reasoning as the answer so the report has data.
            return content_buf or reasoning_buf
        else:
            payload["stream"] = False
            r = requests.post(url, json=payload, headers=self._headers, timeout=600)
            if r.status_code != 200:
                raise RuntimeError(
                    f"HTTP {r.status_code} from {self.base_url}: {r.text[:500]}")
            j = r.json()
            if isinstance(j, dict) and j.get("error"):
                err = j["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                raise RuntimeError(f"Upstream provider error: {msg}")
            msg = j["choices"][0]["message"]
            return msg.get("content") or msg.get("reasoning_content") or ""
