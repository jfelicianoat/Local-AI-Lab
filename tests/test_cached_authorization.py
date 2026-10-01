from __future__ import annotations

import pytest
from datetime import UTC, datetime, timedelta

from local_ai_lab.coordinator.repository.base import LeaseRejected
from local_ai_lab.coordinator.service import CoordinatorService
from local_ai_lab.coordinator.service import AuthenticationError
from local_ai_lab.domain.jobs import JobSpec
from local_ai_lab.training.checkpoints import create_checkpoint_bundle


def leased(tmp_path, *, kind='protocol.authorization-fixture.v1', payload=None):
    service = CoordinatorService(tmp_path / 'coordinator.db')
    tokens = {node: service.pair_and_register(pairing_code=service.create_pairing_code(), node_id=node, hostname=node)['device_token']
              for node in ('owner', 'other')}
    job = JobSpec(kind=kind, payload=payload or {}, requirements={'node_ids': ['owner']})
    service.submit_job(job, 'submit')
    lease = service.claim_job(node_id='owner', token=tokens['owner'], idempotency_key='claim')
    args = {'node_id': 'owner', 'token': tokens['owner'], 'job_id': job.job_id,
            'lease_token': lease['lease_token'], 'lease_generation': lease['lease_generation']}
    service.ack_job(**args, idempotency_key='ack')
    return service, tokens, lease, args


def completion(args, lease):
    return {**args, 'attempt_id': lease['attempt_id'], 'outcome': 'succeeded',
            'payload': {'fixture': 'same result'}, 'idempotency_key': 'complete'}


@pytest.mark.parametrize('fault', ['other_worker', 'lease_token', 'lease_generation'])
def test_completion_receipt_rechecks_authorization_before_returning_cached_success(tmp_path, fault):
    service, tokens, lease, args = leased(tmp_path)
    body = completion(args, lease)
    accepted = service.complete_job(**body)
    invalid = dict(body)
    if fault == 'other_worker': invalid.update(node_id='other', token=tokens['other'])
    elif fault == 'lease_token': invalid['lease_token'] = 'incorrect-lease-token'
    else: invalid['lease_generation'] += 1
    response = service.complete_job(**invalid)
    assert response == {'job_id': lease['job_id'], 'accepted': False, 'classification': 'stale_attempt'}
    assert service.complete_job(**body) == accepted


def test_unauthorized_initial_completion_cannot_reserve_the_owner_idempotency_key(tmp_path):
    service, tokens, lease, args = leased(tmp_path)
    body = completion(args, lease)
    rejected = service.complete_job(**{**body, 'node_id': 'other', 'token': tokens['other']})
    assert rejected['accepted'] is False
    assert service.complete_job(**body)['accepted'] is True


def test_original_owner_can_recover_an_accepted_receipt_after_lease_expiry_and_restart(tmp_path):
    service, _, lease, args = leased(tmp_path)
    body = completion(args, lease)
    accepted = service.complete_job(**body)
    with service.repository.connect() as db:
        db.execute("UPDATE jobs SET lease_expires_at='2000-01-01T00:00:00Z' WHERE job_id=?", (lease['job_id'],))
    reopened = CoordinatorService(service.repository.path)
    assert reopened.complete_job(**body) == accepted


@pytest.mark.parametrize('operation', ['ack', 'progress', 'renew'])
@pytest.mark.parametrize('fault', ['other_worker', 'lease_token'])
def test_other_cached_job_mutations_still_require_the_current_lease_identity(tmp_path, operation, fault):
    service, tokens, lease, args = leased(tmp_path)
    if operation == 'ack': call, extra = service.ack_job, {'idempotency_key': 'ack'}
    elif operation == 'progress': call, extra = service.progress, {'sequence': 1, 'payload': {'stage': 'fixture'}, 'idempotency_key': 'progress'}
    else: call, extra = service.renew_lease, {'lease_seconds': 60, 'idempotency_key': 'renew'}
    accepted = call(**args, **extra)
    invalid = dict(args)
    if fault == 'other_worker': invalid.update(node_id='other', token=tokens['other'])
    else: invalid['lease_token'] = 'incorrect-lease-token'
    with pytest.raises(LeaseRejected): call(**invalid, **extra)
    assert call(**args, **extra) == accepted


@pytest.mark.parametrize('fault', ['other_worker', 'lease_token'])
def test_checkpoint_receipt_is_bound_to_the_publishing_worker_and_lease(tmp_path, fault):
    payload = {'dataset_fingerprint': 'a' * 64, 'base_model': 'synthetic-model', 'chat_template_fingerprint': 'b' * 64}
    service, tokens, lease, args = leased(tmp_path, kind='training.lora.v1', payload=payload)
    directory = tmp_path / 'checkpoint-4'
    directory.mkdir()
    (directory / 'trainer_state.json').write_text('{"global_step":4}', encoding='utf-8')
    for name in ('optimizer.pt', 'scheduler.pt', 'adapter_model.safetensors'):
        (directory / name).write_bytes(b'synthetic protocol fixture')
    metadata = {'source_job_id': lease['job_id'], 'source_attempt_id': lease['attempt_id'],
                'source_lease_generation': lease['lease_generation'],
                'source_spec_sha256': service.repository.job(lease['job_id'])['spec_fingerprint'],
                'training_kind': 'training.lora.v1', 'dataset_fingerprint': 'a' * 64,
                'model_id': 'synthetic-model', 'base_weights_sha256': 'c' * 64, 'chat_template_fingerprint': 'b' * 64}
    bundle, digest = create_checkpoint_bundle(directory, tmp_path / 'checkpoint.zip', metadata=metadata, step=4)
    stored = service.artifacts.ingest_file(bundle)
    service.repository.bind_artifact_upload(artifact_id=stored['artifact_id'], node_id='owner',
                                            job=service.repository.job(lease['job_id']), sha256=digest)
    extra = {'attempt_id': lease['attempt_id'], 'step': 4, 'artifact_id': stored['artifact_id'],
             'artifact_sha256': digest, 'idempotency_key': 'checkpoint'}
    accepted = service.publish_training_checkpoint(**args, **extra)
    invalid = dict(args)
    if fault == 'other_worker': invalid.update(node_id='other', token=tokens['other'])
    else: invalid['lease_token'] = 'incorrect-token'
    with pytest.raises(LeaseRejected): service.publish_training_checkpoint(**invalid, **extra)
    assert service.publish_training_checkpoint(**args, **extra) == accepted
    assert len(service.training_checkpoints(lease['job_id'])) == 1


def test_a_cached_progress_receipt_does_not_authorize_a_reassigned_lease(tmp_path):
    service, _, lease, args = leased(tmp_path)
    extra = {'sequence': 1, 'payload': {'stage': 'fixture'}, 'idempotency_key': 'progress'}
    service.progress(**args, **extra)
    service.repository.expire_leases(datetime.now(UTC) + timedelta(hours=1))
    service.repository.reconcile_orphan(lease['job_id'], 'requeue')
    new = service.claim_job(node_id='owner', token=args['token'], idempotency_key='new-claim')
    assert new['attempt_id'] != lease['attempt_id']
    with pytest.raises(LeaseRejected): service.progress(**args, **extra)


def test_revoked_worker_cannot_recover_an_accepted_completion(tmp_path):
    service, _, lease, args = leased(tmp_path)
    body = completion(args, lease)
    service.complete_job(**body)
    service.repository.revoke_node('owner')
    with pytest.raises(AuthenticationError): service.complete_job(**body)

