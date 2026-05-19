#!/usr/bin/env python3

###############################################################################
# Purpose:
#   Delete oldest files first until one or more cleanup limits are below the
#   configured thresholds.
#
# WARNING:
#   This script permanently deletes files. Use at your own risk.
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


VERSION = "1.06"
LOCK_FILE = Path("/tmp/CleanUpLockFile-CCTV.lock")

LOCK_CREATED = False
TMP_LOG = None
LOG_FILE = None


# =============================================================================
# Logging setup and helpers
# =============================================================================

def setup_logging():
    """
    Create a temporary log file and define the final error log path.
    """
    global TMP_LOG
    global LOG_FILE

    script_dir = Path(__file__).resolve().parent
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    LOG_FILE = script_dir / f"cleanup-error-{timestamp}.log"

    tmp_fd, tmp_log_name = tempfile.mkstemp()
    os.close(tmp_fd)
    TMP_LOG = Path(tmp_log_name)


def write_tmp(message: str = ""):
    """
    Write a line to the temporary log file.
    """
    if TMP_LOG is None:
        return

    with TMP_LOG.open("a", encoding="utf-8") as logfile:
        logfile.write(message + "\n")


def print_and_log(message: str = ""):
    """
    Print to stdout and also write to the temporary log.
    """
    print(message)
    write_tmp(message)


def remove_tmp_log():
    """
    Remove temporary log file if it still exists.
    """
    if TMP_LOG is None:
        return

    try:
        if TMP_LOG.exists():
            TMP_LOG.unlink()
    except OSError:
        pass


def save_error_log(exit_code: int):
    """
    Save the temporary log as a timestamped error log next to the script.
    """
    if TMP_LOG is None or LOG_FILE is None:
        return

    write_tmp(f"Exit code: {exit_code}")

    try:
        if TMP_LOG.exists():
            shutil.move(str(TMP_LOG), str(LOG_FILE))
    except OSError as error:
        print(f"Failed to save error log: {error}", file=sys.stderr)


# =============================================================================
# Cleanup and signal handling
# =============================================================================

def clean_up():
    """
    Remove the lock file if this script instance created it.
    """
    global LOCK_CREATED

    if LOCK_CREATED and LOCK_FILE.exists():
        try:
            LOCK_FILE.unlink()
        except OSError:
            pass


def signal_handler(signum, frame):
    """
    Handle Ctrl+C, SIGTERM, etc.
    """
    print_and_log(f"Received signal {signum}, exiting.")
    save_error_log(1)
    clean_up()
    sys.exit(1)


atexit.register(clean_up)


# =============================================================================
# Lock file handling
# =============================================================================

def create_lock_or_exit():
    """
    Create a lock file.

    If the lock already exists, exit normally. This prevents multiple cleanup
    jobs from running at the same time.
    """
    global LOCK_CREATED

    if LOCK_FILE.exists():
        write_tmp("Lock file exists, exiting normally.")
        remove_tmp_log()
        sys.exit(0)

    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        LOCK_CREATED = True
    except OSError as error:
        print_and_log("Failed to create lock file, exiting.")
        print_and_log(f"Error: {error}")
        save_error_log(1)
        sys.exit(1)


# =============================================================================
# Size parsing and formatting
# =============================================================================

def parse_size(size_text: str) -> int:
    """
    Convert a human-readable size string to bytes.

    Supported examples:
        500G
        500GB
        500GiB
        2T
        2TB
        100M
        100MB
        123456789

    Units are binary, so:
        1G = 1024 MiB
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
        "P": 1024 ** 5,
        "PB": 1024 ** 5,
        "PIB": 1024 ** 5,
    }

    for unit, multiplier in sorted(units.items(), key=lambda item: len(item[0]), reverse=True):
        if text.endswith(unit):
            number = text[:-len(unit)].strip()
            if not number:
                raise ValueError(f"Missing number before unit in size: {size_text}")
            return int(float(number) * multiplier)

    return int(float(text))


def format_size(num_bytes: int) -> str:
    """
    Format bytes as a human-readable binary size.
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

