# OBS Auto Game Recording

Windows-only OBS automation that:

- starts recording when a configured game process launches
- stops recording after the last matching game exits
- verifies the archived copy and removes the original recording only after that succeeds

The project is built as an OBS Python script with testable core modules under `src/`.

## Project Layout

- `obs_scripts/auto_record_games.py`: OBS script entrypoint
- `src/obs_auto_record/`: core logic for parsing settings, scanning processes, session state, and archive copy
- `tests/`: unit tests

## Requirements

- Windows 10 or 11
- 64-bit OBS Studio
- Python 3.12 x64 installed locally
- OBS configured to use that Python installation for scripting

Notes:

- The script uses the OBS Python scripting API directly.
- It does not require `obs-websocket`.
- It does not install game sources or switch scenes automatically.

## Setup

### 1. Keep the project folders together

OBS loads `obs_scripts/auto_record_games.py`, and that script imports the package from the sibling `src` directory.

Keep this layout intact:

```text
F:\GameRecording
|-- obs_scripts
|   `-- auto_record_games.py
|-- src
|   `-- obs_auto_record
`-- tests
```

If you move the script file somewhere else by itself, it will not find the package imports.

### 2. Install Python 3.12 x64

OBS scripting on Windows is sensitive to Python version and architecture.

Recommended:

- Python `3.12.x`
- 64-bit build

Verify with:

```powershell
python --version
python -c "import struct; print(struct.calcsize('P') * 8)"
```

Expected output should show Python `3.12.x` and `64`.

### 3. Point OBS at Python

In OBS:

1. Open `Tools > Scripts`
2. Click `Python Settings`
3. Set the Python install path to your Python 3.12 x64 installation
4. Restart OBS if prompted

Typical path example:

```text
C:\Users\<you>\AppData\Local\Programs\Python\Python312
```

### 4. Load the script in OBS

In `Tools > Scripts`:

1. Click the `+` button
2. Select [auto_record_games.py](F:\GameRecording\obs_scripts\auto_record_games.py)
3. Confirm the script appears in the list

If OBS reports import errors, verify that:

- the `src` folder is still next to `obs_scripts`
- OBS is using Python 3.12 x64

## OBS Script Settings

After loading the script, configure these fields:

- `Enabled`: turns automation on or off
- `Watch List`: one game per line using `exe_name|archive_subfolder`
- `Archive Root`: destination root for archived recordings
- `Poll Interval Ms`: how often the script scans running processes
- `Exit Grace Period Sec`: delay before stop after the last game exits
- `Copy Timeout Sec`: max wait for OBS to release the recording file
- `Verbose Logging`: enables extra log output

### Watch List Format

Use one entry per line:

```text
eldenring.exe|Elden Ring
cs2.exe|Counter-Strike 2
```

Rules:

- executable names must be file names, not full paths
- executable names are matched case-insensitively
- executable names must end in `.exe`
- archive folder names are sanitized for Windows path safety
- duplicate executables are ignored

Comments and blank lines are allowed:

```text
# Souls games
eldenring.exe|Elden Ring

# FPS
cs2.exe|Counter-Strike 2
```

## How It Works

1. OBS starts and loads the script.
2. The script polls running Windows processes.
3. When a configured executable appears, the script starts OBS recording.
4. While any configured matching process is still running, recording continues.
5. After the last matching process disappears and the grace period expires, the script stops recording.
6. When OBS finishes writing the file, the script copies it to:

```text
<Archive Root>\<archive_subfolder>\<original_filename>
```

7. The script verifies the copied file matches the source and then deletes the original recording.

If a file with the same name already exists, the script appends a timestamp before the extension.

## Ownership Rules

The script is intentionally conservative:

- If OBS is already recording before a watched game starts, the script does not take ownership.
- The script only auto-stops recordings that it started.
- If you manually stop a script-started recording while the game is still running, it will not immediately restart.
- Auto-start is re-armed only after all watched games have fully exited.

## Example Configuration

Script properties example:

- `Enabled`: `true`
- `Watch List`:

```text
eldenring.exe|Elden Ring
cs2.exe|Counter-Strike 2
```

- `Archive Root`: `D:\GameArchive`
- `Poll Interval Ms`: `1000`
- `Exit Grace Period Sec`: `10`
- `Copy Timeout Sec`: `120`
- `Verbose Logging`: `false`

Resulting archive examples:

```text
D:\GameArchive\Elden Ring\2026-03-07 20-14-11.mkv
D:\GameArchive\Counter-Strike 2\2026-03-07 22-05-44.mkv
```

## Running Tests

The tests use Python's standard library `unittest`, so no extra test packages are required.

From the project root:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Optional syntax check:

```powershell
python -m compileall src tests obs_scripts
```

## Troubleshooting

### OBS says Python is not configured

Set the Python path under `Tools > Scripts > Python Settings`, then restart OBS.

### Script loads but does nothing

Check:

- `Enabled` is turned on
- `Watch List` has valid `exe|folder` lines
- the game executable name is correct
- OBS recording works manually

Enable `Verbose Logging` and inspect the OBS script log window.

### Recording starts but file is not archived

Check:

- `Archive Root` is set
- the target drive/path exists and is writable
- the recording actually finished and OBS wrote a last recording path

The script retries briefly while OBS releases the file handle.

### Manual recording behavior seems unchanged

That is expected when you start recording manually before the watched game launches. The script avoids taking over recordings it did not start.

## Current Limitations

- Windows only
- executable-name matching only; no generic “detect any game” logic
- one recording session at a time
- overlapping watched games keep the archive target from the first matched game in that session
- the source file is deleted only after the archived copy passes verification

## Relevant Files

- [README.md](F:\GameRecording\README.md)
- [auto_record_games.py](F:\GameRecording\obs_scripts\auto_record_games.py)
- [settings.py](F:\GameRecording\src\obs_auto_record\settings.py)
- [process_scan.py](F:\GameRecording\src\obs_auto_record\process_scan.py)
- [session_engine.py](F:\GameRecording\src\obs_auto_record\session_engine.py)
- [archive.py](F:\GameRecording\src\obs_auto_record\archive.py)
