import logging
import pathlib
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from ..config import Config
from ..database import Database
from ..monitor import Monitor
from ..processor import Processor
from .main_view import MainView
from .settings_dialog import SettingsDialog

logger = logging.getLogger(__name__)

_STATUS_COLORS = {"Running": "green", "Idle": "orange", "Stopped": "red"}


class App(tk.Tk):
    def __init__(self, config: Config, config_path: pathlib.Path):
        super().__init__()

        self._config = config
        self._config_path = config_path

        self._file_queue: queue.Queue = queue.Queue()
        self._db = Database(config.db_path)
        self._processor = Processor(config, self._db)
        self._monitor: Optional[Monitor] = None
        self._worker: Optional[threading.Thread] = None
        self._running = False

        self.title("EML File Manager")
        self.minsize(800, 500)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._tick()
        self.update_idletasks()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry(f"1100x700+{(sw - 1100) // 2}+{(sh - 700) // 2}")

    # ------------------------------------------------------------------ build

    def _build_ui(self):
        self._build_toolbar()
        self._build_main_view()
        self._build_log_panel()

    def _build_toolbar(self):
        bar = ttk.Frame(self, relief=tk.GROOVE)
        bar.pack(fill=tk.X, padx=4, pady=4)

        self._btn_start = ttk.Button(
            bar, text="Start Monitoring", command=self._start_monitoring
        )
        self._btn_start.pack(side=tk.LEFT, padx=2, pady=2)

        self._btn_stop = ttk.Button(
            bar, text="Stop Monitoring", command=self._stop_monitoring, state=tk.DISABLED
        )
        self._btn_stop.pack(side=tk.LEFT, padx=2, pady=2)

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=4)

        ttk.Button(bar, text="Manual Scan...", command=self._manual_scan).pack(
            side=tk.LEFT, padx=2, pady=2
        )
        ttk.Button(bar, text="Settings", command=self._open_settings).pack(
            side=tk.LEFT, padx=2, pady=2
        )

    def _build_main_view(self):
        self._main = MainView(self, self._db, self._config)
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

    # ------------------------------------------------------------------ monitoring

    def _start_monitoring(self):
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
        self._btn_start.config(state=tk.NORMAL)
        self._btn_stop.config(state=tk.DISABLED)
        self._set_status("Idle")

    def _manual_scan(self):
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
            self._processor.config = self._config
            self._main.set_watch_paths(self._config.watch_paths)

    # ------------------------------------------------------------------ worker

    def _worker_loop(self):
        while self._running or not self._file_queue.empty():
            try:
                file_path = self._file_queue.get(timeout=1.0)
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
