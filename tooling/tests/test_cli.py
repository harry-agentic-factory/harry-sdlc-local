import json

from sdlc import cli


def _run(capsys, argv, workspace, monkeypatch):
    monkeypatch.setenv("HIA_SDLC_WORKSPACE", str(workspace))
    rc = cli.main(argv)
    out = capsys.readouterr().out
    return rc, json.loads(out) if out.strip() else {}


def test_cli_end_to_end(tmp_path, capsys, monkeypatch):
    rc, _ = _run(capsys, ["create-epic", "HIA-T", "Demo"], tmp_path, monkeypatch)
    assert rc == 0

    rc, t = _run(capsys, ["create-ticket", "HIA-T", "HIA-T-2", "socle"], tmp_path, monkeypatch)
    assert rc == 0 and t["status"] == "draft"
    _run(capsys, ["create-ticket", "HIA-T", "HIA-T-1", "api", "--deps", "HIA-T-2", "--repos", "back-tenant"], tmp_path, monkeypatch)

    rc, g = _run(capsys, ["get", "HIA-T-1"], tmp_path, monkeypatch)
    assert g["repos"] == ["back-tenant"] and g["deps"] == ["HIA-T-2"]

    rc, n = _run(capsys, ["next", "HIA-T"], tmp_path, monkeypatch)
    assert n["next"] == ["HIA-T-2"]  # HIA-T-1 dépend de HIA-T-2

    rc, s = _run(capsys, ["set-status", "HIA-T-2", "spec_func"], tmp_path, monkeypatch)
    assert rc == 0 and s["status"] == "spec_func"


def test_cli_invalid_transition_errors(tmp_path, capsys, monkeypatch):
    _run(capsys, ["create-epic", "HIA-T", "Demo"], tmp_path, monkeypatch)
    _run(capsys, ["create-ticket", "HIA-T", "HIA-T-1", "api"], tmp_path, monkeypatch)
    monkeypatch.setenv("HIA_SDLC_WORKSPACE", str(tmp_path))
    rc = cli.main(["set-status", "HIA-T-1", "done"])  # saut interdit
    assert rc == 1
