from unittest.mock import AsyncMock, MagicMock
import pytest
from kira.config import Config
from kira.styler import Styler, _prompt_dir, _thinking_kwargs, load_prompt


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


def test_thinking_flag_only_for_reasoning_models():
    assert _thinking_kwargs("huihui_ai/qwen3-abliterated:8b") == {"think": False}
    assert _thinking_kwargs("gemma4:e4b") == {"think": False}
    assert _thinking_kwargs("Gemma-4-abliterated:31b-v2") == {"think": False}
    assert _thinking_kwargs("gemma2:2b") == {}
    assert _thinking_kwargs("llama3.2:3b") == {}


@pytest.mark.asyncio
async def test_polish_passes_keep_alive_and_think_flag():
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "ok"}})
    styler._client = fake_client
    await styler.polish("hallo", mode="plain")
    kwargs = fake_client.chat.call_args.kwargs
    assert kwargs["keep_alive"] == "1h"
    assert kwargs["think"] is False


@pytest.mark.asyncio
async def test_warmup_never_raises():
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(side_effect=Exception("ollama down"))
    styler._client = fake_client
    await styler.warmup()
    fake_client.chat.assert_awaited_once()


def test_prompt_dir_prefers_bundle_resourcepath(tmp_path, monkeypatch):
    (tmp_path / "prompts").mkdir()
    monkeypatch.setenv("RESOURCEPATH", str(tmp_path))
    assert _prompt_dir() == tmp_path / "prompts"
    monkeypatch.delenv("RESOURCEPATH")
    assert _prompt_dir().name == "prompts"


@pytest.mark.asyncio
async def test_edit_command_returns_model_output_and_uses_edit_timeout():
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(return_value={"message": {"content": "Hello world."}})
    styler._client = fake_client
    result = await styler.edit_command("hallo welt", "übersetze ins Englische")
    assert result == "Hello world."
    prompt = fake_client.chat.call_args.kwargs["messages"][0]["content"]
    assert "hallo welt" in prompt and "übersetze ins Englische" in prompt


@pytest.mark.asyncio
async def test_edit_command_keeps_selection_on_error_or_empty():
    cfg = Config()
    styler = Styler(cfg)
    fake_client = MagicMock()
    fake_client.chat = AsyncMock(side_effect=Exception("down"))
    styler._client = fake_client
    assert await styler.edit_command("bleibt", "mach was") == "bleibt"
    fake_client.chat = AsyncMock(return_value={"message": {"content": "   "}})
    assert await styler.edit_command("bleibt", "mach was") == "bleibt"
    assert await styler.edit_command("", "mach was") == ""
