"""Pass the upstream dataclass through the desktop without a reduced schema."""
from dataclasses import fields, MISSING
from typing import get_args, get_origin, get_type_hints

from app.settings import ROOT

LABELS = {
    'backend':'识别引擎', 'backend_policy':'流式识别策略', 'model_size':'Whisper 模型',
    'model_dir':'本地模型目录', 'model_path':'模型文件', 'model_cache_dir':'模型缓存目录',
    'lan':'识别语言', 'target_language':'翻译目标', 'diarization':'区分说话人',
    'diarization_backend':'说话人引擎', 'sortformer_model_path':'Sortformer 模型文件',
    'sortformer_max_speakers':'最多说话人数', 'segmentation_model':'Diart 分段模型',
    'embedding_model':'Diart 声纹嵌入模型', 'translation_backend':'翻译引擎',
    'nllb_backend':'NLLB 运行后端', 'nllb_size':'NLLB 模型大小',
    'direct_english_translation':'Whisper 直接译成英文', 'translate_on_complete':'整段完成后翻译',
    'init_prompt':'识别提示词', 'static_init_prompt':'固定提示词', 'lora_path':'LoRA 适配器',
    'host':'服务监听地址', 'port':'服务端口', 'api_token':'服务访问令牌',
    'cors_origins':'允许的网页来源', 'ssl_certfile':'HTTPS 证书', 'ssl_keyfile':'HTTPS 私钥',
    'vac':'语音活动控制', 'vad':'语音活动检测', 'min_chunk_size':'最小音频块（秒）',
    'asr_coalesce_min_s':'累积新音频阈值（秒）', 'pause_segmentation_seconds':'停顿断句（秒）',
    'buffer_trimming':'识别缓冲裁剪', 'buffer_trimming_sec':'裁剪阈值（秒）',
    'confidence_validation':'置信度校验', 'frame_threshold':'AlignAtt 帧阈值',
    'beams':'解码束数', 'retention_seconds':'服务结果保留时长（秒）',
    'rest_timeout':'文件转写超时（秒）', 'log_level':'日志级别',
    'pcm_input':'原始 PCM 音频', 'transcription':'启用转写',
    'alignatt_url':'AlignAtt 翻译服务', 'alignatt_context':'翻译术语上下文',
    'punctuation_split': '旧版标点切分开关（已弃用）',
    'mlx_llm_mt_model': 'MLX 翻译模型（mlx_llm_mt_model）',
    'mlx_llm_mt_simultaneous': 'MLX 同步翻译（mlx_llm_mt_simultaneous）',
    'mlx_llm_mt_calibration': 'MLX 同步翻译校准文件（mlx_llm_mt_calibration）',
    'mlx_llm_mt_simul_commit': 'MLX 同步译文确认规则（mlx_llm_mt_simul_commit）',
    'mlx_llm_mt_simul_mass_threshold': 'MLX mass 确认阈值（mlx_llm_mt_simul_mass_threshold）',
    'mlx_llm_mt_simul_soft_max_s': 'MLX 同步软等待上限（秒）',
    'mlx_llm_mt_simul_hard_max_s': 'MLX 同步硬等待上限（秒）',
    'alignatt_preset': 'AlignAtt 配置预设（alignatt_preset）',
    'alignatt_latency': 'AlignAtt 延迟档位（alignatt_latency）',
    'vac_chunk_size': 'VAC 音频块大小（秒）',
    'forwarded_allow_ips': '可信反向代理地址（forwarded_allow_ips）',
    'disable_punctuation_split': '旧版停用标点切分（已弃用）',
    'warmup_file': '识别预热音频文件（warmup_file）',
    'max_buffered_audio': '待处理音频缓冲上限（秒）',
    'backpressure_timeout': '队列背压等待上限（秒）',
    'encoder_model_path': '编码器模型文件（encoder_model_path）',
    'decoder_model_path': '解码器模型文件（decoder_model_path）',
    'disable_fast_encoder': '禁用快速编码器（disable_fast_encoder）',
    'custom_alignment_heads': '自定义对齐头（custom_alignment_heads）',
    'decoder_type': 'SimulStreaming 解码器类型（decoder_type）',
    'audio_max_len': 'SimulStreaming 音频窗口上限（秒）',
    'audio_min_len': 'SimulStreaming 音频窗口下限（秒）',
    'cif_ckpt_path': 'SimulStreaming CIF 检查点（cif_ckpt_path）',
    'never_fire': '禁用 CIF 句尾触发（never_fire）',
    'max_context_tokens': '识别上下文词元上限（max_context_tokens）',
    'vllm_model': 'Qwen3 vLLM 识别模型（vllm_model）',
    'vllm_aligner_model': 'Qwen3 vLLM 对齐模型（vllm_aligner_model）',
    'vllm_tensor_parallel_size': 'vLLM 张量并行设备数（vllm_tensor_parallel_size）',
    'vllm_gpu_memory_utilization': 'vLLM GPU 显存使用比例（vllm_gpu_memory_utilization）',
    'vllm_dtype': 'vLLM 计算数据类型（vllm_dtype）',
    'vllm_max_model_len': 'vLLM 最大模型上下文长度（vllm_max_model_len）',
    'qwen3_vllm_audio_backend': 'Qwen3 vLLM 音频处理后端（qwen3_vllm_audio_backend）',
    'qwen3_vllm_causal_decoder_backend': 'Qwen3 vLLM 因果解码后端（qwen3_vllm_causal_decoder_backend）',
    'qwen3_vllm_causal_attn_implementation': 'Qwen3 vLLM 因果注意力实现（qwen3_vllm_causal_attn_implementation）',
    'qwen3_vllm_text_decoder_model': 'Qwen3 vLLM 文本解码模型（qwen3_vllm_text_decoder_model）',
    'qwen3_vllm_live_idle_timeout_ms': 'Qwen3 vLLM 实时空闲等待（毫秒）',
    'qwen3_vllm_tower_checkpoint': 'Qwen3 vLLM 音频塔检查点（qwen3_vllm_tower_checkpoint）',
    'qwen3_vllm_left_context_sec': 'Qwen3 vLLM 左侧音频上下文（秒）',
    'qwen3_vllm_block_frames': 'Qwen3 vLLM 音频帧块大小',
    'qwen3_vllm_cache_block_size': 'Qwen3 vLLM KV 缓存块大小',
    'qwen3_vllm_segment_max_steps': 'Qwen3 vLLM 单段最大解码步数',
    'qwen3_vllm_segment_min_sec': 'Qwen3 vLLM 最短识别片段（秒）',
    'qwen3_vllm_prompt_context_words': 'Qwen3 vLLM 提示上下文词数',
    'qwen3_vllm_live_multiprocessing': 'Qwen3 vLLM 实时路径多进程设置',
    'qwen3_vllm_aligner_multiprocessing': 'Qwen3 vLLM 对齐器多进程设置',
    'holdback_words': '流式结果末尾暂缓词数（holdback_words）',
    'trim_sentence_buffer': '按句子整理识别缓冲（trim_sentence_buffer）',
    'qwen3_vllm_metal_audio_backend': 'Qwen3 Metal 音频处理后端',
    'qwen3_vllm_metal_tower_checkpoint': 'Qwen3 Metal 音频塔检查点',
    'qwen3_vllm_metal_left_context_sec': 'Qwen3 Metal 左侧音频上下文（秒）',
    'qwen3_vllm_metal_block_frames': 'Qwen3 Metal 音频帧块大小',
    'qwen3_streaming_chunk_sec': 'Qwen3 Streaming 音频块（秒）',
    'qwen3_streaming_left_context_sec': 'Qwen3 Streaming 左侧音频上下文（秒）',
    'qwen3_streaming_right_context_ms': 'Qwen3 Streaming 右侧音频上下文（毫秒）',
    'qwen3_streaming_segment_max_steps': 'Qwen3 Streaming 单段最大生成步数',
    'qwen3_streaming_segment_keep_tail_steps': 'Qwen3 Streaming 分段保留尾部步数',
    'qwen3_streaming_hold_back_words': 'Qwen3 Streaming 末尾暂缓词数',
    'qwen3_streaming_stable_iterations': 'Qwen3 Streaming 稳定确认轮数',
    'qwen3_streaming_max_new_tokens': 'Qwen3 Streaming 最大新词元数',
    'qwen3_streaming_device': 'Qwen3 Streaming 运行设备',
    'qwen3_streaming_dtype': 'Qwen3 Streaming 计算数据类型',
    'qwen3_streaming_attn_implementation': 'Qwen3 Streaming 注意力实现',
    'qwen3_streaming_context': 'Qwen3 Streaming 识别上下文',
    'qwen3_streaming_prompt_context_words': 'Qwen3 Streaming 提示上下文词数',
    'qwen3_streaming_audio_backend': 'Qwen3 Streaming 音频处理后端',
    'qwen3_streaming_tower_checkpoint': 'Qwen3 Streaming 音频塔检查点',
    'qwen3_streaming_block_frames': 'Qwen3 Streaming 音频帧块大小',
    'canary_model': 'Canary 识别模型（canary_model）',
    'canary_default_lang': 'Canary 默认语言（canary_default_lang）',
    'canary_lid_model': 'Canary 语言识别模型（canary_lid_model）',
    'canary_lid_min_sec': 'Canary 语言检测最短音频（秒）',
    'canary_lid_min_conf': 'Canary 语言检测最低置信度',
}
CHOICES = {
    'backend': ['auto','faster-whisper','whisper','funasr','canary','qwen3-streaming',
                'qwen3-vllm','qwen3-vllm-metal','voxtral','voxtral-mlx','mlx-whisper'],
    'backend_policy':['localagreement','simulstreaming'],
    'model_size':['tiny','base','small','medium','large-v1','large-v2','large-v3','large-v3-turbo',
                  'tiny.en','base.en','small.en','medium.en'],
    'diarization_backend':['sortformer','diart'],
    'translation_backend':['nllb','alignatt','mlx-llm-mt'],
    'nllb_backend':['ctranslate2','transformers'], 'nllb_size':['600M','1.3B'],
    'buffer_trimming':['segment','sentence'], 'log_level':['DEBUG','INFO','WARNING','ERROR'],
    'alignatt_latency':['quality','balanced','low'],
}


