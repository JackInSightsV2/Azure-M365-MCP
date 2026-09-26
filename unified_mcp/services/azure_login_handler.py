"""Lifecycle-safe interactive Azure CLI login handling (browser or device code)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from unified_mcp.cli_tools import ToolLocator

SignInFlow = Literal["browser", "device_code"]

BROWSER_LOGIN_MESSAGE = (
    "Azure sign-in started: a browser window opened for the Azure CLI (az login). "
    "Complete sign-in there, then retry the request."
)


class AzureLoginHandler:
    """Start an interactive login, return its prompt, and own the remaining process lifetime.

    ``sign_in_flow`` follows the SIGN_IN_FLOW setting: "browser" runs plain ``az login``,
    which opens a browser window; "device_code" adds ``--use-device-code``.
    """

    def __init__(
        self,
        command_timeout: int = 300,
        sign_in_flow: SignInFlow = "browser",
        *,
        browser_wait: float = 3.0,
        tools: "ToolLocator | None" = None,
    ) -> None:
        self.logger = logging.getLogger(__name__)
        self.command_timeout = command_timeout
        self.sign_in_flow = sign_in_flow
        # How long browser sign-in may run before the prompt returns, to catch an
        # immediate failure (for example an unknown argument) instead of hiding it.
        self.browser_wait = browser_wait
        # Resolves az (PATH, then the bundled Azure CLI) when set.
        self.tools = tools
        self.current_process: asyncio.subprocess.Process | None = None
        self._completion_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        # Output of the most recent device login that failed, kept so a later command
        # can explain why sign-in did not complete (for example a Tenant policy refusal).
        self.last_login_error: str | None = None

    async def handle_az_login_command(self, command: str) -> str:
        """Start the configured interactive sign-in and return its prompt promptly."""
        arguments = self._login_arguments(command)
        env: dict[str, str] | None = {**os.environ, "PYTHONUNBUFFERED": "1"}
        if self.tools is not None:
            arguments, env = self.tools.prepare(arguments, env)
        async with self._lock:
            await self._stop_current()
            self.last_login_error = None
            try:
                process = await asyncio.create_subprocess_exec(
                    *arguments,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    stdin=asyncio.subprocess.PIPE,
                    env=env,
                )
                self.current_process = process
                initial = (
                    self._read_initial_output(process)
                    if self.sign_in_flow == "device_code"
                    else self._read_browser_output(process)
                )
                return await asyncio.wait_for(initial, timeout=self.command_timeout)
            except asyncio.TimeoutError:
                await self._stop_current()
                return "Error: Azure login timed out"
            except Exception as error:
                await self._stop_current()
                self.logger.error("Error starting Azure login: %s", error)
                return f"Error: Failed to start login process - {error}"

    def _login_arguments(self, command: str) -> list[str]:
        """Interactive ``az login`` arguments; device code only when SIGN_IN_FLOW asks."""
        sanitized = re.sub(r"--use-device-code\b", "", command)
        sanitized = re.sub(r"--service-principal\b", "", sanitized)
        sanitized = re.sub(r"--username(?:=|\s+)\S+", "", sanitized)
        sanitized = re.sub(r"--password(?:=|\s+)\S+", "", sanitized)
        sanitized = re.sub(r"--tenant(?:=|\s+)\S+", "", sanitized)
        if self.sign_in_flow == "device_code":
            sanitized = sanitized.strip() + " --use-device-code"
        return shlex.split(sanitized.strip(), posix=os.name != "nt")

    async def _read_browser_output(self, process: asyncio.subprocess.Process) -> str:
        """Leave browser sign-in running in the background unless it fails at once."""
        output: list[str] = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.browser_wait
        while process.stdout is not None:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
            except asyncio.TimeoutError:
                break
            if not line:
                # The CLI closed its output: it finished (or failed) before the deadline.
                await process.wait()
                break
            decoded = line.decode("utf-8", errors="replace").strip()
            if decoded:
                output.append(decoded)
            if "browser has been opened" in decoded.lower():
                break

        if process.returncode is None:
            self._continue_in_background(process)
            return BROWSER_LOGIN_MESSAGE
        self.current_process = None
        text = "\n".join(output)
        if process.returncode != 0:
            self.last_login_error = text or None
            return f"Error: Azure sign-in failed\n{text}".rstrip()
        return text or "Azure sign-in completed."

    async def _read_initial_output(self, process: asyncio.subprocess.Process) -> str:
        output: list[str] = []
        prompt: list[str] = []
        if process.stdout is None:
            return "Device code authentication started. Please check Azure CLI output."

        for _ in range(30):
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=1.0)
            except asyncio.TimeoutError:
                if prompt:
                    self._continue_in_background(process)
                    return "\n".join(prompt)
                if process.returncode is not None:
                    break
                continue
            if not line:
                break

            decoded = line.decode("utf-8", errors="replace").strip()
            if not decoded:
                continue
            output.append(decoded)
            if any(
                marker in decoded.lower()
                for marker in ("device", "code", "https://", "to sign in", "microsoft.com")
            ):
                prompt.append(decoded)
            if prompt and (len(prompt) >= 2 or "https://" in decoded):
                self._continue_in_background(process)
                return "\n".join(prompt)

        if process.returncode is None:
            self._continue_in_background(process)
        else:
            self.current_process = None
        return "\n".join(prompt or output) or (
            "Device code authentication started. Please check Azure CLI output."
        )

    def _continue_in_background(self, process: asyncio.subprocess.Process) -> None:
        task = asyncio.create_task(self._finish_login(process))
        self._completion_task = task

        def clear(completed: asyncio.Task[None]) -> None:
            if self._completion_task is completed:
                self._completion_task = None
            if self.current_process is process:
                self.current_process = None

        task.add_done_callback(clear)

    async def _finish_login(self, process: asyncio.subprocess.Process) -> None:
        try:
            tail: list[str] = []
            if process.stdout is not None:
                async for line in process.stdout:
                    tail = [*tail[-19:], line.decode("utf-8", errors="replace").rstrip()]
            return_code = await process.wait()
            if return_code == 0:
                self.logger.info("Azure interactive login completed")
            else:
                self.last_login_error = "\n".join(part for part in tail if part) or None
                self.logger.warning("Azure interactive login failed with code %s", return_code)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.logger.error("Error completing Azure interactive login: %s", error)

    async def _stop_current(self) -> None:
        task = self._completion_task
        process = self.current_process
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._completion_task = None
        self.current_process = None

    async def close(self) -> None:
        """Stop the owned login process and background task."""
        async with self._lock:
            await self._stop_current()
