"""
Copyright (c) 2013-present Matic Kukovec.
Released under the GNU GPL3 license.

For more information check the 'LICENSE.txt' file.
For complete license information of the dependencies, check the 'additional_licenses' directory.
"""

import enum
import os
import threading
from typing import List, Optional, Set

import functions
import qt
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer


class FileEvent(enum.Enum):
    """
    Enumeration of all possible file system events.
    """

    MODIFIED = enum.auto()
    CREATED = enum.auto()
    DELETED = enum.auto()
    MOVED = enum.auto()
    RENAME = enum.auto()


class PathWatcher(qt.QObject):
    """
    A class to monitor file system changes for specific files using watchdog.
    Files can be dynamically added and removed from monitoring.
    """

    # Define a custom signal that matches the callback's signature
    file_changed = qt.pyqtSignal(object, str, object, object)

    ECHO_ENABLED: bool = False  # Class variable to control echo output

    def __init__(self, parent: Optional[qt.QObject] = None) -> None:
        """
        Initialize the PathWatcher.
        """
        super().__init__(parent)
        self.monitored_files: Set[str] = set()  # Set of files being monitored
        self._files_by_directory = {}  # Directory -> files mapping for O(1) lookups
        self.observers = {}  # Dictionary mapping directory paths to observers
        self._lock: threading.Lock = threading.Lock()  # Thread safety for file list operations
        self._is_stopping: threading.Event = (
            threading.Event()
        )  # Signals that monitoring is stopping

    def echo(self, *messages: str) -> None:
        """Print a message only if ECHO_ENABLED is True."""
        if self.ECHO_ENABLED:
            print(f"[{self.__class__.__name__}]", *messages)

    def _is_stopping_active(self) -> bool:
        """Check if stopping is in progress."""
        return self._is_stopping.is_set()

    def _set_stopping(self) -> None:
        """Signal that monitoring is stopping."""
        self._is_stopping.set()

    def _reset_stopping(self) -> None:
        """Reset the stopping flag."""
        self._is_stopping.clear()

    def add_file(self, file_path: str) -> bool:
        """
        Add a file to the monitoring list.

        Args:
            file_path: Path to the file to monitor

        Returns:
            True if file was added successfully, False otherwise
        """
        file_path = functions.normalize_path(file_path)
        directory = os.path.dirname(file_path)

        if os.path.isabs(file_path) and file_path.startswith("/"):
            self.echo(f"Skipping WSL/unix path (not accessible via Windows APIs): {file_path}")
            return False

        if not os.path.isdir(directory):
            self.echo(f"Directory {directory} does not exist")
            return False

        with self._lock:
            if file_path in self.monitored_files:
                self.echo(f"File {file_path} is already being monitored")
                return False

            self.monitored_files.add(file_path)

            # Track file by directory for O(1) lookups
            if directory not in self._files_by_directory:
                self._files_by_directory[directory] = set()
            self._files_by_directory[directory].add(file_path)

            # If we're not already watching this directory, start watching it
            if directory not in self.observers:
                try:
                    self._start_watching_directory(directory)
                except BaseException as ex:
                    self.echo(f"Failed to start watching {directory}: {ex}")
                    self.monitored_files.discard(file_path)
                    self._files_by_directory[directory].discard(file_path)
                    if not self._files_by_directory[directory]:
                        del self._files_by_directory[directory]
                    return False

            self.echo(f"Added {file_path} to monitoring list")
            return True

    def remove_file(self, file_path: str) -> bool:
        """
        Remove a file from the monitoring list.

        Args:
            file_path: Path to the file to stop monitoring

        Returns:
            True if file was removed successfully, False otherwise
        """
        file_path = functions.normalize_path(file_path)

        dir_to_stop = None
        with self._lock:
            if file_path not in self.monitored_files:
                self.echo(f"File {file_path} is not being monitored")
                return False

            directory = os.path.dirname(file_path)
            self.monitored_files.remove(file_path)

            # Use directory mapping for O(1) lookup
            if directory in self._files_by_directory:
                self._files_by_directory[directory].discard(file_path)
                if not self._files_by_directory[directory]:
                    del self._files_by_directory[directory]

            still_needed = directory in self._files_by_directory and bool(
                self._files_by_directory[directory]
            )

            if not still_needed and directory in self.observers:
                dir_to_stop = directory

        if dir_to_stop:
            self._stop_watching_directory(dir_to_stop)

        self.echo(f"Removed {file_path} from monitoring list")
        return True

    def get_monitored_files(self) -> List[str]:
        """
        Get a copy of the list of monitored files.

        Returns:
            Copy of the monitored files list
        """
        with self._lock:
            return list(self.monitored_files)

    def clear_all_files(self) -> None:
        """Remove all files from monitoring and stop all observers."""
        self._set_stopping()  # Signal to callbacks first
        dirs_to_stop = []
        with self._lock:
            for directory in list(self.observers.keys()):
                dirs_to_stop.append(directory)
            self.monitored_files.clear()
            self._files_by_directory.clear()

        for directory in dirs_to_stop:
            self._stop_watching_directory(directory)
        self.echo("Cleared all monitored files")

    def _start_watching_directory(self, directory: str) -> None:
        """Start watching a directory with a new observer."""
        self._reset_stopping()
        directory = functions.normalize_path(directory)
        handler: FileChangeHandler = FileChangeHandler(self)
        observer = Observer()

        # Track that we are about to start it
        self.observers[directory] = observer

        try:
            observer.schedule(handler, directory, recursive=False)
            observer.start()
            self.echo(f"Started watching directory: {directory}")
        except Exception as e:
            self.echo(f"Failed to start watching {directory}: {e}")
            # Clean up if failed
            try:
                observer.stop()
                observer.join()
            except Exception:
                pass
            del self.observers[directory]
            raise

    def _stop_watching_directory(self, directory: str) -> None:
        """Stop watching a directory and clean up the observer."""
        observer = self.observers.pop(directory, None)
        if observer:
            try:
                observer.stop()
                observer.join()
                self.echo(f"Stopped watching directory: {directory}")
            except Exception as e:
                self.echo(f"Error while stopping observer for {directory}: {e}")

    def _handle_file_event(
        self,
        event_type: FileEvent,
        source_path: str,
        destination_path: Optional[str],
        modification_time: Optional[float],
    ) -> None:
        """
        Handle a file system event for one of our monitored files.

        Args:
            event_type: Type of event (FileEvent enum value)
            source_path: Source path of the file
            destination_path: Destination path (only for MOVED events)
        """
        if destination_path:
            self.echo(f"File {event_type.name}: {source_path} -> {destination_path}")
        else:
            self.echo(f"File {event_type.name}: {source_path}")

        # Call the callback if provided
        self.file_changed.emit(event_type, source_path, destination_path, modification_time)

    def stop_monitoring(self) -> None:
        """Stop all monitoring and clean up resources."""
        self._set_stopping()  # Signal to callbacks first
        dirs_to_stop = []
        with self._lock:
            for directory in list(self.observers.keys()):
                dirs_to_stop.append(directory)

        for directory in dirs_to_stop:
            self._stop_watching_directory(directory)
        self.echo("Stopped all monitoring")

    def update_file_path(self, old_path: str, new_path: str) -> bool:
        """
        Update a monitored file path (useful for external move operations).

        Args:
            old_path: Current path being monitored
            new_path: New path to monitor instead

        Returns:
            True if update was successful, False otherwise
        """
        old_path = functions.normalize_path(old_path)
        new_path = functions.normalize_path(new_path)
        new_directory = os.path.dirname(new_path)

        if os.path.isabs(new_path) and new_path.startswith("/"):
            self.echo(f"Skipping WSL/unix path (not accessible via Windows APIs): {new_path}")
            return False

        if not os.path.isdir(new_directory):
            self.echo(f"Directory {new_directory} does not exist")
            return False

        with self._lock:
            if old_path not in self.monitored_files:
                self.echo(f"File {old_path} is not being monitored")
                return False

            if new_path in self.monitored_files:
                self.echo(f"File {new_path} is already being monitored")
                return False

            old_directory = os.path.dirname(old_path)
            self.monitored_files.remove(old_path)
            self.monitored_files.add(new_path)

            # Update directory mapping
            old_directory = os.path.dirname(old_path)

            if old_directory in self._files_by_directory:
                self._files_by_directory[old_directory].discard(old_path)
                if not self._files_by_directory[old_directory]:
                    del self._files_by_directory[old_directory]

            if new_directory not in self._files_by_directory:
                self._files_by_directory[new_directory] = set()
            self._files_by_directory[new_directory].add(new_path)

            # Stop watching old directory if no longer needed
            still_needed_old = old_directory in self._files_by_directory and bool(
                self._files_by_directory[old_directory]
            )
            dir_to_stop = None
            if not still_needed_old and old_directory in self.observers:
                dir_to_stop = old_directory

            # Start watching new directory if needed
            dir_to_start = None
            if new_directory not in self.observers:
                dir_to_start = new_directory

        # Perform observer changes outside the lock to avoid deadlocks
        if dir_to_stop:
            self._stop_watching_directory(dir_to_stop)

        if dir_to_start:
            try:
                self._start_watching_directory(dir_to_start)
            except BaseException as ex:
                self.echo(f"Failed to start watching {dir_to_start}: {ex}")
                # Rollback file tracking changes
                with self._lock:
                    self.monitored_files.discard(new_path)
                    self._files_by_directory[new_directory].discard(new_path)
                    if not self._files_by_directory.get(new_directory):
                        del self._files_by_directory[new_directory]
                return False

        self.echo(f"Updated file path: {old_path} -> {new_path}")
        return True


