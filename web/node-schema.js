// UI draft schema. Node IDs follow docs/design/workflow.md; these values are
// not a replacement for backend contracts. Only the local previews use them today.
const field = (key, label, type, value, extra = {}) => ({ key, label, type, value, ...extra });
const select = (key, label, value, options, extra) => field(key, label, 'select', value, { options, ...extra });
const number = (key, label, value, min, max, step = 1, extra) => field(key, label, 'number', value, { min, max, step, ...extra });
const toggle = (key, label, value, extra) => field(key, label, 'boolean', value, extra);
const text = (key, label, value, extra) => field(key, label, 'text', value, extra);
const area = (key, label, value, extra) => field(key, label, 'textarea', value, extra);
const group = (title, fields) => ({ title, fields });
const node = (id, title, role, category, symbol, x, y, description, input, output, groups, quick) =>
  ({ id, title, role, category, symbol, x, y, description, input, output, groups, quick });

export const categories = {
  source: { title: '素材与识别', color: '#79b5ce' },
  language: { title: '语言智能体', color: '#c3ade3' },
  audio: { title: '配音与时间轴', color: '#d6ae78' },
  media: { title: '视觉与交付', color: '#89bba0' },
};
export const schema = [
  node('probe_input', '视频输入', 'B', 'source', '01', 40, 80,
    '探测原片的时长、分辨率、帧率和音轨，为下游保留统一的全片时间轴。',
    ['输入视频'], ['媒体信息'], [
      group('输入源', [select('source_type', '输入方式', '本地 MP4', ['本地 MP4', '已登记链接']), text('source', '素材路径 / 已登记 URL', '', { placeholder: 'media/source.mp4', help: '这里只保存引用，不会上传文件。链接入口仍待接入。' }), text('label', '任务名称', '英文视频译制')]),
      group('媒体探测', [number('audio_stream', '音轨索引', 0, 0, 15), number('timeout', '探测超时', 30, 5, 300, 1, { unit: '秒' }), toggle('check_decode', '检查音视频可解码', true), toggle('keep_timeline', '保留全片时间戳', true)]),
    ], ['source_type', 'source', 'audio_stream']),
  node('asr_diarize', '转写与说话人', 'B', 'source', '02', 40, 480,
    '本地转写英文，以词级时间戳、语音停顿和说话人标签生成分段。说话人区分不等同于人声分离。',
    ['输入视频'], ['提取音频', '分段结果'], [
      group('语音识别', [select('model', 'Whisper 模型', 'large-v3', ['tiny.en', 'base.en', 'small.en', 'medium.en', 'large-v3', 'turbo']), select('device', '推理设备', 'auto', ['auto', 'cpu', 'cuda']), select('compute_type', '计算精度', 'int8', ['int8', 'float16', 'float32', 'int8_float16']), number('beam_size', '束搜索宽度', 5, 1, 10), select('language', '源语言', 'en', ['en']), toggle('word_timestamps', '词级时间戳', true), area('initial_prompt', '识别提示 / 专有名词', '', { placeholder: '填入讲者姓名或领域术语，辅助识别。' })]),
      group('语音活动检测', [toggle('vad', '启用 VAD', true), number('vad_threshold', '语音概率阈值', 0.5, 0, 1, 0.05), number('silence_ms', '最小静音间隔', 500, 100, 3000, 50, { unit: 'ms' })]),
      group('说话人区分', [toggle('diarization', '启用说话人区分', true), select('diarizer', '区分模型', 'pyannote Community-1', ['pyannote Community-1']), number('min_speakers', '最少说话人数', 1, 1, 2), number('max_speakers', '最多说话人数', 2, 1, 2), select('overlap', '重叠发言策略', '标记并人工复核', ['标记并人工复核', '取最大时间重叠说话人'])]),
    ], ['model', 'device', 'diarization']),
  node('build_blocks', '断句与术语', 'C', 'language', '03', 40, 880,
    '在自然句边界聚合翻译块。切分只改变文本组织，始终保留原片段 ID 和时间范围。',
    ['分段结果'], ['翻译块', '术语表'], [
      group('分块策略', [number('target_seconds', '目标块时长', 75, 30, 120, 5, { unit: '秒' }), number('max_seconds', '最长块时长', 90, 30, 180, 5, { unit: '秒' }), number('pause_ms', '断句停顿阈值', 600, 100, 3000, 50, { unit: 'ms' }), number('context_sentences', '相邻上下文句数', 2, 0, 8), toggle('split_speaker', '说话人切换时断句', true), toggle('keep_segment_ids', '保留源片段 ID', true)]),
      group('术语管理', [toggle('extract_terms', '提取领域术语', true), select('domain', '内容领域', '通用', ['通用', '计算机与人工智能', '科学与工程', '商业与经济', '人文与教育']), area('glossary', '固定术语表', 'agent = 智能体\nworkflow = 工作流', { help: '每行一个「英文 = 中文」，可与组员共享此草稿。' })]),
    ], ['target_seconds', 'context_sentences', 'domain']),
  node('translate_blocks', '翻译智能体', 'C', 'language', '04', 430, 80,
    '结合原文、上下文和术语表，同时生成忠实的中文字幕与自然的中文口播稿。',
    ['翻译块', '术语表'], ['翻译结果'], [
      group('模型与生成', [select('provider', '模型服务', 'DeepSeek', ['DeepSeek']), text('model', '模型名称', 'deepseek-flash', { help: '实际接入时以账号可用模型为准。密钥仅在服务端 .env 配置。' }), number('temperature', 'Temperature', 0.3, 0, 2, 0.05), number('max_tokens', '最大输出 Token', 4096, 256, 16384, 256), number('timeout', '调用超时', 120, 10, 600, 10, { unit: '秒' }), number('concurrency', '并发块数', 2, 1, 8)]),
      group('翻译策略', [select('style', '口播风格', '自然讲解', ['自然讲解', '严谨学术', '轻松对话']), select('target_language', '目标语言', '简体中文', ['简体中文']), toggle('preserve_terms', '遵循术语表', true), toggle('dual_text', '分别生成字幕与口播稿', true), area('instructions', '补充指令', '忠实保留否定、数字、条件和因果关系。不要添加原文没有的信息。', { maxLength: 4000 })]),
    ], ['model', 'temperature', 'style']),
  node('review_blocks', '审校智能体', 'C', 'language', '05', 430, 480,
    '逐段检查错漏译与术语一致性。现有示例演示漏译否定词后的定向返工。',
    ['翻译结果', '分段结果'], ['审校结果'], [
      group('审校模型', [text('model', '模型名称', 'deepseek-flash'), number('temperature', 'Temperature', 0.1, 0, 2, 0.05)]),
      group('检查项', [toggle('omissions', '漏译与事实一致性', true), toggle('negation', '否定、条件与因果', true), toggle('numbers', '数字、单位与专有名词', true), toggle('terminology', '术语一致性', true), toggle('fluency', '中文可读性', true)]),
      group('返工策略（待接入）', [number('max_rework', '每段最多内容返工', 2, 0, 2), select('failure_policy', '达到上限后', '标记人工复核', ['标记人工复核', '停止任务']), area('instructions', '审校标准', '仅标记可定位的问题，返回片段 ID、问题类型和修改建议。')]),
    ], ['model', 'max_rework', 'negation']),
  node('tts_align', '配音与对齐', 'D', 'audio', '06', 820, 80,
    '按全片说话人映射合成普通话音频。测量实际时长，按原时间窗对齐并组装中文音轨。',
    ['审校结果'], ['分段音频清单', '中文配音音轨'], [
      group('语音合成', [select('provider', 'TTS 服务', 'CosyVoice', ['CosyVoice']), text('model', '模型名称', '', { placeholder: '接入时填写可用模型 ID' }), select('sample_rate', '采样率', '24000', ['16000', '24000', '48000'], { unit: 'Hz' }), number('speed', '基础语速', 1, 0.8, 1.15, 0.01)]),
      group('全片音色映射', [text('speaker_0', 'SPEAKER_00 音色 ID', '', { placeholder: '填写第一种普通话音色' }), text('speaker_1', 'SPEAKER_01 音色 ID', '', { placeholder: '填写第二种普通话音色' }), toggle('lock_voices', '全片固定说话人与音色', true)]),
      group('时长与缓存', [number('max_speedup', '最大对齐加速', 1.15, 1, 1.15, 0.01), number('padding_ms', '片段尾部留白', 80, 0, 500, 10, { unit: 'ms' }), select('overflow', '超时处理', '压缩口播并复审', ['压缩口播并复审', '标记人工复核']), toggle('reuse_audio', '复用匹配文本 / 模型 / 音色的缓存', true), number('loudness', '目标响度', -16, -24, -12, 1, { unit: 'LUFS' })]),
    ], ['provider', 'speed', 'max_speedup']),
  node('edit_assets', '中文编辑智能体', 'E', 'language', '07', 430, 880,
    '根据审校后的内容生成中文标题、简介、标签与封面文案，保持信息可追溯。',
    ['审校结果', '媒体信息'], ['发布文案'], [
      group('内容设置', [text('model', '模型名称', 'deepseek-flash'), select('platform', '目标平台', '通用', ['通用', '哔哩哔哩', '视频号', '小红书']), select('tone', '文案语气', '清晰克制', ['清晰克制', '知识科普', '轻松友好']), number('title_length', '标题字数上限', 28, 10, 60), number('description_length', '简介字数上限', 200, 50, 1000, 10), number('tag_count', '标签数量', 5, 0, 10)]),
      group('编辑约束', [toggle('attribution', '保留来源说明', true), toggle('chapters', '生成章节摘要', true), area('instructions', '补充编辑要求', '不夸大结论，不编造观点。封面文案突出一个核心主题。')]),
    ], ['platform', 'tone', 'title_length']),
  node('subtitle_cover', '字幕与封面', 'E', 'media', '08', 820, 880,
    '生成双语 SRT、用于烧录的 ASS 以及中文封面。右侧提供基于当前草稿的样式预览。',
    ['审校结果', '发布文案'], ['双语 SRT', '烧录字幕', '封面图'], [
      group('字幕排版', [select('order', '字幕语言顺序', '中文在上', ['中文在上', '英文在上']), select('font', '字体', '系统黑体', ['系统黑体', '系统宋体']), number('font_size', '中文字号（1080p）', 48, 20, 80, 2, { unit: 'px', preview: true }), number('en_size', '英文字号（1080p）', 30, 16, 60, 2, { unit: 'px', preview: true }), field('text_color', '字幕颜色', 'color', '#ffffff', { preview: true }), field('outline_color', '描边颜色', 'color', '#111111', { preview: true }), number('outline', '描边宽度', 2, 0, 6, 0.5, { unit: 'px', preview: true }), number('margin', '底部安全边距', 60, 20, 160, 5, { unit: 'px', preview: true }), number('max_chars', '中文每行字数', 22, 10, 36), toggle('bilingual', '显示中英双语', true)]),
      group('封面模板', [select('cover_layout', '版式', '左侧标题', ['左侧标题', '居中标题']), field('cover_color', '封面底色', 'color', '#233a4c', { preview: true }), text('cover_title', '预览标题', '让知识跨越语言', { maxLength: 60, preview: true }), select('cover_format', '输出格式', 'JPG', ['JPG', 'PNG']), select('cover_size', '封面尺寸', '1920 × 1080', ['1920 × 1080', '1280 × 720'])]),
    ], ['order', 'font_size', 'cover_color']),
  node('compose_video', '合成视频', 'E', 'media', '09', 1210, 80,
    '保留原画面，用中文配音替换原混音，并按配置烧录字幕，生成可播放的成片。',
    ['输入视频', '中文配音音轨', '烧录字幕'], ['成片'], [
      group('视频编码', [select('codec', '视频编码器', 'libx264', ['libx264']), select('resolution', '输出分辨率', '保持原片', ['保持原片', '1920 × 1080', '1280 × 720']), number('crf', 'CRF 质量', 20, 16, 30, 1, { help: '数值越低，质量越高，文件通常也越大。' }), select('preset', '编码速度', 'medium', ['ultrafast', 'fast', 'medium', 'slow']), select('fps', '帧率', '保持原片', ['保持原片', '24', '25', '30', '60']), toggle('burn_subtitles', '烧录双语字幕', true)]),
      group('音频与兼容性', [select('audio_codec', '音频编码', 'AAC', ['AAC']), select('audio_bitrate', '音频码率', '192k', ['128k', '192k', '256k', '320k']), select('audio_mode', '音轨策略', '替换原混音', ['替换原混音']), toggle('faststart', '启用 MP4 快速起播', true), toggle('verify_output', '验证成片可解码', true)]),
    ], ['codec', 'crf', 'preset']),
  node('collect_manifest', '汇总与检查', 'F', 'media', '10', 1210, 480,
    '收集磁盘产物和运行状态，生成发布包清单。不会在这里重新执行上游业务节点。',
    ['各节点产物'], ['发布包清单'], [
      group('产物校验', [toggle('check_files', '检查文件存在与非空', true), toggle('check_timeline', '检查字幕时间范围', true), toggle('check_duration', '核对音视频时长', true), number('duration_tolerance', '时长容差', 500, 0, 2000, 50, { unit: 'ms' }), select('checksum', '文件校验和', 'SHA-256', ['SHA-256', '不计算'])]),
      group('运行报告', [toggle('timing', '记录各节点耗时', true), toggle('usage', '记录模型调用量', true), toggle('issues', '附带失败与复核清单', true), select('report_format', '报告格式', 'JSON + Markdown', ['JSON + Markdown', 'JSON'])]),
    ], ['checksum', 'duration_tolerance', 'issues']),
  node('package_zip', '发布包导出', 'E', 'media', '11', 1210, 880,
    '按已校验的发布包清单打包成片、字幕、封面、文案和报告。正式产物尚待全流程接入。',
    ['发布包清单', '已落盘产物'], ['最终 ZIP'], [
      group('导出设置', [text('filename', '文件名模板', '{job_id}_zh.zip'), number('compression', 'ZIP 压缩等级', 6, 0, 9), select('on_exists', '文件已存在时', '追加版本号', ['追加版本号', '停止并提示'])]),
      group('包内内容', [toggle('video', '中文配音成片', true), toggle('srt', '中英双语 SRT', true), toggle('ass', 'ASS 字幕', true), toggle('cover', '中文封面', true), toggle('copy', '发布文案', true), toggle('report', '运行报告', true), toggle('review_gate', '有未复核问题时阻止正式打包', true)]),
    ], ['filename', 'compression', 'review_gate']),
];
export const edges = [
  ['probe_input', 'asr_diarize'], ['asr_diarize', 'build_blocks'],
  ['build_blocks', 'translate_blocks'], ['translate_blocks', 'review_blocks'],
  ['review_blocks', 'tts_align'], ['review_blocks', 'edit_assets'],
  ['review_blocks', 'subtitle_cover'], ['edit_assets', 'subtitle_cover'],
  ['tts_align', 'compose_video'], ['subtitle_cover', 'compose_video'],
  ['compose_video', 'collect_manifest'], ['collect_manifest', 'package_zip'],
  ['review_blocks', 'translate_blocks', 'demo'],
];
export const fieldsOf = (node) => node.groups.flatMap(group => group.fields);
export const defaults = () => Object.fromEntries(schema.map(node => [node.id, {
  x: node.x, y: node.y, collapsed: false,
  params: Object.fromEntries(fieldsOf(node).map(field => [field.key, field.value])),
}]));
