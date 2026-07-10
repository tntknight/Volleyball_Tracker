# Speed Volleyball Scoreboard

A real-time scoreboard for rotating-court speed volleyball. Runs entirely on a local WiFi network — no internet required after first load. Supports multiple leagues running independently on the same server.

---

## Requirements

- Python 3.9 or higher
- pip

---

## Install

```bash
cd speed_volleyball
pip install -r requirements.txt
```

---

## Run

```bash
python server/main.py
```

On startup the server prints the four URLs to visit:

```
==================================================
  Speed Volleyball Scoreboard
==================================================
  Kiosk:      http://192.168.1.42:8000/kiosk
  Operator:   http://192.168.1.42:8000/operator
  Scoreboard: http://192.168.1.42:8000/scoreboard
  Watch:      http://192.168.1.42:8000/watch
==================================================
```

---

## Screens

| Screen | URL | Who uses it |
|--------|-----|-------------|
| **Kiosk** | `/kiosk` | Players sign up on a shared tablet or phone |
| **Operator** | `/operator` | One person manages the game from a phone or laptop |
| **Scoreboard** | `/scoreboard` | Displayed on a TV for everyone to watch |
| **Watch** | `/watch` | Score rallies from a smartwatch or phone |

Open the home page at `http://<ip>:8000/` to see links to all four screens.

---

## Network setup

- The server device and all client devices must be on **the same WiFi network**.
- Use the IP address printed at startup (e.g. `192.168.1.42`) — **not** `localhost` — when sharing URLs with other devices.
- The server device's firewall must allow inbound connections on port **8000**.

---

## Leagues

The server ships with two leagues pre-configured: **Presbytery** and **DCC**. Each league has its own independent sign-up list and game state, but shares the same player database and ratings.

Every screen has a league selector — tap a league name to switch. The selection is remembered in the browser across refreshes.

**Kiosk** — players are asked which league they're playing in before signing up. If only one league exists, this step is skipped automatically.

**Operator** — league pills appear in the header. Switching leagues takes you to that league's Players tab. Each league's game runs independently; both can be active at the same time.

**Scoreboard** — league pills appear in the header when there are two or more leagues. On load it auto-selects the first league that has an active game.

**Watch** — league pills appear at the top when there are two or more leagues. Scoring always hits the selected league.

### Adding more leagues

Use the API directly or add entries to the `League` table in `server/players.db`. Via the API:

```bash
curl -X POST http://<ip>:8000/api/leagues \
  -H "Content-Type: application/json" \
  -d '{"name": "Thursday Night"}'
```

The new league appears on all screens immediately.

---

## Displaying the scoreboard fullscreen

1. Open `/scoreboard` in a browser on the TV-connected device.
2. Press **F11** (Windows/Linux) or **Cmd+Ctrl+F** (Mac) to go fullscreen.
3. Most smart TVs with a built-in browser also support fullscreen via the remote.

---

## Watch screen

The watch page is a minimal, no-framework page designed for small screens (280–454 px). It works in any watch browser that supports WebSockets — Wear OS (Chrome), Samsung Galaxy Watch (Samsung Internet), or any phone used as a quick scorer.

- Tap the left half to award a point to Team A, right half for Team B.
- A brief colour flash confirms the tap registered.
- Rating deltas appear as a toast at the bottom for 3 seconds after each rally.
- Apple Watch does not have a user-accessible browser; use a phone instead.

---

## Internet note

React and Babel are loaded from `unpkg.com` CDN on first page load. After that they are cached by the browser and the app works offline. The watch screen uses no external libraries and loads instantly.

If you need fully offline operation from the start, download the following files, place them in `client/vendor/`, and update the `<script>` tags in `client/kiosk.html`, `client/operator.html`, and `client/scoreboard.html` to point to local paths:

- `https://unpkg.com/react@18/umd/react.production.min.js`
- `https://unpkg.com/react-dom@18/umd/react-dom.production.min.js`
- `https://unpkg.com/@babel/standalone/babel.min.js`

Then add a static-files mount in `server/main.py`:

```python
from fastapi.staticfiles import StaticFiles
app.mount("/vendor", StaticFiles(directory=str(CLIENT_DIR / "vendor")), name="vendor")
```

---

## How a game works

1. Players sign in on the **Kiosk** — select the league, then "I'm New" or "I'm Returning".
2. On the **Operator** → *Players* tab: choose a league, set players per team, click **Form Teams**.
3. Optionally swap players between teams using the move buttons.
4. Click **Start Game** — game goes live on all screens.
5. After each rally, tap **+1 Point** on the Operator or Watch screen for the winning team.
   - The losing team rotates to the back of the queue.
   - Elo ratings update automatically for all players on both teams.
6. Click **End Game / Reset** to clear that league's game and sign-up list.

---

## Data

- `server/players.db` is created automatically on first run, with Presbytery and DCC leagues pre-seeded.
- **Ratings are per-league.** A player has an independent rating in each league they play in. Playing in Presbytery never affects their DCC rating.
- When a player signs up for a league for the first time, their rating in that league is seeded from the initial rating set when they were created.
- Sign-ups are per-league and are cleared when that league's game is reset.
- Rating history is per-league and is viewable in the **Admin** tab of the Operator panel (scoped to whichever league is selected).

---

## API reference

All game, sign-up, and rating endpoints are scoped to a league via `/api/leagues/{id}/…`. Adding players is global (the player record itself is shared; ratings are not).

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/leagues` | List all leagues |
| `POST` | `/api/leagues` | Create a league `{"name": "…"}` |
| `GET` | `/api/players` | All players with seed ratings |
| `POST` | `/api/players` | Add player `{"name": "…", "rating": 5.0}` |
| `GET` | `/api/leagues/{id}/players` | All players with their rating for this league |
| `PUT` | `/api/leagues/{id}/players/{player_id}` | Edit a player's name and/or their rating in this league |
| `GET` | `/api/leagues/{id}/players/{player_id}/history` | Rating history for a player in this league |
| `GET` | `/api/leagues/{id}/signups` | Signed-up players for a league |
| `POST` | `/api/leagues/{id}/signups/{player_id}` | Sign a player up for a league |
| `POST` | `/api/leagues/{id}/teams/form` | Form teams `{"players_per_team": 3}` |
| `POST` | `/api/leagues/{id}/game/start` | Start the game (optionally pass custom teams) |
| `POST` | `/api/leagues/{id}/game/point/{0\|1}` | Award a rally point |
| `POST` | `/api/leagues/{id}/game/reset` | Reset game and clear sign-ups |
| `GET` | `/api/leagues/{id}/game/state` | Current game state for a league |
| `WS` | `/ws` | WebSocket — broadcasts full state to all clients on every change |

---

## Config

Edit `server/config.py` to adjust:

| Setting | Default | Description |
|---------|---------|-------------|
| `ELO_K_FACTOR` | `20` | How much each rally shifts ratings |
| `DEFAULT_RATING` | `5.0` | Starting rating for new players |
| `RATING_FLOOR` | `1.0` | Minimum rating (ratings never drop below this) |
| `DEFAULT_PLAYERS_PER_TEAM` | `3` | Pre-filled value for players-per-team input |

To change the default leagues, edit the `DEFAULT_LEAGUES` list in `server/database.py`. Changes only take effect on a fresh database (delete `server/players.db` to reset).
