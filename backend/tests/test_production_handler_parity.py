import ast
import inspect
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.annotations.adjudication_compat import ReviewStatus
from app.annotations.adjudication_handler import AdjudicationHandler, SentenceHighlighter

REFERENCE_PATH = Path(
    "C:/Users/iranik/Documents/Public-CEDARS/CEDARS/cedars/app/adjudication_handler.py"
)

REFERENCE_METHOD_FIXTURES = {
    "_adjudicate_annotation": '''
@log_function_call
def _adjudicate_annotation(self):
    index = self.patient_data['current_index']
    self.patient_data['review_statuses'][index] = ReviewStatus.REVIEWED
    review_statuses = self.patient_data['review_statuses']
    last_index = len(review_statuses) - 1
    new_index = min(index + 1, last_index)
    if self.is_patient_reviewed():
        return new_index
    for new_index in range(index+1, len(review_statuses)):
        if review_statuses[new_index] == ReviewStatus.UNREVIEWED:
            self.patient_data['current_index'] = new_index
            return
    for new_index in range(0, index):
        if review_statuses[new_index] == ReviewStatus.UNREVIEWED:
            self.patient_data['current_index'] = new_index
            return
''',
    "mark_event_date": '''
@log_function_call
def mark_event_date(self, event_date, event_annotation_id, annotations_after_event):
    self.patient_data['event_date'] = self._format_date(event_date)
    self.patient_data['event_annotation_id'] = event_annotation_id
    annotations_after_event = set(annotations_after_event)
    for i, anno_id in enumerate(self.patient_data['annotation_ids']):
        review_status = self.patient_data['review_statuses'][i]
        anno_id = int(anno_id)
        if (anno_id in annotations_after_event) and (review_status == ReviewStatus.UNREVIEWED):
            self.patient_data['review_statuses'][i] = ReviewStatus.SKIPPED
    self._adjudicate_annotation()
''',
    "delete_event_date": '''
@log_function_call
def delete_event_date(self):
    self.patient_data['event_date'] = None
    self.patient_data['event_annotation_id'] = None
    self.reset_all_skipped()
    index = self.patient_data['current_index']
    self.patient_data['review_statuses'][index] = ReviewStatus.UNREVIEWED
''',
    "_filter_duplicates_by_patient": '''
@log_function_call
def _filter_duplicates_by_patient(self, annotations):
    indices_with_duplicates = []
    seen_sentences = set()
    for i, annotation in enumerate(annotations):
        sentence = annotation.sentence.lower().strip()
        if sentence in seen_sentences:
            indices_with_duplicates.append(i)
            continue
        seen_sentences.add(sentence)
    return indices_with_duplicates
''',
    "_filter_duplicates_by_note": '''
@log_function_call
def _filter_duplicates_by_note(self, annotations):
    indices_with_duplicates = []
    prev_note_id = None
    seen_sentences = set()
    for i, annotation in enumerate(annotations):
        if annotation.text_id != prev_note_id:
            seen_sentences.clear()
        prev_note_id = annotation.text_id
        sentence = annotation.sentence.lower().strip()
        if sentence in seen_sentences:
            indices_with_duplicates.append(i)
            continue
        seen_sentences.add(sentence)
    return indices_with_duplicates
''',
}


def _method_node(source, method_name):
    module = ast.parse(source)
    return next(
        node for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name
    )


