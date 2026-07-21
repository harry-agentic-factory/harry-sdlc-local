"""init_project : scaffold complet + enregistrement (registre isolé via HOME)."""
from sdlc.project import init_project, list_projects


def test_init_project_scaffolds_and_registers(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))   # isole ~/.claude/sdlc/projects.json
    res = init_project("DEMO", tmp_path / "demo-data", ["app", "web"], git=False)

    assert res["registered"] and res["prefix"] == "DEMO"
    d = tmp_path / "demo-data"
    assert (d / "sdlc.config.json").exists()
    assert (d / "README.md").exists()
    assert (d / "skills" / "README.md").exists()          # régression : skills/ doit être créé
    assert "DEMO" in list_projects()


def test_init_project_refuses_existing(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    init_project("DEMO", tmp_path / "d", ["a"], git=False)
    try:
        init_project("DEMO", tmp_path / "d", ["a"], git=False)
        assert False, "aurait dû refuser une data déjà initialisée"
    except FileExistsError:
        pass
