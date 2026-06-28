# EML File Manager

An offline desktop application that automatically organises `.eml` email files into a clean folder structure and indexes them in a local database for easy search and export.

Drop emails into a watch folder → the app renames them, sorts them into subject-named folders, and records every detail in a searchable local database. Nothing leaves your machine.

---

## Requirements

- **Windows 10 or Windows 11**
- Python 3.10 or later
- `tkinter` (bundled with the standard Python Windows installer)

---

## Installation

```bat
rem 1. Clone or download this repository
git clone <repo-url>
cd project-eml-file-management-system

rem 2. Create a virtual environment
python -m venv .venv

rem 3. Activate it
.venv\Scripts\activate

rem 4. Install the app and its dependencies
pip install -e .
```

---

## Launching the App

```bat
rem With the venv active:
eml-manager

rem Or without activating the venv:
.venv\Scripts\python -m eml_manager
```

The GUI window opens. On first run, no watch paths are configured — follow the **Quick Start** below.

---

## Quick Start

### 1. Create an Archive

Click **New Archive…** in the toolbar. Choose a parent folder and give the archive a name. The app creates a self-contained archive *bundle* (a folder holding the database and an `emails/` sub-folder) and mounts it. See [Archive Bundles](#archive-bundles) for details.

To re-open an existing archive later, use **Open Archive…**. The most recently mounted archive is re-mounted automatically on startup.

### 2. Open Settings

Click **Settings** in the toolbar.

### 3. Configure Paths (Paths tab)

| Field | What it means |
|---|---|
| **Watch Paths** | Folder(s) the app monitors for new `.eml` files. Click **Add…** to pick a folder. |
| **Duplicates Folder Name** | Sub-folder inside the archive's `emails/` folder where duplicate emails are moved (default: `duplicates`). |

Click **Save**.

### 4. Start Monitoring

With an archive mounted, click **Start Monitoring**. The status indicator turns green.

### 5. Add an Email

Copy or move any `.eml` file into your watch folder. Within a few seconds it will appear in the table with status `processed`.

The file is renamed and moved automatically into the mounted archive:

```
MyArchive\                                    ← the archive bundle folder
├── .emlarchive                               ← marker identifying this folder as an archive
├── archive.db                                ← the metadata database
└── emails\
    └── Hello_World\                          ← normalised subject name (reply/forward prefixes stripped)
        └── Hello_World_20260624143055_Alice_Smith.eml
```

Reply and forward prefixes (`Re:`, `FW:`, `Fwd:`, `答复:`, `转发:`, etc.) are stripped before the folder and filename are generated, so threaded conversations are grouped together regardless of how many times they were replied to or forwarded. The original subject is preserved as-is in the database and displayed in the table.

---

## Dashboard

The main panel shows the last 100 processed files, sorted by **Subject** then **Sent Date**. Use the **Search & Filter** bar to narrow results.

| Column | Description |
|---|---|
| 📎 | A paperclip if the email carries at least one attachment, blank otherwise |
| Type | `Re` if the email is a reply, `Fw` if it was forwarded, blank otherwise |
| Subject | Email subject line with reply/forward prefixes removed |
| Sender | Display name or local-part of the From address |
| Sent Date | Timestamp displayed as `YYYY-MM-DD HH:mm:ss` |
| Tags | User-defined tags. **Click a cell** to open the tag editor where you can type comma-separated tags and re-use previously applied tags from the list. To edit tags for **multiple rows at once**, select them (Ctrl+click or Shift+click), then right-click → **Edit Tags**. New emails are **auto-tagged** on import — see [Automatic Tagging](#automatic-tagging). |
| Open | **Click "Open ↗"** to open the `.eml` file in your default email client (Outlook, etc.), where you can read, reply, or forward. |
| Status | `processed`, `duplicate`, or `error` |

**Right-click** any row for:
- **Open File Location** — opens Explorer with the file selected
- **Edit Tags** — opens the tag editor for the selected row(s); select multiple rows first (Ctrl+click / Shift+click) to bulk-edit
- **Reprocess** — *(coming in a future release)*
- **Delete** — permanently removes the selected file(s) from disk and database (confirmation required); also triggered by the **Delete key**

---

## Search & Filter

The filter bar has six rows:

| Row | Fields |
|---|---|
| 1 | **Keyword** — searches Subject, Sender, and Tags simultaneously; **Tags** — dropdown of all previously used tags; **Attachment** — dropdown to show only emails *with* or *without* an attachment (`Any` by default) |
| 2 | **Subject** — partial-text filter; **Sender** — partial-text filter |
| 3 | **Sent From / To** — filter by the date the email was *sent*, in `YYYYMMDD` format |
| 4 | **Added From / To** — filter by the date the email was *added to the archive* (its `parsed_at` value), in `YYYYMMDD` format |
| 5 | **Search**, **Clear**, **Export CSV…** buttons (right-aligned) |
| 6 | Configured timezone (left) and result count (right) |

Both date ranges are interpreted in the configured timezone (shown at the bottom of the bar) and compared against values stored in UTC. **Sent From / To** filters on when the email was originally sent; **Added From / To** filters on when it was ingested into the archive — useful for reviewing everything imported on a given day regardless of when it was sent.

All active filters combine with AND logic. The Tags dropdown is populated from existing tag values automatically when opened. Search results stay visible until you click **Clear** — they are not reset automatically.

---

## Manual Scan

If you have a folder of existing `.eml` files you want to import all at once:

1. Click **Manual Scan…** in the toolbar.
2. Select the folder.
3. The app queues and processes every `.eml` found (recursively).

(Manual Scan is only available while an archive is mounted.)

---

## Archive Bundles

An **archive** is a self-contained folder — a *bundle* — that holds everything for one collection of emails:

```
MyArchive\
├── .emlarchive      ← marker file that identifies the folder as an archive bundle
├── archive.db       ← the metadata database
└── emails\          ← organised .eml files, in subject-named sub-folders
```

Because the database stores each email's location **relative to `emails/`**, a bundle is fully portable: you can copy, move, or rename the whole folder, put it on a USB drive or network share, and it still works — no paths need rewriting.

The app mounts **zero or one** bundle at a time, like a removable volume:

| Toolbar button | What it does |
|---|---|
| **New Archive…** | Create a new, empty bundle and mount it |
| **Open Archive…** | Mount an existing bundle folder |
| **Eject** | Unmount the current bundle (stops monitoring and closes the database) |

The path of the mounted bundle is remembered in the config, and the app re-mounts it automatically on the next launch (if the folder still exists). Most actions — Start Monitoring, Manual Scan, Export Archive — are only available while a bundle is mounted.

---

## Backup and Restore

### Export Archive

With an archive mounted, click **Export Archive…** in the toolbar. The app zips the **entire bundle folder** — `.emlarchive`, `archive.db`, and the whole `emails/` tree — into a single `.zip` file. No path rewriting is needed because all stored paths are already relative.

### Import Archive

Click **Import Archive…** to restore from a previously exported `.zip`:

1. Select the `.zip` file. The app verifies it is a valid bundle (it must contain the `.emlarchive` marker).
2. Choose a parent folder and a name for the restored archive.
3. The app extracts the zip into that folder and mounts the resulting bundle.

Importing never overwrites the currently mounted archive — it creates a separate bundle and switches to it.

---

## Settings Reference

### Paths tab

| Setting | Default | Description |
|---|---|---|
| Watch Paths | *(none)* | One or more directories to monitor |
| Duplicates Folder Name | `duplicates` | Sub-folder for detected duplicate emails |

### Processing tab

| Setting | Default | Description |
|---|---|---|
| Dedupe Policy | `message_id,sha256` | How duplicates are detected. `message_id,sha256` is the most thorough. |
| Filename Length Limit | `200` | Maximum characters in a generated filename |

### System & Logging tab

| Setting | Default | Description |
|---|---|---|
| Timezone | `UTC` | Timezone used for the timestamp in filenames and the database. Select from the dropdown list of major timezones, or type any valid IANA timezone name (e.g. `Europe/London`). |
| Stable Check (seconds) | `3.0` | How long a file's size must be unchanged before it is processed — prevents reading partially written files |
| Retry Count | `3` | Number of retries on transient file-lock errors |
| Log Level | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |

---

## Command-Line Interface

All features are also available without the GUI. Commands that read or write the archive (`scan`, `import`, `export`, `db-check`, `backfill-attachments`) operate on a bundle. Pass `--bundle PATH` to choose one, or omit it to use the archive last mounted in the GUI.

```bat
rem Scan a directory and process all .eml files found
eml-manager --bundle C:\path\to\MyArchive scan --path C:\Users\you\Downloads\Emails --recursive

rem Import a single file immediately
eml-manager --bundle C:\path\to\MyArchive import C:\Users\you\Downloads\invoice.eml

rem Export the full database to CSV
eml-manager --bundle C:\path\to\MyArchive export --out archive.csv

rem Filter the export by keyword
eml-manager --bundle C:\path\to\MyArchive export --keyword "invoice" --out invoices.csv

rem Verify database integrity
eml-manager --bundle C:\path\to\MyArchive db-check

rem Backfill the has_attachment flag on records imported before that column existed
eml-manager --bundle C:\path\to\MyArchive backfill-attachments

rem Re-scan every record, not just those still flagged as having no attachment
eml-manager --bundle C:\path\to\MyArchive backfill-attachments --force

rem Use a custom config file
eml-manager --config C:\path\to\config.yml --bundle C:\path\to\MyArchive db-check

rem Verbose / debug logging
eml-manager --verbose --bundle C:\path\to\MyArchive scan --path C:\Users\you\Downloads
```

Exit codes: `0` = success, non-zero = error.

The `backfill-attachments` command re-reads each archived `.eml` and recomputes its attachment flag. It is useful in two cases:

- **Archives created before attachment tracking was added.** The database is upgraded automatically when such an archive is opened, but existing records start out flagged as having no attachment. The default run inspects only records still flagged `0` (cheap and repeatable) and fills in the ones that do have attachments.
- **Records flagged incorrectly by an earlier version.** Older builds mistook inline images (signature logos, pictures embedded in HTML) for attachments. To clear those false positives you must re-scan **every** record — including ones currently flagged as having an attachment — so use `--force`:

  ```bat
  eml-manager --bundle C:\path\to\MyArchive backfill-attachments --force
  ```

Missing or unreadable files are skipped.

---

## How Files Are Named

Given an email with:
- Subject: `Re: Project — Planning`
- Sent: `2026-06-24 14:30:55 UTC`
- From: `Alice Smith <alice@example.com>`

The file is saved as:

```
Re_Project_Planning_20260624143055_Alice_Smith.eml
```

Rules applied:
- Illegal filesystem characters (`/ : * ? " < > |`) are removed
- Runs of whitespace or underscores are collapsed to a single `_`
- Length is capped at the **Filename Length Limit** setting
- If a name already exists, a counter suffix is appended (`_2`, `_3`, …)

---

## Automatic Tagging

When a new email is added to the archive, the app checks whether any email already in the database shares the **same conversation subject** — that is, the subject after reply/forward prefixes (`Re:`, `FW:`, `Fwd:`, `答复:`, `转发:`, etc.) are stripped, the same grouping used for folder names. If a match is found and it has tags, the new email automatically inherits those tags (the most recently added matching email wins).

This keeps a conversation consistently tagged without re-entering tags for every reply or forward. For example, once you tag `Re: Invoice` with `finance`, a later `Fwd: Invoice` is tagged `finance` automatically. You can still edit or clear the tags on any row afterward.

---

## Duplicate Detection

When a file is processed, the app checks whether an email with the same **Message-ID** or **SHA-256 content hash** already exists in the database.

- If a duplicate is found, the file is moved to the **Duplicates Folder** and no new database record is created.
- Re-importing the same file is safe and idempotent.

---

## Config & Log File Locations

| File | Path |
|---|---|
| Config | `%APPDATA%\eml_manager\config.yml` |
| Database | inside the archive bundle (`<bundle>\archive.db`) |
| Log | `%APPDATA%\eml_manager\logs\eml-manager.log` |

You can edit `config.yml` by hand if needed.

---

## Troubleshooting

**`watchdog not installed; directory monitoring unavailable`**

Re-run:
```bat
pip install -e .
```

**Files are not being detected**

- Confirm the watch path exists and the app has read/write permission to it.
- Check the **Log** panel at the bottom of the window for error messages.
- Increase **Stable Check** seconds if files are written slowly over a network drive.

**"Open ↗" does nothing or opens the wrong app**

The file is opened with Windows' default handler for `.eml` files. To change it, go to **Windows Settings → Apps → Default apps** and set your preferred email client as the handler for `.eml`.

---

## License

MIT — see [LICENSE](LICENSE).