class FileChangeHandler(FileSystemEventHandler):
    """Event handler for watchdog that filters events to only monitored files."""

    def __init__(self, path_watcher: PathWatcher) -> None:
        self.path_watcher: PathWatcher = path_watcher
        super().__init__()

    def echo(self, *messages: str) -> None:
        """Print a message only if ECHO_ENABLED is True."""
        if PathWatcher.ECHO_ENABLED:
            print(f"[{self.__class__.__name__}]", *messages)

    def __handle_change(
        self,
        event_type: FileEvent,
        source_path: str,
        destination_path: Optional[str] = None,
    ) -> None:
        """
        Handle a file system event for a monitored file.
        Called from the watchdog observer thread.
        """
        if self.path_watcher._is_stopping_active():
            return

        source_path = functions.normalize_path(source_path)

        # Early return if not monitored to avoid expensive syscalls
        with self.path_watcher._lock:
            if source_path not in self.path_watcher.monitored_files:
                self.echo(f"Ignored unmonitored file: {source_path}")
                return

        if event_type == FileEvent.DELETED:
            # DO NOT remove file from monitored_files here.
            #
            # Many external tools (formatters, editors, linters) use atomic-write:
            #   1. write content to a temp file
            #   2. rename/move temp over original
            # This generates a DELETED event (step 2 removes the original inode)
            # followed almost immediately by a CREATED event (new file at same path).
            #
            # Previously we discarded the path from monitored_files on DELETED,
            # which caused the subsequent CREATED event to be ignored (the file
            # wasn't in the monitored set anymore). Result: the editor never
            # reloaded and the tab got marked with "*" incorrectly.
            #
            # By keeping the path in monitored_files, the CREATED event flows
            # through normally and the editor reloads from the new file content.
            # The file entry is properly cleaned up when the editor tab closes
            # (via PathWatcher.remove_file called from editor_deleted signal).
            #
            # Downside: if a file is truly deleted and never re-created, the
            # monitored_files entry is stale until the editor closes. This is
            # an acceptable resource cost (one string per open file) that avoids
            # the far worse UX of silent stale content after atomic writes.
            self.path_watcher._handle_file_event(FileEvent.DELETED, source_path, None, None)
            self.echo(f"File deleted: {source_path}")
            return

        mtime: Optional[float] = None
        try:
            mtime = os.path.getmtime(source_path)
        except (FileNotFoundError, PermissionError) as e:
            self.echo(f"Could not access mtime for {source_path}: {e}")
            if not os.path.exists(source_path):
                self.path_watcher._handle_file_event(FileEvent.DELETED, source_path, None, None)
                return

        self.path_watcher._handle_file_event(event_type, source_path, destination_path, mtime)
        self.echo(f"Handled change event: {event_type.name} on {source_path} with mtime {mtime}")

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            src_path = (
                event.src_path.decode("utf-8")
                if isinstance(event.src_path, bytes)
                else event.src_path
            )
            self.__handle_change(FileEvent.MODIFIED, src_path, None)

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            src_path = (
                event.src_path.decode("utf-8")
                if isinstance(event.src_path, bytes)
                else event.src_path
            )
            self.__handle_change(FileEvent.CREATED, src_path, None)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            src_path = (
                event.src_path.decode("utf-8")
                if isinstance(event.src_path, bytes)
                else event.src_path
            )
            self.__handle_change(FileEvent.DELETED, src_path, None)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            src_path = (
                event.src_path.decode("utf-8")
                if isinstance(event.src_path, bytes)
                else event.src_path
            )
            dest_path = (
                event.dest_path.decode("utf-8")
                if isinstance(event.dest_path, bytes)
                else event.dest_path
            )
            self.__handle_change(FileEvent.MOVED, src_path, dest_path)
