# Basic Concepts

CEDARS uses a system where keywords are searched for using [lemmas](https://en.wikipedia.org/wiki/Lemma_(morphology)) in the search query. This query must be in a [regex](https://en.wikipedia.org/wiki/Regular_expression) format. After a query is entered all events that match the search query will be displayed to the user in the Adjudications page. However, unless it is otherwise specified all events that contain negations will not be shown in the Adjudications page.

## Lemmas
A lemma is defined as the canonical, dictionary or citation form of a word. For example, the words bleeding, bled and bleed all have the lemma bleed. This allows us to search for a reference to an event regardless of tense or grammar. To learn more about lemmas you may read [this article](https://en.wikipedia.org/wiki/Lemma_(morphology)).

## Regex Patterns
A regular expression (regex) pattern is a sequence of characters or words meant to match a pattern in text. For example, the pattern "bleed|cut" will search for both the words bleed and cut within a sentence. If either of them are found we can say that the pattern has been matched. To learn more you can learn more [here](https://en.wikipedia.org/wiki/Regular_expression).

## Negations
A negation is the absence or opposite of a positive. For example, in the sentence "He had no bleeding." the lemma for bleed is present, but a researcher looking for instances of bleeding will not be interested in this sentence. This is because the word "bleeding" has been negated and so must be excluded from the events.
