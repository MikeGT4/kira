"""Smoke-Test: terminal.md prompt gegen gemma3:4b mit 4 realistischen Inputs.

Reproduziert Mike's Bug: 4b halluziniert "git status" auf alle Inputs.
Nach dem Prompt-Härten sollte das nicht mehr passieren.
"""
import ollama

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

print(f"Testing terminal.md gegen gemma3:4b auf {len(TEST_INPUTS)} Inputs\n")
print("=" * 70)

bad_outputs = 0
for inp in TEST_INPUTS:
    prompt = PROMPT.format(text=inp)
    try:
        resp = ollama.chat(
            model="gemma3:4b",
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.2},
            keep_alive="5m",
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
