"""
Diagnostic: replicate exactly what AnalysisPipeline does so we can see
why LM Studio is returning empty agent output.

Runs three checks:
  A. /v1/models         – is the server reachable?
  B. tiny prompt        – does streaming work at all?
  C. realistic prompt   – send the same context size the agents send
                          and capture every line of the SSE stream.
"""
import io
import json
import sys
import time
import requests
from pathlib import Path

# Force UTF-8 console output (LM Studio responses contain emoji / box chars).
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mendix_analyzer.scanner import MendixScanner          # noqa: E402
from mendix_analyzer.pipeline import ARCHITECT_PROMPT      # noqa: E402

BASE = "http://localhost:1234"
MPR  = r"D:\LCGPA_Branches\EV_Production_v10\LCGPA Service Application.mpr"


def hr(t):
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78, flush=True)


def list_models():
    hr("A. /v1/models")
    r = requests.get(f"{BASE}/v1/models", timeout=10)
    print(f"HTTP {r.status_code}")
    data = r.json()
    ids = [m["id"] for m in data.get("data", [])]
    for mid in ids:
        print(f"  - {mid}")
    return ids


def stream_chat(model, messages, max_tokens, label):
    hr(f"{label}  model={model}  max_tokens={max_tokens}")
    sys_chars = sum(len(m["content"]) for m in messages)
    print(f"prompt chars={sys_chars:,}  approx_tokens={sys_chars // 4:,}")

    payload = {"model": model, "messages": messages, "stream": True,
               "temperature": 0.3, "max_tokens": max_tokens}

    t0 = time.time()
    n_lines = n_data = n_content = n_reasoning = n_other = 0
    content = ""
    reasoning = ""
    finish_reason = None
    first_token_at = None
    other_keys: set = set()
    sample_lines: list = []

    with requests.post(f"{BASE}/v1/chat/completions", json=payload,
                       stream=True, timeout=600) as r:
        print(f"HTTP {r.status_code}  CT={r.headers.get('Content-Type')}")
        if r.status_code != 200:
            print("BODY:", r.text[:2000])
            return
        for raw in r.iter_lines():
            if raw is None:
                continue
            n_lines += 1
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            if not line:
                continue
            if len(sample_lines) < 5:
                sample_lines.append(line[:300])
            if not line.startswith("data: "):
                continue
            n_data += 1
            data_str = line[6:]
            if data_str.strip() == "[DONE]":
                break
            try:
                obj = json.loads(data_str)
            except json.JSONDecodeError as e:
                print(f"  ! JSON error: {e}; payload={data_str[:200]}")
                continue
            try:
                choice = obj["choices"][0]
            except (KeyError, IndexError):
                continue
            delta = choice.get("delta", {}) or {}
            other_keys.update(k for k in delta.keys()
                              if k not in ("role", "content", "reasoning_content"))
            ctok = delta.get("content")
            rtok = delta.get("reasoning_content")
            if ctok:
                if first_token_at is None:
                    first_token_at = time.time() - t0
                n_content += 1
                content += ctok
            if rtok:
                n_reasoning += 1
                reasoning += rtok
            if not ctok and not rtok and (delta.get("role") is None):
                n_other += 1
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]

    elapsed = time.time() - t0
    print(f"\nFIRST 5 RAW LINES:")
    for s in sample_lines:
        print(f"   {s}")
    print(f"\nlines={n_lines}  data_lines={n_data}  content_chunks={n_content}  "
          f"reasoning_chunks={n_reasoning}  other_delta_chunks={n_other}")
    print(f"finish_reason={finish_reason}  elapsed={elapsed:.1f}s  "
          f"ttft={first_token_at if first_token_at is not None else 'n/a'}")
    print(f"unexpected delta keys: {sorted(other_keys) or 'none'}")
    print(f"content_len={len(content):,}  reasoning_len={len(reasoning):,}")
    print(f"\nCONTENT PREVIEW (first 600 chars):")
    print(content[:600] if content else "  <empty>")
    if reasoning and not content:
        print(f"\nREASONING PREVIEW (first 400 chars) – content was empty:")
        print(reasoning[:400])


def main():
    ids = list_models()
    chat_models = [m for m in ids if "embed" not in m.lower()]
    if not chat_models:
        print("No chat models loaded in LM Studio – aborting.")
        return

    # B. tiny smoke test on every chat model
    for m in chat_models:
        stream_chat(
            m,
            [{"role": "user", "content": "Say exactly: pong."}],
            max_tokens=128,
            label=f"B. tiny smoke test [{m}]",
        )

    print("\nBuilding realistic project context (scanner + MPR)...")
    scanner = MendixScanner()
    scan = scanner.scan(MPR)
    ctx  = scanner.to_context_string(scan)
    print(f"context built: {len(ctx):,} chars  ({len(ctx)//4:,} tokens approx)")

    user_content = "## PROJECT METADATA\n" + ctx
    messages = [{"role": "system", "content": ARCHITECT_PROMPT},
                {"role": "user",   "content": user_content}]

    # C. realistic Architect prompt on every chat model
    for m in chat_models:
        stream_chat(m, messages, max_tokens=8192,
                    label=f"C. realistic Architect prompt [{m}]")


if __name__ == "__main__":
    main()
