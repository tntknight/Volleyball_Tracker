import random
from collections import deque
from dataclasses import dataclass, field
from typing import List

from config import RATING_FLOOR, RATING_SCALE, TEAM_FORM_JITTER, WIN_SCORE
from elo import calculate_elo
from database import update_league_rating


@dataclass
class Team:
    name: str
    players: List[dict]
    score: int = 0

    @property
    def avg_rating(self) -> float:
        if not self.players:
            return 0.0
        return sum(p["rating"] for p in self.players) / len(self.players)

    def to_dict(self) -> dict:
        """Serializes ratings on the frontend's 1-10 scale; internally they're stored 1-1000."""
        return {
            "name": self.name,
            "players": [
                {"id": p["id"], "name": p["name"], "rating": round(float(p["rating"]) / RATING_SCALE, 1)}
                for p in self.players
            ],
            "score": self.score,
            "avg_rating": round(self.avg_rating / RATING_SCALE, 1),
        }


def form_teams(players: list, players_per_team: int):
    """Splits every signed-up player onto a team - nobody sits out because of
    leftover remainder math. Pools of 6 or fewer always become exactly 2 teams;
    larger pools use players_per_team to size the teams, with any remainder
    spread across teams as one extra player each (uneven counts) rather than
    waitlisting them."""
    if players_per_team < 1:
        players_per_team = 1

    total = len(players)
    if total < 2:
        return [], list(players)

    num_teams = 2 if total <= 6 else max(2, total // players_per_team)

    sorted_players = sorted(
        players,
        key=lambda p: p["rating"] + random.uniform(-TEAM_FORM_JITTER, TEAM_FORM_JITTER),
        reverse=True,
    )

    base_size = total // num_teams
    max_size = base_size + (1 if total % num_teams else 0)

    slots = [[] for _ in range(num_teams)]
    totals = [0.0] * num_teams

    for player in sorted_players:
        idx = min((i for i in range(num_teams) if len(slots[i]) < max_size), key=lambda i: totals[i])
        slots[idx].append(player)
        totals[idx] += player["rating"]

    teams = []
    for i, slot in enumerate(slots):
        label = chr(65 + i) if i < 26 else str(i + 1)
        teams.append(Team(name=f"Team {label}", players=slot))

    return teams, []


class GameState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.status = "waiting"
        self.on_court: List[Team] = []
        self.queue: deque = deque()
        self.all_teams: List[Team] = []
        self.pending_teams: List[Team] = []
        self.last_rating_deltas: List[dict] = []

    def set_pending_teams(self, teams: List[Team]):
        self.pending_teams = list(teams)

    def start_game(self, teams: List[Team] = None):
        use = teams if teams is not None else self.pending_teams
        if len(use) < 2:
            raise ValueError("Need at least 2 teams to start")
        self.all_teams = list(use)
        self.on_court = [self.all_teams[0], self.all_teams[1]]
        self.queue = deque(self.all_teams[2:])
        self.status = "active"
        self.last_rating_deltas = []

    def award_point(self, winning_team_index: int, league_id: int):
        if self.status != "active" or len(self.on_court) < 2:
            raise ValueError("Game is not active")
        if winning_team_index not in (0, 1):
            raise ValueError("team_index must be 0 or 1")

        losing_idx = 1 - winning_team_index
        winner = self.on_court[winning_team_index]
        loser = self.on_court[losing_idx]

        winner.score += 1
        game_over = winner.score >= WIN_SCORE and winner.score - loser.score >= 2

        if game_over:
            w_delta, l_delta = calculate_elo(winner.avg_rating, loser.avg_rating)
            deltas = []
            for p in winner.players:
                new_r = max(RATING_FLOOR, p["rating"] + w_delta)
                update_league_rating(p["id"], league_id, new_r)
                deltas.append({"player_name": p["name"], "delta": round(w_delta / RATING_SCALE, 2)})
                p["rating"] = new_r
            for p in loser.players:
                new_r = max(RATING_FLOOR, p["rating"] + l_delta)
                update_league_rating(p["id"], league_id, new_r)
                deltas.append({"player_name": p["name"], "delta": round(l_delta / RATING_SCALE, 2)})
                p["rating"] = new_r
            self.last_rating_deltas = deltas
            winner.score = 0
            loser.score = 0
        else:
            self.last_rating_deltas = []

        if self.queue:
            next_team = self.queue.popleft()
            self.queue.append(loser)
            self.on_court[losing_idx] = next_team

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "on_court": [t.to_dict() for t in self.on_court],
            "queue": [t.to_dict() for t in list(self.queue)],
            "last_rating_deltas": self.last_rating_deltas,
            "pending_teams": [t.to_dict() for t in self.pending_teams],
            "signed_up": [],
            "all_players": [],
        }
