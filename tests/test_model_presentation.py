from app import model_presentation as presentation


class Combo:
    def __init__(self):
        self.items = []
        self.roles = {}
        self.current = -1

    def clear(self):
        self.items.clear()
        self.roles.clear()
        self.current = -1

    def addItem(self, label, data):
        self.items.append((label, data))

    def setItemData(self, index, value, role):
        self.roles[index, role] = value

    def setCurrentIndex(self, index):
        self.current = index

    def findData(self, data):
        return next((index for index, (_, value) in enumerate(self.items) if value == data), -1)

    def count(self):
        return len(self.items)

    def itemData(self, index):
        return self.items[index][1]

    def itemText(self, index):
        return self.items[index][0]

    def toolTip(self, index):
        from PyQt6.QtCore import Qt
        return self.roles[index, Qt.ItemDataRole.ToolTipRole]


def test_model_labels_and_combo_prioritize_ready_files_without_losing_codes(tmp_path, monkeypatch):
    monkeypatch.setattr(presentation, 'ROOT', tmp_path, raising=False)
    faster = tmp_path / 'models' / 'whisper-medium'
    faster.mkdir(parents=True)
    (faster / 'model.bin').write_bytes(b'fixture')
    native = tmp_path / 'models' / 'native-whisper'
    native.mkdir(parents=True)
    (native / 'small.pt').write_bytes(b'fixture')
    (native / 'medium.pt').write_bytes(b'fixture')

    assert 'Medium' in presentation.model_choice_label('medium', {'asr_model': 'medium'})
    assert presentation.model_choice_label('medium', {'asr_model': 'medium'}) == 'Medium · 已发现文件'
    assert presentation.model_choice_label('large-v3', {'asr_model': 'large-v3'}) == 'Large v3 · 未安装'
    native_label = presentation.model_choice_label('medium', {
        'asr_model': 'medium', 'wlk': {'backend': 'whisper'}
    })
    assert native_label == 'Medium · 已发现文件'

    combo = Combo()
    settings = {'asr_model': 'large-v3', 'wlk': {}}
    presentation.populate_model_combo(combo, settings)
    assert combo.count() == 12
    codes = [combo.itemData(i) for i in range(combo.count())]
    assert set(codes) == {
        'tiny', 'tiny.en', 'base', 'base.en', 'small', 'small.en',
        'medium', 'medium.en', 'large-v1', 'large-v2', 'large-v3', 'large-v3-turbo'
    }
    assert codes[:2] == ['small', 'medium']
    assert combo.itemData(combo.current) == 'large-v3'
    assert combo.itemText(combo.current) == 'Large v3 · 未安装'
    assert '是否已加载未知' in combo.toolTip(combo.current)


def test_explicit_model_path_and_directory_are_detected_without_recursive_walk(tmp_path, monkeypatch):
    monkeypatch.setattr(presentation, 'ROOT', tmp_path, raising=False)
    checkpoint = tmp_path / 'custom.pt'
    checkpoint.write_bytes(b'fixture')
    faster_dir = tmp_path / 'custom-faster'
    faster_dir.mkdir()
    (faster_dir / 'model.bin').write_bytes(b'fixture')

    assert presentation.model_choice_label('small', {
        'asr_model': 'small', 'wlk': {'model_path': str(checkpoint)}
    }) == 'Small · 已发现文件'
    path_settings = {'asr_model': 'medium', 'wlk': {'model_path': str(checkpoint)}}
    assert presentation.model_choice_label('small', path_settings) == 'Small · 未安装'
    assert presentation.model_choice_label('medium', path_settings) == 'Medium · 已发现文件'
    dir_settings = {'asr_model': 'medium', 'wlk': {'model_dir': str(faster_dir)}}
    assert presentation.model_choice_label('small', dir_settings) == 'Small · 未安装'
    assert presentation.model_choice_label('medium', dir_settings) == 'Medium · 已发现文件'


def test_runtime_summary_describes_requested_asr_and_nllb_without_credentials(tmp_path, monkeypatch):
    monkeypatch.setattr(presentation, 'ROOT', tmp_path, raising=False)
    summary = presentation.runtime_summary({
        'asr_model': 'medium', 'server_url': 'http://secret-user:secret-pass@127.0.0.1:9876/v1?token=hidden',
        'translation_mode': 'local', 'translation_provider': 'nllb',
        'wlk': {'backend': 'faster-whisper', 'model_size': 'medium'},
    })
    assert '请求' in summary
    assert '本机外部服务' in summary
    assert '127.0.0.1:9876' in summary
    assert 'secret-user' not in summary and 'secret-pass' not in summary and 'hidden' not in summary
    assert 'NLLB' in summary
    assert len(summary.splitlines()) <= 2
    details = presentation.runtime_details({
        'asr_model': 'medium', 'server_url': 'http://secret-user:secret-pass@127.0.0.1:9876/v1?token=hidden',
        'translation_mode': 'local', 'translation_provider': 'nllb',
        'wlk': {'backend': 'faster-whisper', 'model_size': 'medium'},
    })
    assert '是否已加载未知' in details


def test_runtime_summary_distinguishes_managed_local_engine_remote_and_lm_studio(tmp_path, monkeypatch):
    monkeypatch.setattr(presentation, 'ROOT', tmp_path, raising=False)
    local = presentation.runtime_summary({
        'asr_model': 'small', 'server_url': '', 'translation_mode': 'off',
        'wlk': {'backend': 'faster-whisper', 'model_size': 'small'},
    })
    remote = presentation.runtime_summary({
        'asr_model': 'large-v3', 'server_url': 'https://user:pass@asr.example.test:9443/path?key=secret',
        'translation_mode': 'local', 'translation_provider': 'lmstudio',
        'llm_url': 'http://user:pass@10.0.0.8:1234/v1?token=secret', 'llm_model': 'qwen',
        'wlk': {'backend': 'faster-whisper', 'model_size': 'large-v3'},
    })
    assert '本软件本地' in local and '翻译：关闭' in local
    assert '远程' in remote and 'asr.example.test:9443' in remote
    assert 'LM Studio' in remote and '10.0.0.8:1234' in remote
    assert len(local.splitlines()) <= 2 and len(remote.splitlines()) <= 2
    assert all(secret not in remote for secret in ('user', 'pass', 'secret'))




