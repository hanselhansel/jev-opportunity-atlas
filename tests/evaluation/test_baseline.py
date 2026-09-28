from atlas.evaluation.baseline import PATTERNS, keyword_score


def test_first_person_pain_matches():
    assert keyword_score("I hate how our deploys keep breaking every week") == 1.0
    assert keyword_score("We spent two days fighting the build system") == 1.0


def test_neutral_text_does_not_match():
    assert keyword_score("Rust 2.0 looks like a nice release.") == 0.0


def test_patterns_are_frozen():
    assert len(PATTERNS) >= 10


def test_third_person_pain_does_not_match():
    assert keyword_score("They hate the new UI.") == 0.0


def test_empty_text_scores_zero():
    assert keyword_score("") == 0.0
    assert keyword_score(None) == 0.0
