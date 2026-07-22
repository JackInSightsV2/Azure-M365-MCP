"""Asynchronous subprocess runner shared by Azure CLI lifecycle operations."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


class ProcessTimeoutError(TimeoutError):
    """Raised after a subprocess is terminated because its deadline elapsed."""


@dataclass(frozen=True)
class ProcessResult:
    """Decoded subprocess result."""

    returncode: int
    stdout: str
    stderr: str


class AsyncProcessRunner:
    """Run commands without a shell and enforce termination on timeout."""

    async def run(
        self,
        arguments: Sequence[str],
        timeout: float,
        env: Mapping[str, str] | None = None,
    ) -> ProcessResult:
        if env is None:
            process = await asyncio.create_subprocess_exec(
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        else:
            process = await asyncio.create_subprocess_exec(
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError as error:
            process.kill()
            await process.wait()
            raise ProcessTimeoutError from error

        return ProcessResult(
            returncode=process.returncode or 0,
            stdout=stdout.decode("utf-8", errors="replace") if stdout else "",
            stderr=stderr.decode("utf-8", errors="replace") if stderr else "",
        )
