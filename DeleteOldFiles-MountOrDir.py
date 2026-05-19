#!/usr/bin/env python3

###############################################################################
# Author            : Louwrentius original idea
# Rewritten by      : ChatGPT for Darkyere
# Purpose           : Delete oldest files until mount usage and/or folder size
#                     drops below configured limits.
#
# Examples:
#
# Mount mode:
#   cleanup.py --mount /storage --max-mount-usage 90 --max-cycles 1000
#
# Folder size mode:
#   cleanup.py --folder /storage/cctv --max-folder-size 500G --max-cycles 1000
#
# Both:
#   cleanup.py --mount /storage --max-mount-usage 90 \
#              --folder /storage/cctv --max-folder-size 500G \
#              --max-cycles 1000
###############################################################################

import argparse
import atexit
import math
import os
import shutil
import signal
import sys
import tempfile
from datetime import datetime
from pathlib import Path


VERSION = "1.05"
LOCK_FILE = Path("/tmp/CleanUpLockFile-CCTV.lock")

SCRIPT_DIR = Path(__file__).resolve().parent
TIMESTAMP = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
LOG_FILE = SCRIPT_DIR / f"cleanup-error-{TIMESTAMP}.log"

tmp_fd, tmp_log_name = tempfile.mkstemp()
os.close(tmp_fd)
TMP_LOG = Path(tmp_log_name)

LOCK_CREATED = False


# =============================================================================
# Logging helpers
# =============================================================================

def write_tmp(message: str = ""):
    with TMP_LOG.open("a", encoding="utf-8") as logfile:
        logfile.write(message + "\n")


def print_and_log(message: str = ""):
    print(message)
    write_tmp(message)


def remove_tmp_log():
    try:
        if TMP_LOG.exists():
            TMP_LOG.unlink()
    except OSError:
        pass


def save_error_log(exit_code: int):
    write_tmp(f"Exit code: {exit_code}")
    shutil.move(str(TMP_LOG), str(LOG_FILE))


# =============================================================================
# Cleanup and signal handling
# =============================================================================

def clean_up():
    global LOCK_CREATED

    if LOCK_CREATED and LOCK_FILE.exists():
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass


def signal_handler(signum, frame):
    print_and_log(f"Received signal {signum}, exiting.")
    save_error_log(1)
    clean_up()
    sys.exit(1)


atexit.register(clean_up)
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# =============================================================================
# Lock file handling
# =============================================================================

def create_lock_or_exit():
    global LOCK_CREATED

    if LOCK_FILE.exists():
        write_tmp("Lock file exists, exiting normally.")
        remove_tmp_log()
        sys.exit(0)

    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        LOCK_CREATED = True
    except OSError:
        print_and_log("Failed to create lock file, exiting.")
        save_error_log(1)
        sys.exit(1)


# =============================================================================
# Size parsing
# =============================================================================

def parse_size(size_text: str) -> int:
    """
    Convert size strings to bytes.

    Supported examples:
        500G
        500GB
        500GiB
        2T
        2TB
        100M
        100MB
        123456789
    """
    text = size_text.strip().upper()

    units = {
        "K": 1024,
        "KB": 1024,
        "KIB": 1024,
        "M": 1024 ** 2,
        "MB": 1024 ** 2,
        "MIB": 1024 ** 2,
        "G": 1024 ** 3,
        "GB": 1024 ** 3,
        "GIB": 1024 ** 3,
        "T": 1024 ** 4,
        "TB": 1024 ** 4,
        "TIB": 1024 ** 4,
    }

    for unit, multiplier in sorted(units.items(), key=lambda item: len(item[0]), reverse=True):
        if text.endswith(unit):
            number = text[:-len(unit)].strip()
            return int(float(number) * multiplier)

    return int(float(text))


def format_size(num_bytes: int) -> str:
    """
    Human-readable size output.
    """
    size = float(num_bytes)

    for unit in ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]:
        if size < 1024 or unit == "PiB":
            return f"{size:.2f} {unit}"
        size /= 1024

    return f"{num_bytes} B"


# =============================================================================
# Disk and folder usage
# =============================================================================

def get_mount_usage_percent(mount: Path):
    """
    Return current disk usage percentage for the filesystem containing mount.
    """
    try:
        usage = shutil.disk_usage(mount)
    except OSError:
        return None

    if usage.total <= 0:
        return None

    return math.ceil((usage.used / usage.total) * 100)


def get_folder_size(folder: Path) -> int:
    """
    Return total size of regular files below folder.
    """
    total_size = 0

    for root, dirs, files in os.walk(folder):
        root_path = Path(root)

        for filename in files:
            file_path = root_path / filename

            try:
                if file_path.is_file():
                    total_size += file_path.stat().st_size
            except OSError:
                continue

    return total_size


# =============================================================================
# Oldest file handling
# =============================================================================

def find_oldest_file(folder: Path):
    """
    Find the oldest regular file below folder.

    Oldest means oldest modification time.
    Folder location does not matter.
    """
    oldest_file = None
    oldest_mtime = None

    for root, dirs, files in os.walk(folder):
        root_path = Path(root)

        for filename in files:
            file_path = root_path / filename

            try:
                if not file_path.is_file():
                    continue

                file_mtime = file_path.stat().st_mtime
            except OSError:
                continue

            if oldest_mtime is None or file_mtime < oldest_mtime:
                oldest_mtime = file_mtime
                oldest_file = file_path

    return oldest_file


