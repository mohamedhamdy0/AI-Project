"""
Verifies the AIClient fix:
  1. Tiny prompt against the loaded LM Studio model → must return content normally.
  2. Oversized prompt → must now raise RuntimeError with the upstream message
     (previously returned empty string and the agent reports were blank).
"""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mendix_analyzer.ai_client import AIClient                       # noqa: E402
from mendix_analyzer.scanner import MendixScanner                    # noqa: E402
from mendix_analyzer.pipeline import ARCHITECT_PROMPT                # noqa: E402

MPR = r"D:\LCGPA_Branches\EV_Production_v10\LCGPA Service Application.mpr"

client = AIClient("LM Studio")
ok, msg = client.test_connection()
print(f"connection: ok={ok}  msg={msg}")

models = [m for m in client.list_models() if "embed" not in m.lower()]
print(f"chat models: {models}")
model = models[0]


def streaming_call(label, messages):
    print("\n" + "=" * 70)
    print(label)
    print("=" * 70)
    chunks = []

    def on_tok(t):
        chunks.append(t)

    try:
        out = client.chat(model=model, messages=messages,
                          on_token=on_tok, max_tokens=256)
        print(f"OK  output_len={len(out)}  preview={out[:200]!r}")
    except RuntimeError as e:
        print(f"RuntimeError raised (expected for oversized prompt):")
        print(f"   {e}")
    except Exception as e:
        print(f"UNEXPECTED {type(e).__name__}: {e}")


# 1. Tiny prompt — should still work
streaming_call(
    "1. tiny prompt — should succeed",
    [{"role": "user", "content": "Say exactly: pong."}],
)

# 2. Oversized prompt — should raise RuntimeError now (was empty string before)
print("\nBuilding realistic project context (scanner + MPR)...")
scanner = MendixScanner()
scan = scanner.scan(MPR)
ctx = scanner.to_context_string(scan)
print(f"context built: {len(ctx):,} chars")

streaming_call(
    "2. oversized prompt — should raise RuntimeError with provider message",
    [{"role": "system", "content": ARCHITECT_PROMPT},
     {"role": "user",   "content": "## PROJECT METADATA\n" + ctx}],
)

# 3. Non-streaming oversized — same expectation
print("\n" + "=" * 70)
print("3. non-streaming oversized prompt — should also raise RuntimeError")
print("=" * 70)
try:
    out = client.chat(
        model=model,
        messages=[{"role": "system", "content": ARCHITECT_PROMPT},
                  {"role": "user",   "content": "## PROJECT METADATA\n" + ctx}],
        on_token=None,
        max_tokens=256,
    )
    print(f"OK  output_len={len(out)}  preview={out[:200]!r}")
except RuntimeError as e:
    print(f"RuntimeError raised (expected):")
    print(f"   {e}")
except Exception as e:
    print(f"UNEXPECTED {type(e).__name__}: {e}")
