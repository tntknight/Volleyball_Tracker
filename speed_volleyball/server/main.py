import os
import sys
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))

import database as db
from game_logic import GameState, form_teams, Team
from config import DEFAULT_PLAYERS_PER_TEAM, RATING_SCALE

CLIENT_DIR = Path(__file__).parent.parent / "client"


# ── Rating scale conversion (backend stores 1-1000, frontend shows 1-10) ──────

def _player_to_frontend(player: dict) -> dict:
    d = dict(player)
    d["rating"] = round(d["rating"] / RATING_SCALE, 2)
    return d


def _players_to_frontend(players: list) -> list:
    return [_player_to_frontend(p) for p in players]


def _history_to_frontend(entry: dict) -> dict:
    d = dict(entry)
    d["old_rating"] = round(d["old_rating"] / RATING_SCALE, 2)
    d["new_rating"] = round(d["new_rating"] / RATING_SCALE, 2)
    return d

# Per-league game states, keyed by league id (populated lazily)
game_states: dict[int, GameState] = {}


def _league_state(league_id: int) -> GameState:
    if league_id not in game_states:
        game_states[league_id] = GameState()
    return game_states[league_id]


def _require_league(league_id: int) -> dict:
    league = db.get_league(league_id)
    if not league:
        raise HTTPException(404, f"League {league_id} not found")
    return league


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    ip = _local_ip()
    print("\n" + "=" * 50)
    print("  Speed Volleyball Scoreboard")
    print("=" * 50)
    print(f"  Kiosk:      http://{ip}:8000/kiosk")
    print(f"  Operator:   http://{ip}:8000/operator")
    print(f"  Scoreboard: http://{ip}:8000/scoreboard")
    print(f"  Watch:      http://{ip}:8000/watch")
    print("=" * 50 + "\n")
    yield


app = FastAPI(title="Speed Volleyball Scoreboard", lifespan=lifespan)


# ── WebSocket hub ──────────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self._connections:
            self._connections.remove(ws)

    async def broadcast(self, data: dict):
        dead = []
        for ws in list(self._connections):
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()


def _build_payload() -> dict:
    leagues = db.get_leagues()
    states = {}
    for league in leagues:
        lid = league["id"]
        gs = _league_state(lid).to_dict()
        gs["signed_up"] = _players_to_frontend(db.get_signed_up_players(lid))
        gs["players"] = _players_to_frontend(db.get_all_players_for_league(lid))
        states[str(lid)] = gs
    return {
        "leagues": leagues,
        "states": states,
    }


async def broadcast_state():
    await manager.broadcast(_build_payload())


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


# ── Static pages ───────────────────────────────────────────────────────────────

@app.get("/kiosk")
def kiosk():
    return FileResponse(CLIENT_DIR / "kiosk.html", media_type="text/html")


@app.get("/operator")
def operator():
    return FileResponse(CLIENT_DIR / "operator.html", media_type="text/html")


@app.get("/scoreboard")
def scoreboard():
    return FileResponse(CLIENT_DIR / "scoreboard.html", media_type="text/html")


@app.get("/watch")
def watch():
    return FileResponse(CLIENT_DIR / "watch.html", media_type="text/html")


@app.get("/")
def index():
    return FileResponse(CLIENT_DIR / "index.html", media_type="text/html")


# ── WebSocket ──────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        await ws.send_json(_build_payload())
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)


# ── REST — Leagues ─────────────────────────────────────────────────────────────

@app.get("/api/leagues")
def api_get_leagues():
    return db.get_leagues()


class NewLeagueBody(BaseModel):
    name: str


@app.post("/api/leagues")
async def api_add_league(body: NewLeagueBody):
    if not body.name.strip():
        raise HTTPException(400, "Name is required")
    try:
        league = db.add_league(body.name.strip())
    except Exception:
        raise HTTPException(409, "League name already exists")
    await broadcast_state()
    return league


# ── REST — Players (global — seed ratings) ────────────────────────────────────

@app.get("/api/players")
def api_get_players():
    return _players_to_frontend(db.get_all_players())


class NewPlayerBody(BaseModel):
    name: str
    rating: float = 5.0


@app.post("/api/players")
async def api_add_player(body: NewPlayerBody):
    if not body.name.strip():
        raise HTTPException(400, "Name is required")
    player = db.add_new_player(body.name.strip(), body.rating * RATING_SCALE)
    await broadcast_state()
    return _player_to_frontend(player)


