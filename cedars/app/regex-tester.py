import spacy
from spacy.matcher import Matcher
import argparse
from loguru import logger
from .nlpprocessor import query_to_patterns


def main():
    parser = argparse.ArgumentParser(description="Test NLP query patterns")
    parser.add_argument("query", type=str, help="The query to be converted to patterns")
    parser.add_argument("text", type=str, help="The text to be matched against")
    args = parser.parse_args()

    nlp = spacy.load("en_core_sci_lg")
    matcher = Matcher(nlp.vocab)

    patterns = query_to_patterns(args.query)

    formatted_patterns = "\n".join([str(pattern) for pattern in patterns]) 
    logger.info(f"Patterns: {formatted_patterns}")
    
    for idx, pattern in enumerate(patterns):
        matcher.add(f"Pattern_{idx}", [pattern])

    doc = nlp(args.text)
    matches = matcher(doc)

    print(f"Text: {args.text}")
    print("Matches:")
    for match_id, start, end in matches:
        span = doc[start:end]
        print(f"Matched: {span.text}")


if __name__ == "__main__":
    main()
