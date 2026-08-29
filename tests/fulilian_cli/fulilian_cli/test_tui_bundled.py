

def test_tui_finds_bundled_entry_js(tmp_path):
    """_find_bundled_tui finds entry.js bundled in the package."""
    tui_dist = tmp_path / "fulilian_cli" / "tui_dist"
    tui_dist.mkdir(parents=True)
    entry = tui_dist / "entry.js"
    entry.write_text("// bundled TUI", encoding="utf-8")

    from fulilian_cli.main import _find_bundled_tui
    result = _find_bundled_tui(fulilian_cli_dir=tmp_path / "fulilian_cli")
    assert result is not None
    assert result.name == "entry.js"


