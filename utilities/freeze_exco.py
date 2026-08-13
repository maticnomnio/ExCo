"""
Copyright (c) 2013-present Matic Kukovec.
Released under the GNU GPL3 license.

For more information check the 'LICENSE.txt' file.
For complete license information of the dependencies, check the 'additional_licenses' directory.
"""

import argparse
import importlib.util
import inspect
import json
import os
import platform
import pprint
import py_compile
import shutil
import sys
import sysconfig
from typing import Dict, List, Set

import cx_Freeze


def _project_root() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


CONFIG_PATH = os.path.join(_project_root(), "freeze_config.json")


def _load_config() -> dict:
    if not os.path.isfile(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def _use_pure_black(output_directory: str) -> None:
    """
    Force black to run in pure-Python mode inside the frozen build.

    black ships two implementations: mypyc-compiled extension modules
    (e.g. 'black/cache.cp314-win_amd64.pyd') and the equivalent pure
    Python sources. The compiled modules depend on hash-named top-level
    'mypyc' shared modules that cx_Freeze cannot discover, so they break
    at runtime. Removing the compiled modules makes the frozen app fall
    back to the pure-Python implementation, which needs no such support.
    """
    site_packages: str = sysconfig.get_paths()["purelib"]

    # black, its bundled tokenizer (blib2to3) and pytokens (the tokenizer's
    # engine) are all mypyc-compiled, each with a pure-Python fallback
    for package_name in ("black", "blib2to3", "pytokens"):
        venv_package: str = os.path.join(site_packages, package_name)
        build_package: str = os.path.join(output_directory, "lib", package_name)

        # Remove all mypyc-compiled extension modules from the build's package
        if os.path.isdir(build_package):
            for root, _dirs, files in os.walk(build_package):
                for name in files:
                    if name.endswith(".pyd"):
                        os.remove(os.path.join(root, name))

        # Ship the pure-Python implementation as bytecode
        if os.path.isdir(venv_package):
            for root, dirs, files in os.walk(venv_package):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    src: str = os.path.join(root, name)
                    rel: str = os.path.relpath(src, venv_package)
                    cfile: str = os.path.join(build_package, os.path.splitext(rel)[0] + ".pyc")
                    os.makedirs(os.path.dirname(cfile), exist_ok=True)
                    py_compile.compile(src, cfile=cfile, doraise=True)

    # Drop the hash-named top-level 'mypyc' shared modules that the compiled
    # implementations need (the pure-Python fallbacks do not use them)
    if os.path.isdir(output_directory):
        for name in os.listdir(output_directory):
            if "__mypyc" in name and name.endswith(".pyd"):
                os.remove(os.path.join(output_directory, name))


def _save_config(data: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(data, f, indent=2)


def get_all_imports() -> Dict[str, List[str]]:
    """
    Import exco.py and collect all third-party module imports.
    Returns a dict with 'modules' and 'packages' lists.
    - 'modules': Single file modules (.py files)
    - 'packages': Packages with __init__.py (directories)
    """
    project_dir: str = os.path.dirname(os.path.abspath(__file__))
    parent_dir: str = os.path.dirname(project_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    before: Set[str] = set(sys.modules.keys())

    try:
        import exco  # type: ignore
    except Exception:
        pass

    after: Set[str] = set(sys.modules.keys())
    new_modules: Set[str] = after - before

    # Test each import to determine if it's a module or package
    modules: List[str] = []
    packages: List[str] = []

    for mod_name in new_modules:
        # Try to find the module/package
        try:
            spec = importlib.util.find_spec(mod_name)
        except (ValueError, ModuleNotFoundError):
            # Some modules have None __spec__ and raise ValueError
            continue

        if spec is None:
            continue

        if spec.submodule_search_locations is None:
            # It's a module (single .py file)
            modules.append(mod_name)
        else:
            # It's a package (has __init__.py)
            packages.append(mod_name)

    return {
        "modules": sorted(modules),
        "packages": sorted(packages),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freeze ExCo into a standalone executable.")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=str,
        default=None,
        help="Parent directory for the frozen build. If it does not exist, "
        "you will be prompted to create it. The final output will be "
        "<output-dir>/frozen_exco_<os>_<arch>. "
        "If omitted, the last used directory is read from the config file.",
    )
    return parser.parse_args()


def resolve_output_dir(custom_parent: str, base_name: str) -> str:
    path = os.path.abspath(custom_parent)
    if os.path.exists(path):
        if not os.path.isdir(path):
            raise NotADirectoryError(f"Path exists but is not a directory: {path}")
    else:
        answer = input(f"Directory does not exist:\n  {path}\nCreate it? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            sys.exit(0)
        os.makedirs(path, exist_ok=True)
        print(f"Created: {path}")

    return os.path.join(path, base_name)


def main() -> int:
    """
    Main function to build the ExCo application using cx_Freeze.
    Returns exit code (0 = success).
    """
    args = parse_args()

    parent_dir: str | None = args.output_dir
    if parent_dir is None:
        config = _load_config()
        stored = config.get("last_output_dir")
        if not stored:
            raise RuntimeError(
                "No --output-dir given and no stored directory found in config. "
                "Run with --output-dir once to save it."
            )
        parent_dir = stored
        print(f"Using stored output directory: {parent_dir}")

    if sys.prefix == sys.base_prefix:
        raise RuntimeError(
            "This script must be run inside a Python virtual environment. "
            "Please activate a venv and try again."
        )

    # Get the project directory (parent of utilities/)
    file_directory: str = os.path.join(
        os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))),
        "..",
    )

    # Output directory name based on OS and architecture
    base_output: str = "frozen_exco_{}_{}".format(
        platform.system().lower(),
        platform.architecture()[0],
    )
    output_directory: str = resolve_output_dir(parent_dir, base_output)

    # Get all imports and separate into modules vs packages
    import_result: Dict[str, List[str]] = get_all_imports()
    includes: List[str] = import_result["modules"]
    packages_list: List[str] = import_result["packages"]

    # black imports the top-level '_black_version' module; cx_Freeze does
    # not discover it, so pull it in explicitly
    if "_black_version" not in includes:
        includes.append("_black_version")

    # Add PyQt6 to packages (needed for proper freezing)
    packages_list.append("PyQt6")

    # Code-quality tools are imported lazily at runtime (not during the
    # import-analysis pass), so add them explicitly to be safe
    for lazy_package in ("autopep8", "black", "bs4", "isort", "pyflakes", "ruff", "yapf"):
        if lazy_package not in packages_list:
            packages_list.append(lazy_package)

    # components.codequality is also imported lazily at runtime
    # (gui/mainwindow/tools.py, gui/mainwindow/display.py), so it is not
    # discovered by the import-analysis pass above; include it explicitly
    if "components.codequality" not in includes:
        includes.append("components.codequality")

    # Other local modules imported lazily at runtime that the import-analysis
    # pass misses: gui/mainwindow/menubar.py -> libraryfunctions,
    # gui/thebox.py + gui/tabwidget.py + gui/mainwindow/view.py -> gui.terminal
    for lazy_module in ("gui.terminal", "libraryfunctions"):
        if lazy_module not in includes:
            includes.append(lazy_module)

    # Third-party packages imported lazily at runtime on all platforms
    # (components/processcontroller.py + gui/externalprogram.py -> psutil,
    # gui/terminal.py + gui/nimsuggest.py -> pyte)
    for lazy_package in ("psutil", "pyte"):
        if lazy_package not in packages_list:
            packages_list.append(lazy_package)

    # Directories to exclude when scanning for local modules
    exclude_dirs: list[str] = [
        "cython",
        "utilities",
        "nim",
        "git_clone",
    ]

    # Specific modules to exclude
    excluded_modules: list[str] = [
        "freeze_exco",
        "git_clone",
    ]

    # Add project directory to Python path
    search_path: list[str] = sys.path
    search_path.append(file_directory)

    # Base type for executable (None = console app)
    base: str | None = None
    excludes: list[str] = [
        "tkinter",
    ]
    executable_name: str = "ExCo"

    # Platform-specific configuration
    if platform.system().lower() == "windows":
        base = "gui"  # GUI app without console

        # Exclude PyQt5 modules to avoid conflicts
        excludes = [
            "tkinter",
            "PyQt5",
            "PyQt5.QtCore",
            "PyQt5.QtWidgets",
            "PyQt5.QtGui",
            "PyQt5.Qsci",
            "PyQt5.QtTest",
            "venv",
        ]

        executable_name = "ExCo.exe"

        # Imported lazily at runtime on Windows only:
        # gui/terminal.py -> winpty (pywinpty),
        # gui/externalprogram.py + gui/mainwindow/mainwindow.py -> win32*.pyd
        if "winpty" not in packages_list:
            packages_list.append("winpty")
        for win_module in ("win32gui", "win32process"):
            if win_module not in includes:
                includes.append(win_module)

    elif platform.system().lower() == "linux":
        # Add Linux-specific includes
        includes.extend(["ptyprocess"])

    # Define the executable to create
    executables: list[cx_Freeze.Executable] = [
        cx_Freeze.Executable(
            "exco.py",
            init_script=None,
            base=base,
            icon="resources/exco-icon-win.ico",
            target_name=executable_name,
        )
    ]

    # Configure and run the freezer
    freezer: cx_Freeze.Freezer = cx_Freeze.Freezer(
        executables,
        includes=includes,
        packages=packages_list,
        excludes=excludes,
        replace_paths=[],
        compress=True,
        optimize=True,
        include_msvcr=True,
        path=search_path,
        target_dir=output_directory,
        include_files=[],
        zip_includes=[],
        silent=False,
    )
    freezer.freeze()

    # black is mypyc-compiled; force its pure-Python implementation so
    # the frozen app does not depend on the hash-named mypyc modules
    _use_pure_black(output_directory)

    # Copy resources directory to output
    shutil.copytree("resources", os.path.join(output_directory, "resources"))

    # Save the parent directory for next run
    _save_config({"last_output_dir": parent_dir})
    print(f"Saved output directory to config: {CONFIG_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
