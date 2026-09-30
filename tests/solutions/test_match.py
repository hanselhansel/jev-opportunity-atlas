"""S5 task 1: dictionary matching of tool names from configs/tools.v1.yaml.

Case-insensitive whole-word match on the name and every alias, except terms
of 3 characters or fewer, which match case-sensitively only. A tool with
`name_case` set matches its *name* case-sensitively (aliases keep their
usual rules), so word-like names like Wise do not match the word "wise".
"""

from pathlib import Path

from atlas.solutions import match

ROOT = Path(__file__).resolve().parents[2]


def _tools():
    return [
        match.Tool(
            name="AWS",
            aliases=("aws", "amazon web services"),
            category="cloud_infra",
        ),
        match.Tool(
            name="Go",
            aliases=("golang", "go modules"),
            category="dev_tool",
        ),
        match.Tool(
            name="Cursor",
            aliases=("cursor ide", "cursor.sh"),
            category="ai_coding",
        ),
    ]


def test_alias_whole_word():
    tools = _tools()
    assert match.find_mentions("we moved off AWS last year", tools) == {"AWS"}
    assert match.find_mentions("the laws changed again", tools) == set()


def test_short_alias_case_sensitive():
    tools = _tools()
    assert match.find_mentions("I write Go every day", tools) == {"Go"}
    assert match.find_mentions("just let it go", tools) == set()
    # aliases longer than 3 chars still match case-insensitively
    assert match.find_mentions("GOLANG rocks", tools) == {"Go"}


def test_longest_term_wins_inside_punctuation():
    tools = [
        match.Tool(name="Llama", aliases=("llama 3",), category="ai_model"),
        match.Tool(name="llama.cpp", aliases=("llamacpp",), category="ai_model"),
    ]
    assert match.find_mentions("served by llama.cpp locally", tools) == {
        "llama.cpp"
    }


def test_name_case_flag():
    tools = [
        match.Tool(
            name="Wise",
            aliases=("wise.com",),
            category="saas_business",
            name_case=True,
        ),
    ]
    assert match.find_mentions("that was wise", tools) == set()
    assert match.find_mentions("I used Wise to pay", tools) == {"Wise"}
    # aliases keep their current rules: wise.com still matches case-insensitively
    assert match.find_mentions("checkout at WISE.COM", tools) == {"Wise"}


def test_default_name_still_case_insensitive():
    tools = [
        match.Tool(
            name="Signal", aliases=("signal app",), category="consumer_app"
        ),
    ]
    assert match.find_mentions("a weak signal", tools) == {"Signal"}
    assert match.find_mentions("a SIGNAL boost", tools) == {"Signal"}


def test_load_tools_reads_name_case(tmp_path):
    cfg = tmp_path / "tools.yaml"
    cfg.write_text(
        "version: v1\n"
        "tools:\n"
        "  - {name: Wise, aliases: [wise.com], category: saas_business, "
        "name_case: true}\n"
        "  - {name: Deno, aliases: [deno], category: dev_tool}\n",
        encoding="utf-8",
    )
    tools = {t.name: t for t in match.load_tools(cfg)}
    assert tools["Wise"].name_case is True
    assert tools["Deno"].name_case is False


def test_load_tools_reads_yaml(tmp_path):
    cfg = tmp_path / "tools.yaml"
    cfg.write_text(
        "version: v1\n"
        "tools:\n"
        "  - {name: Zed, aliases: [zed editor, zed.dev], category: ai_coding}\n",
        encoding="utf-8",
    )
    tools = match.load_tools(cfg)
    assert tools == [
        match.Tool(
            name="Zed",
            aliases=("zed editor", "zed.dev"),
            category="ai_coding",
        )
    ]
    assert match.find_mentions("moved to ZED.dev yesterday", tools) == {"Zed"}


def test_load_real_tools_config():
    tools = match.load_tools(ROOT / "configs" / "tools.v1.yaml")
    assert len(tools) > 100
    assert all(t.name and t.category for t in tools)


def test_real_config_flags_word_like_names():
    tools = {t.name: t for t in match.load_tools(ROOT / "configs" / "tools.v1.yaml")}
    assert tools["Wise"].name_case is True
    assert tools["Signal"].name_case is True


def test_compiled_matcher_reuse():
    tools = _tools()
    matcher = match.compile_tools(tools)
    assert match.find_mentions("AWS again", matcher) == {"AWS"}
    assert match.find_mentions("nothing here", matcher) == set()
