ELO_K_FACTOR = 20

# Backend ratings run on a 1-1000 scale; the frontend displays 1-10.
# frontend_value * RATING_SCALE == backend_value (e.g. 5.0 front == 500.0 back).
RATING_SCALE = 100
DEFAULT_RATING = 500.0
RATING_FLOOR = 100.0
DEFAULT_PLAYERS_PER_TEAM = 3
WIN_SCORE = 25

# Small random jitter (backend scale) applied when forming teams, so the same
# roster/ratings don't always produce the exact same team split.
TEAM_FORM_JITTER = 15.0
