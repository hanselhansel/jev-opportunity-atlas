from atlas.sources.htmltext import MAX_SENTENCES, html_to_text, split_sentences


def test_paragraphs_entities_links_and_code():
    html = (
        "First line &amp; more.<p>Second <i>para</i> with "
        '<a href="https://ex.com/a" rel="nofollow">https://ex.com/a</a>.'
        "<p><pre><code>  x = 1\n  y = 2\n</code></pre>"
    )
    assert html_to_text(html) == (
        "First line & more.\n\nSecond para with https://ex.com/a.\n\n  x = 1\n  y = 2"
    )


def test_quotes_and_apostrophes_unescaped():
    assert html_to_text("I&#x27;m &quot;fine&quot; &gt; ok") == 'I\'m "fine" > ok'


def test_empty_and_none():
    assert html_to_text(None) == ""
    assert html_to_text("") == ""


def test_sentence_split_keeps_every_character_of_meaning():
    text = "I tried Stripe. It failed twice! Why? e.g. the API v2.1 broke.\n\nNew para"
    assert split_sentences(text) == [
        "I tried Stripe.",
        "It failed twice!",
        "Why?",
        "e.g. the API v2.1 broke.",
        "New para",
    ]


def test_units_do_not_merge():
    assert split_sentences("It took 200ms. Then it failed.") == [
        "It took 200ms.",
        "Then it failed.",
    ]


def test_sentence_cap_merges_the_tail():
    text = " ".join(f"S{i} ends." for i in range(400))
    out = split_sentences(text)
    assert len(out) == MAX_SENTENCES == 255
    assert out[-1].startswith("S254 ends.") and out[-1].endswith("S399 ends.")


def test_drop_pre_discards_code_blocks():
    html = (
        "Synthetic lead in words.<pre><code>x = 1\ny = 2\n</code></pre>"
        "Synthetic trailing words."
    )
    assert html_to_text(html, drop_pre=True) == (
        "Synthetic lead in words.Synthetic trailing words."
    )
    assert "x = 1" in html_to_text(html)
