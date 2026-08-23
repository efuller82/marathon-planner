# Marathon Planner

Marathon Planner is a local Python desktop application for turning
user-authored running plans into portable Garmin workout packages. A run can
use a mileage goal or a time goal and can produce separate ROAD and TRAIL
choices without changing the underlying training plan.

The intended handoff is one ZIP containing the full plan, Garmin FIT workouts,
a calendar, and simple instructions. A connected-watch installer will load an
upcoming block without requiring the recipient's Garmin credentials.

## Current state

The repository is bootstrapped with a runnable Tkinter shell and tested domain
model for distance- and time-based run goals. Plan editing, FIT encoding, ZIP
export, and watch installation are upcoming features.

## Run locally

Python 3.12 or newer is recommended. Tkinter is included with standard Windows
Python installations.

```powershell
python run.py
```

Run the full project gate:

```powershell
python -m compileall -q src tests run.py
python -m unittest discover -s tests -v
```
