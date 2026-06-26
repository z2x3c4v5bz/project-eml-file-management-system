"""
Main content panel: status overview + search/filter bar + results table.
Sections A and B from CAD §5.1.1 are a single unified view, not tabs.
"""

import csv
import datetime
import os
import pathlib
import re
import subprocess
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import List

from ..config import Config
from ..database import Database
from ..normalizer import strip_subject_prefixes


_RE_PAT = re.compile(r"^(?:re|回复|回覆|答复)\s*[：:]", re.IGNORECASE)
_FW_PAT = re.compile(r"^(?:fw|fwd|转发|轉發)\s*[：:]", re.IGNORECASE)


def _detect_mail_type(subject: str) -> str:
    s = subject.strip()
    if _RE_PAT.match(s):
        return "Re"
    if _FW_PAT.match(s):
        return "Fw"
    return ""


def _tz_label(tz_name: str) -> str:
    """Return a short timezone abbreviation for display (e.g. 'UTC', 'JST', 'EST')."""
    if not tz_name or tz_name.upper() == "UTC":
        return "UTC"
    try:
        import zoneinfo
        return datetime.datetime.now(zoneinfo.ZoneInfo(tz_name)).strftime("%Z")
    except Exception:
        return tz_name


def _local_date_to_utc(date_str: str, tz_name: str, end_of_day: bool = False) -> str:
    """Convert a YYYYMMDD (or YYYYMMDDHHmmss) string in tz_name to a UTC YYYYMMDDHHmmss string."""
    if not date_str:
        return date_str
    if len(date_str) == 8 and date_str.isdigit():
        y, mo, d = int(date_str[:4]), int(date_str[4:6]), int(date_str[6:])
        h, mi, s = (23, 59, 59) if end_of_day else (0, 0, 0)
    elif len(date_str) == 14 and date_str.isdigit():
        y, mo, d = int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8])
        h, mi, s = int(date_str[8:10]), int(date_str[10:12]), int(date_str[12:14])
    else:
        return date_str
    if tz_name and tz_name.upper() != "UTC":
        try:
            import zoneinfo
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            tz = datetime.timezone.utc
    else:
        tz = datetime.timezone.utc
    dt_local = datetime.datetime(y, mo, d, h, mi, s, tzinfo=tz)
    return dt_local.astimezone(datetime.timezone.utc).strftime("%Y%m%d%H%M%S")


class _TagEditDialog(tk.Toplevel):
    """Modal dialog for editing comma-separated tags with quick-pick from prior tags."""

    def __init__(self, parent, current_tags: str, all_tags: list[str], subject: str):
        super().__init__(parent)
        self.title("Edit Tags")
        self.resizable(False, False)
        self.result: str | None = None
        self._all_tags = all_tags
        self._build(current_tags, subject)
        self.transient(parent)
        self.grab_set()
        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self._entry.focus_set()

    def _build(self, current_tags: str, subject: str):
        ttk.Label(self, text=subject, wraplength=340, font=("", 9, "bold")).pack(
            padx=12, pady=(10, 2), anchor=tk.W
        )
        ttk.Label(self, text="Comma-separated tags:").pack(padx=12, anchor=tk.W)

        self._entry_var = tk.StringVar(value=current_tags)
        self._entry = ttk.Entry(self, textvariable=self._entry_var, width=44)
        self._entry.pack(padx=12, pady=(2, 8))
        self._entry.icursor(tk.END)
        self._entry.bind("<Return>", lambda e: self._ok())

        if self._all_tags:
            ttk.Label(self, text="Previously used tags — click to add or remove:").pack(
                padx=12, anchor=tk.W
            )
            frm = ttk.Frame(self)
            frm.pack(padx=12, pady=(2, 8), fill=tk.BOTH)
            # tk.Listbox — no ttk equivalent
            self._lb = tk.Listbox(
                frm, height=6, width=42, selectmode=tk.BROWSE, activestyle="none"
            )
            sb = ttk.Scrollbar(frm, orient=tk.VERTICAL, command=self._lb.yview)
            self._lb.configure(yscrollcommand=sb.set)
            self._lb.pack(side=tk.LEFT, fill=tk.BOTH)
            sb.pack(side=tk.RIGHT, fill=tk.Y)
            for tag in self._all_tags:
                self._lb.insert(tk.END, tag)
            self._lb.bind("<ButtonRelease-1>", lambda e: self._toggle_tag())
            self._lb.bind("<Return>", lambda e: self._toggle_tag())

        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill=tk.X, padx=12, pady=(0, 10))
        ttk.Button(btn_frame, text="OK", command=self._ok).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=2)

        self.bind("<Escape>", lambda e: self.destroy())

    def _toggle_tag(self):
        if not hasattr(self, "_lb"):
            return
        sel = self._lb.curselection()
        if not sel:
            return
        tag = self._lb.get(sel[0])
        existing = [t.strip() for t in self._entry_var.get().split(",") if t.strip()]
        if tag in existing:
            existing.remove(tag)
        else:
            existing.append(tag)
        self._entry_var.set(", ".join(existing))

    def _ok(self):
        self.result = self._entry_var.get()
        self.destroy()


