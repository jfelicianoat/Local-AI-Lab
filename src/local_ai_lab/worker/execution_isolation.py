from __future__ import annotations

import ctypes
import multiprocessing
import os
import signal
import threading
from typing import Any, Callable


class WorkerJobCancelled(RuntimeError):
    pass


class ExecutorProcessError(RuntimeError):
    pass


class _WindowsJob:
    """Own only the new executor and descendants; close releases the whole job."""

    def __init__(self, pid: int) -> None:
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL

        class BasicLimits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                ('flags', wintypes.DWORD), ('min_ws', ctypes.c_size_t),
                ('max_ws', ctypes.c_size_t), ('active_limit', wintypes.DWORD),
                ('affinity', ctypes.c_size_t), ('priority', wintypes.DWORD),
                ('scheduling', wintypes.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                ('read_ops', 'write_ops', 'other_ops', 'read_bytes', 'write_bytes', 'other_bytes')]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', BasicLimits), ('io', IoCounters),
                ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]

        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        process = None
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise ctypes.WinError(ctypes.get_last_error())
            process = kernel.OpenProcess(0x0100 | 0x0001, False, pid)
            if not process or not kernel.AssignProcessToJobObject(self.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise
        finally:
            if process:
                kernel.CloseHandle(process)

    def close(self) -> None:
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _watch_parent(parent_lifetime: Any) -> None:
    try:
        parent_lifetime.recv()
    except (EOFError, OSError):
        # The pipe has one writer in the parent. Its death also stops converters.
        os.killpg(os.getpid(), signal.SIGKILL)


def _execute_child(connection: Any, parent_lifetime: Any,
                   executor: Any, payload: dict[str, Any]) -> None:
    try:
        if os.name != 'nt':
            os.setsid()
            threading.Thread(target=_watch_parent, args=(parent_lifetime,),
                             daemon=True, name='executor-parent-lifetime').start()
        connection.send(('ready', None))
        if connection.recv() != 'start':
            return

        def progress(message: dict[str, Any]) -> None:
            connection.send(('progress', message))
            if connection.recv() != 'continue':
                raise WorkerJobCancelled('parent stopped execution')

        connection.send(('result', executor(payload, progress)))
    except BaseException as error:
        try:
            connection.send(('error', type(error).__name__))
        except (BrokenPipeError, EOFError, OSError):
            pass
    finally:
        connection.close()
        parent_lifetime.close()


class IsolatedExecutor:
    """Spawn ML/Broker work; keep durable progress and transport in the parent."""

    def __init__(self, executor: Callable[..., dict[str, Any]]) -> None:
        self.executor = executor

    def __call__(self, payload: dict[str, Any], progress: Callable[..., None]) -> dict[str, Any]:
        return self.run_cancellable(payload, progress, threading.Event())

    def run_cancellable(self, payload: dict[str, Any], progress: Callable[..., None],
                        cancelled: threading.Event) -> dict[str, Any]:
        if cancelled.is_set():
            raise WorkerJobCancelled('cancelled before executor launch')
        context = multiprocessing.get_context('spawn')
        parent, child = context.Pipe(duplex=True)
        lifetime_reader, lifetime_writer = context.Pipe(duplex=False)
        process = context.Process(target=_execute_child,
                                  args=(child, lifetime_reader, self.executor, payload),
                                  name='local-ai-lab-executor')
        job = None
        started = False
        group_ready = False
        try:
            process.start()
            started = True
            child.close()
            lifetime_reader.close()
            while True:
                if cancelled.is_set():
                    raise WorkerJobCancelled('cancelled during executor operation')
                if parent.poll(0.05):
                    try:
                        kind, value = parent.recv()
                    except EOFError as error:
                        raise ExecutorProcessError('executor exited without a result') from error
                    if kind == 'ready':
                        group_ready = True
                        if os.name == 'nt':
                            job = _WindowsJob(process.pid)
                        parent.send('start')
                    elif kind == 'progress':
                        progress(value)
                        parent.send('continue')
                    elif kind == 'result':
                        if not isinstance(value, dict):
                            raise ExecutorProcessError('executor returned an invalid result')
                        if cancelled.is_set():
                            raise WorkerJobCancelled('cancelled before accepting result')
                        return value
                    elif kind == 'error':
                        raise ExecutorProcessError(f'executor failed: {value}')
                    else:
                        raise ExecutorProcessError('executor sent an invalid message')
                elif not process.is_alive():
                    raise ExecutorProcessError('executor exited without a result')
        finally:
            parent.close()
            child.close()
            lifetime_reader.close()
            lifetime_writer.close()
            if started:
                if job is not None:
                    job.close()
                elif os.name != 'nt' and group_ready:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                elif process.is_alive():
                    process.terminate()
                process.join(timeout=2)
                if process.is_alive():
                    process.kill()
                    process.join(timeout=2)
                if process.is_alive():
                    raise ExecutorProcessError('executor process cleanup failed')
                process.close()
