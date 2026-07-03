from unittest.mock import AsyncMock, MagicMock
import pytest
from ollama import ProcessResponse
from kira.config import Config, ModeConfig
from kira.styler import (
    Styler,
    load_prompt,
    SLOW_POLISH_THRESHOLD_SEC,
    SLOW_POLISH_TRIGGER_COUNT,
)


def _ps(model_name, size, size_vram, *, name=None):
    """Baue eine ollama-ps()-Response mit einem laufenden Modell."""
    return ProcessResponse(models=[ProcessResponse.Model(
        model=model_name, name=name if name is not None else model_name,
        size=size, size_vram=size_vram,
    )])


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


# ---------------------------------------------------------------------------
# CPU-Fallback-Detection (v0.3.0): num_gpu=999 ist ab Ollama 0.30.x wirkungslos
# (Server-seitige Regression, GitHub #16610) — das Polish-Modell landet trotz
# freiem VRAM komplett auf CPU (size_vram=0). Die alte Latenz-Heuristik
# (_observe_polish_duration) ist unzuverlaessig: kurze Inputs polishen auch
# auf CPU unter 3 s. verify_gpu_placement() fragt nach dem Warmup ollama.ps()
# ab und liest size_vram direkt — deterministisch. Bei CPU-Load feuert ein
# actionabler Tray-Toast (Downgrade-Hinweis). Da Whisper hardcoded auf
# device="cuda" laeuft, HAT ein Kira-User immer eine CUDA-GPU — size_vram=0
# ist deshalb immer ein Fehler, kein "kein-GPU"-False-Positive.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_verify_gpu_placement_detects_cpu_fallback():
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    callback = MagicMock()
    styler = Styler(cfg, on_cpu_fallback_detected=callback)
    styler._client = MagicMock()
    styler._client.ps = AsyncMock(
        return_value=_ps("gemma3:12b", size=11_779_775_936, size_vram=0)
    )

    result = await styler.verify_gpu_placement()

    assert result == "cpu"
    callback.assert_called_once()
    # Die Toast-Meldung muss den User handlungsfaehig machen: Modellname +
    # primaerer Hinweis (Ollama neu starten, VRAM-Tuning greift) + Downgrade
    # als Fallback.
    msg = callback.call_args.args[0]
    assert "gemma3:12b" in msg
    assert "neu starten" in msg.lower()
    assert "0.24" in msg


@pytest.mark.asyncio
async def test_verify_gpu_placement_returns_gpu_when_resident_in_vram():
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    callback = MagicMock()
    styler = Styler(cfg, on_cpu_fallback_detected=callback)
    styler._client = MagicMock()
    styler._client.ps = AsyncMock(
        return_value=_ps("gemma3:12b", size=11_779_775_936, size_vram=11_779_775_936)
    )

    result = await styler.verify_gpu_placement()

    assert result == "gpu"
    callback.assert_not_called()


@pytest.mark.asyncio
async def test_verify_gpu_placement_model_not_running_returns_none():
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    callback = MagicMock()
    styler = Styler(cfg, on_cpu_fallback_detected=callback)
    styler._client = MagicMock()
    # Ein anderes Modell laeuft — unser Polish-Modell ist nicht in ps.
    styler._client.ps = AsyncMock(
        return_value=_ps("llama3:8b", size=4_000_000_000, size_vram=0)
    )

    result = await styler.verify_gpu_placement()

    assert result is None
    callback.assert_not_called()


@pytest.mark.asyncio
async def test_verify_gpu_placement_handles_ps_exception():
    """ps() darf nie den Boot/Polish-Pfad umhauen — Fehler -> None, kein Toast."""
    cfg = Config()
    callback = MagicMock()
    styler = Styler(cfg, on_cpu_fallback_detected=callback)
    styler._client = MagicMock()
    styler._client.ps = AsyncMock(side_effect=Exception("ollama unreachable"))

    result = await styler.verify_gpu_placement()

    assert result is None
    callback.assert_not_called()


