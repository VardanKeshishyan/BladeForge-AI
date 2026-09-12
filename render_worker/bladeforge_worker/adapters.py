from __future__ import annotations

import abc
import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path


class RenderAdapter(abc.ABC):
    @abc.abstractmethod
    async def run(self, job_file: Path) -> AsyncIterator[dict[str, object]]:
        raise NotImplementedError


class LocalBlenderAdapter(RenderAdapter):
    def __init__(self, blender_executable: str, engine_path: Path) -> None:
        self.blender_executable = blender_executable
        self.engine_path = engine_path.resolve()
        self.process: asyncio.subprocess.Process | None = None

    async def run(self, job_file: Path) -> AsyncIterator[dict[str, object]]:
        log_path = job_file.parent / "blender.log"
        saw_python_traceback = False
        captured_tail: list[str] = []
        self.process = await asyncio.create_subprocess_exec(
            self.blender_executable,
            "--background",
            "--python",
            str(self.engine_path),
            "--",
            "--job-file",
            str(job_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert self.process.stdout is not None
        with log_path.open("w", encoding="utf-8", errors="replace") as log_file:
            async for raw_line in self.process.stdout:
                line = raw_line.decode(errors="replace").rstrip()
                log_file.write(line + "\n")
                log_file.flush()
                captured_tail.append(line)
                captured_tail = captured_tail[-40:]
                if "Traceback (most recent call last)" in line:
                    saw_python_traceback = True
                if line.startswith("BLADEFORGE_PROGRESS "):
                    yield json.loads(line.removeprefix("BLADEFORGE_PROGRESS "))
        return_code = await self.process.wait()
        if return_code != 0:
            tail = "\n".join(captured_tail[-12:])
            raise RuntimeError(
                f"Blender exited with status {return_code}. See {log_path}. Last output:\n{tail}"
            )
        if saw_python_traceback:
            tail = "\n".join(captured_tail[-12:])
            raise RuntimeError(
                f"Blender reported a Python traceback but exited successfully. "
                f"See {log_path}. Last output:\n{tail}"
            )

    async def cancel(self) -> None:
        if self.process is not None and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=10)
            except TimeoutError:
                self.process.kill()


class RunPodAdapter(RenderAdapter):
    """Interface placeholder. It refuses use until callback verification is configured."""

    async def run(self, job_file: Path) -> AsyncIterator[dict[str, object]]:
        raise RuntimeError(
            "RunPod dispatch is not enabled in this MVP. Use the local polling Blender adapter."
        )
        yield {}
