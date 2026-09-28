from atlas.sources.lang import detect_many


def test_english_other_and_short():
    texts = [
        "I spent three hours debugging our deploy pipeline yesterday.",
        "Ich habe drei Stunden lang unsere Pipeline repariert und es war schlimm.",
        "lol same",
    ]
    assert detect_many(texts) == ["en", "de", "und"]


def test_code_heavy_english_is_kept():
    text = "I tried this and it broke: for i in range(10): print(i) https://ex.com/a/b?c=d"
    assert detect_many([text]) == ["en"]


def test_empty_and_none_input():
    assert detect_many(["", None, "   "]) == ["und", "und", "und"]
