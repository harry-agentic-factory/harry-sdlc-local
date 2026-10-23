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


# --- rattrapage d'un fait deja survenu (`force_reason`) ---------------------------------------
#
# Ne s'est pas invente : le 2026-10-24, deux stories HIA-STATPERF tournaient EN PRODUCTION en
# affichant encore `implemented`, parce que leur deploiement avait eu lieu pour une raison
# d'infra et que rien n'avait notifie la state-machine. Le board inventait du retard inexistant,
# et ce retard a ete rapporte a l'humain comme un fait. Ces tests figent le compromis retenu :
# un FAIT se rattrape (avec motif, et journalise), une SIGNATURE jamais.


def test_a_fact_can_be_caught_up_with_a_reason():
    assert validate_transition(Status.IMPLEMENTED, Status.DEPLOYED,
                               "already in prod, CI #237") == Status.DEPLOYED


def test_without_a_reason_the_guard_holds_and_names_the_hatch():
    with pytest.raises(InvalidTransition) as e:
        validate_transition(Status.IMPLEMENTED, Status.DEPLOYED)
    # l'erreur doit ENSEIGNER l'echappatoire, sinon l'appelant la contourne autrement
    assert "force-reason" in str(e.value)


@pytest.mark.parametrize("signed", [
    Status.ACCEPTED, Status.DONE, Status.SPEC_VALIDATED,
    Status.FEATURE_VALIDATED, Status.SPEC_FUNC_VALIDATED,
])
def test_a_human_signature_is_never_forcible(signed):
    """Le seul refus absolu : un agent ne doit pas pouvoir s'auto-accorder une gate humaine."""
    from sdlc import ForcedTransitionRefused
    with pytest.raises(ForcedTransitionRefused) as e:
        validate_transition(Status.IMPLEMENTED, signed, "je voudrais bien")
    assert "signature" in str(e.value)


def test_an_empty_reason_is_refused():
    from sdlc import ForcedTransitionRefused
    for blank in ("", "   ", "\n\t "):
        with pytest.raises(ForcedTransitionRefused):
            validate_transition(Status.IMPLEMENTED, Status.DEPLOYED, blank)


def test_going_backwards_is_a_rejection_not_a_catch_up():
    from sdlc import ForcedTransitionRefused
    # recette_ok -> reviewed : en arriere, factuel, et PAS deja autorise
    with pytest.raises(ForcedTransitionRefused) as e:
        validate_transition(Status.RECETTE_OK, Status.REVIEWED, "oops")
    assert "rejet" in str(e.value)


def test_the_fix_loop_edge_still_works_with_or_without_a_reason():
    # deployed -> implemented est DEJA legal (retour au dev) : le rattrapage ne doit pas le casser
    for reason in (None, "with a reason"):
        assert validate_transition(Status.DEPLOYED, Status.IMPLEMENTED, reason) == Status.IMPLEMENTED


def test_fact_and_signature_sets_are_disjoint():
    from sdlc import FACTUAL, SIGNED
    assert not (FACTUAL & SIGNED), "un statut ne peut pas etre a la fois un fait et une signature"