def _class_methods(source, class_name):
    module = ast.parse(source)
    class_node = next(
        node for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return {
        node.name: node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _semantic_ast(node):
    node = ast.fix_missing_locations(ast.parse(ast.unparse(node))).body[0]

    class IgnoreNonAlgorithmStatements(ast.NodeTransformer):
        def visit_FunctionDef(self, function):
            self.generic_visit(function)
            if function.body and isinstance(function.body[0], ast.Expr):
                expression = function.body[0].value
                if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
                    function.body.pop(0)
            return function

        def visit_Expr(self, expression):
            value = expression.value
            if (
                isinstance(value, ast.Call)
                and isinstance(value.func, ast.Attribute)
                and isinstance(value.func.value, ast.Name)
                and value.func.value.id == "logger"
                and value.func.attr == "debug"
            ):
                return None
            return self.generic_visit(expression)

    return ast.dump(IgnoreNonAlgorithmStatements().visit(node), include_attributes=False)


def _annotation(annotation_id, text_id, sentence, start, status="U", negated=False):
    return SimpleNamespace(
        annotation_id=annotation_id,
        text_id=text_id,
        sentence=sentence,
        status=status,
        isNegated=negated,
        text_date=date(2026, 1, 1),
        sentence_number=0,
        note_start_index=start,
        note_end_index=start + len(sentence),
    )


def test_reference_handler_ast_matches_fixture_methods():
    handler_path = Path(__file__).parents[1] / "app" / "annotations" / "adjudication_handler.py"
    source = handler_path.read_text(encoding="utf-8")
    actual_handler_methods = _class_methods(source, "AdjudicationHandler")
    actual_filter_methods = _class_methods(source, "AnnotationFilterStrategy")

    for name, fixture in REFERENCE_METHOD_FIXTURES.items():
        actual_methods = (
            actual_filter_methods
            if name.startswith("_filter_duplicates_")
            else actual_handler_methods
        )
        assert _semantic_ast(actual_methods[name]) == _semantic_ast(
            _method_node(fixture, name)
        ), name

    if REFERENCE_PATH.is_file():
        reference_source = REFERENCE_PATH.read_text(encoding="utf-8")
        reference_handler_methods = _class_methods(reference_source, "AdjudicationHandler")
        reference_filter_methods = _class_methods(reference_source, "AnnotationFilterStrategy")
        approved_grouping_changes = {
            "get_all_annotations_for_curr_note",
            "get_all_annotations_for_curr_sentence",
        }
        for name, actual in actual_handler_methods.items():
            if name not in approved_grouping_changes:
                assert _semantic_ast(actual) == _semantic_ast(reference_handler_methods[name]), name
        for name, actual in actual_filter_methods.items():
            assert _semantic_ast(actual) == _semantic_ast(reference_filter_methods[name]), name


def test_reference_adjudication_advances_and_wraps_then_preserves_all_reviewed_return():
    annotations = [
        _annotation(1, "N1", "first", 0),
        _annotation(2, "N1", "second", 6),
        _annotation(3, "N1", "third", 13, status="R"),
    ]
    handler = AdjudicationHandler("P1")
    state, _ = handler.init_patient_data(annotations, hide_duplicates=False)

    handler._adjudicate_annotation()
    assert state["current_index"] == 1
    assert state["review_statuses"] == [
        ReviewStatus.REVIEWED,
        ReviewStatus.UNREVIEWED,
        ReviewStatus.REVIEWED,
    ]

    state["current_index"] = 2
    handler._adjudicate_annotation()
    assert state["current_index"] == 1

    state["review_statuses"][1] = ReviewStatus.REVIEWED
    state["current_index"] = 2
    assert handler._adjudicate_annotation() == 2
    assert state["current_index"] == 2
    assert list(inspect.signature(handler.delete_event_date).parameters) == []
    assert not hasattr(handler, "mark_skipped")


def test_event_date_skips_and_delete_restores_reference_statuses():
    annotations = [
        _annotation(1, "N1", "first", 0),
        _annotation(2, "N1", "second", 6),
        _annotation(3, "N1", "third", 13),
    ]
    handler = AdjudicationHandler("P1")
    state, _ = handler.init_patient_data(annotations, hide_duplicates=False)

    handler.mark_event_date(date(2026, 1, 1), "1", [3])

    assert state["event_date"] == date(2026, 1, 1)
    assert state["review_statuses"] == [
        ReviewStatus.REVIEWED,
        ReviewStatus.UNREVIEWED,
        ReviewStatus.SKIPPED,
    ]
    handler.delete_event_date()
    assert state["event_date"] is None
    assert state["event_annotation_id"] is None
    assert state["review_statuses"] == [
        ReviewStatus.REVIEWED,
        ReviewStatus.UNREVIEWED,
        ReviewStatus.UNREVIEWED,
    ]


def test_duplicate_filtering_matches_reference_patient_and_note_scope():
    annotations = [
        _annotation(1, "N1", "Same sentence", 0),
        _annotation(2, "N2", " same SENTENCE ", 0),
        _annotation(3, "N2", "Other sentence", 16),
    ]

    patient_handler = AdjudicationHandler("P1")
    patient_state, patient_duplicates = patient_handler.init_patient_data(
        annotations.copy(), hide_duplicates=True
    )
    note_handler = AdjudicationHandler("P1")
    note_state, note_duplicates = note_handler.init_patient_data(
        annotations.copy(), hide_duplicates=False
    )

    assert patient_state["annotation_ids"] == ["1", "3"]
    assert patient_duplicates == ["2"]
    assert note_state["annotation_ids"] == ["1", "2", "3"]
    assert note_duplicates == []


def test_retained_negated_annotation_is_grouped_and_highlighted():
    note = SimpleNamespace(text="no finding was seen.")
    annotations = [
        _annotation(1, "N1", "no finding was seen.", 0),
        _annotation(2, "N1", "finding", 3, negated=True),
    ]
    annotations[0].note_end_index = 2
    annotations[1].note_end_index = 10
    handler = AdjudicationHandler("P1")
    state, _ = handler.init_patient_data(annotations, hide_duplicates=False)
    grouped = handler.get_all_annotations_for_curr_sentence()

    assert [item.annotation_id for item in grouped] == [1, 2]
    rendered = SentenceHighlighter().get_highlighted_sentence(
        state["annotations"][0], note, grouped
    )
    assert "<b><mark>finding</mark></b>" in rendered
