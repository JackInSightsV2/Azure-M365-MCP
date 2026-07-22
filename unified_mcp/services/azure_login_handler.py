"""Lifecycle-safe Azure CLI device-code login handling."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex


class AzureLoginHandler:
    """Start device login, return its prompt, and own the remaining process lifetime."""

    def __init__(self, command_timeout: int = 300) -> None:
        self.logger = logging.getLogger(__name__)
        self.command_timeout = command_timeout
        self.current_process: asyncio.subprocess.Process | None = None
        self._completion_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def handle_az_login_command(self, command: str) -> str:
        """Force device authentication and return the sign-in prompt promptly."""
        arguments = self._device_login_arguments(command)
        async with self._lock:
            await self._stop_current()
            try:
                process = await asyncio.create_subprocess_exec(
                    *arguments,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    stdin=asyncio.subprocess.PIPE,
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                )
                self.current_process = process
                return await asyncio.wait_for(
                    self._read_initial_output(process),
                    timeout=self.command_timeout,
                )
            except asyncio.TimeoutError:
                await self._stop_current()
                return "Error: Azure login timed out"
            except Exception as error:
                await self._stop_current()
                self.logger.error("Error starting Azure login: %s", error)
                return f"Error: Failed to start login process - {error}"

    @staticmethod
    def _device_login_arguments(command: str) -> list[str]:
        sanitized = re.sub(r"--use-device-code\b", "", command)
        sanitized = re.sub(r"--service-principal\b", "", sanitized)
        sanitized = re.sub(r"--username(?:=|\s+)\S+", "", sanitized)
        sanitized = re.sub(r"--password(?:=|\s+)\S+", "", sanitized)
        sanitized = re.sub(r"--tenant(?:=|\s+)\S+", "", sanitized)
        return shlex.split(
            sanitized.strip() + " --use-device-code",
            posix=os.name != "nt",
        )

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
            if process.stdout is not None:
                async for _line in process.stdout:
                    pass
            return_code = await process.wait()
            if return_code == 0:
                self.logger.info("Azure device login completed")
            else:
                self.logger.warning("Azure device login failed with code %s", return_code)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.logger.error("Error completing Azure device login: %s", error)

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
