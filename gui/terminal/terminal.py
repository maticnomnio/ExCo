"""
Copyright (c) 2013-present Matic Kukovec.
Released under the GNU GPL3 license.

For more information check the 'LICENSE.txt' file.
For complete license information of the dependencies, check the 'additional_licenses' directory.
"""

import os
import threading
import time
import traceback
from typing import Any, List, Optional, Union
from urllib.parse import ParseResult, unquote, urlparse

import components.internals
import constants
import data
import functions
import pyte
import qt
import settings

from gui.terminal.backend import TerminalBackend, create_terminal_backend
from gui.terminal.screen import ExtendedScreen, ExtendedStream
from gui.terminal.view import TerminalView


class Terminal(qt.QWidget):
    pty_data_received = qt.pyqtSignal(object)
    pty_add_to_buffer = qt.pyqtSignal(object)
    title_changed = qt.pyqtSignal(str)
    process_exited = qt.pyqtSignal()

    # Class variables
    name: Optional[str] = None
    _parent: Any = None
    main_form: Any = None
    current_icon: Optional[qt.QIcon] = None
    savable: int = constants.CanSave.NO
    save_name: Optional[str] = None
    # Reference to the custom context menu
    context_menu: Any = None
    current_working_directory: Optional[str] = None

    def __init__(
        self,
        parent: Optional[qt.QWidget],
        main_form: Any,
        name: str,
        shell: Optional[Union[str, List[str]]] = None,
    ) -> None:
        super().__init__(parent)
        self.name = name
        self._parent = parent
        self.main_form = main_form
        self.current_icon = functions.create_icon("tango_icons/utilities-terminal.png")

        # Initialize components
        self.internals: components.internals.Internals = components.internals.Internals(
            parent=self, tab_widget=parent
        )

        CONSOLE_WIDTH: int = 120
        CONSOLE_HEIGHT: int = 26

        # 'screen' also names a QWidget method; the attribute shadows it.
        self.screen: ExtendedScreen = ExtendedScreen(  # type: ignore[assignment]
            CONSOLE_WIDTH,
            CONSOLE_HEIGHT,
            history=settings.get("terminal-history"),
            ratio=0.1,
        )
        self.screen.set_mode(pyte.modes.DECAWM)
        self.stream: ExtendedStream = ExtendedStream(self.screen)

        self.backend: Optional[TerminalBackend] = create_terminal_backend(
            shell=shell,
            dimensions=(CONSOLE_HEIGHT, CONSOLE_WIDTH),
        )
        self.backend.spawn()

        self._process_exited: bool = False
        self._last_title: Optional[str] = None
        self.process_exited.connect(self.__process_exited)

        self.pty_data_received.connect(self.__stdout_received)
        self.pty_add_to_buffer.connect(self.__send_buffer)
        # Reading
        self.__thread_pty_read: threading.Thread = threading.Thread(
            target=self.__pty_read_loop,
            args=[],
            daemon=True,
        )
        self.__thread_pty_read.start()

        # Create the terminal rendering widget
        self.view: TerminalView = TerminalView(self, self)
        self.view.send_text.connect(self.__input_sent)
        self.view.resize_event.connect(self.__resize_event)
        self.view.paste_event.connect(self.__paste_event)
        self.view.focused.connect(self.__view_focused)
        # Route keyboard focus straight to the view: this widget only
        # contains the view, and container focus would let Tab/keys fall
        # through to base QWidget handling (focus navigation).
        self.setFocusProxy(self.view)

        # Add the widgets to a vertical layout
        layout = qt.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view)

        self.update_style()

    def __del__(self) -> None:
        try:
            backend: Optional[TerminalBackend] = getattr(self, "backend", None)
            if backend is not None:
                try:
                    backend.close()
                except Exception:
                    pass
            view: Optional[TerminalView] = getattr(self, "view", None)
            if view is not None:
                try:
                    view.setParent(None)
                except RuntimeError:
                    pass
        except Exception:
            pass

    def __pty_read_loop(self) -> None:
        while True:
            backend: Optional[TerminalBackend] = self.backend
            if backend is None or not backend.isalive():
                self._mark_process_exited()
                break
            try:
                data = backend.read()
            except EOFError:
                self._mark_process_exited()
                break
            except Exception:
                traceback.print_exc()
                time.sleep(0.001)
                continue
            if data is not None and data != b"" and data != "":
                self.pty_add_to_buffer.emit(data)
            else:
                time.sleep(0.001)

    def _mark_process_exited(self) -> None:
        if self._process_exited:
            return
        self._process_exited = True
        try:
            self.process_exited.emit()
        except RuntimeError:
            pass

    def __process_exited(self) -> None:
        # The shell has terminated; close the terminal tab (if any) so the
        # dead tab does not linger and accept input.
        try:
            parent: Any = getattr(self, "_parent", None)
            if parent is not None and hasattr(parent, "close_tab"):
                parent.close_tab(self)
        except Exception:
            pass

    def __send_buffer(self, new_data: Union[bytes, str]) -> None:
        if len(new_data) > 0:
            if isinstance(new_data, bytes):
                joined_buffer: Union[bytes, str] = new_data
            elif isinstance(new_data, str):
                joined_buffer = new_data
            else:
                raise Exception("Unknown type: '{}'".format(new_data.__class__))
        else:
            joined_buffer = b""
        self.pty_data_received.emit(joined_buffer)

    @qt.pyqtSlot(object)
    def __stdout_received(self, raw_text: object) -> None:
        try:
            if isinstance(raw_text, bytes):
                self.stream.feed(raw_text.decode("utf-8"))
            elif isinstance(raw_text, str):
                self.stream.feed(raw_text)
        except Exception:
            traceback.print_exc()
        # Surface OSC title changes
        if self.screen.title != getattr(self, "_last_title", None):
            self._last_title = self.screen.title
            if self.screen.title:
                self.title_changed.emit(self.screen.title)
        # Surface OSC 7 cwd, fall back to prompt parsing
        if self.screen.cwd:
            try:
                parsed: ParseResult = urlparse(self.screen.cwd)
                path: str = unquote(parsed.path)
                if parsed.netloc and parsed.netloc.lower() != "localhost":
                    path = "//" + parsed.netloc + path
                if (
                    data.on_windows
                    and path.startswith("/")
                    and len(path) > 2
                    and path[1:2].isalpha()
                ):
                    path = path[1:]
                if os.path.isdir(path):
                    self.current_working_directory = path
            except:
                traceback.print_exc()
        # Surface the bell (visual flash)
        if self.screen.bell_triggered:
            self.screen.bell_triggered = False
            self.view.flash()
        # Parse the current working directory from the prompt, if possible
        self._parse_cwd()
        # Schedule a repaint of the changed screen lines
        self.view.schedule_repaint()

    def _parse_cwd(self) -> None:
        try:
            screen: ExtendedScreen = self.screen
            for y in range(screen.lines):
                line: str = "".join(
                    screen.buffer[y][x].data for x in range(screen.columns)
                )
                stripped_line: str = line.strip()
                if stripped_line.endswith(">"):
                    # Windows Console
                    if stripped_line.startswith("PS "):
                        stripped_line = stripped_line[3:]
                    directory: str = stripped_line.replace(">", "")
                    if os.path.isdir(directory):
                        self.current_working_directory = directory
                elif stripped_line.endswith("$"):
                    # Bash: "user@host:/path$"
                    parts: List[str] = stripped_line[:-1].split(":", 1)
                    if len(parts) != 2:
                        continue
                    directory = parts[1].strip()
                    if os.path.isdir(directory):
                        self.current_working_directory = directory
        except:
            traceback.print_exc()

    def __input_sent(self, text: str) -> None:
        if self._process_exited:
            # The shell has already terminated; drop the input instead of
            # failing on a closed PTY.
            return
        backend: Optional[TerminalBackend] = self.backend
        if backend is None:
            return
        try:
            backend.write(text)
        except Exception as ex:
            self.main_form.display.repl_display_error(
                "Terminal has probably already been closed,"
                + "the process returned: '{}'".format(ex)
            )

    def __view_focused(self) -> None:
        try:
            self.main_form.view.indication_check()
        except Exception:
            pass

    def __resize_event(self, width: int, height: int) -> None:
        try:
            if data.on_windows:
                # ConPTY reports one column fewer than the viewport; keep the
                # PTY one column larger so the last column is usable.
                width -= 1
            else:
                # X11/Unix terminals commonly report one row and column fewer
                # than the pixel-derived grid.
                width -= 1
                height -= 1
            width = max(width, 1)
            height = max(height, 1)
            self.screen.resize(height, width)
            self.view.update()
            backend: Optional[TerminalBackend] = self.backend
            if backend is not None:
                backend.setwinsize(height, width)
        except:
            pass

    def __paste_event(self, paste_text: str) -> None:
        if self._process_exited:
            # The shell has already terminated; drop the paste.
            self.view.setFocus()
            return
        backend: Optional[TerminalBackend] = self.backend
        if backend is not None:
            try:
                # Lone-surrogate clipboard text cannot be UTF-8 encoded;
                # replace the unencodable characters instead of crashing the
                # slot.
                sanitized: str = paste_text.encode("utf-8", errors="replace").decode(
                    "utf-8"
                )
                backend.write(sanitized)
            except Exception as ex:
                self.main_form.display.repl_display_error(
                    "Terminal has probably already been closed,"
                    + "the process returned: '{}'".format(ex)
                )
        self.view.setFocus()

    def execute_command(self, command: str) -> None:
        if self._process_exited:
            return
        backend: Optional[TerminalBackend] = self.backend
        if backend is not None:
            backend.write(command + "\r\n")

    def get_cwd(self) -> Optional[str]:
        return self.current_working_directory

    def set_cwd(self, directory: str) -> None:
        # Quote the directory so paths containing spaces survive the shell
        # (cmd, PowerShell and bash all accept double-quoted paths).
        self.execute_command('cd "{}"'.format(directory))

    def setFocus(
        self, reason: qt.Qt.FocusReason = qt.Qt.FocusReason.NoFocusReason
    ) -> None:
        """
        Overridden focus event
        """
        self.view.setFocus()

    def hasFocus(self) -> bool:
        return self.view.hasFocus()

    def update_style(self) -> None:
        self.setStyleSheet(
            f"""
QWidget {{
    background: transparent;
    border: none;
    margin: 0px;
    spacing: 0px;
    padding: 0px;
}}
        """
        )
        self.view.update_style()

    def set_theme(self, theme: Any) -> None:
        # Matches the editor widgets' set_theme contract so the theme
        # refresh dispatch picks the terminal up; colors are re-read from
        # settings inside update_style().
        self.update_style()
