import numpy as np

# Daily event probabilities (observed data)
event_probabilities = np.array([0.01, 0.956, 0.1, .2, 0.95, 0.95])

# Prior: Uniform distribution - no prior knowledge
prior = np.ones(len(event_probabilities)) / len(event_probabilities)

# what is high prob?
high_prob_threshold = 0.955


# look for n days ahead
def sequence_score(day, probabilities, threshold):
    if probabilities[day] < threshold:
        return probabilities[day]  # Low probability, return as is
    # Check subsequent days for another high probability
    for next_day in range(day + 1, min(day + 3, len(probabilities))):  # Look ahead up to 2 days
        if probabilities[next_day] >= threshold:
            return probabilities[day] * 1.5  # Boost the score for sustained high probabilities
    return probabilities[day] * 0.75  # Penalize isolated high probabilities


# Adjusted likelihood
likelihood = np.array([sequence_score(day,
                                      event_probabilities,
                                      high_prob_threshold) for day in range(
                                          len(event_probabilities))])
posterior = prior * likelihood
posterior /= posterior.sum()  # Normalize
print(posterior)

# Most likely day for the first event (take argmax over a certain prob value??)
most_likely_day = np.argmax(posterior)

print(f"Most likely day for the first event: Day {most_likely_day}")
