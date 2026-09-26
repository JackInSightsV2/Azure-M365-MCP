"""Find the command-line tools the server runs: az, kubectl, and kubelogin.

Each tool is looked up in order: the user's PATH, then the server's own environment (the
directory holding ``sys.executable``, where the bundled Azure CLI's ``az`` script lives),
then the per-user tools directory that ``az aks install-cli`` fills with kubectl and
kubelogin on first use. Subprocesses get a PATH with the directories of tools found
outside the user's PATH prepended, so kubectl can start kubelogin and kubelogin can
start az.
"""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Optional

from unified_mcp.config import Settings

MANAGED_TOOLS = ("az", "kubectl", "kubelogin")


class ToolLocator:
    """Resolve managed tools and build the argument list and environment to run them."""

    def __init__(
        self,
        tools_dir: str,
        *,
        bundled_dir: Optional[str] = None,
        which: Callable[[str], Optional[str]] = shutil.which,
        environ: Mapping[str, str] | None = None,
        windows: bool = os.name == "nt",
    ) -> None:
        self.tools_dir = tools_dir
        # Not resolved through symlinks: a venv's bin/python links to the base interpreter.
        self.bundled_dir = bundled_dir or os.path.dirname(sys.executable)
        self.which = which
        self.environ = os.environ if environ is None else environ
        self.windows = windows

    @classmethod
    def from_settings(
        cls, settings: Settings, *, which: Callable[[str], Optional[str]] = shutil.which
    ) -> "ToolLocator":
        return cls(settings.tools_directory(), which=which)

    def installed_path(self, name: str) -> str:
        """Where ``az aks install-cli`` puts ``name`` in the tools directory."""
        return os.path.join(self.tools_dir, name + (".exe" if self.windows else ""))

    def find(self, name: str) -> Optional[str]:
        """Return the path to ``name`` (PATH first), or None when it is nowhere."""
        return self._locate(name)[0]

    def _locate(self, name: str) -> tuple[Optional[str], bool]:
        """Return the path to ``name`` and whether it came from the user's PATH."""
        on_path = self.which(name)
        if on_path:
            return on_path, True
        for directory in (self.bundled_dir, self.tools_dir):
            for filename in self._filenames(name):
                candidate = os.path.join(directory, filename)
                if os.path.isfile(candidate) and (self.windows or os.access(candidate, os.X_OK)):
                    return candidate, False
        return None, False

    def _filenames(self, name: str) -> list[str]:
        if self.windows:
            # az is a batch script on Windows (az.bat, or az.cmd from the MSI).
            return [f"{name}.exe", f"{name}.cmd", f"{name}.bat"]
        return [name]

    def search_path(self, base: Optional[str] = None) -> str:
        """``base`` (default: this process's PATH) with off-PATH tool directories first."""
        base_path = self.environ.get("PATH", "") if base is None else base
        prepend: list[str] = []
        for name in MANAGED_TOOLS:
            path, on_path = self._locate(name)
            directory = os.path.dirname(path) if path and not on_path else None
            if directory and directory not in prepend:
                prepend.append(directory)
        return os.pathsep.join([*prepend, base_path] if base_path else prepend)

    def prepare(
        self, arguments: Sequence[str], env: Mapping[str, str] | None = None
    ) -> tuple[list[str], Optional[dict[str, str]]]:
        """Resolve the program in ``arguments`` and return the environment to run it with.

        The environment is None (inherit) when every managed tool is on the user's PATH.
        """
        resolved = list(arguments)
        if resolved:
            path, on_path = self._locate(resolved[0])
            # Windows does not search the child's PATH or add .bat/.cmd, so use full paths.
            if path and (not on_path or self.windows):
                resolved[0] = path
        base = dict(self.environ if env is None else env)
        search_path = self.search_path(base.get("PATH", ""))
        if env is None and search_path == base.get("PATH", ""):
            return resolved, None
        base["PATH"] = search_path
        return resolved, base
