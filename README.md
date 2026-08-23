# Marathon Planner

Marathon Planner is a local Python desktop application for turning
user-authored running plans into portable Garmin workout packages. A run can
use a mileage goal or a time goal and can produce separate ROAD and TRAIL
choices without changing the underlying training plan.

The intended handoff is one ZIP containing the full plan, Garmin FIT workouts,
a calendar, and simple instructions. A connected-watch installer will load an
upcoming block without requiring the recipient's Garmin credentials.

## Current state

The repository includes a runnable Tkinter weekly editor with tested domain
models for ordered workouts, distance- and time-based goals, and paired ROAD
and TRAIL choices. The editor can import the versioned local JSON format below.
FIT encoding, ZIP export, and watch installation are upcoming features.

## Local JSON plan format

Import accepts UTF-8 `.json` files up to 1,000,000 bytes. Version 1 uses exact
fields: unknown fields, duplicate object fields, unsupported versions, invalid
dates or values, and more than 104 weeks or 21 workouts per week are rejected.
Each workout date must fall from its week `start_date` through the following six
days. All text is preserved as authored, with a 500-character limit and no
control characters. No field may refer to another file or path.

```json
{
  "schema_version": 1,
  "weeks": [
    {
      "start_date": "2030-04-01",
      "workouts": [
        {
          "date": "2030-04-02",
          "title": "Aerobic run",
          "goal": {
            "type": "distance",
            "value": 6.25,
            "unit": "km"
          },
          "choices": {
            "ROAD": "Riverside route",
            "TRAIL": "Orchard trail"
          }
        }
      ]
    }
  ]
}
```

`goal.type` is `distance` with unit `mi`, `km`, or `m`, or `time` with unit
`sec`, `min`, or `hr`. Values must be finite JSON numbers greater than zero.
The app validates the complete document before replacing the open plan. Import
stays local and does not log or upload plan contents.

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