class MainView(ttk.Frame):
    def __init__(self, parent, db, config: Config, bundle=None):
        super().__init__(parent)
        self._db = db
        self._config = config
        self._bundle = bundle
        self._results: List[dict] = []
        self._searching = False
        self._build()

    def _fmt_ts(self, ts: str | None) -> str:
        """Convert stored UTC YYYYMMDDHHmmss to the configured timezone and format for display."""
        if not (ts and len(ts) == 14 and ts.isdigit()):
            return ts or ""
        dt = datetime.datetime(
            int(ts[:4]), int(ts[4:6]), int(ts[6:8]),
            int(ts[8:10]), int(ts[10:12]), int(ts[12:14]),
            tzinfo=datetime.timezone.utc,
        )
        tz_name = self._config.timezone
        if tz_name and tz_name.upper() != "UTC":
            try:
                import zoneinfo
                dt = dt.astimezone(zoneinfo.ZoneInfo(tz_name))
            except Exception:
                pass
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def update_config(self, config: Config) -> None:
        """Apply a new Config (e.g. after Settings save) and re-render all Sent Date cells."""
        self._config = config
        self._sent_from_label_var.set(
            f"Sent From (YYYYMMDD, {_tz_label(config.timezone)}):"
        )
        self.refresh()

    # ------------------------------------------------------------------ build

    def _build(self):
        self._build_status_panel()
        self._build_filter_bar()
        self._build_table()

    def _build_status_panel(self):
        panel = ttk.LabelFrame(self, text="Monitoring Status", padding=(6, 4))
        panel.pack(fill=tk.X, padx=4, pady=(4, 2))

        # tk.Label kept intentionally: ttk.Label ignores fg= under the Windows
        # vista/xpnative theme; we need direct fg control for the colour dot.
        self._status_dot = tk.Label(panel, text="●", fg="orange", font=("", 14))
        self._status_dot.pack(side=tk.LEFT)

        self._status_text = ttk.Label(panel, text="Idle", width=8, anchor=tk.W)
        self._status_text.pack(side=tk.LEFT, padx=(2, 16))

        ttk.Label(panel, text="Queue:").pack(side=tk.LEFT)
        self._queue_var = tk.StringVar(value="0")
        ttk.Label(panel, textvariable=self._queue_var, width=5, anchor=tk.W).pack(
            side=tk.LEFT, padx=(2, 16)
        )

        ttk.Label(panel, text="Watch paths:").pack(side=tk.LEFT)
        self._watch_var = tk.StringVar(value="(none configured)")
        ttk.Label(panel, textvariable=self._watch_var, anchor=tk.W).pack(
            side=tk.LEFT, padx=(4, 0)
        )

    def _build_filter_bar(self):
        bar = ttk.LabelFrame(self, text="Search & Filter", padding=(6, 4))
        bar.pack(fill=tk.X, padx=4, pady=2)

        # Row 1: Keyword
        r1 = ttk.Frame(bar)
        r1.pack(fill=tk.X, pady=(0, 3))
        ttk.Label(r1, text="Keyword:").pack(side=tk.LEFT)
        self._kw_var = tk.StringVar()
        ttk.Entry(r1, textvariable=self._kw_var, width=60).pack(side=tk.LEFT, padx=(2, 0))

        # Row 2: Type | Subject
        r2 = ttk.Frame(bar)
        r2.pack(fill=tk.X, pady=(0, 3))
        ttk.Label(r2, text="Type:").pack(side=tk.LEFT)
        self._type_var = tk.StringVar()
        ttk.Combobox(
            r2, textvariable=self._type_var, values=["", "Re", "Fw"],
            state="readonly", width=5,
        ).pack(side=tk.LEFT, padx=(2, 12))
        ttk.Label(r2, text="Subject:").pack(side=tk.LEFT)
        self._subj_var = tk.StringVar()
        ttk.Entry(r2, textvariable=self._subj_var, width=48).pack(side=tk.LEFT, padx=(2, 0))

        # Row 3: Sender | Sent From | To
        r3 = ttk.Frame(bar)
        r3.pack(fill=tk.X, pady=(0, 3))
        ttk.Label(r3, text="Sender:").pack(side=tk.LEFT)
        self._sndr_var = tk.StringVar()
        ttk.Entry(r3, textvariable=self._sndr_var, width=30).pack(side=tk.LEFT, padx=(2, 12))
        self._sent_from_label_var = tk.StringVar(
            value=f"Sent From (YYYYMMDD, {_tz_label(self._config.timezone)}):"
        )
        ttk.Label(r3, textvariable=self._sent_from_label_var).pack(side=tk.LEFT)
        self._start_var = tk.StringVar()
        ttk.Entry(r3, textvariable=self._start_var, width=10).pack(side=tk.LEFT, padx=(2, 4))
        ttk.Label(r3, text="To:").pack(side=tk.LEFT)
        self._end_var = tk.StringVar()
        ttk.Entry(r3, textvariable=self._end_var, width=10).pack(side=tk.LEFT, padx=(2, 0))

        # Row 4: Tags (left) | Search / Clear / Export CSV / count (right)
        r4 = ttk.Frame(bar)
        r4.pack(fill=tk.X, pady=(3, 0))
        ttk.Label(r4, text="Tags:").pack(side=tk.LEFT)
        self._tags_var = tk.StringVar()
        self._tags_cb = ttk.Combobox(
            r4, textvariable=self._tags_var,
            state="readonly", width=22,
            postcommand=self._refresh_tags_dropdown,
        )
        self._tags_cb.pack(side=tk.LEFT, padx=(2, 0))
        # Pack right-side items right-to-left so visual order is Search|Clear|Export|count
        self._count_var = tk.StringVar(value="")
        ttk.Label(r4, textvariable=self._count_var, anchor=tk.E).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(r4, text="Export CSV...", command=self._export_csv).pack(side=tk.RIGHT, padx=2)
        ttk.Button(r4, text="Clear", command=self._clear_filter).pack(side=tk.RIGHT, padx=2)
        ttk.Button(r4, text="Search", command=self._search).pack(side=tk.RIGHT, padx=(0, 2))

    def _build_table(self):
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._cols = ("type", "subject", "sender", "sent_timestamp", "tags", "open", "status")
        self._tree = ttk.Treeview(frame, columns=self._cols, show="headings", selectmode="extended")

        col_cfg = {
            "type":           ("Type",           50, 40),
            "subject":        ("Subject",        220, 80),
            "sender":         ("Sender",         160, 60),
            "sent_timestamp": ("Sent Date",      130, 90),
            "tags":           ("Tags",           150, 50),
            "open":           ("Open",            60, 50),
            "status":         ("Status",          90, 60),
        }
        for col in self._cols:
            label, width, minw = col_cfg[col]
            self._tree.heading(col, text=label)
            self._tree.column(col, width=width, minwidth=minw)

        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._tree.yview)
        hsb = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")

        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self._tree.tag_configure("error", foreground="red")
        self._tree.tag_configure("duplicate", foreground="gray")
        self._tree.tag_configure("open_link", foreground="#0066CC")

        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Open File Location", command=self._open_location)
        menu.add_command(label="Edit Tags", command=self._edit_tags_selected)
        menu.add_command(label="Reprocess", command=self._reprocess)
        menu.add_separator()
        menu.add_command(label="Delete", command=self._delete_selected)
        self._ctx_menu = menu

        self._tree.bind("<ButtonRelease-1>", self._on_cell_click)
        self._tree.bind("<Button-3>", self._show_ctx)
        self._tree.bind("<Delete>", lambda e: self._delete_selected())

        self.refresh()

    # ------------------------------------------------------------------ data

    def set_bundle(self, bundle, db):
        self._bundle = bundle
        self._db = db
        self.refresh()

    def refresh(self):
        """Reload the view: re-runs the active search if one is set, else shows last 100."""
        if self._db is None:
            self._tree.delete(*self._tree.get_children())
            self._results = []
            self._count_var.set("No archive mounted.")
            return
        if self._searching:
            self._search()
            return
        rows = self._db.recent(100)
        self._populate(rows)
        self._count_var.set(f"Showing last {len(rows)} entries")

    def _search(self):
        self._searching = True
        tz = self._config.timezone
        rows = self._db.search(
            keyword=self._kw_var.get().strip(),
            mail_type=self._type_var.get().strip(),
            subject=self._subj_var.get().strip(),
            sender=self._sndr_var.get().strip(),
            tags=self._tags_var.get().strip(),
            start_date=_local_date_to_utc(self._start_var.get().strip(), tz, end_of_day=False),
            end_date=_local_date_to_utc(self._end_var.get().strip(), tz, end_of_day=True),
            limit=500,
        )
        self._populate(rows)
        self._count_var.set(f"{len(rows)} result(s) found")

    def _clear_filter(self):
        self._searching = False
        self._kw_var.set("")
        self._type_var.set("")
        self._subj_var.set("")
        self._sndr_var.set("")
        self._tags_var.set("")
        self._start_var.set("")
        self._end_var.set("")
        self.refresh()

    def _refresh_tags_dropdown(self):
        """Refresh the Tags combobox values from the database just before it opens."""
        self._tags_cb.configure(values=[""] + self._db.get_all_tags())

    def _populate(self, rows: List[dict]):
        selected = set(self._tree.selection())
        self._results = rows
        self._tree.delete(*self._tree.get_children())
        for row in rows:
            orig = row["subject"] or ""
            self._tree.insert(
                "",
                tk.END,
                iid=str(row["id"]),
                values=(
                    _detect_mail_type(orig),
                    strip_subject_prefixes(orig),
                    row["sender"] or "",
                    self._fmt_ts(row["sent_timestamp"]),
                    row.get("tags") or "",
                    "Open ↗",
                    row["status"],
                ),
                tags=(row["status"],),
            )
        to_restore = [s for s in selected if self._tree.exists(s)]
        if to_restore:
            self._tree.selection_set(to_restore)

    # ------------------------------------------------------------------ public setters (called by App)

    def set_status(self, text: str, color: str):
        self._status_text.config(text=text)
        self._status_dot.config(fg=color)

    def set_queue(self, count: int):
        self._queue_var.set(str(count))

    def set_watch_paths(self, paths: List[str]):
        if paths:
            display = "  |  ".join(paths[:2])
            if len(paths) > 2:
                display += f"  (+{len(paths) - 2} more)"
            self._watch_var.set(display)
        else:
            self._watch_var.set("(none configured)")

    # ------------------------------------------------------------------ table actions

    def _on_cell_click(self, event):
        region = self._tree.identify_region(event.x, event.y)
        if region != "cell":
            return
        col_idx = int(self._tree.identify_column(event.x).lstrip("#")) - 1
        if col_idx >= len(self._cols):
            return
        col_name = self._cols[col_idx]
        item = self._tree.identify_row(event.y)
        if not item:
            return
        row = next((r for r in self._results if r["id"] == int(item)), None)
        if not row:
            return
        if col_name == "open":
            self._open_file(row)
        elif col_name == "tags":
            self._edit_tags(row)

    def _open_file(self, row: dict):
        if not self._bundle:
            return
        p = self._bundle.resolve(row["stored_path"])
        if p.exists():
            os.startfile(p)
        else:
            messagebox.showerror("File Not Found", f"Cannot find:\n{p}")

    def _edit_tags(self, row: dict):
        current = row.get("tags") or ""
        subject = row.get("subject") or "(no subject)"
        all_tags = self._db.get_all_tags()
        dlg = _TagEditDialog(self, current, all_tags, subject)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        self._db.update_tags(row["id"], dlg.result)
        row["tags"] = dlg.result.strip()
        self._tree.set(str(row["id"]), "tags", row["tags"])

    def _edit_tags_selected(self):
        """Edit tags for all currently selected rows (single or multi)."""
        sel = self._tree.selection()
        if not sel:
            return
        if len(sel) == 1:
            row = next((r for r in self._results if str(r["id"]) == sel[0]), None)
            if row:
                self._edit_tags(row)
        else:
            self._bulk_edit_tags(sel)

    def _bulk_edit_tags(self, sel: tuple):
        sel_set = set(sel)
        rows = [r for r in self._results if str(r["id"]) in sel_set]
        if not rows:
            return
        unique_tags = {(r.get("tags") or "") for r in rows}
        initial = list(unique_tags)[0] if len(unique_tags) == 1 else ""
        count = len(rows)
        if len(unique_tags) > 1:
            label = f"Edit tags for {count} selected items\n(tags differ — will replace all)"
        else:
            label = f"Edit tags for {count} selected items"
        dlg = _TagEditDialog(self, initial, self._db.get_all_tags(), label)
        self.wait_window(dlg)
        if dlg.result is None:
            return
        new_tags = dlg.result.strip()
        for row in rows:
            self._db.update_tags(row["id"], dlg.result)
            row["tags"] = new_tags
            self._tree.set(str(row["id"]), "tags", new_tags)

    def _delete_selected(self):
        sel = self._tree.selection()
        if not sel:
            return
        sel_ids = {int(s) for s in sel}
        rows = [r for r in self._results if r["id"] in sel_ids]
        if not rows:
            return
        count = len(rows)
        if not messagebox.askyesno(
            "Confirm Delete",
            f"Permanently delete {count} file(s) from disk and remove from the database?\n\nThis cannot be undone.",
            icon="warning",
        ):
            return
        errors: list[str] = []
        deleted_ids: list[int] = []
        for row in rows:
            p = self._bundle.resolve(row["stored_path"]) if self._bundle else pathlib.Path(row["stored_path"])
            try:
                if p.exists():
                    p.unlink()
            except OSError as e:
                errors.append(f"{p.name}: {e}")
                continue
            deleted_ids.append(row["id"])
        if deleted_ids:
            self._db.delete(deleted_ids)
            deleted_set = set(deleted_ids)
            self._results = [r for r in self._results if r["id"] not in deleted_set]
            for row_id in deleted_ids:
                self._tree.delete(str(row_id))
            self._count_var.set(f"Showing {len(self._results)} entries")
        if errors:
            messagebox.showerror(
                "Delete Errors",
                "Some files could not be deleted:\n\n" + "\n".join(errors),
            )

    def _show_ctx(self, event):
        item = self._tree.identify_row(event.y)
        if item:
            # Preserve multi-selection when right-clicking an already-selected row
            if item not in self._tree.selection():
                self._tree.selection_set(item)
            self._ctx_menu.post(event.x_root, event.y_root)

    def _open_location(self):
        sel = self._tree.selection()
        if not sel:
            return
        row_id = int(sel[0])
        row = next((r for r in self._results if r["id"] == row_id), None)
        if not row:
            return
        if not self._bundle:
            return
        p = self._bundle.resolve(row["stored_path"]).resolve()
        if p.exists():
            # shell=True + quoted path is required for paths containing spaces
            subprocess.run(f'explorer /select,"{p}"', shell=True, check=False)
        elif p.parent.exists():
            os.startfile(str(p.parent))
        else:
            messagebox.showerror("Folder Not Found", f"Cannot find:\n{p.parent}")

    def _reprocess(self):
        messagebox.showinfo("Reprocess", "Reprocess is not implemented in this prototype.")

    def _export_csv(self):
        if not self._results:
            messagebox.showinfo("Export", "No data to export. Run a search or wait for entries.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            title="Export to CSV",
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self._results[0].keys())
            writer.writeheader()
            writer.writerows(self._results)
        messagebox.showinfo("Export", f"Exported {len(self._results)} row(s) to:\n{path}")
