"""
Copyright (c) 2013-present Matic Kukovec.
Released under the GNU GPL3 license.

For more information check the 'LICENSE.txt' file.
For complete license information of the dependencies, check the 'additional_licenses' directory.

Code-formatting and analysis tools.

Wraps formatters (black, autopep8, clang-format, zig, nim) and
linters (ruff, pyflakes). Also manages the file-system path watcher.
Namespace class attached to the MainWindow instance.
"""

import os
from typing import Any, Optional

import qt
import constants
import data
from components.pathwatcher import FileEvent, PathWatcher


class Tools:
    """
    Helper functions for everything
    """

    # Class variables
    _parent: "MainWindow"
    path_watcher: PathWatcher

    def __init__(self, parent: "MainWindow") -> None:
        """
        Initialization of the Tools object instance
        """
        # Get the reference to the MainWindow parent object instance
        self._parent = parent

        # Debounce timers: normalized path → single-shot QTimer
        self._reload_timers: dict[str, qt.QTimer] = {}

        # Initialize the file-system watcher
        self.path_watcher = PathWatcher()
        self.path_watcher.file_changed.connect(self.__file_change_handler)
        data.signal_dispatcher.editor_initialized.connect(self.pathwatcher_add)
        data.signal_dispatcher.editor_file_saved_as.connect(self.pathwatcher_add)
        data.signal_dispatcher.editor_deleted.connect(self.pathwatcher_remove)

    def _schedule_reload(self, path: str) -> None:
        normalized = os.path.normpath(os.path.normcase(path))
        timer = self._reload_timers.get(normalized)
        if timer is not None:
            timer.stop()
        else:
            timer = qt.QTimer(self._parent)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda p=normalized: self._do_reload(p))
            self._reload_timers[normalized] = timer
        timer.start(200)

    def _do_reload(self, normalized_path: str) -> None:
        self._reload_timers.pop(normalized_path, None)
        editors = self._parent.get_all_editors()
        for e in editors:
            try:
                e_path_normalized = os.path.normpath(os.path.normcase(e.save_path))
                if e_path_normalized == normalized_path:
                    e.reload_file()
                    break
            except Exception:
                pass

    def __file_change_handler(
        self,
        event_type: FileEvent,
        source: str,
        destination: Optional[str],
        modification_time: Optional[float],
    ) -> None:
        """Handle all file events with consistent signature."""

        match event_type:
            case FileEvent.CREATED:
                self._schedule_reload(source)

            case FileEvent.MODIFIED:
                self._schedule_reload(source)

            case FileEvent.DELETED:
                # Intentionally a no-op. See pathwatcher.py:__handle_change for
                # the rationale — the file stays in monitoring so CREATED events
                # from atomic-write tools trigger reload.
                #
                # Previously this loop found the matching editor and called
                # _signal_text_changed(e) which set save_status=MODIFIED and
                # added "*" to the tab name. This was wrong because:
                #
                # 1. External formatters use atomic-write (delete + create).
                #    The DELETED is transient — the file is re-created in
                #    milliseconds. The "*" was a false positive.
                #
                # 2. Setting save_status=MODIFIED here caused reload_file() to
                #    prompt "File modified, reload anyway?" when the subsequent
                #    CREATED handler tried to reload. The prompt was spurious
                #    since the user never touched the editor.
                #
                # True deletions (not followed by CREATED) are surfaced when
                # the user attempts to save — the OS returns a file-not-found
                # error, which is clearer than a silent "*" marker.
                pass

            case FileEvent.MOVED:
                editors = self._parent.get_all_editors()
                for e in editors:
                    try:
                        if e.save_path == source or e.save_path == destination:
                            e.reload_file()
                    except Exception:
                        pass

            case FileEvent.RENAME:
                editors = self._parent.get_all_editors()
                for e in editors:
                    try:
                        if e.save_path == source:
                            e.save_path = destination
                            stacked_widget = e.parent()
                            tab_widget = stacked_widget.parent()
                            if hasattr(tab_widget, "setTabText"):
                                index = tab_widget.indexOf(e)
                                if index != -1:
                                    tab_widget.setTabText(index, os.path.basename(destination))
                            e.reload_file()
                            break
                    except Exception:
                        pass

            case _:
                raise Exception(f"Unknown FileEvent: {event_type}")

    def pathwatcher_add(self, path: str) -> bool:
        return self.path_watcher.add_file(path)

    def pathwatcher_remove(self, path: str) -> bool:
        normalized = os.path.normpath(os.path.normcase(path))
        timer = self._reload_timers.pop(normalized, None)
        if timer is not None:
            timer.stop()
        return self.path_watcher.remove_file(path)

    def pretty_print_text(self, _type: constants.FormatterType, **kwargs: Any) -> None:
        import components.codequality

        tab = self._parent.get_tab_by_indication()

        if not hasattr(tab, "text"):
            self._parent.display.repl_display_error(
                f"Indicated tab is not an editor! ('{tab.__class__.__name__}')"
            )
            return

        if _type == constants.FormatterType.JSON:
            prettyfied_string = components.codequality.pretty_print_json(tab.text(), **kwargs)
        elif _type == constants.FormatterType.XML:
            prettyfied_string = components.codequality.pretty_print_xml(tab.text(), **kwargs)
        elif _type == constants.FormatterType.HTML_Python_Standard_Library:
            prettyfied_string = components.codequality.pretty_print_html_python_stdlib(tab.text())
        elif _type == constants.FormatterType.HTML_BeautifulSoup:
            prettyfied_string = components.codequality.custom_format_html_document_beautifulsoup(
                tab.text(), **kwargs
            )
        else:
            self._parent.display.repl_display_error(f"Unknown pretty_print type: '{_type}'")
            return

        tab.set_all_text(prettyfied_string)

    def format_python_all_text(self, library: str) -> None:
        import components.codequality

        tab = self._parent.get_tab_by_indication()

        if not hasattr(tab, "text"):
            self._parent.display.repl_display_error(
                f"Indicated tab is not an editor! ('{tab.__class__.__name__}')"
            )
            return

        first_line: int = tab.firstVisibleLine()
        cursor_line: int
        cursor_index: int
        cursor_line, cursor_index = tab.getCursorPosition()
        code: str = tab.text()

        formatted_code: str = components.codequality.format_python_code(code, library)

        tab.set_all_text(formatted_code)

        tab.setCursorPosition(cursor_line, cursor_index)
        tab.setFirstVisibleLine(first_line)

    def format_python_selected_text(self, library: str) -> None:
        import components.codequality

        tab = self._parent.get_tab_by_indication()

        if not hasattr(tab, "selectedText") or not hasattr(tab, "hasSelectedText"):
            self._parent.display.repl_display_error(
                f"Indicated tab is not an editor! ('{tab.__class__.__name__}')"
            )
            return
        elif not tab.hasSelectedText():
            self._parent.display.repl_display_error("No text selected in the editor!)")
            return

        code: str = tab.selectedText()

        formatted_code: str = components.codequality.format_python_code(code, library)

        tab.replaceSelectedText(formatted_code)

    def format_c_cpp_all_text(self, library: str, style: Optional[str] = "LLVM") -> None:
        import components.codequality

        tab = self._parent.get_tab_by_indication()

        if not hasattr(tab, "text"):
            self._parent.display.repl_display_error(
                f"Indicated tab is not an editor! ('{tab.__class__.__name__}')"
            )
            return

        first_line: int = tab.firstVisibleLine()
        cursor_line: int
        cursor_index: int
        cursor_line, cursor_index = tab.getCursorPosition()
        code: str = tab.text()

        if library == "clang-format":
            formatted_code: str = components.codequality.format_clangformat_c_cpp(
                source_code=code, style=style
            )

        else:
            raise Exception(f"[C/C++-FORMATTING] Unknown foramtter library selected: '{library}'")

        tab.set_all_text(formatted_code)

        tab.setCursorPosition(cursor_line, cursor_index)
        tab.setFirstVisibleLine(first_line)

    def format_zig_all_text(
        self,
    ) -> None:
        import components.codequality

        tab = self._parent.get_tab_by_indication()

        if not hasattr(tab, "text"):
            self._parent.display.repl_display_error(
                f"Indicated tab is not an editor! ('{tab.__class__.__name__}')"
            )
            return

        first_line: int = tab.firstVisibleLine()
        cursor_line: int
        cursor_index: int
        cursor_line, cursor_index = tab.getCursorPosition()
        code: str = tab.text()

        formatted_code: str = components.codequality.format_zig_code(zig_code_string=code)

        tab.set_all_text(formatted_code)

        tab.setCursorPosition(cursor_line, cursor_index)
        tab.setFirstVisibleLine(first_line)

    def format_nim_file(
        self,
    ) -> None:
        import components.codequality

        tab = self._parent.get_tab_by_indication()

        if not hasattr(tab, "save_path"):
            self._parent.display.repl_display_error(
                f"Indicated tab is not an editor! ('{tab.__class__.__name__}')"
            )
            return

        first_line: int = tab.firstVisibleLine()
        cursor_line: int
        cursor_index: int
        cursor_line, cursor_index = tab.getCursorPosition()
        nim_file_path: str = tab.save_path

        components.codequality.format_nim_file(file_path=nim_file_path)

        tab.setCursorPosition(cursor_line, cursor_index)
        tab.setFirstVisibleLine(first_line)

    def analyze_python_file(self, library: str) -> None:
        import components.codequality

        tab = self._parent.get_tab_by_indication()

        if not hasattr(tab, "save_path"):
            self._parent.display.repl_display_error(
                f"Indicated tab is not an editor! ('{tab.__class__.__name__}')"
            )
            return

        file_path: str = tab.save_path

        if library == "ruff":
            exit_code: int
            analysis_results_or_error: str
            exit_code, analysis_results_or_error = components.codequality.analyze_ruff_file(
                file_path
            )
            if exit_code != 0:
                self._parent.display.repl_display_message("Ruff results:")
                self._parent.display.repl_display_message(analysis_results_or_error)
            else:
                self._parent.display.repl_display_success("Ruff says everything is ok.")

        elif library == "pyflakes":
            exit_code: int
            stdout: str
            stderr: str
            exit_code, stdout, stderr = components.codequality.analyze_pyflakes_file(file_path)
            if exit_code != 0:
                self._parent.display.repl_display_message("Pyflakes results:")
                self._parent.display.repl_display_message(stdout)
            else:
                self._parent.display.repl_display_success("Pyflakes says everything is ok.")

        else:
            raise Exception(f"[PYTHON-ANALYZING] Unknown analyzer library selected: '{library}'")
