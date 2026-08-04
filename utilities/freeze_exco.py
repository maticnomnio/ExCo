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
import shutil
import sys
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

    # Add PyQt6 to packages (needed for proper freezing)
    packages_list.append("PyQt6")

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

    # Copy resources directory to output
    shutil.copytree("resources", os.path.join(output_directory, "resources"))

    # Save the parent directory for next run
    _save_config({"last_output_dir": parent_dir})
    print(f"Saved output directory to config: {CONFIG_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
