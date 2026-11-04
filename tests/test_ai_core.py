"""ai_core foundations: hardware profiles, catalog schema, settings, installs, storage, VRAM broker, engines."""
import tests._isolation  # noqa: F401  (must precede application imports)
import hashlib
import io
import json
import os
import re
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from ai_core import catalog, engines, gpu, hardware, models, paths, settings
from ai_core.errors import AIUnavailable, ConsentRequired, ModelMissing
from tests._ai_support import HIGH_INFO, LAPTOP_INFO, FakeOllama, IsolatedAIMixin, wait_for

SHA = re.compile(r'^[0-9a-f]{64}$')
COMMIT_URL = re.compile(r'^https://huggingface\.co/[^/]+/[^/]+/resolve/[0-9a-f]{40}/')


def response(chunks, status=200):
    mock = MagicMock()
    mock.status_code = status
    mock.__enter__.return_value = mock
    mock.iter_content.side_effect = lambda chunk_size=None: iter(chunks)
    mock.raise_for_status.side_effect = None if status < 400 else RuntimeError(f'HTTP {status}')
    return mock


class HardwareProfileTests(IsolatedAIMixin, unittest.TestCase):
    def test_profile_matrix(self):
        cases = [
            ({'gpu_vendor': 'nvidia', 'vram_gb': 12.0}, 'gpu_high'),
            ({'gpu_vendor': 'nvidia', 'vram_gb': 8.0}, 'gpu_mid'),
            ({'gpu_vendor': 'nvidia', 'vram_gb': 6.0}, 'gpu_mid'),
            ({'gpu_vendor': 'nvidia', 'vram_gb': 10.0}, 'gpu_mid'),
            ({'gpu_vendor': 'nvidia', 'vram_gb': 11.0}, 'gpu_high'),
            ({'gpu_vendor': 'nvidia', 'vram_gb': 16.0}, 'gpu_high'),
            ({'gpu_vendor': 'nvidia', 'vram_gb': 24.0}, 'gpu_ultra'),
            ({'gpu_vendor': 'nvidia', 'vram_gb': 4.0}, 'laptop'),
            ({'gpu_vendor': 'amd', 'vram_gb': 16.0}, 'laptop'),
            ({'gpu_vendor': 'intel', 'vram_gb': 0.0}, 'laptop'),
            ({'gpu_vendor': 'none', 'vram_gb': 0.0}, 'laptop'),
            ({'gpu_vendor': 'nvidia', 'vram_gb': 24.0, 'ai_pack': False}, 'essentials'),
        ]
        for info, expected in cases:
            with self.subTest(info=info):
                self.assertEqual(hardware.profile({'ai_pack': True, **info}), expected)

    def test_detect_nvidia_via_nvidia_smi(self):
        memory = MagicMock(total=32 * 1024 ** 3)
        fake_psutil = MagicMock(virtual_memory=MagicMock(return_value=memory))
        with patch.object(hardware.shutil, 'which', return_value='nvidia-smi'), \
                patch.object(hardware, '_run', return_value='NVIDIA GeForce RTX 3060, 6144\nNVIDIA GeForce RTX 3080, 12288\n'), \
                patch.dict('sys.modules', {'psutil': fake_psutil}), \
                patch.object(hardware, 'ai_pack_installed', return_value=True):
            info = hardware.detect(refresh=True)
        self.assertEqual((info['gpu_vendor'], info['gpu_name'], info['vram_gb']), ('nvidia', 'NVIDIA GeForce RTX 3080', 12.0))
        self.assertEqual(info['ram_gb'], 32.0)
        self.assertEqual(len(info['gpus']), 2)
        self.assertEqual(hardware.profile(info), 'gpu_high')

    def test_ram_gb_without_psutil_uses_os_fallback(self):
        with patch.dict('sys.modules', {'psutil': None}):
            ram = hardware._ram_gb()
        self.assertGreater(ram, 0.0)

    def test_detect_other_gpu_uses_cim_and_recommends_laptop(self):
        def run(args, timeout=6):
            return 'Intel(R) UHD Graphics 620\n' if args[0] == 'powershell' else ''
        with patch.object(hardware.shutil, 'which', return_value=None), patch.object(hardware.os, 'name', 'nt'), \
                patch.object(hardware, '_run', side_effect=run), patch.object(hardware, 'ai_pack_installed', return_value=True):
            info = hardware.detect(refresh=True)
        self.assertEqual(info['gpu_vendor'], 'intel')
        self.assertEqual(hardware.profile(info), 'laptop')
        self.assertTrue(hardware.directml_candidate(info))

    def test_detect_is_cached(self):
        with patch.object(hardware, '_nvidia_gpus', return_value=[]) as probe, patch.object(hardware, '_other_gpus', return_value=[]):
            hardware.detect(refresh=True)
            hardware.detect()
        self.assertEqual(probe.call_count, 1)

    def test_run_handles_missing_tools(self):
        self.assertEqual(hardware._run(['definitely-not-a-real-tool-xyz']), '')

    def test_override_in_settings_wins(self):
        with patch.object(hardware, 'detect', return_value=HIGH_INFO):
            self.assertEqual(hardware.current_profile(), 'gpu_high')
            settings.update(lambda data: data.__setitem__('profile_override', 'laptop'))
            self.assertEqual(hardware.current_profile(), 'laptop')
            settings.update(lambda data: data.__setitem__('profile_override', 'bogus'))
            self.assertEqual(hardware.current_profile(), 'gpu_high')

    def test_vendor_names(self):
        self.assertEqual(hardware._vendor('AMD Radeon RX 6600'), 'amd')
        self.assertEqual(hardware._vendor('Qualcomm Adreno'), 'qualcomm')
        self.assertEqual(hardware._vendor('Basic Display'), 'other')

    def test_detect_other_gpu_falls_back_to_win32_display_devices_when_cim_empty(self):
        with patch.object(hardware.shutil, 'which', return_value=None), patch.object(hardware.os, 'name', 'nt'),                 patch.object(hardware, '_run', return_value=''),                 patch.object(hardware, '_display_devices', return_value=[
                    {'vendor': 'intel', 'name': 'Intel(R) UHD Graphics 620', 'vram_gb': 0.0}]),                 patch.object(hardware, 'ai_pack_installed', return_value=True):
            info = hardware.detect(refresh=True)
        self.assertEqual((info['gpu_vendor'], info['gpu_name']), ('intel', 'Intel(R) UHD Graphics 620'))
        self.assertEqual(hardware.profile(info), 'laptop')
        self.assertTrue(hardware.directml_candidate(info))

    def test_recommended_treats_15_9_gb_usable_ram_as_16_gb(self):
        self.assertEqual(catalog.recommended('laptop', 'helper', {'ram_gb': 15.9}), ['qwen3-4b', 'qwen3-1.7b'])
        self.assertEqual(catalog.recommended('laptop', 'speech', {'ram_gb': 15.9}), ['whisper-small', 'whisper-base'])
        self.assertEqual(catalog.recommended('laptop', 'helper', {'ram_gb': 8.0}), ['qwen3-1.7b', 'qwen3-4b'])
        self.assertEqual(catalog.recommended('laptop', 'speech', {'ram_gb': 8.0}), ['whisper-base', 'whisper-small'])

    def test_disk_free_falls_back_to_app_dir_on_permission_error(self):
        usage = MagicMock(free=64 * 1024 ** 3)
        calls = []

        def disk_usage(target):
            calls.append(Path(target))
            if len(calls) == 1:
                raise PermissionError(5, 'Access is denied')
            return usage
        with patch.object(hardware.shutil, 'disk_usage', side_effect=disk_usage):
            self.assertEqual(hardware._disk_free_gb(), 64.0)
        calls.clear()
        with patch.object(models.shutil, 'disk_usage', side_effect=disk_usage):
            self.assertEqual(models._disk_free(paths.MODELS_DIR), 64 * 1024 ** 3)

    def test_engine_ollama_counts_as_installed_when_server_running_without_binary(self):
        with patch.object(engines.ollama, 'executable', return_value=None),                 patch.object(engines.ollama, 'running', return_value=True),                 patch.object(engines.ollama, 'tags', return_value=[]):
            state = models.status()['engine-ollama']
        self.assertTrue(state['installed'] and state['verified'])


