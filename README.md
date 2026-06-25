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

### 1. Open Settings

Click **Settings** in the toolbar.

### 2. Configure Paths (Paths tab)

| Field | What it means |
|---|---|
| **Watch Paths** | Folder(s) the app monitors for new `.eml` files. Click **Add…** to pick a folder. |
| **Archive Root** | Where organised files are stored. The app creates sub-folders here automatically. |
| **Duplicates Folder Name** | Sub-folder inside Archive Root where duplicate emails are moved (default: `duplicates`). |

Click **Save**.

### 3. Start Monitoring

Click **Start Monitoring**. The status indicator turns green.

### 4. Add an Email

Copy or move any `.eml` file into your watch folder. Within a few seconds it will appear in the table with status `processed`.

The file is renamed and moved automatically:

```
Archive Root\
└── Hello_World\                              ← normalised subject name (reply/forward prefixes stripped)
    └── Hello_World_20260624143055_Alice_Smith.eml
```

Reply and forward prefixes (`Re:`, `FW:`, `Fwd:`, `答复:`, `转发:`, etc.) are stripped before the folder and filename are generated, so threaded conversations are grouped together regardless of how many times they were replied to or forwarded. The original subject is preserved as-is in the database and displayed in the table.

---

## Dashboard

The main panel shows the last 100 processed files, sorted by **Subject** then **Sent Date**. Use the **Search & Filter** bar to narrow results.

| Column | Description |
|---|---|
| Type | `Re` if the email is a reply, `Fw` if it was forwarded, blank otherwise |
| Subject | Email subject line with reply/forward prefixes removed |
| Sender | Display name or local-part of the From address |
| Sent Date | Timestamp displayed as `YYYY-MM-DD HH:mm:ss` |
| Tags | User-defined tags. **Click a cell** to open the tag editor where you can type comma-separated tags and re-use previously applied tags from the list. To edit tags for **multiple rows at once**, select them (Ctrl+click or Shift+click), then right-click → **Edit Tags**. |
| Open | **Click "Open ↗"** to open the `.eml` file in your default email client (Outlook, etc.), where you can read, reply, or forward. |
| Status | `processed`, `duplicate`, or `error` |

**Right-click** any row for:
- **Open File Location** — opens Explorer with the file selected
- **Edit Tags** — opens the tag editor for the selected row(s); select multiple rows first (Ctrl+click / Shift+click) to bulk-edit
- **Reprocess** — *(coming in a future release)*
- **Delete** — permanently removes the selected file(s) from disk and database (confirmation required); also triggered by the **Delete key**

---

## Search & Filter

The filter bar has four rows:

| Row | Fields |
|---|---|
| 1 | **Keyword** — searches Subject, Sender, and Tags simultaneously |
| 2 | **Type** — select `Re`, `Fw`, or blank; **Subject** — partial-text filter |
| 3 | **Sender** — partial-text filter; **Sent From / To** — date range in `YYYYMMDD` format |
| 4 | **Tags** — dropdown of all previously used tags; **Search**, **Clear**, **Export CSV…** buttons and result count |

All active filters combine with AND logic. The Tags dropdown is populated from existing tag values automatically when opened. Search results stay visible until you click **Clear** — they are not reset automatically.

---

## Manual Scan

If you have a folder of existing `.eml` files you want to import all at once:

1. Click **Manual Scan…** in the toolbar.
2. Select the folder.
3. The app queues and processes every `.eml` found (recursively).

---

## Settings Reference

### Paths tab

| Setting | Default | Description |
|---|---|---|
| Watch Paths | *(none)* | One or more directories to monitor |
| Archive Root | `%USERPROFILE%\EmailArchive` | Root of the organised folder tree |
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

All features are also available without the GUI.

```bat
rem Scan a directory and process all .eml files found
eml-manager scan --path C:\Users\you\Downloads\Emails --recursive

rem Import a single file immediately
eml-manager import C:\Users\you\Downloads\invoice.eml

rem Export the full database to CSV
eml-manager export --out archive.csv

rem Filter the export by keyword
eml-manager export --keyword "invoice" --out invoices.csv

rem Verify database integrity
eml-manager db-check

rem Use a custom config file
eml-manager --config C:\path\to\config.yml

rem Verbose / debug logging
eml-manager --verbose scan --path C:\Users\you\Downloads
```

Exit codes: `0` = success, non-zero = error.

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

## Duplicate Detection

When a file is processed, the app checks whether an email with the same **Message-ID** or **SHA-256 content hash** already exists in the database.

- If a duplicate is found, the file is moved to the **Duplicates Folder** and no new database record is created.
- Re-importing the same file is safe and idempotent.

---

## Config & Log File Locations

| File | Path |
|---|---|
| Config | `%APPDATA%\eml_manager\config.yml` |
| Database | `%APPDATA%\eml_manager\eml_manager.db` |
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
