import argparse
import csv
import logging
import pathlib
import queue
import sys
from logging.handlers import RotatingFileHandler

from . import __version__
from .bundle import Bundle
from .config import Config, default_config_path
from .database import Database
from .monitor import Monitor
from .processor import Processor


def setup_logging(config: Config):
    log_path = pathlib.Path(config.log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    level = getattr(logging, config.log_level.upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root = logging.getLogger()
    root.setLevel(level)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    fh = RotatingFileHandler(str(log_path), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)


# --- sub-commands ---

def cmd_scan(args, config: Config, db: Database, bundle: Bundle):
    q: queue.Queue = queue.Queue()
    processor = Processor(config, db, bundle)
    monitor = Monitor([], q)
    count = monitor.scan_directory(pathlib.Path(args.path), recursive=args.recursive)
    if args.dry_run:
        print(f"[dry-run] Would process {count} file(s).")
        return

    processed = errors = dupes = 0
    while not q.empty():
        f = q.get()
        result = processor.process(f)
        s = result["status"]
        print(f"  [{s}] {f.name}")
        if s == "processed":
            processed += 1
        elif s == "duplicate":
            dupes += 1
        else:
            errors += 1

    print(f"\nDone — processed={processed}, duplicates={dupes}, errors={errors}")


def cmd_import(args, config: Config, db: Database, bundle: Bundle):
    processor = Processor(config, db, bundle)
    target = pathlib.Path(args.target)
    if target.is_file():
        files = [target]
    elif target.is_dir():
        files = list(target.rglob("*.eml") if args.recursive else target.glob("*.eml"))
    else:
        print(f"Error: {target} is not a file or directory.", file=sys.stderr)
        sys.exit(1)

    print(f"Importing {len(files)} file(s)…")
    for f in files:
        result = processor.process(f)
        print(f"  [{result['status']}] {f.name}")


def cmd_db_check(args, config: Config, db: Database):
    ok = db.check_integrity()
    print("integrity_check:", "ok" if ok else "FAILED")
    sys.exit(0 if ok else 1)


def cmd_export(args, config: Config, db: Database):
    rows = db.search(keyword=args.keyword or "", limit=100_000)
    if not rows:
        print("No results.", file=sys.stderr)
        return

    out = open(args.out, "w", newline="", encoding="utf-8") if args.out != "-" else sys.stdout
    writer = csv.DictWriter(out, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    if args.out != "-":
        out.close()
    print(f"Exported {len(rows)} row(s).", file=sys.stderr)


# --- entry point ---

def main():
    parser = argparse.ArgumentParser(prog="eml-manager", description="EML File Management System")
    parser.add_argument("--config", default=str(default_config_path()), help="Config file path")
    parser.add_argument("--bundle", default="", help="Path to the archive bundle to use")
    parser.add_argument("--verbose", "-v", action="store_true", help="Set log level to DEBUG")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("gui", help="Launch the graphical UI (default when no command given)")
    sub.add_parser("version", help="Print version and exit")
    sub.add_parser("db-check", help="Validate SQLite database integrity")

    scan_p = sub.add_parser("scan", help="Scan a directory and process all .eml files")
    scan_p.add_argument("--path", required=True, help="Directory to scan")
    scan_p.add_argument("--recursive", action="store_true")
    scan_p.add_argument("--dry-run", action="store_true", help="Report without processing")

    imp_p = sub.add_parser("import", help="Import a file or directory immediately")
    imp_p.add_argument("target", help="File or directory path")
    imp_p.add_argument("--recursive", action="store_true")

    exp_p = sub.add_parser("export", help="Export metadata to CSV")
    exp_p.add_argument("--keyword", default="", help="Filter by subject/sender keyword")
    exp_p.add_argument("--out", default="-", help="Output file path (- for stdout)")

    args = parser.parse_args()

    if args.command == "version":
        print(f"eml-manager {__version__}")
        return

    config_path = pathlib.Path(args.config)
    config = Config.load(config_path)
    if args.verbose:
        config.log_level = "DEBUG"
    setup_logging(config)

    if args.command in ("scan", "import", "db-check", "export"):
        bundle_path = args.bundle or config.active_bundle
        if not bundle_path:
            print(
                "Error: no archive bundle specified. Use --bundle PATH "
                "or set an active bundle via the GUI.",
                file=sys.stderr,
            )
            sys.exit(1)
        bundle = Bundle(pathlib.Path(bundle_path))
        if not bundle.is_valid():
            print(f"Error: not a valid archive bundle: {bundle_path}", file=sys.stderr)
            sys.exit(1)
        db = Database(bundle.db_path, str(bundle.emails_root), tz_name=config.timezone)

        if args.command == "scan":
            cmd_scan(args, config, db, bundle)
        elif args.command == "import":
            cmd_import(args, config, db, bundle)
        elif args.command == "db-check":
            cmd_db_check(args, config, db)
        elif args.command == "export":
            cmd_export(args, config, db)
    else:
        # gui (default)
        from .ui.app import App

        app = App(config, config_path)
        app.mainloop()


if __name__ == "__main__":
    main()
