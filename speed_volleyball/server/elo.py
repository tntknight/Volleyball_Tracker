from config import ELO_K_FACTOR


def calculate_elo(winner_avg_rating: float, loser_avg_rating: float, k: float = ELO_K_FACTOR):
    """Standard Elo expected score formula, operating on the backend's 1-1000 rating scale."""
    expected_winner = 1.0 / (1.0 + 10.0 ** ((loser_avg_rating - winner_avg_rating) / 400.0))
    winner_delta = k * (1.0 - expected_winner)
    loser_delta = k * (0.0 - (1.0 - expected_winner))
    return winner_delta, loser_delta