def _group(name):
    if name.startswith(('sortformer','segmentation','embedding','diarization')):
        return '说话人'
    if name.startswith(('nllb','translation','alignatt','mlx_llm_mt','translate_')) or name == 'target_language':
        return '翻译'
    if name in {'host','port','api_token','cors_origins','ssl_certfile','ssl_keyfile',
                'forwarded_allow_ips','retention_seconds','rest_timeout','log_level'}:
        return '服务'
    if name.startswith(('qwen3','vllm','canary')):
        return '其他识别引擎'
    return '识别'


def field_schema():
    from whisperlivekit.config import WhisperLiveKitConfig
    hints = get_type_hints(WhisperLiveKitConfig)
    result = []
    for f in fields(WhisperLiveKitConfig):
        hint = hints.get(f.name, str)
        args = get_args(hint)
        nullable = type(None) in args
        if nullable:
            hint = next(a for a in args if a is not type(None))
        kind = {bool:'bool', int:'int', float:'float', str:'str'}.get(hint, 'str')
        result.append({'name':f.name,'label':LABELS.get(f.name,f.name),'type':kind,
                       'nullable':nullable,'default':f.default if f.default is not MISSING else None,
                       'group':_group(f.name),'choices':[(v,v) for v in CHOICES.get(f.name,[])],
                       'help':f'WhisperLiveKit 原参数：{f.name}'})
    return result


