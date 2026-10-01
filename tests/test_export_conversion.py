"""Export filesystem/reload orchestration with mocked ML libraries, not real GPU proof."""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from local_ai_lab.exporting.executor import ExportExecutionError, ModelExportExecutor
from local_ai_lab.exporting.package import ExportPackageVerifier


def conversion(tmp_path, monkeypatch, *, format='merged_model', fault=None):
    root = tmp_path / 'training'
    (root / 'adapter').mkdir(parents=True)
    (root / 'adapter' / 'adapter_model.safetensors').write_bytes(b'synthetic adapter')
    (root / 'tokenizer').mkdir()
    template = 'trained-chat-template'
    (root / 'tokenizer' / 'tokenizer_config.json').write_text(json.dumps({'chat_template': template}), encoding='utf-8')
    (root / 'tokenizer' / 'chat_template.jinja').write_text(template, encoding='utf-8')
    manifest = root / 'training-manifest.json'
    manifest.write_text('{"schema_version":"training-result.v1"}', encoding='utf-8')
    if fault == 'missing_tokenizer':
        (root / 'tokenizer' / 'tokenizer_config.json').unlink()

    class Merged:
        def save_pretrained(self, directory, **kwargs):
            directory.mkdir()
            (directory / 'model.safetensors').write_bytes(b'synthetic merged weights')
            (directory / 'config.json').write_text('{"model_type":"fixture"}', encoding='utf-8')

    class Model:
        @staticmethod
        def from_pretrained(location, **kwargs):
            if kwargs.get('output_loading_info'):
                assert (Path(location) / 'tokenizer_config.json').is_file()
                return object(), {'missing_keys': ['weight'] if fault == 'reload' else []}
            return object()

    class Tokenizer:
        @staticmethod
        def from_pretrained(location, **kwargs):
            saved = json.loads((Path(location) / 'tokenizer_config.json').read_text(encoding='utf-8'))
            return SimpleNamespace(chat_template='changed' if fault == 'template' else saved['chat_template'])

    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(AutoModelForCausalLM=Model, AutoTokenizer=Tokenizer))
    monkeypatch.setitem(sys.modules, 'peft', SimpleNamespace(PeftModel=SimpleNamespace(
        from_pretrained=lambda *args, **kwargs: SimpleNamespace(merge_and_unload=lambda: Merged()))))
    converter = tmp_path / 'converter.py'
    converter.write_text('# synthetic converter; it is never executed', encoding='utf-8')

    def fake_convert(command, **kwargs):
        # A real llama.cpp converter needs the tokenizer alongside model config/weights.
        assert (Path(command[2]) / 'tokenizer_config.json').is_file()
        target = Path(command[command.index('--outfile') + 1])
        content = b'GGUF' + struct.pack('<IQQ', 3, 1, 1) + b'synthetic container content'
        if fault == 'empty_gguf': content = b''
        if fault == 'bad_gguf': content = b'not a GGUF model' * 3
        target.write_bytes(content)
        return SimpleNamespace(returncode=0, stderr='')

    monkeypatch.setattr('local_ai_lab.exporting.executor.subprocess.run', fake_convert)
    return {'resolved_training_output': str(root), 'base_model': 'synthetic-local-model',
            'source_manifest_file_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
            'source_training_manifest_sha256': 'a' * 64, 'source_artifact_reference': 'sha256:' + 'b' * 64,
            'formats': [format], 'required_support_artifacts': ['tokenizer'],
            'license_id': 'apache-2.0', 'serving': {'runtime': 'transformers',
                'chat_template_fingerprint': hashlib.sha256(template.encode()).hexdigest()},
            'llama_cpp_converter': str(converter), 'output_dir': str(tmp_path / 'export')}


@pytest.mark.parametrize('format', ['adapter', 'merged_model', 'safetensors', 'gguf'])
def test_export_keeps_saved_tokenizer_template_and_merged_configuration(tmp_path, monkeypatch, format):
    result = ModelExportExecutor()(conversion(tmp_path, monkeypatch, format=format), lambda event: None)
    package = Path(result['package_path'])
    manifest = ExportPackageVerifier().verify(package)
    assert {item['kind'] for item in manifest['artifacts']} == {format, 'tokenizer'}
    metadata = next(item for item in manifest['artifacts'] if item['kind'] == 'tokenizer')
    with zipfile.ZipFile(package / metadata['filename']) as archive:
        assert json.loads(archive.read('tokenizer_config.json'))['chat_template'] == 'trained-chat-template'
        assert archive.read('chat_template.jinja') == b'trained-chat-template'
        if format != 'adapter': assert 'config.json' in archive.namelist()
    if format == 'merged_model':
        model = next(item for item in manifest['artifacts'] if item['kind'] == format)
        with zipfile.ZipFile(package / model['filename']) as archive:
            assert {'config.json', 'tokenizer_config.json', 'chat_template.jinja', 'model.safetensors'} <= set(archive.namelist())


@pytest.mark.parametrize('fault', ['missing_tokenizer', 'reload', 'template', 'empty_gguf', 'bad_gguf'])
def test_incomplete_or_failed_conversion_cannot_publish_a_package(tmp_path, monkeypatch, fault):
    payload = conversion(tmp_path, monkeypatch, format='gguf' if 'gguf' in fault else 'merged_model', fault=fault)
    with pytest.raises(ExportExecutionError):
        ModelExportExecutor()(payload, lambda event: None)
    assert not (tmp_path / 'export' / 'packages').exists()

