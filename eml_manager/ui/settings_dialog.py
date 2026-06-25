import copy
import pathlib
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

_TIMEZONES = [
    "UTC",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    "America/Toronto",
    "America/Vancouver",
    "America/Sao_Paulo",
    "America/Argentina/Buenos_Aires",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Rome",
    "Europe/Amsterdam",
    "Europe/Madrid",
    "Europe/Stockholm",
    "Europe/Moscow",
    "Africa/Cairo",
    "Africa/Johannesburg",
    "Africa/Lagos",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Dhaka",
    "Asia/Bangkok",
    "Asia/Singapore",
    "Asia/Shanghai",
    "Asia/Hong_Kong",
    "Asia/Taipei",
    "Asia/Seoul",
    "Asia/Tokyo",
    "Australia/Perth",
    "Australia/Adelaide",
    "Australia/Sydney",
    "Australia/Melbourne",
    "Pacific/Auckland",
    "Pacific/Fiji",
]

from ..config import Config


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, config: Config):
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self._cfg = copy.deepcopy(config)
        self.result: Optional[Config] = None
        self._build()
        self.transient(parent)
        self.grab_set()
        self.update_idletasks()
        w = self.winfo_reqwidth()
        h = self.winfo_reqheight()
        x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def _build(self):
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        paths_tab = ttk.Frame(nb, padding=8)
        nb.add(paths_tab, text="Paths")
        self._build_paths_tab(paths_tab)

        proc_tab = ttk.Frame(nb, padding=8)
        nb.add(proc_tab, text="Processing")
        self._build_processing_tab(proc_tab)

        sys_tab = ttk.Frame(nb, padding=8)
        nb.add(sys_tab, text="System & Logging")
        self._build_system_tab(sys_tab)

        btns = ttk.Frame(self)
        btns.pack(fill=tk.X, padx=8, pady=(0, 8))
        ttk.Button(btns, text="Save", command=self._save).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btns, text="Export Settings…", command=self._export_settings).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(btns, text="Import Settings…", command=self._import_settings).pack(
            side=tk.LEFT, padx=2
        )

    # --- tab builders ---

    def _build_paths_tab(self, tab):
        ttk.Label(tab, text="Watch Paths:").grid(row=0, column=0, columnspan=2, sticky=tk.W)

        # tk.Listbox has no ttk equivalent.
        self._watch_lb = tk.Listbox(tab, height=5, width=52)
        self._watch_lb.grid(row=1, column=0, pady=2, sticky=tk.W)
        for p in self._cfg.watch_paths:
            self._watch_lb.insert(tk.END, p)

        btn_col = ttk.Frame(tab)
        btn_col.grid(row=1, column=1, padx=4, sticky=tk.N)
        ttk.Button(btn_col, text="Add...", command=self._add_watch).pack(fill=tk.X)
        ttk.Button(btn_col, text="Remove", command=self._remove_watch).pack(fill=tk.X, pady=2)

        ttk.Label(tab, text="Archive Root:").grid(
            row=2, column=0, columnspan=2, sticky=tk.W, pady=(8, 0)
        )
        self._archive_var = tk.StringVar(value=self._cfg.archive_root)
        row_frame = ttk.Frame(tab)
        row_frame.grid(row=3, column=0, columnspan=2, sticky=tk.W)
        ttk.Entry(row_frame, textvariable=self._archive_var, width=44).pack(side=tk.LEFT)
        ttk.Button(row_frame, text="...", width=3, command=self._browse_archive).pack(
            side=tk.LEFT, padx=2
        )

        ttk.Label(tab, text="Duplicates Folder Name:").grid(
            row=4, column=0, columnspan=2, sticky=tk.W, pady=(8, 0)
        )
        self._dup_var = tk.StringVar(value=self._cfg.duplicates_folder)
        ttk.Entry(tab, textvariable=self._dup_var, width=24).grid(
            row=5, column=0, sticky=tk.W
        )

    def _build_processing_tab(self, tab):
        ttk.Label(tab, text="Dedupe Policy:").grid(row=0, column=0, sticky=tk.W)
        self._dedupe_var = tk.StringVar(value=self._cfg.dedupe_policy)
        _options = ["message_id,sha256", "sha256", "message_id"]
        ttk.Combobox(
            tab, textvariable=self._dedupe_var, values=_options, state="readonly", width=20
        ).grid(row=1, column=0, sticky=tk.W, pady=(0, 8))

        ttk.Label(tab, text="Filename Length Limit:").grid(row=2, column=0, sticky=tk.W)
        self._limit_var = tk.IntVar(value=self._cfg.filename_limit)
        ttk.Spinbox(tab, textvariable=self._limit_var, from_=50, to=500, width=8).grid(
            row=3, column=0, sticky=tk.W
        )

    def _build_system_tab(self, tab):
        ttk.Label(tab, text="Timezone:").grid(row=0, column=0, sticky=tk.W, pady=(4, 0))
        self._tz_var = tk.StringVar(value=self._cfg.timezone)
        ttk.Combobox(
            tab, textvariable=self._tz_var, values=_TIMEZONES, width=32
        ).grid(row=1, column=0, sticky=tk.W)

        ttk.Label(tab, text="Stable Check (seconds):").grid(
            row=2, column=0, sticky=tk.W, pady=(8, 0)
        )
        self._stable_var = tk.StringVar(value=str(self._cfg.stable_check_seconds))
        ttk.Spinbox(
            tab, textvariable=self._stable_var, from_=0.5, to=30.0, increment=0.5, width=8
        ).grid(row=3, column=0, sticky=tk.W)

        ttk.Label(tab, text="Retry Count:").grid(row=4, column=0, sticky=tk.W, pady=(8, 0))
        self._retry_var = tk.IntVar(value=self._cfg.retry_count)
        ttk.Spinbox(tab, textvariable=self._retry_var, from_=0, to=10, width=8).grid(
            row=5, column=0, sticky=tk.W
        )

        ttk.Label(tab, text="Log Level:").grid(row=6, column=0, sticky=tk.W, pady=(8, 0))
        self._log_level_var = tk.StringVar(value=self._cfg.log_level)
        ttk.Combobox(
            tab,
            textvariable=self._log_level_var,
            values=["DEBUG", "INFO", "WARNING", "ERROR"],
            state="readonly",
            width=10,
        ).grid(row=7, column=0, sticky=tk.W)

    # --- settings export / import ---

    def _export_settings(self):
        out_path = filedialog.asksaveasfilename(
            defaultextension=".yml",
            filetypes=[("YAML files", "*.yml"), ("All files", "*.*")],
            initialfile="eml_manager_settings.yml",
            title="Export Settings",
        )
        if not out_path:
            return
        try:
            # Strip machine-specific paths so the file is portable
            from ..config import Config
            export_cfg = copy.deepcopy(self._cfg)
            defaults = Config()
            export_cfg.db_path = defaults.db_path
            export_cfg.log_path = defaults.log_path
            export_cfg.save(pathlib.Path(out_path))
            messagebox.showinfo("Export Settings", f"Settings exported to:\n{out_path}")
        except Exception as exc:
            messagebox.showerror("Export Settings", f"Export failed:\n{exc}")

    def _import_settings(self):
        in_path = filedialog.askopenfilename(
            filetypes=[("YAML files", "*.yml *.yaml"), ("All files", "*.*")],
            title="Import Settings",
        )
        if not in_path:
            return
        try:
            from ..config import Config
            loaded = Config.load(pathlib.Path(in_path))
            # Preserve machine-specific paths from the current running config
            loaded.db_path = self._cfg.db_path
            loaded.log_path = self._cfg.log_path
            self._cfg = loaded
            self._apply_cfg_to_fields()
            messagebox.showinfo(
                "Import Settings",
                "Settings loaded. Review and click Save to apply.",
            )
        except Exception as exc:
            messagebox.showerror("Import Settings", f"Import failed:\n{exc}")

    def _apply_cfg_to_fields(self):
        self._watch_lb.delete(0, tk.END)
        for p in self._cfg.watch_paths:
            self._watch_lb.insert(tk.END, p)
        self._archive_var.set(self._cfg.archive_root)
        self._dup_var.set(self._cfg.duplicates_folder)
        self._dedupe_var.set(self._cfg.dedupe_policy)
        self._limit_var.set(self._cfg.filename_limit)
        self._tz_var.set(self._cfg.timezone)
        self._stable_var.set(str(self._cfg.stable_check_seconds))
        self._retry_var.set(self._cfg.retry_count)
        self._log_level_var.set(self._cfg.log_level)

    # --- helpers ---

    def _add_watch(self):
        path = filedialog.askdirectory(title="Select Watch Directory")
        if path:
            self._watch_lb.insert(tk.END, path)

    def _remove_watch(self):
        sel = self._watch_lb.curselection()
        if sel:
            self._watch_lb.delete(sel[0])

    def _browse_archive(self):
        path = filedialog.askdirectory(title="Select Archive Root")
        if path:
            self._archive_var.set(path)

    def _save(self):
        self._cfg.watch_paths = list(self._watch_lb.get(0, tk.END))
        self._cfg.archive_root = self._archive_var.get()
        self._cfg.duplicates_folder = self._dup_var.get()
        self._cfg.dedupe_policy = self._dedupe_var.get()
        self._cfg.filename_limit = int(self._limit_var.get())
        self._cfg.timezone = self._tz_var.get()
        try:
            self._cfg.stable_check_seconds = float(self._stable_var.get())
        except ValueError:
            pass
        try:
            self._cfg.retry_count = int(self._retry_var.get())
        except ValueError:
            pass
        self._cfg.log_level = self._log_level_var.get()
        self.result = self._cfg
        self.destroy()
