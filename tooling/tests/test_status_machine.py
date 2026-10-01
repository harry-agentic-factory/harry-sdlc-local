import pytest

from sdlc import Status, validate_transition, InvalidTransition


def test_forward_step_ok():
    assert validate_transition(Status.DRAFT, Status.SPEC_FUNC) == Status.SPEC_FUNC
    assert validate_transition("reviewed", "deployed") == Status.DEPLOYED


def test_spec_func_skippable():
    # feature triviale : DRAFT -> SPEC_TECH direct
    assert validate_transition(Status.DRAFT, Status.SPEC_TECH) == Status.SPEC_TECH


def test_fix_loop_back_to_implemented():
    for s in ("reviewed", "deployed", "recette_ok"):
        assert validate_transition(s, "implemented") == Status.IMPLEMENTED


def test_backward_is_rejected():
    with pytest.raises(InvalidTransition):
        validate_transition(Status.DEPLOYED, Status.DRAFT)


def test_skip_more_than_one_rejected():
    with pytest.raises(InvalidTransition):
        validate_transition(Status.DRAFT, Status.IMPLEMENTED)


def test_done_is_terminal():
    with pytest.raises(InvalidTransition):
        validate_transition(Status.DONE, Status.ACCEPTED)


def test_spec_validated_gate():
    # gate: spec_tech -> spec_validated -> implemented
    assert validate_transition(Status.SPEC_TECH, Status.SPEC_VALIDATED) == Status.SPEC_VALIDATED
    assert validate_transition(Status.SPEC_VALIDATED, Status.IMPLEMENTED) == Status.IMPLEMENTED


def test_spec_validated_gate_is_skippable():
    # backward-compat : spec_tech -> implemented direct reste toléré (gate portée par l'orchestration)
    assert validate_transition(Status.SPEC_TECH, Status.IMPLEMENTED) == Status.IMPLEMENTED


def test_spec_validated_cannot_skip_from_spec_func():
    with pytest.raises(InvalidTransition):
        validate_transition(Status.SPEC_FUNC, Status.SPEC_VALIDATED)


def test_functional_gate():
    # gate fonctionnelle : spec_func -> spec_func_validated -> spec_tech
    assert validate_transition(Status.SPEC_FUNC, Status.SPEC_FUNC_VALIDATED) == Status.SPEC_FUNC_VALIDATED
    assert validate_transition(Status.SPEC_FUNC_VALIDATED, Status.SPEC_TECH) == Status.SPEC_TECH


def test_functional_gate_is_skippable():
    # elle vaut surtout au niveau épic ; sur une story isolée le saut reste toléré
    assert validate_transition(Status.SPEC_FUNC, Status.SPEC_TECH) == Status.SPEC_TECH


def test_functional_gate_does_not_reach_the_technical_one():
    # les deux gates restent distinctes : on ne saute pas de l'une à l'autre
    with pytest.raises(InvalidTransition):
        validate_transition(Status.SPEC_FUNC_VALIDATED, Status.SPEC_VALIDATED)
    with pytest.raises(InvalidTransition):
        validate_transition(Status.SPEC_FUNC_VALIDATED, Status.IMPLEMENTED)


def test_feature_gate_sits_between_spec_validated_and_implemented():
    from sdlc import PIPELINE
    i = PIPELINE.index(Status.FEATURE_VALIDATED)
    assert PIPELINE[i - 1] == Status.SPEC_VALIDATED and PIPELINE[i + 1] == Status.IMPLEMENTED
    assert validate_transition(Status.SPEC_VALIDATED, Status.FEATURE_VALIDATED) == Status.FEATURE_VALIDATED
    assert validate_transition(Status.FEATURE_VALIDATED, Status.IMPLEMENTED) == Status.IMPLEMENTED


def test_feature_gate_is_skippable_but_not_reachable_from_spec_tech():
    assert validate_transition(Status.SPEC_VALIDATED, Status.IMPLEMENTED) == Status.IMPLEMENTED
    with pytest.raises(InvalidTransition):
        validate_transition(Status.SPEC_TECH, Status.FEATURE_VALIDATED)
    with pytest.raises(InvalidTransition):
        validate_transition(Status.FEATURE_VALIDATED, Status.SPEC_VALIDATED)


def test_routed_return_after_a_spec_or_feature_gate():
    for src in (Status.SPEC_VALIDATED, Status.FEATURE_VALIDATED):
        assert validate_transition(src, Status.SPEC_TECH) == Status.SPEC_TECH
        assert validate_transition(src, Status.SPEC_FUNC) == Status.SPEC_FUNC
