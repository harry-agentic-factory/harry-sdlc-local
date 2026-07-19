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
