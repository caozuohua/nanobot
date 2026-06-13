from nanobot.command.builtin import build_help_text


def test_vps_lite_help_is_grouped_and_hides_unavailable_commands() -> None:
    text = build_help_text("vps-lite")

    assert "会话" in text
    assert "模型" in text
    assert "维护" in text
    assert "/model [序号|preset]" in text
    assert "/goal" not in text
    assert "/dream" not in text
    assert max(map(len, text.splitlines())) <= 42