@pytest.mark.asyncio
async def test_verify_gpu_placement_none_size_vram_is_unknown():
    """size_vram=None (alte Server / unklare Antwort) -> kein False-Positive."""
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    callback = MagicMock()
    styler = Styler(cfg, on_cpu_fallback_detected=callback)
    styler._client = MagicMock()
    styler._client.ps = AsyncMock(
        return_value=_ps("gemma3:12b", size=11_779_775_936, size_vram=None)
    )

    result = await styler.verify_gpu_placement()

    assert result is None
    callback.assert_not_called()


@pytest.mark.asyncio
async def test_verify_gpu_placement_matches_by_name_field():
    """Manche ps-Antworten fuellen nur 'name', nicht 'model'."""
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    callback = MagicMock()
    styler = Styler(cfg, on_cpu_fallback_detected=callback)
    styler._client = MagicMock()
    resp = ProcessResponse(models=[ProcessResponse.Model(
        model=None, name="gemma3:12b", size=11_779_775_936, size_vram=0,
    )])
    styler._client.ps = AsyncMock(return_value=resp)

    result = await styler.verify_gpu_placement()

    assert result == "cpu"
    callback.assert_called_once()


@pytest.mark.asyncio
async def test_verify_gpu_placement_checks_active_model_under_fast_mode():
    """Bei fast_mode muss das tatsaechlich gewarmte fast_model geprueft werden,
    nicht das Default-Modell."""
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    cfg.styler.fast_model = "gemma3:4b"
    cfg.styler.fast_mode = True
    callback = MagicMock()
    styler = Styler(cfg, on_cpu_fallback_detected=callback)
    styler._client = MagicMock()
    styler._client.ps = AsyncMock(
        return_value=_ps("gemma3:4b", size=3_300_000_000, size_vram=0)
    )

    result = await styler.verify_gpu_placement()

    assert result == "cpu"
    callback.assert_called_once()


@pytest.mark.asyncio
async def test_verify_gpu_placement_callback_exception_swallowed():
    """Kaputtes Tray/notify darf die Detection nicht crashen."""
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    callback = MagicMock(side_effect=RuntimeError("tray dead"))
    styler = Styler(cfg, on_cpu_fallback_detected=callback)
    styler._client = MagicMock()
    styler._client.ps = AsyncMock(
        return_value=_ps("gemma3:12b", size=11_779_775_936, size_vram=0)
    )

    # Darf NICHT raisen
    result = await styler.verify_gpu_placement()
    assert result == "cpu"


@pytest.mark.asyncio
async def test_verify_gpu_placement_no_callback_configured():
    """Ohne gesetzten Callback (z.B. vor Late-Binding) trotzdem kein Crash."""
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    styler = Styler(cfg)  # kein Callback
    styler._client = MagicMock()
    styler._client.ps = AsyncMock(
        return_value=_ps("gemma3:12b", size=11_779_775_936, size_vram=0)
    )

    result = await styler.verify_gpu_placement()
    assert result == "cpu"


def test_set_on_cpu_fallback_detected_late_binding():
    """Setter analog zu set_on_slow_polish_detected — Tray entsteht nach Styler."""
    cfg = Config()
    styler = Styler(cfg)
    callback = MagicMock()
    styler.set_on_cpu_fallback_detected(callback)
    assert styler._on_cpu_fallback_detected is callback


@pytest.mark.asyncio
async def test_warmup_triggers_gpu_placement_check(monkeypatch):
    """warmup() loest die Placement-Pruefung aus, nachdem das Modell geladen ist."""
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "ok"}})
    styler._client = fake_client
    calls = []

    async def fake_verify():
        calls.append(True)
        return "gpu"

    monkeypatch.setattr(styler, "verify_gpu_placement", fake_verify)

    await styler.warmup()

    assert calls == [True]


