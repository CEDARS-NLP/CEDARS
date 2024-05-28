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
                            {"LOWER": "doctor"}]]]),
    ("gib OR ?gib OR bled OR bleed* OR bloody OR brbpr OR bruis* OR contusion OR ecchymo* OR epistax* OR exsanguinat* OR haemorrhag* OR hemarthros* OR hematemesis OR hematochezia OR hematoma OR hematuria OR hemoperi* OR hemoptysis OR hemorrhag* OR hemothorax OR ich OR melena OR menorrhagia OR metrorrhagia OR petechia OR petechia? OR purpur* OR rectorrhagia OR ( blood AND loss ) OR ( blood AND rectum ) OR ( blood AND stained ) OR ( blood AND tinged ) OR ( tarry AND stools ) OR ( hct AND drop* ) OR ( hb AND drop* ) OR ( hgb AND drop* ) OR ( hematocrit AND drop* ) OR ( hemoglobin AND drop* ) OR ( blood AND in AND urine ) OR ( coffee AND ground AND emesis )",
     [36, [[{"LEMMA": "gib"}]]])
    ])
def test_query_to_pattern(query, expected):
    res = nlpprocessor.query_to_patterns(query)
    assert len(res) == expected[0]
    for i, r in enumerate(res):
        assert r[0] == expected[1][i][0]


@pytest.mark.parametrize("token, expected", [
    ("thromb*", "(?i)thromb.*"),
    ("thromb?", "(?i)thromb\\w?")
])
def test_get_regex_dict(token, expected):
    res = nlpprocessor.get_regex_dict(token)
    assert res["TEXT"]["REGEX"] == expected
