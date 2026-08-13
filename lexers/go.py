"""
Copyright (c) 2013-present Matic Kukovec.
Released under the GNU GPL3 license.

For more information check the 'LICENSE.txt' file.
For complete license information of the dependencies, check the 'additional_licenses' directory.
"""

from __future__ import annotations

import keyword
import builtins
import re
import time
from typing import Any

import data
import qt
import settings
import functions
import lexers
from lexers.baselexer import BaseLexer


class Go(BaseLexer):
    """Custom lexer for the Go programming language"""

    styles: dict[str, int] = {
        "Default": 0,
        "Comment": 1,
        "Keyword": 2,
        "String": 3,
        "RawString": 4,
        "Number": 5,
        "Identifier": 6,
        "Operator": 7,
        "Predefined": 8,
    }

    # Go keywords
    keyword_list: list[str] = [
        "break",
        "default",
        "func",
        "interface",
        "select",
        "case",
        "defer",
        "go",
        "map",
        "struct",
        "chan",
        "else",
        "goto",
        "package",
        "switch",
        "const",
        "fallthrough",
        "if",
        "range",
        "type",
        "continue",
        "for",
        "import",
        "return",
        "var",
    ]

    # Go predefined identifiers (built-ins)
    predefined_list: list[str] = [
        "bool",
        "byte",
        "complex64",
        "complex128",
        "error",
        "float32",
        "float64",
        "int",
        "int8",
        "int16",
        "int32",
        "int64",
        "rune",
        "string",
        "uint",
        "uint8",
        "uint16",
        "uint32",
        "uint64",
        "uintptr",
        "true",
        "false",
        "nil",
        "append",
        "cap",
        "close",
        "complex",
        "copy",
        "delete",
        "imag",
        "len",
        "make",
        "new",
        "panic",
        "print",
        "println",
        "real",
        "recover",
    ]

    # Operators and delimiters
    operator_list: list[str] = [
        "+",
        "-",
        "*",
        "/",
        "%",
        "&",
        "|",
        "^",
        "<<",
        ">>",
        "&^",
        "==",
        "!=",
        "<",
        "<=",
        ">",
        ">=",
        "=",
        ":=",
        "...",
        ".",
        ",",
        ";",
        ":",
        "(",
        ")",
        "[",
        "]",
        "{",
        "}",
    ]

    # Regex splitter for tokenization
    splitter: re.Pattern[str] = re.compile(r"(\/\/|\/\*|\*\/\|\s+|\w+|\W)")

    def __init__(self, parent: Any = None) -> None:
        """Overridden initialization"""
        # Initialize superclass
        super().__init__()
        # Set the default style values
        self.setDefaultColor(qt.QColor(settings.get_theme()["fonts"]["default"]["color"]))
        self.setDefaultPaper(qt.QColor(settings.get_theme()["fonts"]["default"]["background"]))
        self.setDefaultFont(settings.get_editor_font())
        # Reset autoindentation style
        self.setAutoIndentStyle(0)
        # Set the theme
        self.set_theme(settings.get_theme())

    def language(self) -> str:
        return "Go"

    def description(self, style: int) -> str:
        if style <= len(self.styles):
            description = "Custom lexer for the Go programming language"
        else:
            description = ""
        return description

    def set_theme(self, theme: dict[str, Any]) -> None:
        for style in self.styles:
            # Papers - use default background if style not found in theme
            bg_color = (
                settings.get_theme()["fonts"]
                .get(style.lower(), {})
                .get("background", settings.get_theme()["fonts"]["default"]["background"])
            )
            self.setPaper(
                qt.QColor(bg_color),
                self.styles[style],
            )
            # Fonts - use default font if style not found in theme
            font_settings = settings.get_theme()["fonts"].get(
                style.lower(), settings.get_theme()["fonts"]["default"]
            )
            lexers.set_font(self, style, font_settings)

    def styleText(self, start: int, end: int) -> None:
        """
        Overloaded method for styling text.
        """
        # Style in pure Python
        editor = self.editor()
        if editor is None:
            return

        # Initialize the styling
        self.startStyling(start)
        # Scintilla works with bytes, so we have to adjust the start and end boundaries
        text = bytearray(editor.text(), "utf-8")[start:end].decode("utf-8")
        # Loop optimizations
        setStyling = self.setStyling
        keyword_list = self.keyword_list
        predefined_list = self.predefined_list
        operator_list = self.operator_list

        DEFAULT = self.styles["Default"]
        COMMENT = self.styles["Comment"]
        KEYWORD = self.styles["Keyword"]
        STRING = self.styles["String"]
        RAWSTRING = self.styles["RawString"]
        NUMBER = self.styles["Number"]
        IDENTIFIER = self.styles["Identifier"]
        OPERATOR = self.styles["Operator"]
        PREDEFINED = self.styles["Predefined"]

        # Initialize various states and split the text into tokens
        line_comment = False
        block_comment = False
        string_literal = False
        raw_string_literal = False
        escape_next = False

        tokens = [(token, len(bytearray(token, "utf-8"))) for token in self.splitter.findall(text)]

        # Style the tokens accordingly
        for i, token in enumerate(tokens):
            token_value = token[0]
            token_length = token[1]

            if line_comment:
                # Continuation of line comment
                setStyling(token_length, COMMENT)
                # Check if comment ends at newline
                if "\n" in token_value:
                    line_comment = False
                continue

            elif block_comment:
                # Continuation of block comment
                setStyling(token_length, COMMENT)
                # Check if block comment ends
                if "*/" in token_value:
                    block_comment = False
                continue

            elif string_literal:
                # Continuation of string literal
                setStyling(token_length, STRING)
                # Handle escape sequences
                if escape_next:
                    escape_next = False
                elif token_value == "\\":
                    escape_next = True
                elif token_value == '"' and not escape_next:
                    string_literal = False
                continue

            elif raw_string_literal:
                # Continuation of raw string literal
                setStyling(token_length, RAWSTRING)
                # Raw strings end with backtick, no escape processing
                if token_value == "`":
                    raw_string_literal = False
                continue

            # Check for start of comments
            elif token_value == "//":
                setStyling(token_length, COMMENT)
                line_comment = True
                continue

            elif token_value == "/*":
                setStyling(token_length, COMMENT)
                block_comment = True
                continue

            # Check for string literals
            elif token_value == '"' and not string_literal and not raw_string_literal:
                setStyling(token_length, STRING)
                string_literal = True
                escape_next = False
                continue

            elif token_value == "`" and not string_literal and not raw_string_literal:
                setStyling(token_length, RAWSTRING)
                raw_string_literal = True
                continue

            # Check for keywords
            elif token_value in keyword_list:
                setStyling(token_length, KEYWORD)
                continue

            # Check for predefined identifiers
            elif token_value in predefined_list:
                setStyling(token_length, PREDEFINED)
                continue

            # Check for operators
            elif token_value in operator_list:
                setStyling(token_length, OPERATOR)
                continue

            # Check for numbers
            elif token_value[0].isdigit() or (
                token_value.startswith("-") and len(token_value) > 1 and token_value[1].isdigit()
            ):
                setStyling(token_length, NUMBER)
                continue

            # Check for identifiers (must start with letter or underscore)
            elif token_value[0].isalpha() or token_value[0] == "_":
                setStyling(token_length, IDENTIFIER)
                continue

            # Default styling
            else:
                setStyling(token_length, DEFAULT)