@pytest.mark.asyncio
async def test_warmup_gpu_check_failure_does_not_break_warmup(monkeypatch):
    """Wenn die Placement-Pruefung wirft, darf warmup() trotzdem sauber durchlaufen."""
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "ok"}})
    styler._client = fake_client

    async def boom():
        raise RuntimeError("ps blew up")

    monkeypatch.setattr(styler, "verify_gpu_placement", boom)

    # Darf NICHT raisen
    await styler.warmup()


@pytest.mark.asyncio
async def test_warmup_success_sets_warmup_succeeded():
    """Der Setup-Re-Probe in main.py holt den Warmup nur nach, wenn der
    Boot-Warmup NICHT durchkam — dafuer braucht er ein lesbares Flag."""
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "ok"}})
    fake_client.ps = AsyncMock(side_effect=Exception("ps egal"))
    styler._client = fake_client

    assert styler.warmup_succeeded is False
    await styler.warmup()
    assert styler.warmup_succeeded is True


@pytest.mark.asyncio
async def test_warmup_failure_leaves_warmup_succeeded_false():
    """Chat-Fehler (Ollama down beim Boot, 30.06.-Muster "Server
    disconnected") -> Flag bleibt False, Re-Probe darf nachholen."""
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(side_effect=Exception("Server disconnected"))
    styler._client = fake_client

    await styler.warmup()
    assert styler.warmup_succeeded is False


@pytest.mark.asyncio
async def test_verify_gpu_placement_detects_partial_offload():
    """49/51-CPU/GPU-Split (das v0.2.7-Muster): size_vram > 0, aber deutlich
    unter size — der CPU-Anteil zwingt jede Token-Generation ueber PCIe,
    ~8x Slowdown. Muss als "partial" gemeldet werden, nicht als "gpu"."""
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    callback = MagicMock()
    styler = Styler(cfg, on_cpu_fallback_detected=callback)
    styler._client = MagicMock()
    styler._client.ps = AsyncMock(
        return_value=_ps("gemma3:12b", size=12_000_000_000, size_vram=6_000_000_000)
    )

    result = await styler.verify_gpu_placement()

    assert result == "partial"
    callback.assert_called_once()
    msg = callback.call_args.args[0]
    assert "gemma3:12b" in msg
    assert "teilweise" in msg.lower()


@pytest.mark.asyncio
async def test_verify_gpu_placement_tolerates_small_nonvram_share():
    """Knapp unter 100 % VRAM (Graph-/Rundungsanteile) ist KEIN Partial-
    Offload — sonst wuerde jeder gesunde Load einen falschen Toast feuern."""
    cfg = Config()
    cfg.styler.model = "gemma3:12b"
    callback = MagicMock()
    styler = Styler(cfg, on_cpu_fallback_detected=callback)
    styler._client = MagicMock()
    styler._client.ps = AsyncMock(
        return_value=_ps("gemma3:12b", size=12_000_000_000, size_vram=11_700_000_000)
    )

    result = await styler.verify_gpu_placement()

    assert result == "gpu"
    callback.assert_not_called()


@pytest.mark.asyncio
async def test_verify_gpu_placement_matches_untagged_model_as_latest():
    """Config `model: gemma3` (ohne Tag) muss den ps()-Eintrag `gemma3:latest`
    matchen — Ollama normalisiert untagged Modellnamen serverseitig auf
    :latest, sonst laeuft die CPU-Detection fuer solche Configs ins Leere."""
    cfg = Config()
    cfg.styler.model = "gemma3"
    callback = MagicMock()
    styler = Styler(cfg, on_cpu_fallback_detected=callback)
    styler._client = MagicMock()
    styler._client.ps = AsyncMock(
        return_value=_ps("gemma3:latest", size=3_300_000_000, size_vram=0)
    )

    result = await styler.verify_gpu_placement()

    assert result == "cpu"
    callback.assert_called_once()
