"""Smoke-Test: terminal.md-Prompt gegen ein Ollama-Modell mit realistischen Inputs.

Modell als optionales CLI-Argument (`python probe_terminal_prompt.py qwen3:8b`),
Default gemma3:4b. Reproduziert Mike's Bug: schwache Modelle halluzinieren
"git status" auf alle Inputs. Nach dem Prompt-Härten sollte das nicht mehr
passieren.
"""
import sys
import ollama

# Modell aus argv[1], sonst der urspruengliche Bug-Reproducer gemma3:4b.
MODEL = sys.argv[1] if len(sys.argv) > 1 else "gemma3:4b"

PROMPT = open(
    r"C:\Users\mike\dev\kira\prompts\terminal.md",
    encoding="utf-8",
).read()

TEST_INPUTS = [
    # Bug-Reproducer aus Mike's Log
    "Okay, das heisst, wir muessen jetzt erstmal schauen auf der PBX, "
    "ob diese 880 schon vergeben ist",
    "Heisst das, wir schauen zuerst mal, ob die 880 irgendwo vergeben ist "
    "oder kannst",
    "Hallo?",
    "Okay, ich meine, wenn nichts Destruktives dabei ist, warum wollen wir das nicht",
    # Echte Shell-Befehle (sollten funktionieren)
    "get status",
    "ssh root att 192 168 1 1",
]

print(f"Testing terminal.md gegen {MODEL} auf {len(TEST_INPUTS)} Inputs\n")
print("=" * 70)

bad_outputs = 0
for inp in TEST_INPUTS:
    prompt = PROMPT.format(text=inp)
    try:
        resp = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2},
            keep_alive="5m",
            # Qwen 3 & Co. denken sonst per Default — fuer eine treue
            # Polish-Pruefung muss das aus, sonst leaken <think>-Bloecke.
            **({"think": False} if "qwen3" in MODEL.lower() else {}),
        )
        out = resp["message"]["content"].strip()
        # Bug: Output ist "git status" obwohl Input das nicht war
        is_bug = (
            out.lower() == "git status"
            and "get status" not in inp.lower()
            and "git status" not in inp.lower()
        )
        if is_bug:
            bad_outputs += 1
            tag = "BUG"
        else:
            tag = "OK "
        print(f"\n[{tag}] IN  ({len(inp):3d}c): {inp[:60]!r}")
        print(f"      OUT ({len(out):3d}c): {out[:80]!r}")
    except Exception as e:
        print(f"\n[ERR] IN: {inp[:60]!r}\n      {e}")

print("\n" + "=" * 70)
print(f"Buggy outputs: {bad_outputs} / {len(TEST_INPUTS)}")
