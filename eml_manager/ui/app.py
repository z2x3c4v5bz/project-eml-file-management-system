import datetime
import json
import logging
import pathlib
import queue
import shutil
import subprocess
import tempfile
import threading
import tkinter as tk
import zipfile
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

        ttk.Separator(bar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=4)

        ttk.Button(bar, text="Export Archive…", command=self._export_archive).pack(
            side=tk.LEFT, padx=2, pady=2
        )
        ttk.Button(bar, text="Import Archive…", command=self._import_archive).pack(
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

    # ------------------------------------------------------------------ archive export / import

    def _export_archive(self):
        archive_root = pathlib.Path(self._config.archive_root)
        if not archive_root.exists():
            messagebox.showerror(
                "Export Archive",
                f"Archive root does not exist:\n{archive_root}\n\n"
                "Configure a valid Archive Root in Settings first.",
            )
            return

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = filedialog.asksaveasfilename(
            defaultextension=".zip",
            filetypes=[("ZIP archive", "*.zip"), ("All files", "*.*")],
            initialfile=f"eml_backup_{ts}.zip",
            title="Export Archive",
        )
        if not out_path:
            return

        try:
            self.config(cursor="watch")
            self.update()
            manifest = {
                "version": 1,
                "archive_root": str(archive_root),
                "exported_at": datetime.datetime.utcnow().isoformat(),
            }
            file_count = 0
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
                zf.write(self._db._path, "database.db")
                for src in archive_root.rglob("*"):
                    if src.is_file():
                        zf.write(src, f"files/{src.relative_to(archive_root)}")
                        file_count += 1
            messagebox.showinfo(
                "Export Archive",
                f"Exported {file_count} file(s) to:\n{out_path}",
            )
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

        # Validate before asking the user to confirm
        try:
            with zipfile.ZipFile(in_path, "r") as zf:
                names = zf.namelist()
                if "manifest.json" not in names:
                    messagebox.showerror("Import Archive", "Invalid archive: missing manifest.json")
                    return
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                if manifest.get("version") != 1:
                    messagebox.showerror(
                        "Import Archive",
                        f"Unsupported archive version: {manifest.get('version')}",
                    )
                    return
                if "database.db" not in names:
                    messagebox.showerror("Import Archive", "Invalid archive: missing database.db")
                    return
        except zipfile.BadZipFile:
            messagebox.showerror("Import Archive", "The selected file is not a valid ZIP archive.")
            return
        except Exception as exc:
            messagebox.showerror("Import Archive", f"Failed to read archive:\n{exc}")
            return

        old_root = manifest.get("archive_root", "")
        exported_at = manifest.get("exported_at", "unknown")

        if not messagebox.askyesno(
            "Import Archive — Replace All Data",
            f"This will REPLACE your current database and archived emails.\n\n"
            f"Backup archive root: {old_root}\n"
            f"Exported at:         {exported_at}\n\n"
            f"Emails currently in the app but not in this backup will no longer appear "
            f"(files on disk are not deleted).\n\n"
            f"This cannot be undone. Continue?",
            icon="warning",
        ):
            return

        new_root = filedialog.askdirectory(
            title="Select destination folder for archived emails",
            initialdir=self._config.archive_root,
        )
        if not new_root:
            return
        new_root_path = pathlib.Path(new_root)

        was_running = self._running
        if was_running:
            self._stop_monitoring()

        try:
            self.config(cursor="watch")
            self.update()

            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = pathlib.Path(tmp)

                with zipfile.ZipFile(in_path, "r") as zf:
                    zf.extract("database.db", tmp_path)
                    file_count = 0
                    prefix = "files/"
                    for entry in zf.infolist():
                        name = entry.filename
                        if name.startswith(prefix) and not entry.is_dir():
                            dest = new_root_path / name[len(prefix):]
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            dest.write_bytes(zf.read(name))
                            file_count += 1

                # Rewrite stored_path values in the extracted DB, then swap it in
                tmp_db_path = str(tmp_path / "database.db")
                tmp_db = Database(tmp_db_path)
                updated = tmp_db.rewrite_paths(old_root, str(new_root_path))
                if hasattr(tmp_db._local, "conn"):
                    tmp_db._local.conn.close()

                self._db.replace_file_and_reinit(tmp_db_path)

            # Update config archive_root if the destination differs
            if new_root_path.resolve() != pathlib.Path(self._config.archive_root).resolve():
                self._config.archive_root = str(new_root_path)
                self._config.save(self._config_path)
                self._processor.config = self._config

            self._main.set_watch_paths(self._config.watch_paths)
            self._main.refresh()

            all_rows = self._db.search(limit=100_000)
            orphans = sum(
                1 for r in all_rows if not pathlib.Path(r["stored_path"]).exists()
            )
            msg = (
                f"Import complete.\n"
                f"{file_count} file(s) extracted, {updated} record(s) updated."
            )
            if orphans:
                msg += f"\n\nWarning: {orphans} record(s) point to missing files."
            messagebox.showinfo("Import Archive", msg)

        except Exception as exc:
            messagebox.showerror("Import Archive", f"Import failed:\n{exc}")
        finally:
            self.config(cursor="")

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
