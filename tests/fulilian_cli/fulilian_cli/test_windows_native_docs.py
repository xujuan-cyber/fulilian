from pathlib import Path


def test_windows_native_install_path_docs_match_installer() -> None:
    doc = Path("website/docs/user-guide/windows-native.md").read_text()
    install = Path("scripts/install.ps1").read_text()

    # The launchers live in the managed binary dir OUTSIDE the git checkout
    # (FULILIAN_HOME\bin, next to the managed uv) — NOT the whole venv\Scripts
    # (which would shadow the user's python, #83797) and NOT a dir inside
    # the checkout (which `fulilian update`'s autostash swept off disk).
    assert "%LOCALAPPDATA%\\fulilian\\bin" in doc
    assert (
        "Get-Command fulilian        # should print "
        "C:\\Users\\<you>\\AppData\\Local\\fulilian\\bin\\fulilian.exe"
    ) in doc
    # Installer exposes $FulilianHome\bin, and must copy the launchers into it.
    assert '$fulilianBin = "$FulilianHome\\bin"' in install
    assert "fulilian.exe" in install and "fulilian-acp.exe" in install
    # Guard against regressions to either legacy layout.
    assert '$fulilianBin = "$InstallDir\\venv\\Scripts"' not in install
    assert '$fulilianBin = "$InstallDir\\bin"' not in install
