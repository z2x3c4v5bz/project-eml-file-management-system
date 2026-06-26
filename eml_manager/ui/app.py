import datetime
import logging
import pathlib
import queue
import threading
import tkinter as tk
import zipfile
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Optional

from tkinterdnd2 import DND_FILES, TkinterDnD

from ..bundle import Bundle, MARKER_FILENAME
from ..config import Config
from ..database import Database
from ..monitor import Monitor
from ..processor import Processor
from .main_view import MainView
from .settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)

_STATUS_COLORS = {"Running": "green", "Idle": "orange", "Stopped": "red"}


class App(TkinterDnD.Tk):
    def __init__(self, config: Config, config_path: pathlib.Path):
        super().__init__()

        self._config = config
        self._config_path = config_path

        self._file_queue: queue.Queue = queue.Queue()
        self._bundle: Optional[Bundle] = None
        self._db: Optional[Database] = None
        self._processor: Optional[Processor] = None
        self._monitor: Optional[Monitor] = None
        self._worker: Optional[threading.Thread] = None
        self._running = False

        self.title("EML File Manager")
        self.minsize(800, 500)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self.drop_target_register(DND_FILES)
        self.dnd_bind("<<Drop>>", self._on_drop)
        self._tick()
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"1100x700+{(sw - 1100) // 2}+{(sh - 700) // 2}")

        self._update_controls()

        if self._config.active_bundle:
            p = pathlib.Path(self._config.active_bundle)
            if p.exists():
                self._mount_bundle(p)

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        self._build_toolbar()
        self._build_main_view()
        self._build_log_panel()

    def _build_toolbar(self):
        bar = ttk.Frame(self, relief=tk.GROOVE)
        bar.pack(fill=tk.X, padx=4, pady=4)

        ttk.Button(bar, text="New Archive…", command=self._new_bundle).pack(
            side=tk.LEFT, padx=2, pady=2
        )
        ttk.Button(bar, text="Open Archive…", command=self._open_bundle).pack(
            side=tk.LEFT, padx=2, pady=2
        )
        self._btn_eject = ttk.Button(
            bar, text="Eject", command=self._eject_bundle, state=tk.DISABLED
        )
        self._btn_eject.pack(side=tk.LEFT, padx=2, pady=2)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=4)

        self._btn_start = ttk.Button(
            bar, text="Start Monitoring", command=self._start_monitoring
        )
        self._btn_start.pack(side=tk.LEFT, padx=2, pady=2)

        self._btn_stop = ttk.Button(
            bar, text="Stop Monitoring", command=self._stop_monitoring, state=tk.DISABLED
        )
        self._btn_stop.pack(side=tk.LEFT, padx=2, pady=2)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=4)

        self._btn_scan = ttk.Button(bar, text="Manual Scan…", command=self._manual_scan)
        self._btn_scan.pack(side=tk.LEFT, padx=2, pady=2)
        ttk.Button(bar, text="Settings", command=self._open_settings).pack(
            side=tk.LEFT, padx=2, pady=2
        )

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=4)

        self._btn_export = ttk.Button(
            bar, text="Export Archive…", command=self._export_archive
        )
        self._btn_export.pack(side=tk.LEFT, padx=2, pady=2)
        ttk.Button(bar, text="Import Archive…", command=self._import_archive).pack(
            side=tk.LEFT, padx=2, pady=2
        )

    def _build_main_view(self):
        self._main = MainView(self, self._db, self._config, self._bundle)
        self._main.pack(fill=tk.BOTH, expand=True)
        self._main.set_watch_paths(self._config.watch_paths)

    def _build_log_panel(self):
        frame = ttk.LabelFrame(self, text="Log", padding=2)
        frame.pack(fill=tk.X, padx=4, pady=(0, 4))

        self._log_text = tk.Text(frame, height=4, state=tk.DISABLED, font=("Courier", 9))
        sb = ttk.Scrollbar(frame, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=sb.set)
        self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        logging.getLogger().addHandler(_WidgetLogHandler(self._log_text))

    # ------------------------------------------------------------------ bundle mount / eject

    def _new_bundle(self):
        parent = filedialog.askdirectory(title="Select folder to create the archive in")
        if not parent:
            return
        name = simpledialog.askstring("New Archive", "Name for the new archive:", parent=self)
        if not name:
            return
        dest = pathlib.Path(parent) / name
        if dest.exists() and any(dest.iterdir()):
            if not messagebox.askyesno(
                "New Archive",
                f"Folder already exists:\n{dest}\n\nUse it as an archive anyway?",
                icon="warning",
            ):
                return
        try:
            Bundle.create(dest)
        except Exception as exc:
            messagebox.showerror("New Archive", f"Could not create archive:\n{exc}")
            return
        self._mount_bundle(dest)

    def _open_bundle(self):
        path = filedialog.askdirectory(title="Open Archive Folder")
        if not path:
            return
        self._mount_bundle(pathlib.Path(path))

    def _mount_bundle(self, path: pathlib.Path):
        bundle = Bundle(path)
        if not bundle.is_valid():
            messagebox.showerror(
                "Open Archive",
                f"Not a valid archive:\n{path}\n\nMissing {MARKER_FILENAME} marker.",
            )
            return
        if self._running:
            self._stop_monitoring()
        self._bundle = bundle
        self._db = Database(bundle.db_path, str(bundle.emails_root))
        self._processor = Processor(self._config, self._db, bundle)
        self.title(f"EML File Manager — {bundle.name}")
        self._main.set_bundle(bundle, self._db)
        self._main.refresh()
        self._config.active_bundle = str(path)
        recent = [str(path)] + [r for r in self._config.recent_archives if r != str(path)]
        self._config.recent_archives = recent[:10]
        self._config.save(self._config_path)
        self._update_controls()

    def _eject_bundle(self):
        if self._running:
            self._stop_monitoring()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=2.0)
        if self._db and hasattr(self._db._local, "conn"):
            self._db._local.conn.close()
        self._bundle = None
        self._db = None
        self._processor = None
        self.title("EML File Manager")
        self._config.active_bundle = ""
        self._config.save(self._config_path)
        self._main.set_bundle(None, None)
        self._update_controls()

    def _update_controls(self):
        has_bundle = bool(self._bundle)
        state = tk.NORMAL if has_bundle else tk.DISABLED
        self._btn_eject.config(state=state)
        self._btn_export.config(state=state)
        self._btn_scan.config(state=state)
        if not has_bundle:
            self._btn_start.config(state=tk.DISABLED)
            self._btn_stop.config(state=tk.DISABLED)
        elif not self._running:
            self._btn_start.config(state=tk.NORMAL)
            self._btn_stop.config(state=tk.DISABLED)

    # ------------------------------------------------------------------ monitoring

    def _start_monitoring(self):
        if not self._bundle:
            return
        if not self._config.watch_paths:
            messagebox.showwarning(
                "No Watch Paths",
                "Please configure at least one watch path in Settings before starting.",
            )
            return

        self._monitor = Monitor(self._config.watch_paths, self._file_queue)
        self._monitor.start()
        self._running = True
        self._worker = threading.Thread(
            target=self._worker_loop, daemon=True, name="eml-worker"
        )
        self._worker.start()

        self._btn_start.config(state=tk.DISABLED)
        self._btn_stop.config(state=tk.NORMAL)
        self._set_status("Running")

    def _stop_monitoring(self):
        self._running = False
        if self._monitor:
            self._monitor.stop()
        self._btn_start.config(state=tk.NORMAL if self._bundle else tk.DISABLED)
        self._btn_stop.config(state=tk.DISABLED)
        self._set_status("Idle")

    def _manual_scan(self):
        if not self._bundle:
            return
        path = filedialog.askdirectory(title="Select Directory to Scan")
        if not path:
            return
        if self._monitor is None:
            self._monitor = Monitor([], self._file_queue)
        count = self._monitor.scan_directory(pathlib.Path(path), recursive=True)
        if count and not self._running:
            self._running = True
            self._worker = threading.Thread(
                target=self._worker_loop, daemon=True, name="eml-worker"
            )
            self._worker.start()
        messagebox.showinfo("Manual Scan", f"Enqueued {count} file(s) for processing.")

    def _open_settings(self):
        dlg = SettingsDialog(self, self._config)
        self.wait_window(dlg)
        if dlg.result:
            self._config = dlg.result
            self._config.save(self._config_path)
            if self._processor:
                self._processor.config = self._config
            self._main.set_watch_paths(self._config.watch_paths)
            self._main.update_config(self._config)

    # ------------------------------------------------------------------ archive export / import

    def _export_archive(self):
        if not self._bundle:
            messagebox.showwarning("Export Archive", "No archive is mounted.")
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = filedialog.asksaveasfilename(
            defaultextension=".zip",
            filetypes=[("ZIP archive", "*.zip"), ("All files", "*.*")],
            initialfile=f"{self._bundle.name}_{ts}.zip",
            title="Export Archive",
        )
        if not out_path:
            return
        try:
            self.config(cursor="watch")
            self.update()
            file_count = 0
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for src in self._bundle.path.rglob("*"):
                    if src.is_file():
                        zf.write(src, src.relative_to(self._bundle.path))
                        file_count += 1
            messagebox.showinfo("Export Archive", f"Exported {file_count} file(s) to:\n{out_path}")
        except Exception as exc:
            messagebox.showerror("Export Archive", f"Export failed:\n{exc}")
        finally:
            self.config(cursor="")

    def _import_archive(self):
        in_path = filedialog.askopenfilename(
            filetypes=[("ZIP archive", "*.zip"), ("All files", "*.*")],
            title="Import Archive",
        )
        if not in_path:
            return
        try:
            with zipfile.ZipFile(in_path, "r") as zf:
                if MARKER_FILENAME not in zf.namelist():
                    messagebox.showerror(
                        "Import Archive",
                        f"Not a valid archive bundle — missing {MARKER_FILENAME}.",
                    )
                    return
        except zipfile.BadZipFile:
            messagebox.showerror("Import Archive", "Not a valid ZIP file.")
            return
        except Exception as exc:
            messagebox.showerror("Import Archive", f"Failed to read archive:\n{exc}")
            return

        parent_dir = filedialog.askdirectory(title="Select folder to extract archive into")
        if not parent_dir:
            return
        default_name = pathlib.Path(in_path).stem
        bundle_name = simpledialog.askstring(
            "Import Archive", "Name for the imported archive:", initialvalue=default_name, parent=self
        )
        if not bundle_name:
            return
        dest = pathlib.Path(parent_dir) / bundle_name
        if dest.exists() and any(dest.iterdir()):
            if not messagebox.askyesno(
                "Import Archive",
                f"Folder already exists:\n{dest}\n\nExtract into it anyway?",
                icon="warning",
            ):
                return
        try:
            self.config(cursor="watch")
            self.update()
            dest.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(in_path, "r") as zf:
                zf.extractall(dest)
            self._mount_bundle(dest)
        except Exception as exc:
            messagebox.showerror("Import Archive", f"Import failed:\n{exc}")
        finally:
            self.config(cursor="")

    # ------------------------------------------------------------------ drag-and-drop

    def _on_drop(self, event):
        if not self._bundle:
            logger.warning("Drop ignored — no archive is mounted.")
            return
        paths = self.tk.splitlist(event.data)
        eml_files = [
            pathlib.Path(p)
            for p in paths
            if p.lower().endswith(".eml") and pathlib.Path(p).is_file()
        ]
        if not eml_files:
            return
        for path in eml_files:
            self._file_queue.put(path)
        # Start a one-shot worker if none is alive; a running monitoring worker
        # will pick up the queued files automatically.
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(
                target=self._worker_loop, daemon=True, name="eml-worker"
            )
            self._worker.start()
        logger.info("Queued %d dropped .eml file(s) for processing.", len(eml_files))

    # ------------------------------------------------------------------ worker

    def _worker_loop(self):
        while self._running or not self._file_queue.empty():
            try:
                file_path = self._file_queue.get(timeout=1.0)
                if self._processor:
                    self._processor.process(file_path)
                self._file_queue.task_done()
            except queue.Empty:
                pass
            except Exception as exc:
                logger.error("Worker error: %s", exc, exc_info=True)

    # ------------------------------------------------------------------ tick

    def _tick(self):
        self._main.set_queue(self._file_queue.qsize())
        self._main.refresh()
        self.after(2000, self._tick)

    def _set_status(self, text: str):
        color = _STATUS_COLORS.get(text, "black")
        self._main.set_status(text, color)

    def _on_close(self):
        self._stop_monitoring()
        self.destroy()


class _WidgetLogHandler(logging.Handler):
    def __init__(self, widget: tk.Text):
        super().__init__(level=logging.WARNING)
        self._w = widget
        self.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
        )

    def emit(self, record):
        msg = self.format(record) + "\n"

        def _append():
            self._w.configure(state=tk.NORMAL)
            self._w.insert(tk.END, msg)
            self._w.see(tk.END)
            self._w.configure(state=tk.DISABLED)

        self._w.after(0, _append)
