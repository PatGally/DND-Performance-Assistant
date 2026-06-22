# Dungeons and Dragons Performance Assistant — Backend

> The Core Engine and Performance Assistant powering real-time, ruleset-aware action recommendations for D&D 5e 2014 combat encounters.

Built by **MinMaxCollective** 2026.

---

## Overview

This repository contains the **backend** of the DND Performance Assistant — the authoritative state machine for combat encounters and the recommendation engine that runs NPC turns for the Dungeon Master.

The backend exposes a FastAPI service that the frontend consumes. It owns:

- The **Core Engine** — D&D 5e 2014 rules enforcement (action economy, spell slots, concentration, range, movement)
- The **Performance Assistant** — ranking and recommending legal actions per turn using dynamic weighting
- **Combat state** — encounter, initiative, and creature state are authoritative on the server
- **Persistence** — encounter, creature, and ruleset data are stored via the `db` layer

For the frontend (React app, Grid Map System, UI), see the companion repository.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Framework | FastAPI |
| Validation | Pydantic |
| Server | Uvicorn |
| Rules Engine | Custom Core Engine |
| Recommendation | Performance Assistant w/ Dynamic Weighting |
| ML / Analytics | `ml/` module |
| Persistence | `db/` layer |
| Testing | pytest |

---

## Features

### Core Engine
The authoritative ruleset implementation for D&D 5e 2014 combat. Lives in `CoreEngine/` as a set of domain classes (`Encounter`, `Monster`, `Player`, `Action`, `MonAction`, `Spell`, `Stats`, `Weapon`) plus class-specific behavior under `DNDClasses/` and static rules data under `data/`.

- **Action economy enforcement**: Tracks action, bonus action, reaction, and movement state per creature per turn.
- **Spell slot management**: Validates slot availability before allowing a spell action and decrements on cast.
- **Concentration exclusivity**: Enforces the one-concentration-spell rule; new concentration drops prior concentration.
- **Range & targeting checks**: Validates target legality based on creature position, weapon/spell range, and grid distance.
- **Movement validation**: Confirms requested movement is within the creature's remaining speed and not blocked by occupancy.
- **Legal action computation**: Returns the set of actions a creature is permitted to take given current state.

### Performance Assistant
Real-time action recommender invoked at the start of each NPC turn. Backed by the `ml/` module for scoring and dynamic weighting.

- **Candidate generation**: Enumerates all legal actions for the active creature.
- **Dynamic weighting**: Scores candidates against context-aware weights (HP thresholds, target priority, ally state, etc.).
- **Analytics computation**: For each candidate, computes probability of success, expected damage, and impact rating.
- **Ranked recommendation**: Returns ranked candidates and a chosen recommendation, surfaced to the DM via the frontend.

### Backend API
FastAPI service in `BackendAPI/` that exposes the engine and assistant to the frontend.

- Create encounters with maps, players, and monsters
- Submit turns and receive updated state
- Toggle Ruleset vs. Manual mode per turn
- Query legal actions and recommendations on demand

### Mode Handling
Per-turn execution mode selected before resolution.

- **Ruleset mode**: Performance Assistant runs and rules are strictly enforced.
- **Manual mode**: DM overrides; the engine validates state but does not auto-recommend.

---

## Project Structure High Level

```
DND-Performance-Assistant/
├── BackendAPI/             # FastAPI service layer
│   ├── models/             # API request/response models
│   ├── __init__.py
│   └── server.py           # FastAPI app entry point
├── CoreEngine/             # D&D 5e rules engine and domain model
│   ├── data/               # Static rules data
│   ├── DNDClasses/         # Class-specific behavior (Fighter, Wizard, etc.)
│   ├── Action.py           # Generic action model
│   ├── Encounter.py        # Encounter state machine
│   ├── MonAction.py        # Monster-specific actions
│   ├── Monster.py
│   ├── Player.py
│   ├── Spell.py
│   ├── Stats.py
│   └── Weapon.py
├── db/                     # Persistence layer
│   ├── db_access.py        # Data access functions
│   └── driver.py           # Database driver / connection
├── ml/                     # Performance Assistant scoring & dynamic weighting
├── logs/                   # Logging
│   └── loggingConfig.py
├── artifacts/              # Build / ML artifacts
├── tests/                  # pytest suite
├── .env                    # Local default environment
├── .env.development        # Development environment
└── .env.production         # Production environment
```

---

## Getting Started

### Prerequisites
- Python 3.11+
- pip (or uv / poetry)
- (Optional) A running instance of the frontend application

### Installation

```bash
git clone <this-repo-url>
cd DND-Performance-Assistant
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Environment

The repo ships with three environment files:

- `.env` — local default
- `.env.development` — development environment
- `.env.production` — production environment

Populate the appropriate file with at minimum:

```
ALLOWED_ORIGINS=http://localhost:5173
LOG_LEVEL=INFO
DB_URL=...
```

`ALLOWED_ORIGINS` is consumed by `fastapi.middleware.cors.CORSMiddleware` and should include the frontend dev origin (and any deployed origin). If the frontend reports blocked requests in the browser console, verify this value matches the frontend's actual origin.

### Run

```bash
uvicorn BackendAPI.server:app --reload          # local development
uvicorn BackendAPI.server:app --host 0.0.0.0    # production-style
pytest                                          # run the test suite
```

The service defaults to `http://localhost:8000`. Interactive API docs are available at `/docs` (Swagger UI) and `/redoc`.

---

## Scope Notes

A few intentional scoping decisions worth flagging:

- **D&D 5e 2014 ruleset only.** 2024 ruleset changes are out of scope.
- **No fog of war / obstacles.** Movement and targeting assume fully-visible, fully-traversable tiles, matching the frontend Grid Map System.
- **Authoritative state lives here.** The frontend renders and submits; it does not own combat state.

---

## License

This project is licensed under the PolyForm Noncommercial License 1.0.0.
It is free to use for personal, educational, research, and other 
non-commercial purposes. Commercial use is not permitted without a 
separate license — contact [testingorange5000@gmail.com] for commercial licensing.

See the LICENSE file for full terms.
