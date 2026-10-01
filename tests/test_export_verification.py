"""Initial format verification using synthetic protocol packages, not real ML."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from local_ai_lab.artifacts.archive import deterministic_zip
from local_ai_lab.coordinator.api import create_app
from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.domain.jobs import JobSpec
from local_ai_lab.exporting.package import ExportArtifact, ExportPackageBuilder
from result_fixtures import training_inputs, training_package


def completed_training(tmp_path: Path, *, dependencies=True):
    service = CoordinatorService(tmp_path / 'coordinator.db')
    registration = service.pair_and_register(
        pairing_code=service.create_pairing_code(), node_id='worker', hostname='worker',
    )
    token = registration['device_token']
    service.heartbeat(node_id='worker', token=token, capabilities={
        'facts': [{'key': f'runtime.package.{name}', 'value': 'fixture-version', 'status': 'detected'}
                  for name in ('torch', 'transformers', 'peft')] if dependencies else [],
        'workloads': [],
    })
    spec = JobSpec(kind='training.lora.v1', payload=training_inputs())
    service.submit_job(spec, 'training-fixture')
    service.record_product_item(record_id=spec.job_id, category='training', title='Synthetic training',
                                status='TRAINING_QUEUED', artifact_sha256=spec.fingerprint(), summary={})
    lease = service.claim_job(node_id='worker', token=token, idempotency_key='training-claim')
    service.ack_job(node_id='worker', token=token, job_id=spec.job_id,
                    lease_token=lease['lease_token'], lease_generation=lease['lease_generation'], idempotency_key='training-ack')
    result = training_package(service, lease, tmp_path / 'training')
    complete(service, token, lease, result, 'training-complete')
    return service, token, spec.job_id


def complete(service, token, lease, result, key):
    return service.complete_job(node_id='worker', token=token, job_id=lease['job_id'],
                                attempt_id=lease['attempt_id'], lease_token=lease['lease_token'],
                                lease_generation=lease['lease_generation'], outcome='succeeded',
                                payload=result, idempotency_key=key)


def request(training_id, format, *, verify=True):
    return {'training_job_id': training_id, 'node_id': 'worker', 'formats': [format],
            'license_id': 'apache-2.0', 'serving': {'runtime': 'transformers', 'local_only': True},
            'llama_cpp_converter': 'local-converter.py' if format == 'gguf' else None,
            'verification_only': verify, 'idempotency_key': f'{format}:{verify}'}


@pytest.mark.parametrize('format', ['adapter', 'merged_model', 'safetensors', 'gguf'])
def test_initial_verification_can_run_before_format_proof_and_publishes_only_after_validation(tmp_path, format):
    service, token, training_id = completed_training(tmp_path)
    client = TestClient(create_app(service, app_token='local-test-session'))
    response = client.post('/app/v1/exports', headers={'X-App-Token': 'local-test-session'}, json=request(training_id, format))
    assert response.status_code == 200, response.text
    record = response.json()
    assert record['status'] == 'EXPORT_VERIFICATION_QUEUED'
    spec = json.loads(service.repository.job(record['record_id'])['spec_json'])
    assert spec['requirements']['required_workloads'] == []
    assert spec['payload']['verification_only'] is True
    if format != 'adapter':
        assert f'export.{format}' not in service.repository.overview()['nodes'][0]['tested_workloads']
        normal = client.post('/app/v1/exports', headers={'X-App-Token': 'local-test-session'}, json=request(training_id, format, verify=False))
        assert normal.status_code == 422
        assert 'lacks tested export capabilities' in normal.text
    lease = service.claim_job(node_id='worker', token=token, idempotency_key='verify-claim')
    service.ack_job(node_id='worker', token=token, job_id=lease['job_id'],
                    lease_token=lease['lease_token'], lease_generation=lease['lease_generation'], idempotency_key='verify-ack')
    # The bytes below deliberately are not a real converted model.
    source = tmp_path / 'synthetic-output.bin'
    source.write_bytes(b'synthetic conversion protocol fixture')
    attempt = {'source_job_id': lease['job_id'], 'source_attempt_id': lease['attempt_id'],
               'source_lease_generation': lease['lease_generation'],
               'source_spec_sha256': service.repository.job(lease['job_id'])['spec_fingerprint'],
               'training_kind': lease['spec']['kind']}
    package = ExportPackageBuilder().build(
        [ExportArtifact(kind, source, hashlib.sha256(source.read_bytes()).hexdigest(), 'apache-2.0', spec['payload']['source_artifact_reference'])
         for kind in (format, 'tokenizer')],
        tmp_path / 'packages', source_training_manifest_sha256=spec['payload']['source_training_manifest_sha256'],
        serving=spec['payload']['serving'], source_attempt=attempt,
    )
    archive, _ = deterministic_zip(package.path, tmp_path / 'package.zip')
    stored = service.artifacts.ingest_file(archive)
    service.repository.bind_artifact_upload(artifact_id=stored['artifact_id'], node_id='worker',
                                            job=service.repository.job(lease['job_id']), sha256=stored['sha256'])
    result = {'package_id': package.package_id, 'package_fingerprint': package.fingerprint,
              'formats': [format], 'artifacts': [{'kind': 'export_package', **stored}]}
    with pytest.raises(ValueError):
        complete(service, token, lease, {**result, 'package_fingerprint': '0' * 64}, 'bad-verify')
    assert service.repository.product_record(lease['job_id'])['status'] == 'EXPORT_VERIFICATION_QUEUED'
    assert complete(service, token, lease, result, 'verified')['accepted'] is True
    assert f'export.{format}' in service.repository.overview()['nodes'][0]['tested_workloads']
    normal = client.post('/app/v1/exports', headers={'X-App-Token': 'local-test-session'}, json=request(training_id, format, verify=False))
    assert normal.status_code == 200, normal.text
    normal_spec = json.loads(service.repository.job(normal.json()['record_id'])['spec_json'])
    assert normal_spec['requirements']['required_workloads'] == [f'export.{format}']


@pytest.mark.parametrize('fault', ['dependencies', 'training', 'revoked', 'converter', 'flag', 'format'])
def test_initial_verification_retains_source_and_environment_gates(tmp_path, fault):
    service, _, training_id = completed_training(tmp_path, dependencies=fault != 'dependencies')
    body = request(training_id, 'gguf' if fault == 'converter' else 'merged_model')
    if fault == 'training':
        with service.repository.connect() as db:
            db.execute('UPDATE jobs SET result_validation_version=0 WHERE job_id=?', (training_id,))
    elif fault == 'revoked':
        service.repository.revoke_node('worker')
    elif fault == 'converter':
        body['llama_cpp_converter'] = None
    elif fault == 'flag':
        body['verification_only'] = 'true'
    elif fault == 'format':
        body['formats'] = ['invented']
    client = TestClient(create_app(service, app_token='local-test-session'))
    response = client.post('/app/v1/exports', headers={'X-App-Token': 'local-test-session'}, json=body)
    assert response.status_code in {400, 422}
    assert service.product_workspace()['exports'] == []

