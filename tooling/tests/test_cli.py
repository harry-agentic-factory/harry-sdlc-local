import json

from sdlc import cli


def _run(capsys, argv, workspace, monkeypatch):
    monkeypatch.setenv("SDLC_WORKSPACE", str(workspace))
    rc = cli.main(argv)
    out = capsys.readouterr().out
    return rc, json.loads(out) if out.strip() else {}


def test_cli_end_to_end(tmp_path, capsys, monkeypatch):
    rc, _ = _run(capsys, ["create-epic", "SAMPLE-T", "Demo"], tmp_path, monkeypatch)
    assert rc == 0

    rc, t = _run(capsys, ["create-ticket", "SAMPLE-T", "SAMPLE-T-2", "socle"], tmp_path, monkeypatch)
    assert rc == 0 and t["status"] == "draft"
    _run(capsys, ["create-ticket", "SAMPLE-T", "SAMPLE-T-1", "api", "--deps", "SAMPLE-T-2", "--repos", "app-repo"], tmp_path, monkeypatch)

    rc, g = _run(capsys, ["get", "SAMPLE-T-1"], tmp_path, monkeypatch)
    assert g["repos"] == ["app-repo"] and g["deps"] == ["SAMPLE-T-2"]

    rc, n = _run(capsys, ["next", "SAMPLE-T"], tmp_path, monkeypatch)
    assert n["next"] == ["SAMPLE-T-2"]  # SAMPLE-T-1 dépend de SAMPLE-T-2

    rc, s = _run(capsys, ["set-status", "SAMPLE-T-2", "spec_func"], tmp_path, monkeypatch)
    assert rc == 0 and s["status"] == "spec_func"


def test_cli_invalid_transition_errors(tmp_path, capsys, monkeypatch):
    _run(capsys, ["create-epic", "SAMPLE-T", "Demo"], tmp_path, monkeypatch)
    _run(capsys, ["create-ticket", "SAMPLE-T", "SAMPLE-T-1", "api"], tmp_path, monkeypatch)
    monkeypatch.setenv("SDLC_WORKSPACE", str(tmp_path))
    rc = cli.main(["set-status", "SAMPLE-T-1", "done"])  # saut interdit
    assert rc == 1