# ── REST — Players (league-scoped — live ratings) ─────────────────────────────

@app.get("/api/leagues/{league_id}/players")
def api_get_league_players(league_id: int):
    _require_league(league_id)
    return _players_to_frontend(db.get_all_players_for_league(league_id))


class UpdateLeaguePlayerBody(BaseModel):
    name: Optional[str] = None
    rating: Optional[float] = None


@app.put("/api/leagues/{league_id}/players/{player_id}")
async def api_update_league_player(league_id: int, player_id: int, body: UpdateLeaguePlayerBody):
    _require_league(league_id)
    backend_rating = body.rating * RATING_SCALE if body.rating is not None else None
    player = db.update_player_for_league(player_id, league_id, name=body.name, rating=backend_rating)
    if not player:
        raise HTTPException(404, "Player not found")
    await broadcast_state()
    return _player_to_frontend(player)


@app.get("/api/leagues/{league_id}/players/{player_id}/history")
def api_league_rating_history(league_id: int, player_id: int):
    _require_league(league_id)
    return [_history_to_frontend(h) for h in db.get_league_rating_history(player_id, league_id)]


# ── REST — Sign-ups (league-scoped) ───────────────────────────────────────────

@app.get("/api/leagues/{league_id}/signups")
def api_get_signups(league_id: int):
    _require_league(league_id)
    return _players_to_frontend(db.get_signed_up_players(league_id))


@app.post("/api/leagues/{league_id}/signups/{player_id}")
async def api_sign_up(league_id: int, player_id: int):
    _require_league(league_id)
    ok = db.sign_up_player(player_id, league_id)
    if not ok:
        raise HTTPException(409, "Player already signed up for this league")
    await broadcast_state()
    return {"ok": True}


# ── REST — Teams & Game (league-scoped) ────────────────────────────────────────

class FormTeamsBody(BaseModel):
    players_per_team: int = DEFAULT_PLAYERS_PER_TEAM


@app.post("/api/leagues/{league_id}/teams/form")
async def api_form_teams(league_id: int, body: FormTeamsBody):
    _require_league(league_id)
    players = db.get_signed_up_players(league_id)
    if len(players) < 2:
        raise HTTPException(400, "Not enough signed-up players to form 2 teams")
    teams, waitlist = form_teams(players, body.players_per_team)
    _league_state(league_id).set_pending_teams(teams)
    await broadcast_state()
    return {"teams": [t.to_dict() for t in teams], "waitlist": _players_to_frontend(waitlist)}


class StartTeamDef(BaseModel):
    name: str
    player_ids: List[int]


class StartGameBody(BaseModel):
    teams: Optional[List[StartTeamDef]] = None


@app.post("/api/leagues/{league_id}/game/start")
async def api_start_game(league_id: int, body: StartGameBody = None):
    _require_league(league_id)
    gs = _league_state(league_id)
    if body and body.teams:
        all_players = {p["id"]: p for p in db.get_all_players_for_league(league_id)}
        teams = [
            Team(name=td.name, players=[all_players[pid] for pid in td.player_ids if pid in all_players])
            for td in body.teams
        ]
        try:
            gs.start_game(teams)
        except ValueError as e:
            raise HTTPException(400, str(e))
    else:
        try:
            gs.start_game()
        except ValueError as e:
            raise HTTPException(400, str(e))
    await broadcast_state()
    return {"ok": True}


@app.post("/api/leagues/{league_id}/game/point/{team_index}")
async def api_award_point(league_id: int, team_index: int):
    _require_league(league_id)
    try:
        _league_state(league_id).award_point(team_index, league_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await broadcast_state()
    return {"ok": True}


@app.post("/api/leagues/{league_id}/game/reset")
async def api_reset(league_id: int):
    _require_league(league_id)
    _league_state(league_id).reset()
    db.clear_signups(league_id)
    await broadcast_state()
    return {"ok": True}


@app.get("/api/leagues/{league_id}/game/state")
def api_game_state(league_id: int):
    _require_league(league_id)
    gs = _league_state(league_id).to_dict()
    gs["signed_up"] = _players_to_frontend(db.get_signed_up_players(league_id))
    gs["players"] = _players_to_frontend(db.get_all_players_for_league(league_id))
    return gs


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
