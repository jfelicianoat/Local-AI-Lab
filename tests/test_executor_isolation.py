from __future__ import annotations

import ctypes
import multiprocessing
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from local_ai_lab.worker.execution_isolation import (
    ExecutorProcessError, IsolatedExecutor, WorkerJobCancelled,
)
from local_ai_lab.worker.executors import default_executors
from local_ai_lab.worker.runtime import WorkerRuntime
from local_ai_lab.training.checkpoints import create_checkpoint_bundle
from local_ai_lab.domain.jobs import IdempotencyClass, ReassignmentPolicy
from test_distributed_core import CoordinatorService, JobSpec, ServiceTransport, TestProtector, registered


def blocking_load(payload, progress):
    Path(payload['started']).write_text(str(os.getpid()), encoding='utf-8')
    time.sleep(1.5)
    Path(payload['finished']).write_text('done', encoding='utf-8')
    return {'completed': True}


def progress_result(payload, progress):
    progress({'step': 1, 'executor_pid': os.getpid()})
    progress({'step': 2})
    return {'value': payload['value'], 'executor_pid': os.getpid()}


def crashing_executor(payload, progress):
    os._exit(17)


def raising_executor(payload, progress):
    raise ValueError('private error detail must not cross the process boundary')


def checkpoint_then_fail(payload, progress):
    root = Path(payload['test_root'])
    source = root / 'checkpoint-4'
    source.mkdir()
    (source / 'trainer_state.json').write_text('{"global_step":4}', encoding='utf-8')
    for name in ('optimizer.pt', 'scheduler.pt', 'adapter_model.safetensors'):
        (source / name).write_bytes(b'controlled checkpoint protocol fixture')
    bundle, digest = create_checkpoint_bundle(source, root / 'checkpoint.zip', metadata={
        **payload['_worker_attempt'], 'dataset_fingerprint': 'b' * 64,
        'model_id': 'local/base', 'base_weights_sha256': 'c' * 64,
        'chat_template_fingerprint': 'd' * 64}, step=4)
    progress({'stage': 'checkpoint', 'step': 4, '_checkpoint_artifact': {
        'kind': 'training_checkpoint', 'local_path': str(bundle), 'sha256': digest,
        'size': bundle.stat().st_size, 'media_type': 'application/zip'}})
    raise RuntimeError('controlled interrupted training')


