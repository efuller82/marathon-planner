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
The core can also encode each dated workout as deterministic ROAD and TRAIL
Garmin FIT variants, export the complete open plan as one deterministic ZIP,
and preview a selected upcoming USB installation block without changing the
device. Applying the preview to a physical watch is not yet implemented.

## Local JSON plan format

Import accepts UTF-8 `.json` files up to 1,000,000 bytes. Versions 1 and 2 use
exact fields: unknown fields, duplicate object fields, unsupported versions,
invalid dates or values, and more than 104 weeks or 21 workouts per week are
rejected. Each workout date must fall from its week `start_date` through the
following six days. All text is preserved as authored, with a 500-character
limit and no control characters. No field may refer to another file or path.

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

Version 2 adds optional pace targets, all whole seconds and all authored by
the user. A plan-level `pace_settings` object holds one road-to-trail
adjustment and one alert buffer, and any workout may add a `pace` object:

```json
{
  "schema_version": 2,
  "pace_settings": {
    "trail_adjustment_seconds": 90,
    "alert_buffer_seconds": 30
  },
  "weeks": [
    {
      "start_date": "2030-04-01",
      "workouts": [
        {
          "date": "2030-04-02",
          "title": "Aerobic run",
          "goal": { "type": "distance", "value": 6.25, "unit": "km" },
          "choices": { "ROAD": "Riverside route", "TRAIL": "Orchard trail" },
          "pace": {
            "road_seconds_per_mile": 660,
            "trail_seconds_per_mile": 765,
            "alert_buffer_seconds": 45
          }
        }
      ]
    }
  ]
}
```

Only `road_seconds_per_mile` is required inside `pace`; the trail pace
defaults to the road pace plus the plan adjustment, and the buffer defaults to
the plan buffer. If any workout carries a pace, the plan must carry
`pace_settings`. Paces run 1–5999 seconds per mile, buffers 1–600 seconds, and
the buffer must stay smaller than both terrain paces. A workout without `pace`
keeps today's open-target behavior, and version 1 plans import unchanged.

## FIT workout encoding

Each workout produces one ROAD and one TRAIL `.fit` file. Both files contain
the same authored distance or time goal; terrain and the matching authored
choice appear in the workout and step labels. A paced workout's ROAD file
carries the road pace range and its TRAIL file the trail pace range as custom
speed targets, so a compatible watch alerts when the runner leaves the band;
a paceless workout still encodes an open target and produces exactly the same
bytes as before. Stable plan positions plus a content digest make filenames
and identifiers deterministic and collision-safe within a plan. Encoding uses
an in-repository FIT protocol 2.0/profile 21.00 writer and requires no
account, network access, or third-party dependency.

FIT structure and CRCs are parser-tested with synthetic plans. The Forerunner
265 accepted these files in issue #12's owner-run check; pace-range display
and alerting on-watch await issue #16's owner-run check.

## Plan package export

After importing a dated plan, use **Export plan ZIP**. Visible edits are
validated and stored before the entire open plan is exported. Package schema
version 1 has this fixed layout:

```text
manifest.json
plan.json
calendar.ics
README.txt
workouts/ROAD/<deterministic FIT filename>
workouts/TRAIL/<deterministic FIT filename>
```

`manifest.json` identifies the format and inventories every other member by
path, byte count, and SHA-256 digest. `plan.json` preserves the complete plan
in its importable JSON format: version 1 exactly as before when the plan has
no pace rules, version 2 when it does. `calendar.ics` creates one all-day
event per
workout on its authored date and maps that event to both FIT choices. The
included instructions explain local variant selection and USB handoff without
requesting Garmin credentials.

Member order, timestamps, permissions, and storage are fixed, so an identical
plan produces identical ZIP bytes. Archive paths and generated filenames are
validated. Export can replace a recognized Marathon Planner package at the
same destination, but refuses to overwrite unrelated files or symbolic links.

## USB installation dry run

After importing a dated plan, choose the start week, number of contiguous
weeks, and ROAD or TRAIL variant under **USB install dry run**, then select the
connected device root. The preview requires a bounded Garmin
`GarminDevice.xml` with one unambiguous existing `NewFiles` FIT destination. It
lists each proposed copy, replacement, removal, and metadata update without
writing any device file or requesting Garmin credentials.

Rotation ownership uses a device-bound Marathon Planner manifest containing
the managed relative path, byte count, and SHA-256 digest of every staged FIT
file. A missing prior file is treated as already consumed by the device. A
tampered managed file, malformed manifest, unsafe path, symbolic link, or
unrelated file collision blocks the preview rather than guessing. Unrelated
device files are never proposed for replacement or removal. Physical-device
compatibility remains unverified.

## Windows MTP installation

The separate Windows MTP action previews and applies the selected contiguous
week block to the verified Forerunner 265 destination
`Internal Storage/GARMIN/NewFiles`. It uses Windows Portable Devices directly,
never requests Garmin credentials, and does not fall back to the mounted-drive
installer. The Forerunner 265 profile passed issue #12's owner-run
synthetic-device check; other Garmin models remain unsupported.

MTP is the only feature with an optional third-party dependency. On Windows,
install the reviewed, MIT-licensed `comtypes` wheel from the hash-pinned file:

```powershell
python -m pip install --require-hashes -r requirements-windows-mtp.txt
```

The dependency has no required dependencies or recurring service cost. It is
loaded only when a Windows MTP operation begins; plan editing, export, mounted
USB installation, and the synthetic test gate remain standard-library-only.

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
