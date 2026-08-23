"""Tkinter desktop shell for Marathon Planner."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class MarathonPlannerApp(ttk.Frame):
    """Initial walking skeleton for the local planner."""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=24)
        self.grid(sticky="nsew")
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        ttk.Label(self, text="Marathon Planner", font=("Segoe UI", 20)).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self,
            text="Build user-authored Garmin plans with road and trail choices.",
        ).grid(row=1, column=0, sticky="w", pady=(4, 20))

        goal_frame = ttk.LabelFrame(self, text="Running workout goal", padding=16)
        goal_frame.grid(row=2, column=0, sticky="ew")
        goal_frame.columnconfigure(1, weight=1)

        self.goal_type = tk.StringVar(value="distance")
        ttk.Radiobutton(
            goal_frame,
            text="Mileage / distance",
            value="distance",
            variable=self.goal_type,
        ).grid(row=0, column=0, sticky="w", padx=(0, 24))
        ttk.Radiobutton(
            goal_frame,
            text="Time",
            value="time",
            variable=self.goal_type,
        ).grid(row=0, column=1, sticky="w")

        ttk.Label(
            self,
            text="Weekly editing, ROAD/TRAIL variants, and ZIP export are next.",
        ).grid(row=3, column=0, sticky="w", pady=(20, 0))


def main() -> None:
    root = tk.Tk()
    root.title("Marathon Planner")
    root.minsize(620, 300)
    MarathonPlannerApp(root)
    root.mainloop()
