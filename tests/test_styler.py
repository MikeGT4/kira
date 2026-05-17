from unittest.mock import AsyncMock, MagicMock
import pytest
from kira.config import Config, ModeConfig
from kira.styler import Styler, load_prompt


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