def config_values(settings):
    from whisperlivekit.config import WhisperLiveKitConfig
    values = {f.name:f.default for f in fields(WhisperLiveKitConfig)}
    # Defaults describe the existing installed models. Every upstream setting
    # remains editable and is subsequently validated by its native dataclass.
    values.update(backend='faster-whisper', backend_policy='localagreement',
                  nllb_backend='ctranslate2', min_chunk_size=.5,
                  asr_coalesce_min_s=.6, pause_segmentation_seconds=.8,
                  log_level='INFO', model_cache_dir=str(ROOT/'models/cache'))
    values.update(settings.get('wlk') or {})
    values['model_size'] = settings.get('asr_model', values['model_size'])
    values['lan'] = settings.get('source_language', values['lan'])
    if settings.get('translation_mode', 'local') == 'off' or values['direct_english_translation'] or settings.get('translation_provider')=='lmstudio':
        values['target_language'] = ''
    else:
        values['target_language'] = settings.get('target_language', values['target_language'])
    if settings.get('long_meeting_mode',False) and values.get('retention_seconds') is None:
        values['retention_seconds']=120.
    if not any(values.get(k) for k in ('model_dir','model_path')) and values['backend'] in ('auto','faster-whisper'):
        local = ROOT/'models'/f"whisper-{values['model_size']}"
        if (local/'model.bin').is_file():
            values['model_dir'] = str(local)
    if not values.get('model_path') and values['backend']=='whisper':
        checkpoint=ROOT/'models/native-whisper'/f"{values['model_size']}.pt"
        if checkpoint.is_file(): values['model_path']=str(checkpoint)
    local_speaker = ROOT/'models/sortformer/diar_streaming_sortformer_4spk-v2.nemo'
    if not values.get('sortformer_model_path') and local_speaker.is_file():
        values['sortformer_model_path'] = str(local_speaker)
    return values


def make_config(settings, *, pcm=True):
    from whisperlivekit.config import WhisperLiveKitConfig
    values = config_values(settings)
    unknown = set(values) - {f.name for f in fields(WhisperLiveKitConfig)}
    if unknown:
        raise ValueError('WhisperLiveKit 不存在这些参数：'+', '.join(sorted(unknown)))
    if values['target_language'] and values['lan']=='auto' and values['backend_policy']!='simulstreaming':
        raise ValueError('原库 LocalAgreement 翻译不支持自动识别语言；请选择讲话语言，或使用 SimulStreaming。')
    if values.get('direct_english_translation') and values['backend'] in {'funasr','canary','qwen3-streaming','voxtral'}:
        raise ValueError('Whisper 直接译成英文仅适用于支持此功能的 Whisper 引擎。')
    if values.get('direct_english_translation') and settings.get('translation_provider')=='lmstudio':
        raise ValueError('使用 LM Studio 翻译时请关闭 Whisper 直接译成英语，以保留原语言听写。')
    if bool(values.get('ssl_certfile')) != bool(values.get('ssl_keyfile')):
        raise ValueError('HTTPS 证书与私钥必须同时设置。')
    if pcm:
        values['pcm_input'] = True
    return WhisperLiveKitConfig(**values)