def get_mount_usage(mount: Path):
    """
    Return filesystem usage information for the filesystem containing mount.

    Returns:
        tuple[int, int, int, int]
        total bytes, used bytes, free bytes, used percentage rounded up
    """
    try:
        usage = shutil.disk_usage(mount)
    except OSError:
        return None

    if usage.total <= 0:
        return None

    used_percent = math.ceil((usage.used / usage.total) * 100)
    return usage.total, usage.used, usage.free, used_percent


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
        description=(
            "Delete oldest files until mount usage, mount used size, and/or "
            "folder size is below configured limits."
        )
    )

    parser.add_argument(
        "--mount",
        type=Path,
        help="Mount point/filesystem to check, for example /storage",
    )

    parser.add_argument(
        "--max-mount-usage",
        type=int,
        help="Maximum allowed mount usage percentage, for example 90",
    )

    parser.add_argument(
        "--max-mount-size",
        type=str,
        help="Maximum allowed used size on the mount/filesystem, for example 500G",
    )

    parser.add_argument(
        "--folder",
        type=Path,
        help=(
            "Folder to scan for oldest files. If --max-folder-size is also used, "
            "this folder size is checked too."
        ),
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

    if args.max_mount_size is not None and args.mount is None:
        parser.error("--max-mount-size requires --mount")

    if args.max_folder_size is not None and args.folder is None:
        parser.error("--max-folder-size requires --folder")

    if args.mount is not None and not args.mount.is_dir():
        parser.error(f"--mount is not a directory: {args.mount}")

    if args.folder is not None and not args.folder.is_dir():
        parser.error(f"--folder is not a directory: {args.folder}")

    if args.max_mount_usage is not None:
        if args.max_mount_usage < 0 or args.max_mount_usage > 100:
            parser.error("--max-mount-usage must be between 0 and 100")

    if args.max_mount_size is not None:
        try:
            args.max_mount_size_bytes = parse_size(args.max_mount_size)
        except ValueError:
            parser.error(f"Invalid --max-mount-size value: {args.max_mount_size}")

        if args.max_mount_size_bytes < 1:
            parser.error("--max-mount-size must be larger than 0")
    else:
        args.max_mount_size_bytes = None

    if args.max_folder_size is not None:
        try:
            args.max_folder_size_bytes = parse_size(args.max_folder_size)
        except ValueError:
            parser.error(f"Invalid --max-folder-size value: {args.max_folder_size}")

        if args.max_folder_size_bytes < 1:
            parser.error("--max-folder-size must be larger than 0")
    else:
        args.max_folder_size_bytes = None

    has_mount_trigger = (
        args.max_mount_usage is not None
        or args.max_mount_size_bytes is not None
    )
    has_folder_trigger = args.max_folder_size_bytes is not None

    if not has_mount_trigger and not has_folder_trigger:
        parser.error(
            "No cleanup limit configured. Use at least one of "
            "--max-mount-usage, --max-mount-size, or --max-folder-size"
        )

    # Safety behavior:
    #   If --folder is supplied, files are deleted only from that folder.
    #   If --folder is not supplied, files are deleted from --mount.
    if args.folder is not None:
        args.cleanup_folder = args.folder
    else:
        args.cleanup_folder = args.mount

    return args


# =============================================================================
# Cleanup condition check
# =============================================================================

def check_cleanup_needed(args):
    """
    Return True if cleanup is needed.

    Cleanup is needed if any configured limit is exceeded:
      - mount usage percentage is above --max-mount-usage
      - mount used size is above --max-mount-size
      - folder size is above --max-folder-size
    """
    cleanup_needed = False

    if args.mount is not None:
        mount_usage = get_mount_usage(args.mount)

        if mount_usage is None:
            print_and_log(f"Could not determine disk usage. Check mount path: {args.mount}")
            save_error_log(1)
            sys.exit(1)

        total_bytes, used_bytes, free_bytes, used_percent = mount_usage

        if args.max_mount_usage is not None:
            print(f"Mount usage: {used_percent}% limit: {args.max_mount_usage}%")

            if used_percent > args.max_mount_usage:
                cleanup_needed = True

        if args.max_mount_size_bytes is not None:
            print(
                f"Mount used size: {format_size(used_bytes)} "
                f"limit: {format_size(args.max_mount_size_bytes)}"
            )

            if used_bytes > args.max_mount_size_bytes:
                cleanup_needed = True

    if args.max_folder_size_bytes is not None:
        folder_size = get_folder_size(args.folder)

        print(
            f"Folder size: {format_size(folder_size)} "
            f"limit: {format_size(args.max_folder_size_bytes)}"
        )

        if folder_size > args.max_folder_size_bytes:
            cleanup_needed = True

    return cleanup_needed


# =============================================================================
# Main program
# =============================================================================

def main():
    args = parse_args()

    setup_logging()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    create_lock_or_exit()

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
        write_tmp(f"Mount check        : {args.mount}")

    if args.max_mount_usage is not None:
        print(f"Max mount usage    : {args.max_mount_usage}%")
        write_tmp(f"Max mount usage    : {args.max_mount_usage}%")

    if args.max_mount_size_bytes is not None:
        print(f"Max mount size     : {format_size(args.max_mount_size_bytes)}")
        write_tmp(f"Max mount size     : {format_size(args.max_mount_size_bytes)}")

    if args.folder is not None:
        print(f"Folder             : {args.folder}")
        write_tmp(f"Folder             : {args.folder}")

    if args.max_folder_size_bytes is not None:
        print(f"Max folder size    : {format_size(args.max_folder_size_bytes)}")
        write_tmp(f"Max folder size    : {format_size(args.max_folder_size_bytes)}")

    print()
    write_tmp("")

    cycles = 0

    while True:
        cleanup_needed = check_cleanup_needed(args)

        if not cleanup_needed:
            print("Cleanup limits are OK. Done.")
            remove_tmp_log()
            sys.exit(0)

        if cycles >= args.max_cycles:
            print(
                f"Reached max cycles ({args.max_cycles}) "
                "but one or more cleanup limits are still exceeded."
            )
            write_tmp(
                f"Reached max cycles ({args.max_cycles}) "
                "but one or more cleanup limits are still exceeded."
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