def converter_executor(payload, progress):
    code = 'import time; time.sleep(30)'
    converter = subprocess.Popen([sys.executable, '-c', code],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    Path(payload['converter_pid']).write_text(str(converter.pid), encoding='utf-8')
    Path(payload['executor_pid']).write_text(str(os.getpid()), encoding='utf-8')
    progress({'step': 1})
    converter.wait()
    return {'unexpected': True}


def pid_running(pid: int) -> bool:
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            assert ctypes.get_last_error() == 87  # process no longer exists
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 0x102
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    status = Path(f'/proc/{pid}/stat')
    return not status.exists() or status.read_text().split()[2] != 'Z'


def test_runtime_cancel_interrupts_blocking_load_without_progress(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / 'coordinator.db')
    _, transport = registered(service, 'worker')
    started, finished = tmp_path / 'started', tmp_path / 'finished'
    spec = JobSpec(kind='controlled-blocking-load', payload={
        'started': str(started), 'finished': str(finished)})
    service.submit_job(spec, 'submit-blocking')
    cancel_time = []

    def request_cancel():
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if started.exists():
            service.request_cancel(job_id=spec.job_id, idempotency_key='cancel-blocking')
            cancel_time.append(time.monotonic())

    requester = threading.Thread(target=request_cancel)
    requester.start()
    worker = WorkerRuntime(node_id='worker', journal_path=tmp_path / 'worker.db',
        transport=transport, executors={spec.kind: IsolatedExecutor(blocking_load)},
        secret_protector=TestProtector(), lease_keepalive_seconds=0.02)
    outcome = worker.run_once('claim-blocking')
    requester.join(5)
    assert cancel_time, 'executor did not reach the controlled blocking operation'
    assert outcome == 'cancelled'
    assert time.monotonic() - cancel_time[0] < 0.7
    assert not finished.exists()
    assert not pid_running(int(started.read_text()))
    assert worker.journal.job(spec.job_id)['outcome'] == 'cancelled'
    assert service.repository.job(spec.job_id)['state'] == 'cancelled'


def test_spawned_result_and_progress_stay_in_parent_journal(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / 'coordinator.db')
    _, transport = registered(service, 'worker')
    spec = JobSpec(kind='isolated-pure', payload={'value': 'passed'})
    service.submit_job(spec, 'submit-isolated')
    worker = WorkerRuntime(node_id='worker', journal_path=tmp_path / 'worker.db',
        transport=transport, executors={spec.kind: IsolatedExecutor(progress_result)},
        secret_protector=TestProtector())
    assert worker.run_once('claim-isolated') == 'succeeded'
    local = worker.journal.job(spec.job_id)
    assert local['progress_sequence'] == 2
    assert local['outcome'] == 'succeeded'
    assert local['sync_state'] == 'synced'
    assert service.repository.job(spec.job_id)['state'] == 'succeeded'


@pytest.mark.parametrize('stop_mode', ['cancel', 'progress_error'])
def test_cancel_and_parent_failure_stop_converter_descendants(tmp_path: Path, stop_mode: str) -> None:
    cancelled = threading.Event()

    def progress(message):
        if stop_mode == 'cancel':
            cancelled.set()
        else:
            raise ValueError('parent progress failed')

    exception = WorkerJobCancelled if stop_mode == 'cancel' else ValueError
    with pytest.raises(exception):
        IsolatedExecutor(converter_executor).run_cancellable({
            'converter_pid': str(tmp_path / 'converter'),
            'executor_pid': str(tmp_path / 'executor')}, progress, cancelled)
    for name in ('converter', 'executor'):
        pid = int((tmp_path / name).read_text())
        deadline = time.monotonic() + 1
        while pid_running(pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not pid_running(pid), f'{name} remained running'


@pytest.mark.parametrize('executor', [crashing_executor, raising_executor])
def test_child_failure_cannot_return_success_or_private_details(executor) -> None:
    previous = {child.pid for child in multiprocessing.active_children()}
    with pytest.raises(ExecutorProcessError) as failure:
        IsolatedExecutor(executor)({}, lambda message: None)
    assert 'private error detail' not in str(failure.value)
    assert {child.pid for child in multiprocessing.active_children()} == previous


def test_cancel_before_launch_does_not_start_executor(tmp_path: Path) -> None:
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(WorkerJobCancelled):
        IsolatedExecutor(blocking_load).run_cancellable({
            'started': str(tmp_path / 'started'), 'finished': str(tmp_path / 'finished')},
            lambda message: None, cancelled)
    assert not (tmp_path / 'started').exists()


def test_default_workloads_use_isolated_executors() -> None:
    assert all(isinstance(executor, IsolatedExecutor) for executor in default_executors().values())


def test_isolated_checkpoint_survives_lost_publication_and_worker_restart(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / 'coordinator.db')
    token, _ = registered(service, 'worker')

    class LostPublication(ServiceTransport):
        lost = False

        def publish_checkpoint(self, lease, **kwargs):
            answer = super().publish_checkpoint(lease, **kwargs)
            if not self.lost:
                self.lost = True
                self.online = False
                raise ConnectionError('lost checkpoint publication response')
            return answer

    transport = LostPublication(service, 'worker', token)
    spec = JobSpec(kind='training.lora.v1', payload={'test_root': str(tmp_path),
        'dataset_fingerprint': 'b' * 64, 'base_model': 'local/base',
        'chat_template_fingerprint': 'd' * 64,
        'collect_outputs': [{'result_key': 'output_dir', 'kind': 'training_result'}]},
        idempotency_class=IdempotencyClass.CHECKPOINTABLE,
        reassignment_policy=ReassignmentPolicy.HUMAN_ONLY)
    service.submit_job(spec, 'submit-isolated-checkpoint')

    def runtime():
        return WorkerRuntime(node_id='worker', journal_path=tmp_path / 'worker.db',
            transport=transport, executors={spec.kind: IsolatedExecutor(checkpoint_then_fail)},
            secret_protector=TestProtector(), lease_keepalive_seconds=100,
            control_poll_seconds=100)

    worker = runtime()
    with pytest.raises(ConnectionError, match='simulated disconnect'):
        worker.run_once('claim-checkpoint')
    assert worker.journal.job(spec.job_id)['outcome'] == 'failed'
    assert len(service.training_checkpoints(spec.job_id)) == 1
    assert worker.journal.pending_messages()[0]['kind'] == 'checkpoint'
    transport.online = True
    recovered = runtime()
    assert recovered.sync_all_pending() >= 1
    assert len(service.training_checkpoints(spec.job_id)) == 1
    assert recovered.journal.job(spec.job_id)['sync_state'] == 'synced'


def test_control_polling_does_not_renew_lease_on_every_poll(tmp_path: Path) -> None:
    service = CoordinatorService(tmp_path / 'coordinator.db')
    token, _ = registered(service, 'worker')

    class CountingTransport(ServiceTransport):
        controls = 0
        renewals = 0

        def control(self, lease, *, idempotency_key):
            self.controls += 1
            return super().control(lease, idempotency_key=idempotency_key)

        def renew(self, lease, *, idempotency_key):
            self.renewals += 1
            return super().renew(lease, idempotency_key=idempotency_key)

    transport = CountingTransport(service, 'worker', token)
    spec = JobSpec(kind='blocking-pure', payload={
        'started': str(tmp_path / 'started'), 'finished': str(tmp_path / 'finished')})
    service.submit_job(spec, 'submit-polling')
    worker = WorkerRuntime(node_id='worker', journal_path=tmp_path / 'worker.db',
        transport=transport, executors={spec.kind: IsolatedExecutor(blocking_load)},
        secret_protector=TestProtector(), lease_keepalive_seconds=0.5,
        control_poll_seconds=0.02)
    assert worker.run_once('claim-polling') == 'succeeded'
    assert transport.renewals >= 2
    assert transport.controls > transport.renewals * 3


def crash_parent(root: str) -> None:
    def crash_after_converter_starts(message):
        os._exit(23)

    IsolatedExecutor(converter_executor)({
        'converter_pid': str(Path(root) / 'converter'),
        'executor_pid': str(Path(root) / 'executor')}, crash_after_converter_starts)


def test_unexpected_parent_exit_stops_executor_and_converter(tmp_path: Path) -> None:
    environment = os.environ.copy()
    environment['PYTHONPATH'] = os.pathsep.join(sys.path)
    completed = subprocess.run([sys.executable, '-c',
        'from test_executor_isolation import crash_parent; import sys; crash_parent(sys.argv[1])',
        str(tmp_path)], env=environment, capture_output=True, text=True, timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    assert completed.returncode == 23, completed.stderr
    for name in ('converter', 'executor'):
        pid = int((tmp_path / name).read_text())
        deadline = time.monotonic() + 2
        while pid_running(pid) and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not pid_running(pid), f'{name} outlived its Worker parent'