class CatalogSchemaTests(unittest.TestCase):
    def test_every_item_is_complete_and_pinned(self):
        items = catalog.items()
        ids = [item['id'] for item in items]
        self.assertEqual(len(ids), len(set(ids)))
        for item in items:
            with self.subTest(item=item['id']):
                for key in ('id', 'kind', 'roles', 'profiles', 'name', 'purpose', 'features', 'source', 'license',
                            'size_bytes', 'vram_gb', 'ram_gb', 'local', 'companions'):
                    self.assertIn(key, item)
                self.assertTrue(set(item['profiles']) <= set(hardware.PROFILES))
                self.assertTrue(item['source'].get('publisher'))
                self.assertTrue(item['source'].get('url', '').startswith('https://'))
                self.assertIn(item['license'].get('non_commercial'), (True, False))
                self.assertTrue(item['license'].get('name'))
                self.assertTrue(item['license'].get('url', '').startswith('https://'))
                self.assertGreater(item['size_bytes'], 0)
                self.assertTrue(item['local'])
                for companion in item['companions']:
                    self.assertTrue(catalog.exists(companion), companion)
                if item['backend'] == 'ollama':
                    self.assertTrue(item['source']['ollama_tag'])
                    self.assertIsNone(item['sha256'])
                    continue
                self.assertTrue(item['files'])
                self.assertRegex(item['sha256'], SHA)
                for entry in item['files']:
                    self.assertTrue(entry['url'].startswith('https://'))
                    self.assertRegex(entry['sha256'], SHA)
                    self.assertGreater(entry['size_bytes'], 0)
                    if 'huggingface.co' in entry['url']:
                        self.assertRegex(entry['url'], COMMIT_URL)
                    paths.resolve_item_path(entry['path'], 'engines' if item.get('install_root') == 'engines' else 'models')

    def test_whisper_sha_matches_official_url(self):
        for name in ('base', 'small', 'large-v3-turbo', 'large-v3'):
            entry = catalog.get(f'whisper-{name}')['files'][0]
            self.assertIn(f'/{entry["sha256"]}/{name}.pt', entry['url'])

    def test_builtin_qwen3_4b_reuses_existing_pinned_file(self):
        from assets import lyric_translation
        entry = catalog.get('qwen3-4b')['files'][0]
        self.assertEqual((entry['url'], entry['sha256'], entry['size_bytes']),
                         (lyric_translation.MODEL_URL, lyric_translation.MODEL_SHA256, lyric_translation.MODEL_SIZE))
        self.assertIn('@app/ai_models/Qwen3-4B-Q4_K_M.gguf', entry['legacy'])

    def test_non_commercial_flags(self):
        for item_id in ('inswapper-128', 'insightface-buffalo-l', 'flux-kontext-dev-q4', 'codeformer', 'qwen2.5vl:3b'):
            self.assertTrue(catalog.get(item_id)['license']['non_commercial'], item_id)
        for item_id in ('gfpgan-1.4', 'flux-schnell-q4', 'qwen3:14b', 'whisper-large-v3-turbo', 'wan22-ti2v-5b'):
            self.assertFalse(catalog.get(item_id)['license']['non_commercial'], item_id)

    def test_contract_default_recommendations(self):
        expected = {
            'gpu_mid': {'helper': 'qwen3:8b', 'translator': 'translategemma:4b', 'speech': 'whisper-large-v3-turbo', 'vision': 'qwen2.5vl:3b'},
            'gpu_high': {'helper': 'qwen3:14b', 'translator': 'translategemma:12b', 'speech': 'whisper-large-v3-turbo', 'vision': 'qwen2.5vl:7b'},
            'gpu_ultra': {'helper': 'qwen3:32b', 'translator': 'translategemma:27b', 'speech': 'whisper-large-v3', 'vision': 'qwen2.5vl:32b'},
        }
        for profile, roles in expected.items():
            for role, first in roles.items():
                self.assertEqual(catalog.recommended(profile, role)[0], first)
        self.assertEqual(catalog.recommended('essentials', 'helper'), [])
        for profile, roles in catalog.section('recommendations').items():
            for ids in roles.values():
                self.assertTrue(all(catalog.exists(i) for i in ids))
        for ids in catalog.section('bundles').values():
            self.assertTrue(all(catalog.exists(i) for i in ids))

    def test_laptop_recommendations_follow_ram(self):
        self.assertEqual(catalog.recommended('laptop', 'helper', {'ram_gb': 8})[0], 'qwen3-1.7b')
        self.assertEqual(catalog.recommended('laptop', 'helper', {'ram_gb': 32})[0], 'qwen3-4b')
        self.assertEqual(catalog.recommended('laptop', 'speech', {'ram_gb': 8})[0], 'whisper-base')
        self.assertEqual(catalog.recommended('laptop', 'speech', {'ram_gb': 16})[0], 'whisper-small')

    def test_workflows_reference_installable_items_and_placeholders(self):
        from ai_core import comfy
        for name, meta in catalog.section('workflows').items():
            with self.subTest(workflow=name):
                for item_id in meta['requires'] + meta['custom_nodes']:
                    self.assertTrue(catalog.exists(item_id))
                _, data = comfy.workflow_spec(name)
                text = json.dumps(data['prompt'])
                placeholders = set(re.findall(r'"\{\{(\w+)\}\}"', text))
                self.assertEqual(placeholders, set(data['inputs']))
                for spec in data['inputs'].values():
                    self.assertIn(spec['node'], data['prompt'])
                    self.assertIn(spec['field'], data['prompt'][spec['node']]['inputs'])

    def test_cloud_endpoints_use_documented_argument_names(self):
        self.assertEqual(catalog.cloud_endpoint('fal', 'kling_motion_control')['image_arg'], 'image_url')
        self.assertEqual(catalog.cloud_endpoint('fal', 'kling_motion_control')['video_arg'], 'video_url')
        self.assertEqual(catalog.cloud_endpoint('fal', 'live_portrait')['image_arg'], 'image_url')
        self.assertTrue(catalog.cloud_endpoint('gemini', 'nano_banana')['model'])
        self.assertIsNone(catalog.cloud_endpoint('fal', 'missing'))
        with self.assertRaises(KeyError):
            catalog.workflow('missing')
        with self.assertRaises(KeyError):
            catalog.get('missing')

    def test_paths_cannot_escape(self):
        with self.assertRaises(ValueError):
            paths.resolve_item_path('../outside.bin')
        with self.assertRaises(ValueError):
            paths.resolve_item_path('@app/../../outside.bin')


