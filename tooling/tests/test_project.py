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


# --- provenance : « une story existe-t-elle déjà pour ce signalement ? » ---

def test_source_survives_a_status_change(tmp_path):
    """Le piège : `load` filtre sur les champs du dataclass. Un champ écrit à la main dans
    status.json disparaissait au premier set-status."""
    from sdlc.workspace import Workspace
    from sdlc.service import Sdlc
    s = Sdlc(Workspace(tmp_path))
    s.create_epic("E", "epic")
    s.create_ticket("E", "E-1", "story")

    s.set_source("E-1", "tracker", "aB3dEf", "https://tracker.example/c/aB3dEf")
    s.set_status("E-1", "spec_tech")
    s.set_status("E-1", "implemented")

    assert s.get_ticket("E-1")["source"]["id"] == "aB3dEf"


def test_find_by_source_answers_the_duplicate_question(tmp_path):
    from sdlc.workspace import Workspace
    from sdlc.service import Sdlc
    s = Sdlc(Workspace(tmp_path))
    s.create_epic("E", "epic")
    s.create_ticket("E", "E-1", "deja instruite")
    s.create_ticket("E", "E-2", "autre sujet")
    s.set_source("E-1", "tracker", "aB3dEf", "https://tracker.example/c/aB3dEf")

    assert [t.id for t in s.find_by_source("aB3dEf")] == ["E-1"]
    assert s.find_by_source("zZ9yYy") == []          # signalement jamais ingéré
    # retrouvable aussi par l'URL complète, c'est ce que colle un humain
    assert [t.id for t in s.find_by_source("https://tracker.example/c/aB3dEf".split("/c/")[1])] == ["E-1"]
