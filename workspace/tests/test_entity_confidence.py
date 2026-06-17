"""Beta-confidence math for entity facts (Phase 1). Pure, no app deps."""

import src.entity_confidence as conf


def test_prior_is_one_half():
    assert conf.confidence(conf.PRIOR_ALPHA, conf.PRIOR_BETA) == 0.5


def test_corroboration_raises_confidence():
    a, b = conf.PRIOR_ALPHA, conf.PRIOR_BETA
    for _ in range(5):
        a, b = conf.observe(a, b, positive=True)
    assert conf.confidence(a, b) > 0.8


def test_contradiction_lowers_confidence():
    a, b = conf.PRIOR_ALPHA, conf.PRIOR_BETA
    for _ in range(5):
        a, b = conf.observe(a, b, positive=False)
    assert conf.confidence(a, b) < 0.2


def test_weight_scales_evidence():
    a1, b1 = conf.observe(conf.PRIOR_ALPHA, conf.PRIOR_BETA, True, weight=1.0)
    a3, b3 = conf.observe(conf.PRIOR_ALPHA, conf.PRIOR_BETA, True, weight=3.0)
    assert conf.confidence(a3, b3) > conf.confidence(a1, b1)


def test_fold_matches_sequential_observe():
    seq = [True, True, False, True]
    a, b = conf.fold(seq)
    a2, b2 = conf.PRIOR_ALPHA, conf.PRIOR_BETA
    for p in seq:
        a2, b2 = conf.observe(a2, b2, p)
    assert (a, b) == (a2, b2)


def test_confidence_clamped_and_safe():
    assert conf.confidence(0, 0) == 0.0
    assert 0.0 <= conf.confidence(10, 1) <= 1.0
