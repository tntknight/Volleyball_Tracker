from config import ELO_K_FACTOR, RATING_FLOOR


def calculate_elo(winner_avg_rating: float, loser_avg_rating: float, k: float = ELO_K_FACTOR):
    """Standard Elo expected score formula. Ratings are scaled *100 so the
    0-10 initial range maps to a 0-1000 point scale matching the 400-divisor."""
    w = winner_avg_rating * 100.0
    l = loser_avg_rating * 100.0
    expected_winner = 1.0 / (1.0 + 10.0 ** ((l - w) / 400.0))
    winner_delta = k * (1.0 - expected_winner)
    loser_delta = k * (0.0 - (1.0 - expected_winner))
    return winner_delta, loser_delta
