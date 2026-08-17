"""
Copyright (c) 2013-present Matic Kukovec.
Released under the GNU GPL3 license.

For more information check the 'LICENSE.txt' file.
For complete license information of the dependencies, check the 'additional_licenses' directory.
"""

##  FILE DESCRIPTION:
##      Pluggable PTY backends for the integrated terminal emulator.
##      Windows uses ConPTY (via pywinpty), Linux uses ptyprocess.

import os
from typing import Any, Dict, List, Optional, Tuple, Union

import data
import settings


def get_default_shell() -> str:
    return settings.get("terminal-shell")


def create_terminal_backend(
    shell: Optional[Union[str, List[str]]] = None,
    cwd: Optional[str] = None,
    env: Optional[Dict[str, str]] = None,
    dimensions: Tuple[int, int] = (24, 80),
) -> TerminalBackend:
    """
    Create the appropriate PTY backend for the current platform.

    Arguments:
        shell:      command to run inside the terminal. Defaults to the
                    configured 'terminal-shell' setting.
        cwd:        initial working directory of the spawned process.
        env:        environment dictionary for the spawned process.
        dimensions: (rows, columns) size of the terminal.
    """
    if shell is None:
        shell = get_default_shell()
    if data.on_windows:
        return ConPtyBackend(shell, cwd, env, dimensions)
    else:
        return PtyProcessBackend(shell, cwd, env, dimensions)


class TerminalBackend:
    """
    Base class for a PTY backend.

    Subclasses must implement the PTY accessors; the emulator talks only to
    this interface, never to the underlying process library directly.
    """

    shell: Union[str, List[str]]
    cwd: Optional[str]
    env: Optional[Dict[str, str]]
    dimensions: Tuple[int, int]
    process: Any

    def __init__(
        self,
        shell: Union[str, List[str]],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        dimensions: Tuple[int, int] = (24, 80),
    ) -> None:
        self.shell = shell
        self.cwd = cwd
        self.env = env
        self.dimensions = dimensions
        self.process = None

    def spawn(self) -> None:
        raise NotImplementedError

    def isalive(self) -> bool:
        raise NotImplementedError

    def read(self, size: Optional[int] = None) -> Union[bytes, str]:
        raise NotImplementedError

    def write(self, text: str) -> None:
        raise NotImplementedError

    def setwinsize(self, rows: int, cols: int) -> None:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def pid(self) -> Optional[int]:
        return None


class ConPtyBackend(TerminalBackend):
    """
    Windows backend using the Windows Pseudo Console (ConPTY).
    """

    def spawn(self) -> None:
        import winpty

        command: Union[str, List[str]] = self.shell
        if isinstance(command, (list, tuple)):
            command = " ".join(command)
        self.process = winpty.PtyProcess.spawn(
            command,
            cwd=self.cwd,
            env=self.env,
            dimensions=(self.dimensions[0], self.dimensions[1]),
            backend=0,
        )
        self._normalize_encoding()

    def _normalize_encoding(self) -> None:
        """
        Normalize the child console to UTF-8 output.

        ConPTY passes the child's raw console output through unchanged, and
        pywinpty decodes it as UTF-8. cmd.exe writes OEM-codepage bytes, so
        non-ASCII text would be garbled unless the console codepage is set to
        UTF-8 first.
        """
        shell0: str = self.shell[0] if isinstance(self.shell, list) else self.shell
        name: str = os.path.basename(shell0).lower()
        if name in ("cmd.exe", "cmd", "command.com"):
            self.write("@chcp 65001 >nul\r\n")
        elif name in ("powershell.exe", "pwsh.exe", "powershell", "pwsh"):
            self.write("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\r\n")

    def isalive(self) -> bool:
        return self.process.isalive()

    def read(self, size: Optional[int] = None) -> bytes:
        if size is None:
            size = 4096
        return self.process.read(size)

    def write(self, text: str) -> None:
        self.process.write(text)

    def setwinsize(self, rows: int, cols: int) -> None:
        self.process.setwinsize(rows, cols)

    def close(self) -> None:
        try:
            self.process.terminate(force=True)
        except Exception:
            pass

    def pid(self) -> int:
        return self.process.pid


class PtyProcessBackend(TerminalBackend):
    """
    Linux/Unix backend using ptyprocess.
    """

    def spawn(self) -> None:
        import shlex

        import ptyprocess

        argv: Union[str, List[str]] = self.shell
        if isinstance(argv, str):
            argv = shlex.split(argv)
        self.process = ptyprocess.PtyProcessUnicode.spawn(
            argv,
            cwd=self.cwd,
            env=self.env,
        )

    def isalive(self) -> bool:
        return self.process.isalive()

    def read(self, size: Optional[int] = None) -> str:
        if size is None:
            size = 4096
        return self.process.read(size)

    def write(self, text: str) -> None:
        self.process.write(text)

    def setwinsize(self, rows: int, cols: int) -> None:
        self.process.setwinsize(rows, cols)

    def close(self) -> None:
        try:
            self.process.close()
        except Exception:
            pass

    def pid(self) -> int:
        return self.process.pid