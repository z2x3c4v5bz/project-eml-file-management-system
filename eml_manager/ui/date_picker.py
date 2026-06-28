"""A lightweight, dependency-free date picker built on the stdlib `calendar`
module and `ttk` widgets.

Why custom rather than a library:
- `tkcalendar` is LGPL — outside the project's commercial-safe whitelist.
- `ttkbootstrap.DateEntry` only renders once a `ttkbootstrap.Style` is created,
  and doing so re-themes every `ttk` widget app-wide, conflicting with the
  Windows vista-theme reliance documented in `main_view.py`.

The widget is a drop-in replacement for the plain `ttk.Entry` that previously
fed the search query builder: it stores its value as a canonical ``YYYYMMDD``
string in the supplied `StringVar` (empty string when no date is chosen), so the
existing timezone→UTC conversion in `MainView` needs no changes.
"""

import calendar
import datetime
import tkinter as tk
from tkinter import ttk
from typing import Optional


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    """Return (year, month) shifted by `delta` months, handling year rollover."""
    index = (year * 12 + (month - 1)) + delta
    return index // 12, index % 12 + 1


class DatePicker(ttk.Frame):
    """Read-only date entry (YYYY-MM-DD) plus a ttk calendar pop-up.

    The backing value is a ``YYYYMMDD`` string held in `textvariable`; an empty
    string means "no date selected". Setting the variable externally (e.g. the
    Clear button resetting it to "") updates the display automatically.
    """

    def __init__(self, parent, textvariable: tk.StringVar, width: int = 12):
        super().__init__(parent)
        self._var = textvariable
        self._popup: Optional[tk.Toplevel] = None
        self._view_year = datetime.date.today().year
        self._view_month = datetime.date.today().month

        self._display = tk.StringVar()
        self._entry = ttk.Entry(
            self, textvariable=self._display, width=width, state="readonly"
        )
        self._entry.pack(side=tk.LEFT)
        self._entry.bind("<Button-1>", lambda _e: self._open())
        ttk.Button(self, text="📅", width=3, command=self._open).pack(
            side=tk.LEFT, padx=(2, 0)
        )

        # Keep the visible text in sync with the backing value, including
        # external resets such as the filter-bar "Clear" button.
        self._var.trace_add("write", lambda *_: self._render())
        self._render()

    # ------------------------------------------------------------------ value

    def _render(self) -> None:
        raw = self._var.get().strip()
        if len(raw) == 8 and raw.isdigit():
            self._display.set(f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}")
        else:
            self._display.set("")

    def _selected_date(self) -> Optional[datetime.date]:
        raw = self._var.get().strip()
        if len(raw) == 8 and raw.isdigit():
            try:
                return datetime.date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
            except ValueError:
                return None
        return None

    # ------------------------------------------------------------------ pop-up

    def _open(self) -> None:
        if self._popup is not None and self._popup.winfo_exists():
            self._popup.lift()
            return
        # Open the calendar on the month of the current selection, else today.
        anchor = self._selected_date() or datetime.date.today()
        self._view_year, self._view_month = anchor.year, anchor.month

        self._popup = tk.Toplevel(self)
        self._popup.title("Select date")
        self._popup.resizable(False, False)
        self._popup.transient(self.winfo_toplevel())
        self._popup.protocol("WM_DELETE_WINDOW", self._close)
        self._popup.bind("<Escape>", lambda _e: self._close())
        self._build_popup()
        self._place_popup()
        self._popup.grab_set()
        self._popup.focus_set()

    def _place_popup(self) -> None:
        self.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        self._popup.wm_geometry(f"+{x}+{y}")

    def _close(self) -> None:
        if self._popup is not None:
            self._popup.grab_release()
            self._popup.destroy()
            self._popup = None

    def _build_popup(self) -> None:
        assert self._popup is not None
        for child in self._popup.winfo_children():
            child.destroy()

        outer = ttk.Frame(self._popup, padding=6)
        outer.pack()

        # Header: ‹  Month Year  ›
        header = ttk.Frame(outer)
        header.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(header, text="‹", width=3, command=self._prev_month).pack(side=tk.LEFT)
        ttk.Label(
            header,
            text=f"{calendar.month_name[self._view_month]} {self._view_year}",
            anchor=tk.CENTER,
            width=16,
        ).pack(side=tk.LEFT, expand=True)
        ttk.Button(header, text="›", width=3, command=self._next_month).pack(side=tk.LEFT)

        # Week starts on Sunday. The header labels and the day grid both derive
        # their column order from this same Calendar instance so they stay aligned.
        cal = calendar.Calendar(firstweekday=6)  # 6 = Sunday

        grid = ttk.Frame(outer)
        grid.pack()
        for col, weekday in enumerate(cal.iterweekdays()):
            ttk.Label(grid, text=calendar.day_abbr[weekday][:2], width=3, anchor=tk.CENTER).grid(
                row=0, column=col, padx=1, pady=1
            )

        today = datetime.date.today()
        selected = self._selected_date()
        focus_btn: Optional[ttk.Button] = None
        for r, week in enumerate(cal.monthdayscalendar(self._view_year, self._view_month), start=1):
            for c, day in enumerate(week):
                if day == 0:
                    continue
                d = datetime.date(self._view_year, self._view_month, day)
                btn = ttk.Button(
                    grid, text=str(day), width=3,
                    command=lambda dd=d: self._pick(dd),
                )
                btn.grid(row=r, column=c, padx=1, pady=1)
                # Give keyboard focus (a visible ring) to the selected day, or
                # today when nothing is selected yet — a theme-safe highlight.
                if selected is not None and d == selected:
                    focus_btn = btn
                elif focus_btn is None and selected is None and d == today:
                    focus_btn = btn

        # Footer: Today (left) | Clear (right)
        footer = ttk.Frame(outer)
        footer.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(footer, text="Today", command=lambda: self._pick(today)).pack(side=tk.LEFT)
        ttk.Button(footer, text="Clear", command=self._clear).pack(side=tk.RIGHT)

        if focus_btn is not None:
            focus_btn.focus_set()

    # ------------------------------------------------------------------ actions

    def _prev_month(self) -> None:
        self._view_year, self._view_month = _shift_month(self._view_year, self._view_month, -1)
        self._build_popup()

    def _next_month(self) -> None:
        self._view_year, self._view_month = _shift_month(self._view_year, self._view_month, +1)
        self._build_popup()

    def _pick(self, d: datetime.date) -> None:
        self._var.set(d.strftime("%Y%m%d"))
        self._close()

    def _clear(self) -> None:
        self._var.set("")
        self._close()
