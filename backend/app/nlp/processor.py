"""Faithful port of cedars/app/nlpprocessor.py to the v2 async stack.

The query-parsing and negation helpers (``query_to_patterns``, ``is_negated``,
and the ``get_*_dict`` builders) are copied verbatim from v1. ``process_notes``
and ``process_patient_pines`` keep v1's algorithm exactly; the only changes are:

* MongoDB reads/writes → async SQLAlchemy (via :mod:`app.workflow.db_ops`).
* One annotation is written per matched *sentence* with its keyword hits stored
  as :class:`~app.annotations.models.AnnotationToken` rows, instead of one
  annotation document per token. A sentence annotation is negated only when
  *all* of its token hits are negated, preserving v1's "hide negated" behaviour.
* The optional predictor step uses v2's active :class:`PredictorConfig` + the
  predictor factory, but retains v1's per-note threshold auto-review logic.

Negation fidelity note: :func:`is_negated` relies on dependency-parse structure,
so a parser-capable spaCy model must be configured via ``CEDARS_SPACY_MODEL``
(e.g. ``en_core_sci_lg``). With the default blank pipeline there is no parser and
negation detection degrades — matching v1, which loaded ``en_core_sci_lg``.
"""

import logging

from spacy.matcher import Matcher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, AnnotationToken, ReviewStatus
from app.connectors.models import Note
from app.nlp.engine import get_nlp
from app.predictors.factory import create_predictor
from app.predictors.models import PredictorConfig, PredictorType
from app.workflow import db_ops

logger = logging.getLogger(__name__)


# ── Query → spaCy pattern helpers (verbatim from v1 nlpprocessor.py) ──


def get_regex_dict(token):
    if "*" in token:
        token = token.replace("*", ".*")
    if "?" in token:
        token = token.replace("?", ".")
    return {"TEXT": {"REGEX": rf"\b{token}\b"}}


def get_lemma_dict(token):
    return {"LEMMA": token}


def get_negated_dict(token):
    return {"LOWER": token, "OP": "!"}


def query_to_patterns(query: str) -> list:
    """Convert CEDARS query syntax into spaCy Matcher patterns (verbatim v1)."""
    or_expressions = query.split(" OR ")
    res = [[] for _ in range(len(or_expressions))]
    for i, expression in enumerate(or_expressions):
        spacy_pattern = []
        expression = expression.strip().replace("(", "").replace(")", "")
        and_expressions = expression.split(" AND ")
        for tok in and_expressions:
            tok = tok.strip()
            if not tok:
                continue
            if "*" in tok or "?" in tok:
                spacy_pattern.append(get_regex_dict(tok))
            elif "!" in tok:
                spacy_pattern.append(get_negated_dict(tok.replace("!", "")))
            else:
                spacy_pattern.append(get_lemma_dict(tok))
        logger.debug(f"{expression} -> {spacy_pattern}")
        res[i] = spacy_pattern
    return res


def is_negated(span):
    """Determine if a matched span is negated in its sentence (verbatim v1 NegEx)."""
    neg_words = ['no', 'not', "n't", "wouldn't", 'never', 'nobody', 'nothing',
                 'neither', 'nowhere', 'noone', 'no-one', 'hardly', 'scarcely', 'barely']

    for token in span.subtree:
        parents = list(token.ancestors)
        children = list(token.children)

        for parent in token.ancestors:
            children.extend(list(parent.children))

        if ("neg" in [child.dep_ for child in children]) or ("neg" in [par.dep_ for par in parents]):
            return True

        parents_text = [par.text for par in parents]
        children_text = [child.text for child in children]

        for word in neg_words:
            if word in parents_text or word in children_text:
                return True

    return False


# ── Predictor resolution (v2 equivalent of v1's _get_predictor_name/get_prediction) ──


async def _get_active_predictor(session: AsyncSession, project_id: str):
    """Return (predictor, predictor_name) for the project's active config, or (None, None)."""
    result = await session.execute(
        select(PredictorConfig).where(
            PredictorConfig.project_id == project_id,
            PredictorConfig.is_active.is_(True),
            PredictorConfig.deleted_at.is_(None),
        )
    )
    cfg = result.scalars().first()
    if cfg is None:
        return None, None

    predictor = create_predictor(cfg)
    if cfg.predictor_type == PredictorType.PINES:
        name = "PINES"
    else:
        model = cfg.config.get("model") if isinstance(cfg.config, dict) else None
        name = f"LLM:{model or cfg.name}"
    return predictor, name


# ── Main processing entrypoints ──────────────────────────────────


