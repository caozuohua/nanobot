from nanobot.agent.model_selection import load_model_selection, save_model_selection


def test_model_selection_round_trip_is_atomic(tmp_path) -> None:
    path = tmp_path / "runtime" / "model.json"

    save_model_selection(path, "vertex-flash")

    assert load_model_selection(path) == "vertex-flash"
    assert not path.with_suffix(".tmp").exists()


def test_invalid_model_selection_is_ignored(tmp_path) -> None:
    path = tmp_path / "model.json"
    path.write_text('{"preset": 42}', encoding="utf-8")

    assert load_model_selection(path) is None
