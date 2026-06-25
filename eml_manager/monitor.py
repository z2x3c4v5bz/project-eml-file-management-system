import logging
import pathlib
import queue
from typing import List

logger = logging.getLogger(__name__)

try:
    from watchdog.events import FileCreatedEvent, FileMovedEvent, FileSystemEventHandler
    from watchdog.observers import Observer

    _WATCHDOG = True
except ImportError:
    _WATCHDOG = False
    logger.warning("watchdog not installed; directory monitoring unavailable")


if _WATCHDOG:

    class _EmlHandler(FileSystemEventHandler):
        def __init__(self, q: queue.Queue):
            self._q = q

        def _enqueue(self, path: str):
            p = pathlib.Path(path)
            if p.suffix.lower() == ".eml" and not p.name.startswith("."):
                logger.debug("Enqueuing: %s", p)
                self._q.put(p)

        def on_created(self, event):
            if not event.is_directory:
                self._enqueue(event.src_path)

        def on_moved(self, event):
            if not event.is_directory:
                self._enqueue(event.dest_path)


class Monitor:
    """Watches one or more directories for new .eml files."""

    def __init__(self, watch_paths: List[str], file_queue: queue.Queue, recursive: bool = False):
        self._paths = [pathlib.Path(p) for p in watch_paths]
        self._queue = file_queue
        self._recursive = recursive
        self._observer = None
        self._running = False

    def start(self):
        if not _WATCHDOG:
            logger.error("Cannot start monitor: watchdog library not installed")
            return
        if self._running:
            return
        self._observer = Observer()
        handler = _EmlHandler(self._queue)
        for p in self._paths:
            if p.is_dir():
                self._observer.schedule(handler, str(p), recursive=self._recursive)
                logger.info("Watching: %s", p)
            else:
                logger.warning("Watch path missing: %s", p)
        self._observer.start()
        self._running = True

    def stop(self):
        if self._observer and self._running:
            self._observer.stop()
            self._observer.join()
            self._running = False
            logger.info("Monitor stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    def scan_directory(self, path: pathlib.Path, recursive: bool = False) -> int:
        """Enqueue all .eml files found in path. Returns count enqueued."""
        pattern = "**/*.eml" if recursive else "*.eml"
        count = 0
        for f in path.glob(pattern):
            if not f.name.startswith("."):
                self._queue.put(f)
                count += 1
        logger.info("Scan enqueued %d file(s) from %s", count, path)
        return count