class SettingsTests(IsolatedAIMixin, unittest.TestCase):
    def test_defaults_licenses_and_overrides(self):
        data = settings.load()
        self.assertIsNone(data['profile_override'])
        self.assertFalse(settings.cloud_enabled('fal'))
        settings.accept_license('inswapper-128')
        settings.accept_license('inswapper-128')
        self.assertEqual(settings.accepted_licenses(), {'inswapper-128'})
        settings.update(lambda d: d['roles'].__setitem__('helper', 'qwen2.5:14b'))
        self.assertEqual(settings.get_role_override('helper'), 'qwen2.5:14b')
        self.assertIsNone(settings.get_role_override('vision'))
        self.assertGreaterEqual(settings.idle_release_seconds(), 10)

    def test_corrupt_settings_file_is_preserved(self):
        paths.SETTINGS_FILE.write_text('{broken', encoding='utf-8')
        self.assertEqual(settings.load()['roles']['helper'], None)
        self.assertTrue(list(self.root.glob('ai_settings.corrupt-*.json')))

    def test_invalid_idle_value_falls_back(self):
        settings.save({'idle_release_seconds': 'soon'})
        self.assertEqual(settings.idle_release_seconds(), 300.0)


def _fake_item(item_id, data, *, nc=False, path=None, sha=None, size=None, **extra):
    return {'id': item_id, 'kind': extra.pop('kind', 'asr'), 'backend': extra.pop('backend', 'whisper'), 'roles': [],
            'profiles': ['laptop'], 'name': item_id.title(), 'purpose': 'test', 'features': ['Test'],
            'source': {'publisher': 'Test', 'url': 'https://example.invalid'},
            'files': [{'path': path or f'test/{item_id}.bin', 'url': f'https://example.invalid/{item_id}.bin',
                       'size_bytes': len(data) if size is None else size,
                       'sha256': hashlib.sha256(data).hexdigest() if sha is None else sha}],
            'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'license': {'name': 'Test', 'url': 'https://example.invalid/license', 'non_commercial': nc},
            'vram_gb': 0, 'ram_gb': 1, 'local': True, 'companions': [], **extra}


