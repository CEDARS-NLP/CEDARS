import pytest
from app import nlpprocessor


@pytest.mark.parametrize("query, expected", [
    ("DVT OR (!deep AND vein AND thromb*) OR clot ",
     [3, [[{"LEMMA": "DVT"}],
          [{"LOWER": "deep", "OP": "!"},
           {"LEMMA": "vein"},
           {"TEXT": {"REGEX": 'thromb*'}}],
          [{"LEMMA": "clot"}]]]),
    ("bleed", [1, [[{"LEMMA": "bleed"}]]]),
    ("be AND doctor", [1, [[{"LEMMA": "be"},
                            {"LOWER": "doctor"}]]])
    ])
def test_query_to_pattern(query, expected):
    res = nlpprocessor.query_to_patterns(query)
    assert len(res) == expected[0]
    for i, r in enumerate(res):
        assert r[0] == expected[1][i][0]


@pytest.mark.parametrize("token, expected", [
    ("thromb*", "\\bthromb.*\\b"),
    ("thromb?", "\\bthromb.\\b")
])
def test_get_regex_dict(token, expected):
    res = nlpprocessor.get_regex_dict(token)
    assert res["TEXT"]["REGEX"] == expected
