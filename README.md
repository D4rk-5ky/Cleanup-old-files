# Delete Oldest Files Cleanup Script

A Python 3 cleanup script that deletes the **oldest files first** until one or more configured storage limits are below the wanted threshold.

This is useful for CCTV/video recording folders, temporary storage, cache folders, or other directories where old files should be removed automatically.

---

## ⚠️ WARNING — DESTRUCTIVE SCRIPT

This script **deletes files permanently**.

There is no recycle bin, trash folder, or undo function.

By using this script, **you accept full responsibility for any damage, data loss, misconfiguration, accidental deletion, or other problems caused by running it**.

The author, contributors, and anyone providing examples are **not responsible** for lost data or damage.

Always test carefully before using it on important data.

Recommended before real use:

- Test on a dummy folder first
- Use a small test dataset
- Check your paths carefully
- Make sure you understand what folder the script deletes files from
- Make backups of important data

---

## Features

- Deletes the **oldest files first**
- Works recursively through subfolders
- Can clean based on mount usage percentage
- Can clean based on folder size
- Can use both limits at the same time
- Stops after a configured maximum number of deleted files
- Uses a lock file to avoid multiple copies running at once
- Intended for cron/systemd timer usage

---

## How It Works

The script checks whether cleanup is needed.

Cleanup can be triggered by:

1. A mount point being over a usage percentage
2. A folder being over a maximum size
3. Either of the above when both are configured

When cleanup is needed, the script scans the cleanup folder and deletes the single oldest file it can find.

It then checks the limits again and repeats until:

- The mount usage is below the configured limit
- The folder size is below the configured limit
- The maximum delete cycle count is reached
- No deletable files are found
- An error occurs

---

## Important Behavior

The script deletes files based on **modification time**.

That means “oldest” means the oldest file according to file `mtime`.

It does **not** use:

- Filename date
- Folder name
- Creation date
- Camera name
- File extension

Example:

```text
/storage/camera1/newer-file.mp4
/storage/camera2/oldest-file.mp4
/storage/camera3/archive/second-oldest-file.mp4
```

If `oldest-file.mp4` has the oldest modification time, it will be deleted first, even though it is in another folder.

---

## Requirements

- Python 3
- Linux or Unix-like system
- Permission to read the folder tree
- Permission to delete files from the cleanup folder

No external Python packages are required.

---

## Installation

Save the script somewhere sensible, for example:

```bash
sudo nano /home/cfna08h/Scripts/CleanUp/delete_oldest_files_cleanup.py
```

Make it executable:

```bash
chmod +x /home/cfna08h/Scripts/CleanUp/delete_oldest_files_cleanup.py
```

---

## Usage

```bash
./delete_oldest_files_cleanup.py [options]
```

---

## Options

| Option | Description |
|---|---|
| `--mount` | Mount point to check for disk usage percentage |
| `--max-mount-usage` | Maximum allowed mount usage percentage |
| `--folder` | Folder to scan for oldest files and optionally check size |
| `--max-folder-size` | Maximum allowed folder size |
| `--max-cycles` | Maximum number of files to delete in one run |

---

## Example: Clean by Mount Usage

Delete oldest files under `/storage` until `/storage` is at or below `90%` usage.

```bash
/usr/bin/python3 /home/cfna08h/Scripts/CleanUp/delete_oldest_files_cleanup.py \
  --mount /storage \
  --max-mount-usage 90 \
  --max-cycles 1000
```

---

## Example: Clean by Folder Size

Delete oldest files under `/storage/cctv` until that folder is at or below `500G`.

```bash
/usr/bin/python3 /home/cfna08h/Scripts/CleanUp/delete_oldest_files_cleanup.py \
  --folder /storage/cctv \
  --max-folder-size 500G \
  --max-cycles 1000
```

---

## Example: Clean by Mount Usage or Folder Size

Delete oldest files under `/storage/cctv` if either:

- `/storage` is above `90%`
- `/storage/cctv` is above `500G`

```bash
/usr/bin/python3 /home/cfna08h/Scripts/CleanUp/delete_oldest_files_cleanup.py \
  --mount /storage \
  --max-mount-usage 90 \
  --folder /storage/cctv \
  --max-folder-size 500G \
  --max-cycles 1000
```

In this mode, files are deleted from:

```text
/storage/cctv
```

Not from the whole mount.

---

## Supported Folder Size Formats

Examples:

```text
500G
500GB
500GiB
2T
2TB
100M
100MB
123456789
```

Sizes are interpreted as binary units using powers of 1024.

Example:

```text
1G = 1024 MiB
```

---

## Cron Example

Run every 10 minutes:

```bash
crontab -e
```

Add:

```cron
*/10 * * * * /usr/bin/python3 /home/cfna08h/Scripts/CleanUp/delete_oldest_files_cleanup.py --mount /storage --max-mount-usage 90 --folder /storage/cctv --max-folder-size 500G --max-cycles 1000
```

---

## Cron Example With Only Error Mail

This sends normal output to `/dev/null`, but still lets errors go to cron mail:

```cron
*/10 * * * * /usr/bin/python3 /home/cfna08h/Scripts/CleanUp/delete_oldest_files_cleanup.py --mount /storage --max-mount-usage 90 --folder /storage/cctv --max-folder-size 500G --max-cycles 1000 > /dev/null
```

---

## Lock File

The script uses a lock file:

```text
/tmp/CleanUpLockFile-CCTV.lock
```

This prevents multiple cleanup jobs from running at the same time.

If the lock file already exists, the script exits normally.

---

## Logging

The script creates temporary logs while running.

On normal successful completion, the temporary log is removed.

On errors, a log file is saved next to the script, for example:

```text
cleanup-error-2026-05-19_08-30-00.log
```

---

## Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Finished normally |
| `1` | Error occurred |
| `2` | Invalid arguments/configuration |

---

## Safety Notes

Before using this script for real CCTV recordings or important data, test with a small folder:

```bash
mkdir -p /tmp/cleanup-test/cam1
mkdir -p /tmp/cleanup-test/cam2
```

Create test files with different timestamps and confirm that the oldest files are deleted first.

Do **not** run this script against folders containing important files unless you are completely sure your options are correct.

---

## License

Simplified BSD License, unless otherwise specified by the original author.

---

## Disclaimer

This script is provided as-is.

You are fully responsible for how you use it.

The author and contributors are not responsible for:

- Deleted files
- Lost recordings
- Broken systems
- Wrong paths
- Bad cron jobs
- Misconfigured mount points
- Any other damage or data loss

Use at your own risk.
