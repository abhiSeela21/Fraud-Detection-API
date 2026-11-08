SCORING_VERSION = "combined-v1"


def combined_score(probability: float, rule_score: int) -> int:
    return min(100, round(probability * 100) + min(40, rule_score))