def delete_oldest_file(folder: Path):
    """
    Delete the oldest regular file below folder.
    """
    oldest_file = find_oldest_file(folder)

    if oldest_file and oldest_file.is_file():
        print(f"Deleting oldest file: {oldest_file}")

        try:
            oldest_file.unlink()
            return True
        except OSError as error:
            print_and_log(f"Failed to delete file: {oldest_file}")
            print_and_log(f"Error: {error}")
            return False

    print_and_log("No file found or file disappeared.")
    return False


# =============================================================================
# Argument parsing
# =============================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Delete oldest files until mount usage and/or folder size is below limits."
    )

    parser.add_argument(
        "--mount",
        type=Path,
        help="Mount point to check for percentage usage, for example /storage",
    )

    parser.add_argument(
        "--max-mount-usage",
        type=int,
        help="Maximum allowed mount usage percentage, for example 90",
    )

    parser.add_argument(
        "--folder",
        type=Path,
        help="Folder to scan for oldest files and optionally check size",
    )

    parser.add_argument(
        "--max-folder-size",
        type=str,
        help="Maximum allowed folder size, for example 500G, 2T, 100GB",
    )

    parser.add_argument(
        "--max-cycles",
        type=int,
        required=True,
        help="Maximum number of files to delete in one run",
    )

    args = parser.parse_args()

    if args.max_cycles < 1:
        parser.error("--max-cycles must be 1 or higher")

    if args.mount is None and args.folder is None:
        parser.error("You must specify --mount, --folder, or both")

    if args.max_mount_usage is not None and args.mount is None:
        parser.error("--max-mount-usage requires --mount")

    if args.mount is not None and args.max_mount_usage is None:
        parser.error("--mount requires --max-mount-usage")

    if args.max_folder_size is not None and args.folder is None:
        parser.error("--max-folder-size requires --folder")

    if args.folder is not None and not args.folder.is_dir():
        parser.error(f"--folder is not a directory: {args.folder}")

    if args.mount is not None and not args.mount.is_dir():
        parser.error(f"--mount is not a directory: {args.mount}")

    if args.max_mount_usage is not None:
        if args.max_mount_usage < 0 or args.max_mount_usage > 100:
            parser.error("--max-mount-usage must be between 0 and 100")

    if args.max_folder_size is not None:
        try:
            args.max_folder_size_bytes = parse_size(args.max_folder_size)
        except ValueError:
            parser.error(f"Invalid --max-folder-size value: {args.max_folder_size}")

        if args.max_folder_size_bytes < 1:
            parser.error("--max-folder-size must be larger than 0")
    else:
        args.max_folder_size_bytes = None

    # If only mount mode is used, delete from the mount itself.
    # If folder is supplied, delete only from that folder.
    if args.folder is None:
        args.cleanup_folder = args.mount
    else:
        args.cleanup_folder = args.folder

    return args


# =============================================================================
# Cleanup condition check
# =============================================================================

def check_cleanup_needed(args):
    """
    Return True if cleanup is needed.

    Cleanup is needed if either:
      - mount usage is above max mount usage
      - folder size is above max folder size
    """
    cleanup_needed = False

    mount_usage = None
    folder_size = None

    if args.mount is not None:
        mount_usage = get_mount_usage_percent(args.mount)

        if mount_usage is None:
            print_and_log(f"Could not determine disk usage. Check mount path: {args.mount}")
            save_error_log(1)
            sys.exit(1)

        print(f"Mount usage: {mount_usage}% limit: {args.max_mount_usage}%")

        if mount_usage > args.max_mount_usage:
            cleanup_needed = True

    if args.max_folder_size_bytes is not None:
        folder_size = get_folder_size(args.folder)

        print(
            f"Folder size: {format_size(folder_size)} "
            f"limit: {format_size(args.max_folder_size_bytes)}"
        )

        if folder_size > args.max_folder_size_bytes:
            cleanup_needed = True

    return cleanup_needed, mount_usage, folder_size


# =============================================================================
# Main program
# =============================================================================

def main():
    create_lock_or_exit()
    args = parse_args()

    print()
    print(f"DELETE OLD FILES {VERSION}")
    print(f"Cleanup folder     : {args.cleanup_folder}")
    print(f"Max delete cycles  : {args.max_cycles}")

    write_tmp("")
    write_tmp(f"DELETE OLD FILES {VERSION}")
    write_tmp(f"Cleanup folder     : {args.cleanup_folder}")
    write_tmp(f"Max delete cycles  : {args.max_cycles}")

    if args.mount is not None:
        print(f"Mount check        : {args.mount}")
        print(f"Max mount usage    : {args.max_mount_usage}%")
        write_tmp(f"Mount check        : {args.mount}")
        write_tmp(f"Max mount usage    : {args.max_mount_usage}%")

    if args.max_folder_size_bytes is not None:
        print(f"Folder size check  : {args.folder}")
        print(f"Max folder size    : {format_size(args.max_folder_size_bytes)}")
        write_tmp(f"Folder size check  : {args.folder}")
        write_tmp(f"Max folder size    : {format_size(args.max_folder_size_bytes)}")

    print()
    write_tmp("")

    cycles = 0

    while True:
        cleanup_needed, mount_usage, folder_size = check_cleanup_needed(args)

        if not cleanup_needed:
            print("Cleanup limits are OK. Done.")
            remove_tmp_log()
            sys.exit(0)

        if cycles >= args.max_cycles:
            write_tmp(
                f"Reached max cycles ({args.max_cycles}) but cleanup limits are still exceeded."
            )
            remove_tmp_log()
            sys.exit(0)

        if not delete_oldest_file(args.cleanup_folder):
            save_error_log(1)
            sys.exit(1)

        cycles += 1
        print(f"Deleted files this run: {cycles}")
        print()


if __name__ == "__main__":
    main()
