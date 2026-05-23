from unittest.mock import AsyncMock, MagicMock
import pytest
from kira.config import Config, ModeConfig
from kira.styler import (
    Styler,
    load_prompt,
    SLOW_POLISH_THRESHOLD_SEC,
    SLOW_POLISH_TRIGGER_COUNT,
)


@pytest.mark.asyncio
async def test_polish_returns_model_output():
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "Hallo Welt."}})
    styler._client = fake_client
    result = await styler.polish("hallo welt", mode="plain")
    assert result == "Hallo Welt."


@pytest.mark.asyncio
async def test_polish_falls_back_to_raw_on_error():
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(side_effect=Exception("ollama down"))
    styler._client = fake_client
    result = await styler.polish("raw text", mode="plain")
    assert result == "raw text"


@pytest.mark.asyncio
async def test_polish_falls_back_to_raw_on_empty_response():
    """gemma3 occasionally returns an empty content string — must fall back."""
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": ""}})
    styler._client = fake_client
    result = await styler.polish("raw text", mode="plain")
    assert result == "raw text"


@pytest.mark.asyncio
async def test_polish_falls_back_to_raw_on_whitespace_response():
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "   \n  "}})
    styler._client = fake_client
    result = await styler.polish("raw text", mode="plain")
    assert result == "raw text"


@pytest.mark.asyncio
async def test_polish_raises_when_fallback_disabled():
    cfg = Config()
    cfg.styler.fallback_to_raw = False
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(side_effect=Exception("ollama down"))
    styler._client = fake_client
    with pytest.raises(Exception):
        await styler.polish("raw text", mode="plain")


def test_load_prompt_returns_template():
    tpl = load_prompt("plain")
    assert "{text}" in tpl
    assert len(tpl) > 50


def test_load_prompt_unknown_mode_falls_back_to_plain():
    tpl = load_prompt("nonexistent")
    assert "{text}" in tpl


def test_new_prompts_exist_and_have_text_placeholder():
    """Die in v0.2 hinzugefuegten Mode-Prompts muessen das {text}-Token haben,
    sonst wuerde Styler.polish() einen KeyError werfen statt Polish zu liefern."""
    for mode in ("clean", "translate_en", "email_formal"):
        tpl = load_prompt(mode)
        assert "{text}" in tpl, f"prompts/{mode}.md fehlt das {{text}} Token"


@pytest.mark.asyncio
async def test_polish_uses_per_mode_model_override():
    """ModeConfig.model ueberschreibt StylerConfig.model fuer den jeweiligen Mode."""
    cfg = Config()
    cfg.styler.model = "gemma2:2b"
    cfg.styler.modes["translate_en"] = ModeConfig(model="qwen3:8b")
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(
        return_value={"message": {"content": "Hello world."}}
    )
    styler._client = fake_client

    await styler.polish("hallo welt", mode="translate_en")

    fake_client.chat.assert_called_once()
    kwargs = fake_client.chat.call_args.kwargs
    assert kwargs["model"] == "qwen3:8b", \
        "Mode-Override sollte das gemma2:2b-Default ueberschreiben"


@pytest.mark.asyncio
async def test_polish_uses_default_model_when_no_mode_config():
    """Mode ohne Override-Eintrag faellt auf StylerConfig.model zurueck."""
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    # Kein cfg.styler.modes-Eintrag fuer "plain"
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(
        return_value={"message": {"content": "Hallo Welt."}}
    )
    styler._client = fake_client

    await styler.polish("hallo welt", mode="plain")

    kwargs = fake_client.chat.call_args.kwargs
    assert kwargs["model"] == "gemma3:12b"


@pytest.mark.asyncio
async def test_polish_uses_per_mode_temperature():
    cfg = Config()
    cfg.styler.modes["code"] = ModeConfig(temperature=0.0)
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(
        return_value={"message": {"content": "x = 1"}}
    )
    styler._client = fake_client

    await styler.polish("x ist gleich eins", mode="code")

    kwargs = fake_client.chat.call_args.kwargs
    assert kwargs["options"]["temperature"] == 0.0


@pytest.mark.asyncio
async def test_edit_command_calls_llm_with_selection_and_command():
    """edit_command muss beide {selection} und {command} ins Prompt einsetzen."""
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(
        return_value={"message": {"content": "Sehr geehrte Damen und Herren,"}}
    )
    styler._client = fake_client

    result = await styler.edit_command(
        selection="hi leute",
        command="mach das foermlich",
    )

    assert result == "Sehr geehrte Damen und Herren,"
    kwargs = fake_client.chat.call_args.kwargs
    user_msg = kwargs["messages"][0]["content"]
    assert "hi leute" in user_msg
    assert "mach das foermlich" in user_msg