async def process_patient_notes(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    *,
    batch_size: int = 20,
) -> dict:
    """Annotate a patient's un-annotated notes (faithful port of v1 ``process_notes``).

    Returns a small summary dict for job bookkeeping.
    """
    search_query = await db_ops.get_active_search_query(session, project_id)
    if search_query is None:
        logger.info("No active search query for project %s; nothing to process.", project_id)
        return {"status": "no_query", "annotated_notes": 0}

    query = search_query.query
    nlp_apply = search_query.nlp_apply

    nlp_model = get_nlp()
    matcher = Matcher(nlp_model.vocab)
    spacy_patterns = query_to_patterns(query)
    for i, item in enumerate(spacy_patterns):
        matcher.add(f"DVT_{i}", [item])

    documents = await db_ops.get_documents_to_annotate(session, project_id, patient_id)
    if len(documents) == 0:
        logger.info("No documents to process for patient %s", patient_id)
        if nlp_apply:
            await process_patient_pines(session, project_id, patient_id)
        return {"status": "no_documents", "annotated_notes": 0}

    logger.info("Found %d notes to process for patient %s", len(documents), patient_id)

    # v1 lowercases the note text before running the pipeline; token offsets are
    # therefore into the lowercased text, which is position-identical to the
    # original text used for display.
    texts = [(note.text or "").lower() for note in documents]
    docs = nlp_model.pipe(texts, batch_size=batch_size)

    docs_with_annotations = 0
    for note, doc in zip(documents, docs):
        note_has_positive = False
        sentence_start = 0
        for sent_no, sentence_annotation in enumerate(doc.sents):
            sentence_text = sentence_annotation.text.strip()
            sentence_end = sentence_start + len(sentence_text)
            matches = matcher(sentence_annotation)

            token_rows = []
            for match in matches:
                _, start, end = match
                token = sentence_annotation[start:end]
                has_negation = is_negated(token)
                token_start = token.start_char
                token_end = token_start + len(token.text)
                token_rows.append((token.text, has_negation, token_start, token_end))

            if token_rows:
                # A sentence is negated (hidden) only if it has no positive match.
                sentence_negated = all(neg for _, neg, _, _ in token_rows)
                if not sentence_negated:
                    note_has_positive = True

                annotation = Annotation(
                    project_id=project_id,
                    patient_id=patient_id,
                    note_id=note.id,
                    sentence_text=sentence_text,
                    matched_tokens=",".join(t[0] for t in token_rows),
                    is_negated=sentence_negated,
                    sentence_number=sent_no,
                    sentence_start=sentence_start,
                    sentence_end=sentence_end,
                    text_date=note.note_date,
                    review_status=ReviewStatus.UNREVIEWED,
                )
                session.add(annotation)
                for tok_text, neg, tok_start, tok_end in token_rows:
                    session.add(
                        AnnotationToken(
                            annotation_id=annotation.id,
                            token=tok_text,
                            note_start_index=tok_start,
                            note_end_index=tok_end,
                            is_negated=neg,
                        )
                    )

            sentence_start = sentence_end + 1

        # v1: a note with no non-negated matches is auto-reviewed by "CEDARS".
        if note_has_positive:
            docs_with_annotations += 1
        else:
            await db_ops.mark_note_reviewed(session, note.id, reviewed_by="CEDARS")

    await session.commit()

    # v1: if no note produced a positive match, the patient has nothing to review.
    if docs_with_annotations == 0:
        await db_ops.mark_patient_reviewed(session, project_id, patient_id, "CEDARS")
        await session.commit()

    # v1: run the optional predictor step when the query enables it.
    if docs_with_annotations > 0 and nlp_apply:
        logger.info("Processing %d notes with predictor", docs_with_annotations)
        await process_patient_pines(session, project_id, patient_id)

    return {"status": "completed", "annotated_notes": docs_with_annotations}


async def process_patient_pines(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    threshold: float = 0.95,
) -> None:
    """Optional predictor pass with threshold auto-review (verbatim v1 ``process_patient_pines``).

    For each annotated note: predict a score; if below ``threshold`` mark its
    annotations + the note reviewed. If every note scores below threshold, the
    whole patient is auto-reviewed.
    """
    note_ids = await db_ops.get_annotated_notes_for_patient(session, project_id, patient_id)
    logger.info("Found %d annotated notes for patient %s", len(note_ids), patient_id)
    if len(note_ids) == 0:
        await db_ops.mark_patient_reviewed(session, project_id, patient_id, reviewed_by="CEDARS")
        await session.commit()
        return

    predictor, predictor_name = await _get_active_predictor(session, project_id)
    if predictor is None:
        logger.warning(
            "nlp_apply is enabled but no active predictor is configured for project %s.",
            project_id,
        )
        return

    # predict_and_save: score any note that doesn't already have a stored score.
    for note_id in note_ids:
        if await db_ops.get_note_prediction(session, note_id, predictor_name) is None:
            note = await session.get(Note, note_id)
            if note is None:
                continue
            result = await predictor.predict(note.text)
            await db_ops.save_note_prediction(
                session, project_id, note_id, predictor_name, result.score
            )
    await session.commit()

    scores = []
    for note_id in note_ids:
        score = await db_ops.get_note_prediction(session, note_id, predictor_name)
        scores.append(score)
        if score is not None and score < threshold:
            updated = await db_ops.update_annotation_reviewed(session, note_id)
            await db_ops.mark_note_reviewed(session, note_id, reviewed_by=predictor_name)
            logger.info(
                "Auto-reviewed %d annotations for note %s (score %.2f)", updated, note_id, score
            )

    valid_scores = [s for s in scores if s is not None]
    if valid_scores and max(valid_scores) < threshold:
        await db_ops.mark_patient_reviewed(session, project_id, patient_id, reviewed_by=predictor_name)

    await session.commit()