class InstallTests(IsolatedAIMixin, unittest.TestCase):
    DATA = b'model-bytes-' * 1000

    def setUp(self):
        super().setUp()
        tags = patch.object(engines.ollama, 'tags', return_value=[])
        tags.start()
        self.addCleanup(tags.stop)

    def wait_job(self, job_id):
        self.assertTrue(wait_for(lambda: models.job(job_id)['state'] not in ('queued', 'running')))
        return models.job(job_id)

    def test_consent_required_and_no_network_without_acceptance(self):
        for nc in (True, False):
            self.use_catalog([_fake_item('tiny', self.DATA, nc=nc)])
            with self.subTest(nc=nc), patch.object(models.requests, 'get', side_effect=AssertionError('network')) as get, \
                    patch.object(models.requests, 'head', side_effect=AssertionError('network')):
                with self.assertRaises(ConsentRequired) as raised:
                    models.start_install('tiny')
                self.assertEqual(raised.exception.setup_hint, 'tiny')
                get.assert_not_called()
        self.assertIn('non-commercial', str(ConsentRequired('x non-commercial')))

    def test_real_catalog_nc_item_needs_consent(self):
        with self.assertRaisesRegex(ConsentRequired, 'non-commercial'):
            models.start_install('inswapper-128')

    def test_verified_download_installs_and_records_acceptance(self):
        self.use_catalog([_fake_item('tiny', self.DATA, nc=True)])
        chunks = [self.DATA[i:i + 4096] for i in range(0, len(self.DATA), 4096)]
        with patch.object(models.requests, 'get', return_value=response(chunks)):
            job = self.wait_job(models.start_install('tiny', accept_license=True))
        self.assertEqual(job['state'], 'done', job)
        target = paths.MODELS_DIR / 'test' / 'tiny.bin'
        self.assertEqual(target.read_bytes(), self.DATA)
        self.assertFalse(target.with_name('tiny.bin.part').exists())
        self.assertIn('tiny', settings.accepted_licenses())
        state = models.status()['tiny']
        self.assertTrue(state['installed'] and state['verified'])
        self.assertEqual(models.ensure('tiny'), target)
        with patch.object(models.requests, 'get', side_effect=AssertionError('network')):
            self.assertEqual(self.wait_job(models.start_install('tiny'))['state'], 'done')

    def test_hash_mismatch_is_rejected_and_discarded(self):
        self.use_catalog([_fake_item('tiny', self.DATA, sha='0' * 64)])
        with patch.object(models.requests, 'get', return_value=response([self.DATA])):
            job = self.wait_job(models.start_install('tiny', accept_license=True))
        self.assertEqual(job['state'], 'error')
        self.assertIn('SHA-256', job['error'])
        self.assertFalse((paths.MODELS_DIR / 'test' / 'tiny.bin').exists())
        self.assertFalse((paths.MODELS_DIR / 'test' / 'tiny.bin.part').exists())

    def test_oversized_download_is_rejected(self):
        self.use_catalog([_fake_item('tiny', self.DATA, size=10, sha='0' * 64)])
        with patch.object(models.requests, 'get', return_value=response([self.DATA])):
            job = self.wait_job(models.start_install('tiny', accept_license=True))
        self.assertIn('larger than expected', job['error'])

    def test_resume_from_partial_download(self):
        self.use_catalog([_fake_item('tiny', self.DATA)])
        part = paths.MODELS_DIR / 'test' / 'tiny.bin.part'
        part.parent.mkdir(parents=True)
        half = len(self.DATA) // 2
        part.write_bytes(self.DATA[:half])
        with patch.object(models.requests, 'get', return_value=response([self.DATA[half:]], status=206)) as get:
            job = self.wait_job(models.start_install('tiny', accept_license=True))
        self.assertEqual(job['state'], 'done', job)
        self.assertEqual(get.call_args.kwargs['headers'], {'Range': f'bytes={half}-'})
        self.assertEqual((paths.MODELS_DIR / 'test' / 'tiny.bin').read_bytes(), self.DATA)

    def test_server_ignoring_range_restarts_cleanly(self):
        self.use_catalog([_fake_item('tiny', self.DATA)])
        part = paths.MODELS_DIR / 'test' / 'tiny.bin.part'
        part.parent.mkdir(parents=True)
        part.write_bytes(b'garbage')
        with patch.object(models.requests, 'get', return_value=response([self.DATA], status=200)):
            job = self.wait_job(models.start_install('tiny', accept_license=True))
        self.assertEqual(job['state'], 'done', job)
        self.assertEqual((paths.MODELS_DIR / 'test' / 'tiny.bin').read_bytes(), self.DATA)

    def test_cancel_keeps_partial_and_never_installs(self):
        self.use_catalog([_fake_item('tiny', self.DATA)])
        holder = {}

        def chunks():
            yield self.DATA[:100]
            models.cancel(holder['job'])
            yield self.DATA[100:]
        mock = response([])
        mock.iter_content.side_effect = lambda chunk_size=None: chunks()
        started = threading.Event()
        original = models._run_install

        def delayed(job_ref):
            started.wait(2)
            original(job_ref)
        with patch.object(models, '_run_install', delayed), patch.object(models.requests, 'get', return_value=mock):
            holder['job'] = models.start_install('tiny', accept_license=True)
            started.set()
            job = self.wait_job(holder['job'])
        self.assertEqual(job['state'], 'cancelled')
        self.assertFalse((paths.MODELS_DIR / 'test' / 'tiny.bin').exists())
        self.assertTrue((paths.MODELS_DIR / 'test' / 'tiny.bin.part').exists())
        self.assertFalse(models.cancel(holder['job']))

    def test_ensure_never_downloads(self):
        self.use_catalog([_fake_item('tiny', self.DATA)])
        with patch.object(models.requests, 'get', side_effect=AssertionError('network')) as get:
            with self.assertRaises(ModelMissing) as raised:
                models.ensure('tiny')
            self.assertEqual(raised.exception.setup_hint, 'tiny')
            target = paths.MODELS_DIR / 'test' / 'tiny.bin'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'x' * len(self.DATA))
            with self.assertRaisesRegex(ModelMissing, 'failed verification'):
                models.ensure('tiny')
            target.write_bytes(self.DATA)
            self.assertEqual(models.ensure('tiny'), target)
        get.assert_not_called()

    def test_existing_corrupt_file_blocks_install(self):
        self.use_catalog([_fake_item('tiny', self.DATA)])
        target = paths.MODELS_DIR / 'test' / 'tiny.bin'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'y' * len(self.DATA))
        with patch.object(models.requests, 'get', side_effect=AssertionError('network')):
            job = self.wait_job(models.start_install('tiny', accept_license=True))
        self.assertEqual(job['state'], 'error')
        self.assertEqual(target.read_bytes(), b'y' * len(self.DATA))

    def test_legacy_location_counts_as_installed_and_is_never_deleted(self):
        legacy = '@home/.cache/whisper/tiny.bin'
        self.use_catalog([_fake_item('tiny', self.DATA, legacy=None)])
        item = _fake_item('tiny', self.DATA)
        item['files'][0]['legacy'] = [legacy]
        self.use_catalog([item])
        cached = paths.HOME_DIR / '.cache' / 'whisper' / 'tiny.bin'
        cached.parent.mkdir(parents=True)
        cached.write_bytes(self.DATA)
        self.assertTrue(models.status()['tiny']['installed'])
        self.assertEqual(models.ensure('tiny'), cached.resolve())
        self.assertEqual(models.remove('tiny'), {'removed': []})
        self.assertTrue(cached.exists())

    def test_remove_deletes_app_owned_files(self):
        self.use_catalog([_fake_item('tiny', self.DATA)])
        target = paths.MODELS_DIR / 'test' / 'tiny.bin'
        target.parent.mkdir(parents=True)
        target.write_bytes(self.DATA)
        self.assertEqual(models.remove('tiny')['removed'], [str(target.resolve())])
        self.assertFalse(target.exists())

    def test_notice_live_sizes_and_fallback(self):
        self.use_catalog([_fake_item('tiny', self.DATA, nc=True, companions=['dep']), _fake_item('dep', b'dep' * 10)])
        head = MagicMock(status_code=302, headers={'X-Linked-Size': '123456'})
        with patch.object(models.requests, 'head', return_value=head):
            notice = models.notice('tiny')
        self.assertEqual((notice['size_bytes'], notice['size_source']), (123456, 'live'))
        self.assertTrue(notice['non_commercial'] and notice['consent_required'])
        self.assertEqual([c['id'] for c in notice['companions']], ['dep'])
        self.assertEqual(notice['download_bytes'], 123456 + 30)
        with patch.object(models.requests, 'head', side_effect=models.requests.Timeout()):
            notice = models.notice('tiny')
        self.assertEqual((notice['size_bytes'], notice['size_source']), (len(self.DATA), 'catalog'))
        redirect = MagicMock(status_code=302, headers={})
        final = MagicMock(status_code=200, headers={'Content-Length': '999'})
        with patch.object(models.requests, 'head', side_effect=[redirect, final]):
            self.assertEqual(models._live_file_size('https://example.invalid/x'), 999)

    def test_ollama_notice_reads_registry_manifest(self):
        manifest = MagicMock()
        manifest.json.return_value = {'layers': [{'size': 100}, {'size': 23}]}
        with patch.object(models.requests, 'get', return_value=manifest) as get:
            size, source = models.live_size(catalog.get('qwen3:14b'))
        self.assertEqual((size, source), (123, 'live'))
        self.assertIn('registry.ollama.ai/v2/library/qwen3/manifests/14b', get.call_args.args[0])
        with patch.object(models.requests, 'get', side_effect=models.requests.ConnectionError()):
            self.assertEqual(models.live_size(catalog.get('qwen3:14b'))[1], 'catalog')

    def test_companions_install_first_engines_before_nodes(self):
        order = models._closure('flux-schnell-q4')
        self.assertEqual(order[-1], 'flux-schnell-q4')
        self.assertLess(order.index('engine-comfyui'), order.index('node-comfyui-gguf'))
        self.assertLess(order.index('node-comfyui-gguf'), order.index('flux-ae'))

    def test_disk_space_is_checked_before_download(self):
        self.use_catalog([_fake_item('tiny', self.DATA)])
        with patch.object(models, '_disk_free', return_value=0), patch.object(models.requests, 'get') as get:
            job = self.wait_job(models.start_install('tiny', accept_license=True))
        self.assertIn('disk space', job['error'])
        get.assert_not_called()

    def test_zip_engine_extracts_atomically_with_marker(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as bundle:
            bundle.writestr('top/ollama.exe', b'exe')
            bundle.writestr('top/lib/readme.txt', b'hi')
        data = buffer.getvalue()
        item = _fake_item('engine-x', data, kind='engine', backend='engine', install_root='engines',
                          path='downloads/x.zip', extract={'format': 'zip', 'to': 'x', 'strip_components': 1})
        self.use_catalog([item])
        with patch.object(models.requests, 'get', return_value=response([data])):
            job = self.wait_job(models.start_install('engine-x', accept_license=True))
        self.assertEqual(job['state'], 'done', job)
        target = paths.ENGINES_DIR / 'x'
        self.assertEqual((target / 'ollama.exe').read_bytes(), b'exe')
        self.assertTrue((target / models.MARKER).is_file())
        self.assertFalse((paths.ENGINES_DIR / 'downloads' / 'x.zip').exists())
        self.assertTrue(models.status()['engine-x']['verified'])
        self.assertEqual(models.remove('engine-x')['removed'], [str(target.resolve())])

    def test_zip_engine_retries_transient_windows_permission_error_on_replace(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as bundle:
            bundle.writestr('top/ollama.exe', b'exe')
        data = buffer.getvalue()
        item = _fake_item('engine-x', data, kind='engine', backend='engine', install_root='engines',
                          path='downloads/x.zip', extract={'format': 'zip', 'to': 'x', 'strip_components': 1})
        self.use_catalog([item])
        real_replace = os.replace
        attempts = {'extract': 0}

        def flaky_replace(src, dst):
            if str(src).endswith('.extracting') and attempts['extract'] == 0:
                attempts['extract'] += 1
                raise PermissionError(5, 'Access is denied')
            return real_replace(src, dst)

        with patch.object(models.requests, 'get', return_value=response([data])), \
                patch('storage_utils.os.replace', side_effect=flaky_replace), \
                patch('storage_utils.time.sleep'):
            job = self.wait_job(models.start_install('engine-x', accept_license=True))
        self.assertEqual(job['state'], 'done', job)
        self.assertEqual(attempts['extract'], 1)

    def test_zip_with_traversal_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as bundle:
            bundle.writestr('../evil.txt', b'x')
        data = buffer.getvalue()
        item = _fake_item('engine-x', data, kind='engine', backend='engine', install_root='engines',
                          path='downloads/x.zip', extract={'format': 'zip', 'to': 'x'})
        self.use_catalog([item])
        with patch.object(models.requests, 'get', return_value=response([data])):
            job = self.wait_job(models.start_install('engine-x', accept_license=True))
        self.assertIn('unsafe', job['error'])
        self.assertFalse((paths.ENGINES_DIR / 'evil.txt').exists())

    def test_ollama_items_pull_through_local_api(self):
        server = FakeOllama().start()
        self.addCleanup(server.stop)
        with patch.object(engines.ollama, 'base_url', server.url):
            job = self.wait_job(models.start_install('qwen3:14b', accept_license=True))
        self.assertEqual(job['state'], 'done', job)
        pulls = [body for method, path, body in server.requests if path == '/api/pull']
        self.assertEqual(pulls, [{'model': 'qwen3:14b', 'stream': True}])

    def test_ollama_pull_error_is_reported(self):
        server = FakeOllama().start()
        server.pull_events = [{'error': 'pull model manifest: file does not exist'}]
        self.addCleanup(server.stop)
        with patch.object(engines.ollama, 'base_url', server.url):
            job = self.wait_job(models.start_install('qwen3:14b', accept_license=True))
        self.assertEqual(job['state'], 'error')
        self.assertIn('does not exist', job['error'])

    def test_ollama_ensure_and_remove(self):
        server = FakeOllama(models=[{'name': 'qwen3:14b', 'size': 10}]).start()
        self.addCleanup(server.stop)
        with patch.object(engines.ollama, 'base_url', server.url), patch.object(engines.ollama, 'tags', return_value=[{'name': 'qwen3:14b'}]):
            self.assertTrue(models.status()['qwen3:14b']['installed'])
            self.assertTrue(models.ensure('qwen3:14b'))
            self.assertEqual(models.remove('qwen3:14b'), {'removed': ['qwen3:14b']})
        with self.assertRaises(ModelMissing):
            models.ensure('qwen3:14b')


class ReclaimTests(IsolatedAIMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        tags = patch.object(engines.ollama, 'tags', return_value=[])
        tags.start()
        self.addCleanup(tags.stop)

    def test_duplicates_and_obsolete_files_listed_and_removed_only_on_request(self):
        payload = os.urandom(2 * 1024 * 1024)
        video = paths.MODELS_DIR / 'video'
        video.mkdir(parents=True)
        owned = video / 'wan2.1-i2v-14b-480p-Q4_0.gguf'
        duplicate = video / 'wan2.2-animate-14b-480p-Q4_0.gguf'
        other = video / 'different.gguf'
        owned.write_bytes(payload)
        duplicate.write_bytes(payload)
        other.write_bytes(os.urandom(len(payload)))
        legacy = paths.APP_DIR / 'ai_models' / 'Llama-3.2-1B-Instruct-Q4_K_M.gguf'
        legacy.parent.mkdir(parents=True)
        legacy.write_bytes(b'old')
        stale = video / 'partial.gguf.part'
        stale.write_bytes(b'x')
        old = time.time() - 3 * 86400
        os.utime(stale, (old, old))
        listed = models.reclaimable()
        by_path = {entry['path']: entry for entry in listed}
        self.assertIn(str(duplicate), by_path)
        self.assertEqual(by_path[str(duplicate)]['duplicate_of'], str(owned))
        self.assertNotIn(str(owned), by_path)
        self.assertNotIn(str(other), by_path)
        self.assertIn(str(legacy.resolve()), by_path)
        self.assertEqual(by_path[str(stale)]['reason'], 'incomplete download')
        self.assertTrue(duplicate.exists() and legacy.exists())
        removed = models.remove_reclaimable(by_path[str(duplicate)]['id'])
        self.assertEqual(removed['path'], str(duplicate))
        self.assertFalse(duplicate.exists())
        self.assertTrue(owned.exists())
        with self.assertRaises(ValueError):
            models.remove_reclaimable(str(owned))
        storage = models.storage()
        self.assertIn('reclaimable', storage)
        self.assertEqual(storage['models_dir'], str(paths.MODELS_DIR))

    def test_storage_returns_immediately_and_verifies_in_background_or_explicitly(self):
        data = b'preexisting-weights'
        self.use_catalog([_fake_item('existing', data)])
        dest = paths.MODELS_DIR / 'test' / 'existing.bin'
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        self.assertFalse(models.status()['existing']['verified'])
        # storage() must not hash synchronously; it returns verified=None ('Checking…') and starts background verification.
        with patch.object(models, '_start_background_verify') as bg_mock, \
                patch.object(models, 'sha256_file', side_effect=AssertionError('synchronous hash in storage()')):
            storage = models.storage()
        bg_mock.assert_called_once()
        installed_by_id = {entry['id']: entry for entry in storage['installed']}
        self.assertIsNone(installed_by_id['existing']['verified'])
        # Explicit verification hashes the file and records the result.
        verified = models.verify_installed('existing')
        self.assertEqual(verified, {'existing': True})
        self.assertTrue(models.status()['existing']['verified'])
        self.assertTrue(models.storage()['installed'][0]['verified'])


class GpuBrokerTests(unittest.TestCase):
    def setUp(self):
        self.evicted = []
        for name in ('t-a', 't-b', 't-c'):
            gpu.register_evictor(name, lambda name=name: self.evicted.append(name))
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for name in ('t-a', 't-b', 't-c', 't-bad'):
            gpu.release(name)
            gpu.unregister_evictor(name)

    def test_lease_evicts_other_heavy_resident_models(self):
        with patch.object(settings, 'idle_release_seconds', return_value=60):
            with gpu.lease('t-a', 6):
                pass
            with gpu.lease('t-c', 0):
                pass
            self.assertEqual(self.evicted, [])
            with gpu.lease('t-b', 6):
                self.assertEqual(self.evicted, ['t-a'])
            self.assertIn('t-b', gpu.status())

    def test_idle_release_restarts_after_last_use(self):
        gpu.touch('t-a', idle_seconds=0.3)
        time.sleep(0.15)
        gpu.touch('t-a', idle_seconds=0.3)
        time.sleep(0.2)
        self.assertEqual(self.evicted, [])
        self.assertTrue(wait_for(lambda: self.evicted == ['t-a'], timeout=2))

    def test_concurrent_heavy_lease_waits_then_times_out(self):
        entered, release = threading.Event(), threading.Event()

        def hold():
            with gpu.lease('t-a', 6):
                entered.set()
                release.wait(2)
        worker = threading.Thread(target=hold)
        worker.start()
        entered.wait(2)
        with self.assertRaises(TimeoutError):
            with gpu.lease('t-b', 6, timeout=0.1):
                pass
        release.set()
        worker.join()
        with gpu.lease('t-b', 6, timeout=2):
            self.assertIn('t-a', self.evicted)

    def test_release_skips_active_and_evictor_errors_are_contained(self):
        gpu.register_evictor('t-bad', lambda: (_ for _ in ()).throw(RuntimeError('boom')))
        with gpu.lease('t-bad', 6):
            self.assertFalse(gpu.release('t-bad'))
        self.assertTrue(gpu.release('t-bad'))
        self.assertIs(gpu.model_lock('x'), gpu.model_lock('x'))


class EngineTests(IsolatedAIMixin, unittest.TestCase):
    def test_ollama_executable_search_order(self):
        portable = paths.ENGINES_DIR / 'ollama' / 'ollama.exe'
        local = self.root / 'local' / 'Programs' / 'Ollama' / 'ollama.exe'
        with patch.object(engines.shutil, 'which', return_value=None), patch.dict(os.environ, {'LOCALAPPDATA': str(self.root / 'local')}), \
                patch.object(engines.os, 'name', 'nt'):
            self.assertIsNone(engines.ollama.executable())
            portable.parent.mkdir(parents=True)
            portable.write_bytes(b'')
            self.assertEqual(engines.ollama.executable(), portable)
            local.parent.mkdir(parents=True)
            local.write_bytes(b'')
            self.assertEqual(engines.ollama.executable(), local)

    def test_ollama_never_installs_and_starts_hidden_when_installed(self):
        with patch.object(engines.ollama, 'running', return_value=False), patch.object(engines.ollama, 'executable', return_value=None), \
                patch.object(engines, '_spawn') as spawn:
            with self.assertRaises(ModelMissing) as raised:
                engines.ollama.ensure_running()
        self.assertEqual(raised.exception.setup_hint, 'engine-ollama')
        spawn.assert_not_called()
        exe = Path('C:/ollama/ollama.exe')
        with patch.object(engines.ollama, 'running', side_effect=[False, False, False, True]), \
                patch.object(engines.ollama, 'executable', return_value=exe), patch.object(engines, '_spawn') as spawn, \
                patch.object(engines.time, 'sleep'):
            self.assertTrue(engines.ollama.ensure_running(timeout=5))
        self.assertEqual(spawn.call_args.args[0], [str(exe), 'serve'])
        self.assertEqual(spawn.call_args.kwargs['env']['OLLAMA_HOST'], '127.0.0.1:11434')
        with patch.object(engines.subprocess, 'Popen') as popen:
            engines._spawn(['x'])
        self.assertEqual(popen.call_args.kwargs['creationflags'], engines._NO_WINDOW)

    def test_ollama_start_timeout_is_honest(self):
        with patch.object(engines.ollama, 'running', return_value=False), \
                patch.object(engines.ollama, 'executable', return_value=Path('ollama.exe')), patch.object(engines, '_spawn'), \
                patch.object(engines.time, 'sleep'), patch.object(engines.time, 'monotonic', side_effect=[0, 0, 100, 100]):
            with self.assertRaises(AIUnavailable):
                engines.ollama.ensure_running(timeout=1)

    def test_ollama_evictor_unloads_loaded_models_and_lists_tags(self):
        server = FakeOllama(models=[{'name': 'qwen3:14b'}, {'name': 'cloud', 'remote_host': 'https://ollama.com'}]).start()
        server.loaded = ['qwen3:14b', 'qwen2.5vl:7b']
        self.addCleanup(server.stop)
        with patch.object(engines.ollama, 'base_url', server.url):
            self.assertTrue(engines.ollama.status()['running'])
            self.assertEqual([t['name'] for t in engines.ollama.tags()], ['qwen3:14b'])
            engines._evict_ollama()
            self.assertIn('capabilities', engines.ollama.show('qwen3:14b'))
        unloads = [body for method, path, body in server.requests if path == '/api/generate']
        self.assertEqual(unloads, [{'model': 'qwen3:14b', 'keep_alive': 0}, {'model': 'qwen2.5vl:7b', 'keep_alive': 0}])

    def test_ollama_disk_manifests_when_server_stopped(self):
        manifest = paths.HOME_DIR / '.ollama' / 'models' / 'manifests' / 'registry.ollama.ai' / 'library' / 'qwen2.5' / '14b'
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({'layers': [{'size': 5}, {'size': 7}]}), encoding='utf-8')
        with patch.object(engines.ollama, 'base_url', 'http://127.0.0.1:9'), patch.dict(os.environ, {}, clear=False):
            os.environ.pop('OLLAMA_MODELS', None)
            self.assertEqual(engines.ollama.tags(), [{'name': 'qwen2.5:14b', 'size': 12, 'source': 'disk'}])
            self.assertFalse(engines.ollama.running())
            self.assertEqual(engines.ollama.loaded_models(), [])

    def test_builtin_availability(self):
        with patch.object(engines.importlib.util, 'find_spec', return_value=None):
            self.assertFalse(engines.builtin.status()['installed'])

    def test_comfy_requires_install_and_starts_with_safe_arguments(self):
        with patch.object(engines.comfy, 'running', return_value=False):
            with self.assertRaises(ModelMissing) as raised:
                engines.comfy.ensure_running()
        self.assertEqual(raised.exception.setup_hint, 'engine-comfyui')
        root = paths.ENGINES_DIR / 'comfyui' / 'ComfyUI_windows_portable'
        (root / 'ComfyUI').mkdir(parents=True)
        (root / 'ComfyUI' / 'main.py').write_text('')
        (root / 'python_embeded').mkdir()
        (root / 'python_embeded' / 'python.exe').write_bytes(b'')
        with patch.object(engines.comfy, 'running', side_effect=[False, False, False, True]), \
                patch.object(engines, '_spawn') as spawn, patch.object(engines.time, 'sleep'), \
                patch.object(settings, 'idle_release_seconds', return_value=60):
            self.assertTrue(engines.comfy.ensure_running(timeout=5))
        args = spawn.call_args.args[0]
        self.assertEqual(args[args.index('--listen') + 1], '127.0.0.1')
        self.assertEqual(args[args.index('--port') + 1], '8188')
        self.assertIn('--disable-auto-launch', args)
        self.assertEqual(spawn.call_args.kwargs['env']['USERPROFILE'], str(engines.comfy.home()))
        text = engines.comfy.model_paths_file().read_text(encoding='utf-8')
        self.assertIn(paths.MODELS_DIR.as_posix(), text)
        self.assertIn('clip_vision: clip_vision', text)
        engines.comfy.stop()

    def test_comfy_links_models_without_copying(self):
        root = paths.ENGINES_DIR / 'comfyui' / 'ComfyUI'
        root.mkdir(parents=True)
        (root / 'main.py').write_text('')
        source = paths.MODELS_DIR / 'liveportrait' / 'landmark.onnx'
        source.parent.mkdir(parents=True)
        source.write_bytes(b'onnx')
        engines.comfy.link_models({'comfy_links': [{'from': 'liveportrait/landmark.onnx', 'to': 'models/liveportrait/landmark.onnx'},
                                                   {'from': 'liveportrait/landmark.onnx', 'to': '@home/.cache/x.onnx'},
                                                   {'from': 'liveportrait/missing.onnx', 'to': 'models/liveportrait/missing.onnx'}]})
        self.assertEqual((root / 'models' / 'liveportrait' / 'landmark.onnx').read_bytes(), b'onnx')
        self.assertTrue((engines.comfy.home() / '.cache' / 'x.onnx').exists())
        with self.assertRaises(ValueError):
            engines.comfy.link_destination('../../escape.txt')

    def test_comfy_evictor_frees_memory(self):
        with patch.object(engines.comfy, 'running', return_value=True), patch.object(engines.requests, 'post') as post:
            engines._evict_comfy()
        self.assertTrue(post.call_args.args[0].endswith('/free'))
        self.assertEqual(post.call_args.kwargs['json'], {'unload_models': True, 'free_memory': True})

    def test_status_reports_every_engine(self):
        with patch.object(engines.ollama, 'version', return_value=None), patch.object(engines.ollama, 'executable', return_value=None), \
                patch.object(engines.comfy, 'running', return_value=False):
            status = engines.status()
        self.assertEqual(set(status), {'ollama', 'builtin', 'comfy'})
        self.assertEqual(status['ollama']['setup_hint'], 'engine-ollama')

    def test_comfy_install_requirements_skips_core_packages_and_clears_marker_on_failure(self):
        import job_process
        root = paths.ENGINES_DIR / 'comfyui' / 'ComfyUI_windows_portable'
        node_dir = root / 'ComfyUI' / 'custom_nodes' / 'ComfyUI-LivePortraitKJ'
        node_dir.mkdir(parents=True)
        (root / 'ComfyUI' / 'main.py').write_text('')
        (root / 'python_embeded').mkdir()
        py = root / 'python_embeded' / 'python.exe'
        py.write_bytes(b'')
        (node_dir / 'requirements.txt').write_text(
            'pyyaml\nnumpy<=1.26.4\ntorch>=2.0\nopencv-python\nonnxruntime-gpu\npykalman # comment\n',
            encoding='utf-8',
        )
        with patch.object(job_process, 'run', return_value=MagicMock(returncode=0)) as run_mock:
            engines.comfy.install_requirements('ComfyUI-LivePortraitKJ')
        cmd = run_mock.call_args.args[0]
        self.assertIn('pykalman', cmd)
        self.assertIn('onnxruntime-gpu==1.31.1', cmd)
        self.assertFalse(any(arg.startswith('numpy') or arg.startswith('torch') for arg in cmd))

        # Verify LatentSyncWrapper extra packages are all pinned (including soundfile and decord).
        ls_dir = root / 'ComfyUI' / 'custom_nodes' / 'ComfyUI-LatentSyncWrapper'
        ls_dir.mkdir(parents=True)
        (ls_dir / 'requirements.txt').write_text('diffusers==0.32.2\n', encoding='utf-8')
        with patch.object(job_process, 'run', return_value=MagicMock(returncode=0)) as ls_run:
            engines.comfy.install_requirements('ComfyUI-LatentSyncWrapper')
        ls_cmd = ls_run.call_args_list[0].args[0]
        for pinned in ('accelerate==1.15.0', 'pytorch-lightning==2.6.6', 'scikit-image==0.26.0',
                       'soundfile==0.14.0', 'decord==0.6.0'):
            self.assertIn(pinned, ls_cmd)
        self.assertIn('insightface==2.1', ls_run.call_args_list[1].args[0])

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as bundle:
            bundle.writestr('top/requirements.txt', b'pykalman\n')
        data = buffer.getvalue()
        item = _fake_item(
            'node-test', data, kind='comfy_node', backend='comfy', install_root='engines',
            path='downloads/node-test.zip', node_folder='ComfyUI-TestNode',
            extract={'format': 'zip', 'to': '@comfy/custom_nodes/ComfyUI-TestNode', 'strip_components': 1}
        )
        self.use_catalog([item])
        with patch.object(models.requests, 'get', return_value=response([data])), \
                patch.object(engines.comfy, 'install_requirements', side_effect=AIUnavailable('pip failed')):
            job_id = models.start_install('node-test', accept_license=True)
            self.assertTrue(wait_for(lambda: models.job(job_id)['state'] not in ('queued', 'running')))
        self.assertEqual(models.job(job_id)['state'], 'error')
        self.assertFalse(models.status()['node-test']['verified'])

    def test_comfy_prepare_home_env_and_idle_stop_respects_active_gpu_lease(self):
        env = engines.comfy._prepare_home_env()
        self.assertEqual(env['PYTHONIOENCODING'], 'utf-8')
        self.assertEqual(env['PYTHONUTF8'], '1')
        self.assertTrue((engines.comfy.home() / '.latentsync16_dependencies_installed').is_file())
        with patch.object(engines.comfy, 'stop') as stop_mock, patch.object(engines.comfy, 'touch') as touch_mock:
            with gpu.lease('comfy', 8):
                engines.comfy._idle_stop()
            stop_mock.assert_not_called()
            touch_mock.assert_called_once()
            engines.comfy._idle_stop()
            stop_mock.assert_called_once()

    def test_comfy_patch_custom_nodes_applies_is_idempotent_and_reports_warnings(self):
        root = paths.ENGINES_DIR / 'comfyui' / 'ComfyUI'
        custom = root / 'custom_nodes'
        (root / 'main.py').parent.mkdir(parents=True, exist_ok=True)
        (root / 'main.py').write_text('')
        py = paths.ENGINES_DIR / 'comfyui' / 'venv' / 'Scripts' / 'python.exe'
        py.parent.mkdir(parents=True, exist_ok=True)
        py.write_bytes(b'')
        # Build fixture files containing the `target` for every named patch in ComfyEngine._CUSTOM_NODE_PATCHES.
        by_file = {}
        for name, node_folder, rel_path, target, replacement in engines.ComfyEngine._CUSTOM_NODE_PATCHES:
            by_file.setdefault((node_folder, rel_path), []).append(target)
        for (node_folder, rel_path), snippets in by_file.items():
            file_path = custom / node_folder / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text('\n\n'.join(snippets) + '\n', encoding='utf-8')

        first_states = engines.comfy._patch_custom_nodes()
        self.assertEqual(len(first_states), len(engines.ComfyEngine._CUSTOM_NODE_PATCHES))
        for name, *_ in engines.ComfyEngine._CUSTOM_NODE_PATCHES:
            self.assertEqual(first_states[name], 'applied_now', name)
        self.assertEqual(engines.comfy.status()['patch_warnings'], [])

        second_states = engines.comfy._patch_custom_nodes()
        for name, *_ in engines.ComfyEngine._CUSTOM_NODE_PATCHES:
            self.assertEqual(second_states[name], 'already_applied', name)
        self.assertEqual(engines.comfy.status()['patch_warnings'], [])

        # When a file changes upstream and a target isn't found, record target_not_found and surface in status()['comfy']['patch_warnings'].
        (custom / 'ComfyUI-LatentSyncWrapper' / 'nodes.py').write_text(
            '# upstream changed this file\n', encoding='utf-8'
        )
        third_states = engines.comfy._patch_custom_nodes()
        self.assertEqual(third_states['latentsync_torchaudio_save'], 'target_not_found')
        warnings = engines.status()['comfy']['patch_warnings']
        self.assertTrue(any('latentsync_torchaudio_save' in w for w in warnings))

    def test_captions_whisper_name_helper_and_third_party_notices(self):
        import captions
        with patch.object(captions.asr, 'whisper_model_name', return_value='large-v3-turbo'):
            self.assertEqual(captions._whisper_name(), 'large-v3-turbo')
        with patch.object(captions.asr, 'whisper_model_name', side_effect=RuntimeError('missing')):
            self.assertIsNone(captions._whisper_name())
        root_dir = Path(__file__).resolve().parents[1]
        captions_src = (root_dir / 'captions.py').read_text(encoding='utf-8')
        self.assertEqual(captions_src.count('asr.whisper_model_name()'), 1)
        notices = (root_dir / 'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8')
        for pkg in ('curl-cffi', 'cffi', 'pycparser', 'soundfile', 'decord',
                    'mediapipe', 'pytorch-lightning', 'accelerate'):
            self.assertIn(pkg, notices, pkg)


if __name__ == '__main__':
    unittest.main()