@pytest.mark.asyncio
async def test_edit_command_returns_selection_on_empty_response():
    """Leere LLM-Antwort darf Selection NICHT mit "" ueberschreiben —
    sonst wuerde Strg+V die Selektion mit Garbage ersetzen."""
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": ""}})
    styler._client = fake_client

    result = await styler.edit_command(
        selection="original text",
        command="mach was",
    )
    assert result == "original text"


@pytest.mark.asyncio
async def test_edit_command_returns_selection_on_exception():
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(side_effect=Exception("ollama down"))
    styler._client = fake_client

    result = await styler.edit_command(
        selection="original text",
        command="mach was",
    )
    assert result == "original text"


@pytest.mark.asyncio
async def test_edit_command_skips_llm_when_either_input_empty():
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(
        return_value={"message": {"content": "should-not-see-this"}}
    )
    styler._client = fake_client

    # Empty selection
    assert await styler.edit_command(selection="", command="cmd") == ""
    # Empty command — Selection unveraendert zurueckgeben
    assert await styler.edit_command(
        selection="text", command="",
    ) == "text"
    # LLM darf in beiden Faellen NICHT gerufen worden sein
    fake_client.chat.assert_not_called()


@pytest.mark.asyncio
async def test_edit_command_uses_per_mode_model_override():
    """Ein 'edit_command'-ModeConfig-Eintrag ueberschreibt das Default-Modell."""
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    cfg.styler.modes["edit_command"] = ModeConfig(model="qwen3:8b")
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "out"}})
    styler._client = fake_client

    await styler.edit_command(selection="text", command="cmd")

    kwargs = fake_client.chat.call_args.kwargs
    assert kwargs["model"] == "qwen3:8b"


@pytest.mark.asyncio
async def test_polish_uses_fast_model_when_fast_mode_enabled():
    """fast_mode=True schaltet auf fast_model (Speed-Toggle in Settings)."""
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    cfg.styler.fast_model = "gemma3:4b"
    cfg.styler.fast_mode = True
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "ok"}})
    styler._client = fake_client

    await styler.polish("text", mode="plain")

    assert fake_client.chat.call_args.kwargs["model"] == "gemma3:4b"


@pytest.mark.asyncio
async def test_polish_uses_quality_model_when_fast_mode_disabled():
    """fast_mode=False (Default) muss exakt das alte Behavior reproduzieren."""
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    cfg.styler.fast_model = "gemma3:4b"
    cfg.styler.fast_mode = False
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "ok"}})
    styler._client = fake_client

    await styler.polish("text", mode="plain")

    assert fake_client.chat.call_args.kwargs["model"] == "gemma3:12b"


@pytest.mark.asyncio
async def test_polish_per_mode_override_beats_fast_mode():
    """Hierarchie: Per-Mode-Override > fast_mode > Default. Per-Mode bleibt
    immer der explizite User-Wille — sonst wuerde fast_mode-an silent das
    in YAML eingestellte Translate-Modell ueberschreiben."""
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    cfg.styler.fast_model = "gemma3:4b"
    cfg.styler.fast_mode = True
    cfg.styler.modes["translate_en"] = ModeConfig(model="qwen3:8b")
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "out"}})
    styler._client = fake_client

    await styler.polish("text", mode="translate_en")

    assert fake_client.chat.call_args.kwargs["model"] == "qwen3:8b"


@pytest.mark.asyncio
async def test_warmup_uses_fast_model_when_fast_mode_enabled():
    """Warmup beim Boot muss das tatsaechlich genutzte Modell laden, sonst
    zahlt der erste F8 trotzdem den Cold-Start."""
    cfg = Config()
    cfg.styler.fast_model = "gemma3:4b"
    cfg.styler.fast_mode = True
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "ok"}})
    styler._client = fake_client

    await styler.warmup()

    assert fake_client.chat.call_args.kwargs["model"] == "gemma3:4b"


@pytest.mark.asyncio
async def test_edit_command_uses_fast_model_when_fast_mode_enabled():
    """fast_mode wirkt einheitlich auf alle Pfade — auch F9-Editing.
    Wenn User explizit fast_mode toggelt, akzeptiert er den Trade-off."""
    cfg = Config()
    cfg.styler.fast_model = "gemma3:4b"
    cfg.styler.fast_mode = True
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "edited"}})
    styler._client = fake_client

    await styler.edit_command(selection="text", command="cmd")

    assert fake_client.chat.call_args.kwargs["model"] == "gemma3:4b"


# ---------------------------------------------------------------------------
# Polish-Latenz-Detection (v0.2.6): bei SLOW_POLISH_TRIGGER_COUNT langsamen
# Polishes in Folge wird ein Tray-Toast (Callback) gefeuert und temporaer
# auf fast_model umgeschaltet. Hintergrund: Ollama-on-Win11-Bug, bei dem das
# Polish-Modell auf CPU statt GPU geladen wird → Polish 10-15s statt <1s.
# Detection unterscheidet sich vom manuellen fast_mode-Toggle dadurch dass
# es automatisch greift und nach FORCE_FAST_DURATION_SEC wieder zurueck-
# faellt; der User-Toggle bleibt persistent.
# ---------------------------------------------------------------------------

def test_observe_fast_polish_does_not_increment_counter():
    cfg = Config()
    styler = Styler(cfg)
    styler._observe_polish_duration(0.5)
    assert styler._slow_polish_count == 0
    assert styler._force_fast_until is None


def test_observe_slow_polish_increments_counter_but_does_not_trigger():
    cfg = Config()
    styler = Styler(cfg)
    styler._observe_polish_duration(SLOW_POLISH_THRESHOLD_SEC + 1.0)
    assert styler._slow_polish_count == 1
    assert styler._force_fast_until is None


def test_observe_three_slow_polishes_in_a_row_triggers_force_fast():
    cfg = Config()
    callback = MagicMock()
    styler = Styler(cfg, on_slow_polish_detected=callback)
    for _ in range(SLOW_POLISH_TRIGGER_COUNT):
        styler._observe_polish_duration(SLOW_POLISH_THRESHOLD_SEC + 1.0)
    assert styler._force_fast_until is not None
    callback.assert_called_once()
    # Counter wird nach Trigger zurueckgesetzt, damit nicht jede weitere
    # Slow-Polish nochmal feuert.
    assert styler._slow_polish_count == 0


def test_observe_fast_polish_resets_counter():
    """Voruebergehender Spike (z.B. ein langer Input) darf nicht reichen —
    nur ein echter Strom an Slow-Polishes triggert. Reset bei jedem
    schnellen Polish dazwischen sorgt dafuer."""
    cfg = Config()
    callback = MagicMock()
    styler = Styler(cfg, on_slow_polish_detected=callback)
    styler._observe_polish_duration(SLOW_POLISH_THRESHOLD_SEC + 1.0)
    styler._observe_polish_duration(SLOW_POLISH_THRESHOLD_SEC + 1.0)
    styler._observe_polish_duration(0.5)  # reset
    styler._observe_polish_duration(SLOW_POLISH_THRESHOLD_SEC + 1.0)
    assert styler._slow_polish_count == 1
    assert styler._force_fast_until is None
    callback.assert_not_called()


def test_observe_force_fast_active_blocks_re_notification():
    """Wenn force_fast schon aktiv ist, Re-Trigger nicht erneut feuern
    — Spam vermeiden. User kann sehen ob es nach Ablauf wieder slow ist."""
    cfg = Config()
    callback = MagicMock()
    styler = Styler(cfg, on_slow_polish_detected=callback)
    # Initial triggern
    for _ in range(SLOW_POLISH_TRIGGER_COUNT):
        styler._observe_polish_duration(SLOW_POLISH_THRESHOLD_SEC + 1.0)
    assert callback.call_count == 1
    # Weitere Slow-Polishes waehrend force_fast aktiv: kein Re-Trigger
    for _ in range(SLOW_POLISH_TRIGGER_COUNT * 2):
        styler._observe_polish_duration(SLOW_POLISH_THRESHOLD_SEC + 1.0)
    assert callback.call_count == 1


def test_observe_does_not_switch_when_fast_mode_already_user_enabled():
    """User hat fast_mode bereits manuell an — Auto-Switch waere no-op,
    aber Toast trotzdem fuer den Fall dass auch fast_model langsam ist
    (Ollama komplett am Boden, GPU tot)."""
    cfg = Config()
    cfg.styler.fast_mode = True
    callback = MagicMock()
    styler = Styler(cfg, on_slow_polish_detected=callback)
    for _ in range(SLOW_POLISH_TRIGGER_COUNT):
        styler._observe_polish_duration(SLOW_POLISH_THRESHOLD_SEC + 1.0)
    callback.assert_called_once()
    # Kein force_fast-Switch gesetzt, weil fast_mode eh schon True
    assert styler._force_fast_until is None


def test_resolve_model_uses_fast_model_when_force_fast_active():
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    cfg.styler.fast_model = "gemma3:4b"
    styler = Styler(cfg)
    styler._activate_force_fast()
    assert styler._resolve_model("plain") == "gemma3:4b"


def test_resolve_model_falls_back_to_default_after_force_fast_expires(monkeypatch):
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    cfg.styler.fast_model = "gemma3:4b"
    styler = Styler(cfg)
    styler._activate_force_fast()
    # Zeit nach Ablauf vorspulen via monkeypatch auf time.monotonic im
    # styler-Modul. wait_for/asyncio.run nutzen ihr eigenes time, also
    # sicher fuer diesen Sync-Test.
    import kira.styler as styler_mod
    until = styler._force_fast_until
    assert until is not None  # _activate_force_fast() hat es eben gesetzt
    fake_now = until + 1.0
    monkeypatch.setattr(styler_mod.time, "monotonic", lambda: fake_now)
    assert styler._resolve_model("plain") == "gemma3:12b"
    # Nach Ablauf wird _force_fast_until auf None gesetzt (lazy cleanup).
    assert styler._force_fast_until is None


def test_resolve_model_per_mode_override_beats_force_fast():
    """Hierarchie: Per-Mode-Override > fast_mode/force_fast > Default.
    Wer translate_en explizit auf qwen3:8b gepinnt hat, behaelt es auch
    waehrend des Auto-Switches."""
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    cfg.styler.fast_model = "gemma3:4b"
    cfg.styler.modes["translate_en"] = ModeConfig(model="qwen3:8b")
    styler = Styler(cfg)
    styler._activate_force_fast()
    assert styler._resolve_model("translate_en") == "qwen3:8b"


def test_callback_exception_does_not_break_observe():
    """Wenn der Callback wirft (kaputtes Tray, kein notify-Support),
    darf das den Polish-Flow nicht aufhalten."""
    cfg = Config()
    callback = MagicMock(side_effect=RuntimeError("tray dead"))
    styler = Styler(cfg, on_slow_polish_detected=callback)
    for _ in range(SLOW_POLISH_TRIGGER_COUNT):
        # Darf NICHT raisen
        styler._observe_polish_duration(SLOW_POLISH_THRESHOLD_SEC + 1.0)
    # Counter wurde trotzdem zurueckgesetzt und force_fast aktiviert
    assert styler._slow_polish_count == 0
    assert styler._force_fast_until is not None


@pytest.mark.asyncio
async def test_polish_observes_duration_via_finally(monkeypatch):
    """End-to-End: polish() muss _observe_polish_duration ueber den
    finally-Pfad triggern, sowohl im Erfolgs- als auch im Fallback-Pfad."""
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "ok"}})
    styler._client = fake_client
    observed = []
    monkeypatch.setattr(
        styler, "_observe_polish_duration",
        lambda d: observed.append(d),
    )
    await styler.polish("hi", mode="plain")
    assert len(observed) == 1
    assert observed[0] >= 0.0


# ---------------------------------------------------------------------------
# num_gpu=999 forciert alle Modell-Layer auf GPU (Fix fuer Polish-Latenz
# 2026-05-23): Ollama 0.23.x entscheidet bei gemma3:12b auf einer 32GB-GPU
# manchmal fehlerhaft, einen ~787 MiB Embedding-Tensor (Q4_K_M) auf CPU
# zu lassen trotz reichlich freiem VRAM — Resultat: 14 tok/s statt 114
# tok/s, Polish 5-15s statt <1s. Mit explizitem num_gpu=999 ("alle
# Layer auf GPU") laedt Ollama 100% in VRAM. Hardcoded an allen 3 chat-
# Sites, damit Ollama nicht zwischen Calls das Modell mit anderen Options
# reloadet (ein Mix aus mit/ohne num_gpu wuerde bei jedem Wechsel einen
# Model-Reload kosten ~7s).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_polish_forces_num_gpu_999():
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "ok"}})
    styler._client = fake_client

    await styler.polish("text", mode="plain")

    assert fake_client.chat.call_args.kwargs["options"]["num_gpu"] == 999


@pytest.mark.asyncio
async def test_warmup_forces_num_gpu_999():
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "ok"}})
    styler._client = fake_client

    await styler.warmup()

    assert fake_client.chat.call_args.kwargs["options"]["num_gpu"] == 999


@pytest.mark.asyncio
async def test_edit_command_forces_num_gpu_999():
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "edited"}})
    styler._client = fake_client

    await styler.edit_command(selection="text", command="cmd")

    assert fake_client.chat.call_args.kwargs["options"]["num_gpu"] == 999
