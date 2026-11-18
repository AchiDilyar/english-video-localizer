import { getReviewView, openSubtitleReview, refreshSubtitleReview, restoreReviewView, setPreviewInput, setPreviewJob } from './subtitle-review.js';
import { refreshTasks } from './task-queue.js';
import { schema, categories, edges, defaults } from './node-schema.js';

const $ = id => document.getElementById(id);

const NS = 'http://www.w3.org/2000/svg';
const STORAGE = 'video-localizer.canvas.v1';
const LEGACY_LAYOUT_KEYS = ['video-localizer.project.v4', 'video-localizer.project.v3', 'video-localizer.workflow.v2'];
const ID = /^[a-f0-9]{32}$/;
const DEFAULT_CAMERA = { x: 23, y: 11, scale: 0.86 };
const index = new Map(schema.map(node => [node.id, node]));
const modeLabels = { mock: '模拟', real: '真实' };
const narrowScreen = matchMedia('(max-width:640px)');
const MAX_ANCHORS = 16;
const edgeKey = (from, to) => `${from}:${to}`;
const edgeKeys = new Set(edges.map(([from, to]) => edgeKey(from, to)));
const SIZE_LIMITS = { width: [220, 680], height: [155, 1440] };
const elements = new Map();
let backendModes = {};
let runResult = null;
let inputVideo = null;
let inputMode = 'file';
let youtubeUrl = '';
let authorizeVoiceClone = false;
let selectedSourceId = '';
let knownSources = [];
let config = defaults();
let anchors = {};
let selected = 'probe_input';
let camera = { ...DEFAULT_CAMERA };
let drag = null;
let busy = false;
let history = [];
let future = [];
let toastTimer;
let minimapBounds;
let minimapDrag = null;
let consoleLog = null;
let logPollTimer = null;
const LOG_DISPLAY_LIMIT = 256 * 1024;
let viewSaveTimer;
let serializedLayout;

function validateAnchors(value) {
  if (typeof value !== 'object' || Array.isArray(value)) throw new Error('连线锚点格式无效。');
  return Object.fromEntries(Object.entries(value).map(([key, points]) => {
    if (!edgeKeys.has(key) || !Array.isArray(points) || points.length > MAX_ANCHORS ||
        points.some(point => ![point?.x, point?.y].every(n => Number.isFinite(n) && Math.abs(n) <= 10000))) {
      throw new Error('连线锚点无效。');
    }
    return [key, points.map(({ x, y }) => ({ x, y }))];
  }));
}

// Restore browser-local geometry, including the last layout from older builds.
function validateLayout(data) {
  if (!data?.nodes || typeof data.nodes !== 'object' || Array.isArray(data.nodes)) {
    throw new Error('画布布局无效。');
  }
  const clean = defaults();
  for (const node of schema) {
    const record = data.nodes[node.id] ?? (node.id === 'subtitle_cover' ? data.nodes.subtitle_render : null);
    if (!record) continue; // A node added by a newer backend uses its default position.
    if (typeof record.collapsed !== 'boolean' || !Number.isFinite(record.x) || !Number.isFinite(record.y)
        || Math.abs(record.x) > 10000 || Math.abs(record.y) > 10000) {
      throw new Error(`${node.title}：节点位置或结构无效。`);
    }
    Object.assign(clean[node.id], { x: record.x, y: record.y, collapsed: record.collapsed });
    for (const [dimension, limits] of Object.entries(SIZE_LIMITS)) {
      const value = record[dimension];
      if (value === undefined || (dimension === 'height' && value === null)) continue;
      if (!Number.isFinite(value) || value < limits[0] || value > limits[1]) {
        throw new Error(`${node.title}：节点尺寸超出允许范围。`);
      }
      clean[node.id][dimension] = value;
    }
  }
  const savedAnchors = data.anchors ?? {};
  if (typeof savedAnchors !== 'object' || Array.isArray(savedAnchors)) throw new Error('连线锚点格式无效。');
  const currentAnchors = Object.fromEntries(Object.entries(savedAnchors)
    .map(([key, points]) => [key.split(':').map(id => id === 'subtitle_render' ? 'subtitle_cover' : id).join(':'), points])
    .filter(([key]) => edgeKeys.has(key)));
  const view = validateView(data.view);
  return { nodes: clean, anchors: validateAnchors(currentAnchors), view };
}

function validateView(view) {
  const c = view?.camera;
  const validCamera = c && [c.x, c.y, c.scale].every(Number.isFinite)
    && Math.abs(c.x) <= 100000 && Math.abs(c.y) <= 100000 && c.scale >= 0.08 && c.scale <= 1.8;
  const review = view?.review;
  return {
    camera: validCamera ? { x: c.x, y: c.y, scale: c.scale } : { ...DEFAULT_CAMERA },
    selected: ['subtitle_render', 'cover_localize'].includes(view?.selected) ? 'subtitle_cover' :
      index.has(view?.selected) ? view.selected : 'probe_input',
    consoleCollapsed: view?.consoleCollapsed === true,
    consoleTab: view?.consoleTab === 'output' ? 'output' : 'log',
    review: {
      tab: review?.tab === 'subtitles' ? 'subtitles' : 'workflow',
      stage: ['initial', 'segmented', 'draft', 'final'].includes(review?.stage) ? review.stage : 'segmented',
      follow: review?.follow !== false,
      jobId: ID.test(review?.jobId) ? review.jobId : null,
    },
  };
}
function toast(message, error = false) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').classList.toggle('error', error);
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4500);
}
function readLayout() {
  for (const key of [STORAGE, ...LEGACY_LAYOUT_KEYS]) {
    try {
      const saved = localStorage.getItem(key);
      if (saved) return validateLayout(JSON.parse(saved));
    } catch { /* Invalid or unavailable browser storage falls back to defaults. */ }
  }
  return null;
}

function persist() {
  const view = {
    camera, selected,
    consoleCollapsed: $('console').classList.contains('collapsed'),
    consoleTab: $('output-tab').getAttribute('aria-selected') === 'true' ? 'output' : 'log',
    review: getReviewView(),
  };
  const data = JSON.stringify({ nodes: config, anchors, view });
  if (data === serializedLayout) return;
  try {
    localStorage.setItem(STORAGE, data);
    serializedLayout = data;
  } catch { /* The workbench still works without browser storage. */ }
}

function scheduleViewSave() {
  clearTimeout(viewSaveTimer);
  viewSaveTimer = setTimeout(persist, 140);
}
function snapshot() {
  return structuredClone({ nodes: config, anchors });
}
function commit(previous) {
  if (JSON.stringify(previous) === JSON.stringify({ nodes: config, anchors })) return;
  history.push(previous);
  if (history.length > 50) history.shift();
  future = [];
  persist();
  syncHistory();
}
function syncHistory() {
  $('undo').disabled = busy || history.length === 0;
  $('redo').disabled = busy || future.length === 0;
}
function undo(redo = false) {
  if (busy || drag) return;
  const from = redo ? future : history;
  const to = redo ? history : future;
  if (!from.length) return;
  to.push(snapshot());
  ({ nodes: config, anchors } = from.pop());
  rebuild();
  persist();
  syncHistory();
}
function el(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}
function svg(tag, attributes = {}) {
  const element = document.createElementNS(NS, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}
async function refreshSources() {
  try {
    const data = await workflowResponse(await fetch('/api/video-sources'));
    knownSources = data.sources;
    if (!knownSources.some(source => source.id === selectedSourceId)) selectedSourceId = knownSources[0]?.id ?? '';
    if (inputMode === 'existing') { renderNodes(); draw(); }
  } catch (error) { toast(error.message || '无法读取已有素材', true); }
}

function videoPicker() {
  const picker = el('div', 'source-picker');
  const tabs = el('div', 'source-tabs');
  for (const [mode, title] of [['file', '本地 MP4'], ['youtube', 'YouTube 链接'], ['existing', '已有素材']]) {
    const tab = el('button', '', title);
    tab.type = 'button';
    tab.disabled = busy;
    tab.setAttribute('aria-pressed', String(inputMode === mode));
    tab.onclick = () => {
      inputMode = mode;
      authorizeVoiceClone = false;
      if (mode === 'youtube') setPreviewInput(null);
      else if (mode === 'file' && inputVideo) setPreviewInput(inputVideo);
      else setPreviewInput(null);
      renderNodes();
      draw();
      if (mode === 'existing') void refreshSources();
    };
    tabs.append(tab);
  }
  picker.append(tabs);
  const consent = el('label', 'voice-clone-consent');
  const check = el('input');
  check.type = 'checkbox';
  check.checked = authorizeVoiceClone;
  check.disabled = busy;
  check.onchange = () => { authorizeVoiceClone = check.checked; };
  consent.append(check, el('span', '', '已获本视频所有说话人授权，允许上传参考原声并创建复刻音色（可能收费）'));
  picker.append(consent);
  if (inputMode === 'existing') {
    const label = el('label', 'source-url-label', '选择已下载或上传的原视频');
    const select = el('select', 'source-url');
    select.setAttribute('aria-label', '已有原视频');
    select.disabled = busy;
    if (!knownSources.length) select.add(new Option('暂无素材，请先下载或上传一次', ''));
    for (const source of knownSources) select.add(new Option(source.title, source.id));
    select.value = selectedSourceId;
    const location = el('p', 'connection-note', knownSources.find(source => source.id === selectedSourceId)?.path ?? '');
    location.style.overflowWrap = 'anywhere';
    select.onchange = () => {
      selectedSourceId = select.value;
      authorizeVoiceClone = false; check.checked = false;
      location.textContent = knownSources.find(source => source.id === selectedSourceId)?.path ?? '';
    };
    const refresh = el('button', '', '刷新素材列表');
    refresh.type = 'button'; refresh.disabled = busy; refresh.onclick = () => { void refreshSources(); };
    label.append(select);
    picker.append(label, location, el('p', 'connection-note', '直接读取首次下载的原片；任务目录只保存处理结果。'), refresh);
    return picker;
  }
  if (inputMode === 'youtube') {
    const label = el('label', 'source-url-label', '原视频链接');
    const input = el('input', 'source-url');
    input.type = 'url';
    input.placeholder = 'https://www.youtube.com/watch?v=…';
    input.value = youtubeUrl;
    input.disabled = busy;
    input.setAttribute('aria-label', 'YouTube 视频链接');
    input.oninput = () => { youtubeUrl = input.value; authorizeVoiceClone = false; check.checked = false; };
    label.append(input);
    picker.append(label, el('p', 'connection-note', '点击顶部运行：下载后自动完成翻译、配音、字幕与成片。'));
    return picker;
  }
  const row = el('div', 'video-input-picker');
  const button = el('button', '', '选择视频');
  button.type = 'button';
  button.disabled = busy;
  button.onclick = () => $('workflow-video').click();
  const name = el('span', '', inputVideo?.name ?? '未选择 MP4');
  name.title = name.textContent;
  row.append(button, name);
  picker.append(row);
  return picker;
}

function updateNodeMode(card, nodeId) {
  const mode = backendModes[nodeId] ?? '';
  const badge = card.querySelector('.node-mode');
  card.dataset.mode = mode;
  badge.dataset.mode = mode;
  badge.textContent = modeLabels[mode] ?? '未知';
  badge.setAttribute('aria-label', `运行模式：${badge.textContent}`);
  const mockNote = card.querySelector('.node-mock-note');
  if (mockNote) mockNote.hidden = mode !== 'mock';
}

function applyBackendModes(modes) {
  backendModes = modes;
  for (const [id, card] of elements) updateNodeMode(card, id);
  for (const step of $('step-strip').children) step.dataset.mode = modes[step.dataset.step] ?? '';
  if (!$('workflow-panel').hidden) drawMinimap(bounds());
}

async function refreshBackendModes() {
  try {
    const snapshot = await workflowResponse(await fetch('/api/workflow-modes'));
    applyBackendModes(snapshot.modes);
    return snapshot;
  } catch {
    applyBackendModes({});
    return null;
  }
}

const modeMenu = $('node-mode-menu');
const modeButtons = [...modeMenu.querySelectorAll('button[data-mode]')];
let modeTarget;
let savingMode = false;

function closeNodeModes(restoreFocus = false) {
  if (!modeMenu.matches(':popover-open')) return;
  modeMenu.hidePopover();
  if (restoreFocus) elements.get(modeTarget.node.id)?.querySelector('.node-header').focus({ preventScroll: true });
}

document.addEventListener('pointerdown', event => {
  if (!modeMenu.contains(event.target)) closeNodeModes();
});
modeMenu.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  event.preventDefault();
  closeNodeModes(true);
});

function updateModeMenu(message) {
  const { node, x, y, snapshot } = modeTarget;
  for (const button of modeButtons) {
    const mode = button.dataset.mode;
    const current = snapshot?.modes[node.id] === mode;
    const unavailable = snapshot && mode === 'real' && !snapshot.available.includes(node.id);
    button.disabled = busy || savingMode || !snapshot || current || Boolean(unavailable);
    button.textContent = unavailable ? '真实（待接入）' : modeLabels[mode];
    button.setAttribute('aria-pressed', String(current));
  }
  $('node-mode-message').textContent = message;
  modeMenu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - modeMenu.offsetWidth - 8))}px`;
  modeMenu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - modeMenu.offsetHeight - 8))}px`;
}

async function openNodeModes(node, x, y) {
  if (drag || savingMode) return;
  const target = { node, x, y, snapshot: null };
  modeTarget = target;
  $('node-mode-title').textContent = `${node.title} · 运行模式`;
  if (!modeMenu.matches(':popover-open')) modeMenu.showPopover();
  modeMenu.focus({ preventScroll: true });
  updateModeMenu(busy ? '任务运行中，模式已锁定。' : '正在读取节点模式…');
  target.snapshot = await refreshBackendModes();
  if (modeTarget !== target || !modeMenu.matches(':popover-open')) return;
  updateModeMenu(busy ? '任务运行中，模式已锁定。' : target.snapshot
    ? '对 CLI 和 WebUI 的后续任务生效。' : '无法读取后端节点模式。');
  if (document.activeElement === modeMenu) modeButtons.find(button => !button.disabled)?.focus();
}

for (const button of modeButtons) {
  button.onclick = async () => {
    if (busy || savingMode || !modeTarget?.snapshot) return;
    const target = modeTarget;
    const { node, snapshot } = target;
    const mode = button.dataset.mode;
    savingMode = true;
    updateModeMenu('正在保存节点模式…');
    try {
      const saved = await workflowResponse(await fetch('/api/workflow-modes', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revision: snapshot.revision, modes: { ...snapshot.modes, [node.id]: mode } }),
      }));
      applyBackendModes(saved.modes);
      closeNodeModes(true);
      toast(`${node.title}已切换为${modeLabels[mode]}，下次运行生效。`);
    } catch (error) {
      if (modeMenu.matches(':popover-open')) {
        target.snapshot = await refreshBackendModes();
        if (modeMenu.matches(':popover-open')) {
          savingMode = false;
          updateModeMenu(error.message);
          modeButtons.find(option => !option.disabled)?.focus();
        }
      } else {
        toast(error.message, true);
      }
    } finally {
      savingMode = false;
    }
  };
}
window.addEventListener('resize', () => closeNodeModes());

function renderNodes() {
  $('nodes').replaceChildren();
  elements.clear();
  for (const node of schema) {
    const card = el('article', 'node');
    card.dataset.node = node.id;
    card.style.setProperty('--node-category', categories[node.category].color);
    card.setAttribute('aria-label', node.title);
    const header = el('div', 'node-header');
    header.tabIndex = 0;
    header.setAttribute('role', 'button');
    header.setAttribute('aria-label', `选择${node.title}`);
    header.setAttribute('aria-keyshortcuts', 'Shift+F10 ContextMenu');
    const collapse = el('button', 'node-collapse', config[node.id].collapsed ? '+' : '−');
    collapse.setAttribute('aria-label', `折叠或展开${node.title}`);
    collapse.setAttribute('aria-expanded', String(!config[node.id].collapsed));
    collapse.addEventListener('click', event => {
      event.stopPropagation();
      const before = snapshot();
      config[node.id].collapsed = !config[node.id].collapsed;
      commit(before);
      renderNodes();
      draw();
    });
    const modeBadge = el('span', 'node-mode');
    header.append(el('span', 'node-number', node.symbol), el('h3', 'node-title', node.title), modeBadge, collapse);
    header.addEventListener('click', () => selectNode(node.id));
    header.addEventListener('keydown', event => {
      if (event.target !== header) return;
      if (event.key === 'ContextMenu' || (event.shiftKey && event.key === 'F10')) {
        event.preventDefault();
        const rect = header.getBoundingClientRect();
        void openNodeModes(node, rect.left, rect.bottom);
      } else if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectNode(node.id);
      }
    });
    card.addEventListener('contextmenu', event => {
      if (event.target.closest('input,select,textarea,[contenteditable]')) return;
      event.preventDefault();
      void openNodeModes(node, event.clientX, event.clientY);
    });
    const ports = el('div', 'ports');
    ports.append(el('span', 'port', node.input), el('span', 'port out', node.output));
    const fields = el('div', 'node-fields');
    fields.setAttribute('aria-label', `${node.title}参数`);
    renderNodeFields(fields, node);
    const mockNote = el('p', 'node-mock-note', '模拟节点：此处配置不影响运行结果。');
    mockNote.hidden = true;
    fields.prepend(mockNote);
    if (node.id === 'asr_diarize') {
      const preview = el('details', 'node-preview');
      const body = el('div', 'node-preview-content');
      preview.addEventListener('toggle', draw);
      preview.append(el('summary', '', '字幕查看'), body);
      renderPreview(body);
      fields.append(preview);
    }
    const footer = el('div', 'node-footer');
    const state = el('span', 'node-state');
    footer.append(state);
    const handle = el('button', 'node-resize');
    handle.type = 'button';
    handle.title = '拖动调整节点尺寸，也可使用方向键';
    handle.setAttribute('aria-label', `调整${node.title}尺寸`);
    handle.addEventListener('keydown', event => resizeWithKeyboard(event, node.id));
    card.append(header, el('div', 'node-id', `${node.id} · ${node.role}组 · ${node.incremental ? '增量' : '基础版'}`), ports, fields, footer, handle);
    updateNodeMode(card, node.id);
    card.addEventListener('focusin', () => { if (selected !== node.id) selectNode(node.id); });
    card.addEventListener('click', event => {
      if (!event.target.closest('button,.node-header') && selected !== node.id) selectNode(node.id);
    });
    $('nodes').append(card);
    elements.set(node.id, card);
  }
}
function selectNode(id) {
  if (selected !== id) {
    selected = id;
    scheduleViewSave();
  }
  updateOutput();
  draw();
}
const configLabels = {
  fade_enabled: '字幕渐入渐出',
  resolution: '输出分辨率', bitrate: '视频码率档位',
  ffprobe: 'ffprobe 路径', ffmpeg: 'FFmpeg 路径',
  audio_stream: '音频流索引', video_stream: '视频流索引',
  model_dir: 'Whisper 模型目录', max_duration_sec: '视频时长上限（秒）',
  audio_recheck: '启用音频复识别', community1_python: 'Community-1 Python',
  community1_cache: 'Community-1 缓存目录', community1_device: 'Community-1 设备',
  num_speakers: '说话人数量', worker_timeout_sec: '说话人区分超时（秒）',
  semantic_provider: '语义复核服务', allow_semantic_network: '允许语义复核联网',
  semantic_max_calls: '语义复核调用上限', model: 'DeepSeek 模型',
  timeout_sec: '请求超时（秒）', max_block_span_ms: '翻译块跨度上限（毫秒）',
  default_terminology: '默认术语表', style: '字幕风格', layout: '语言排布',
  event_model_dir: '非语言事件模型目录', device: '分离设备',
  restore_nonverbal: '保留笑声等非语言声音', event_threshold: '事件识别阈值',
  speech_guard_sec: '对白保护间隔（秒）', nonverbal_gain: '非语言声音增益',
  background_gain: '背景音增益', voice_mode: '音色方式', min_speed: '最低播放速度',
  max_speedup: '常规最高播放速度', natural_groups: '按自然语义组配音',
  duration_repair_attempts: '最多时长返工轮数', duration_exhaustion_policy: '轮数耗尽策略（use_latest：直接采用最后返工稿）',
  max_forward_delay_ms: '允许向后顺延（毫秒）', short_audio_policy: '短音频处理策略',
  timing_source: '字幕时间依据', speech_model_dir: '中文语音定位模型',
  paginate: '字幕分页', semantic_pairing: '双语分段匹配', strict_single_line: '严格单行',
  display_font_path: '字幕字体路径',
};
const backendSettings = new Map();
const savingSettings = new Set();
let settingsQueue = Promise.resolve();
let subtitleCatalog;

function subtitleStylePreview(form) {
  const preview = el('figure', 'subtitle-style-preview');
  const frame = el('div', 'subtitle-style-frame');
  preview.append(el('figcaption', '', '字幕样式预览'), frame);
  subtitleCatalog ??= fetch('/subtitle-styles.json').then(workflowResponse).catch(error => {
    subtitleCatalog = null;
    throw error;
  });
  const catalog = subtitleCatalog;
  const update = async () => {
    try {
      const { styles, layouts, geometry, appearance } = await catalog;
      const style = { ...appearance, ...styles[form.elements.style.value] };
      const layout = layouts[form.elements.layout.value];
      frame.style.setProperty('--subtitle-side', `${geometry.margin_x / geometry.width * 100}%`);
      frame.replaceChildren(...layout.lines.map(lang => {
        const line = el('span', 'subtitle-style-line',
          lang === 'zh' ? '让知识跨越语言。' : 'Let knowledge cross languages.');
        line.lang = lang === 'zh' ? 'zh-Hans' : 'en';
        line.style.bottom = `${layout.margin_y[lang] / geometry.height * 100}%`;
        line.style.fontFamily = `${style.font ?? layout.font}, "Arial Unicode MS", sans-serif`;
        line.style.fontSize = `${geometry[`${lang}_size`] / geometry.width * 100}cqw`;
        line.style.color = style.color;
        const edge = `${style[`${lang}_outline`] / geometry.width * 100}cqw`;
        const edgeColor = style[`${lang}_edge`];
        if (style.box) {
          line.style.backgroundColor = edgeColor;
          line.style.paddingInline = edge;
        } else {
          line.style.webkitTextStroke = `${edge} ${edgeColor}`;
          if (style.shadow) {
            line.style.textShadow = `0 ${style.shadow / geometry.width * 100}cqw 0 ${style[`${lang}_background`] ?? style.background}`;
          }
        }
        return line;
      }));
    } catch {
      frame.textContent = '暂时无法加载样式预览';
    }
  };
  return { preview, update };
}

function configRow(key, value) {
  const row = el('div', 'param-row node-config-value');
  row.append(el('span', 'param-label', configLabels[key] ?? key),
    el('output', '', value));
  return row;
}

function settingControl(field) {
  const { key, value, type, min, max, choices, choice_labels: labels, optional } = field;
  const input = el(choices ? 'select' : 'input');
  input.name = key;
  input.dataset.param = key;
  input.setAttribute('aria-label', configLabels[key] ?? key);
  if (choices) {
    for (const choice of choices) input.add(new Option(labels?.[choice] ?? choice, choice));
  } else {
    input.type = ({ boolean: 'checkbox', integer: 'number', number: 'number' })[type] ?? 'text';
    if (input.type === 'number') {
      if (min !== null) input.min = min;
      if (max !== null) input.max = max;
      input.step = type === 'integer' ? '1' : 'any';
      input.required = !optional;
    }
    if (optional) input.placeholder = '留空自动选择';
  }
  if (type === 'boolean') input.checked = value;
  else input.value = value ?? '';
  return input;
}

function renderSettings(content, node, settings) {
  content.replaceChildren();
  if (!settings) {
    content.append(el('p', 'connection-note', '暂时无法读取后端配置，请刷新页面。'));
    return;
  }
  if (settings.fixed) {
    const entries = Object.entries(settings.fixed);
    for (const [key, value] of entries) {
      const display = typeof value === 'object'
        ? Object.entries(value).map(([en, zh]) => `${en} → ${zh}`).join('、')
        : String(value);
      const row = configRow(key, display);
      if (node.id === 'tts_align' && key === 'model') row.firstElementChild.textContent = '配音模型';
      content.append(row);
    }
    return;
  }

  const form = el('form', 'node-config-form');
  const fields = el('fieldset', 'param-group');
  fields.disabled = busy || savingSettings.has(node.id);
  fields.append(el('legend', '', 'CLI 共享配置'));
  const inputs = [];
  for (const field of settings.fields) {
    if (field.readonly) {
      const value = field.type === 'object'
        ? Object.entries(field.value ?? {}).map(([key, value]) => `${key} = ${value}`).join(' · ')
        : field.value || '继承当前 Python 环境';
      fields.append(configRow(field.key, value));
      continue;
    }
    const row = el('label', 'param-row');
    const input = settingControl(field);
    row.classList.toggle('bool', field.type === 'boolean');
    row.classList.toggle('numeric', input.type === 'number');
    const label = field.key === 'model_dir' && node.id === 'b_environment' ? '背景分离模型目录' : configLabels[field.key] ?? field.key;
    input.setAttribute('aria-label', label);
    row.append(el('span', 'param-label', label), input);
    fields.append(row);
    inputs.push([input, field]);
  }
  form.append(fields);
  let updatePreview;
  if (node.id === 'subtitle_cover') {
    const { preview, update } = subtitleStylePreview(form);
    updatePreview = update;
    fields.append(preview);
    void update();
  }
  form.onchange = () => {
    void updatePreview?.();
    form.requestSubmit();
  };
  form.onsubmit = async event => {
    event.preventDefault();
    if (busy || fields.disabled || savingSettings.has(node.id)) return;
    const values = Object.fromEntries(inputs.map(([input, field]) => [
      input.name, input.type === 'checkbox' ? input.checked
        : field.optional && input.value === '' ? null
        : input.type === 'number' ? input.valueAsNumber : input.value,
    ]));
    fields.disabled = true;
    savingSettings.add(node.id);
    $('run').disabled = true;
    form.querySelector('[role="alert"]')?.remove();
    try {
      const save = settingsQueue.then(async () => workflowResponse(await fetch(`/api/workflow-settings/${node.id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revision: settings.revision, values }),
      })));
      settingsQueue = save.catch(() => {});
      backendSettings.set(node.id, await save);
    } catch (error) {
      const target = elements.get(node.id)?.querySelector('.node-backend-settings') ?? content;
      savingSettings.delete(node.id);
      renderSettings(target, node, settings);
      const message = el('p', 'connection-note', error.message || '无法保存节点配置。');
      message.setAttribute('role', 'alert');
      target.querySelector('form').append(message);
      return;
    } finally {
      savingSettings.delete(node.id);
      $('run').disabled = busy || savingSettings.size > 0;
    }
    const target = elements.get(node.id)?.querySelector('.node-backend-settings') ?? content;
    renderSettings(target, node, backendSettings.get(node.id));
  };
  content.append(form);
}

function renderNodeFields(content, node) {
  if (node.id === 'probe_input') content.append(videoPicker());
  const settings = el('div', 'node-backend-settings');
  if (backendSettings.has(node.id)) renderSettings(settings, node, backendSettings.get(node.id));
  else settings.append(el('p', 'connection-note', '正在读取后端配置…'));
  content.append(settings);
}

async function refreshNodeSettings(node) {
  try {
    const settings = await workflowResponse(await fetch(`/api/workflow-settings/${node.id}`));
    backendSettings.set(node.id, settings);
  } catch {
    backendSettings.set(node.id, null);
  }
  const target = elements.get(node.id)?.querySelector('.node-backend-settings');
  if (target) renderSettings(target, node, backendSettings.get(node.id));
  if (!$('workflow-panel').hidden) draw();
}

function renderPreview(content) {
  const open = el('button', '', '打开字幕查看');
  open.onclick = openSubtitleReview;
  const message = runResult?.english_srt_ready
    ? '英文字幕初稿已保存，可在字幕查看中对照视频复核。'
    : runResult?.english_segments_ready
      ? '英文分段已就绪，可在字幕查看中对照视频复核。'
      : '运行工作流后，在字幕查看中对照视频检查各阶段字幕。';
  content.replaceChildren(el('p', 'connection-note', message), open);
}

function renderStepStrip() {
  const strip = $('step-strip');
  for (const node of schema) {
    const button = el('button', 'step-jump');
    button.title = node.title;
    button.dataset.step = node.id;
    button.style.setProperty('--node-category', categories[node.category].color);
    button.append(el('span', 'step-index', node.symbol), el('span', 'step-title', node.title));
    button.onclick = () => { selectNode(node.id); focusNode(); };
    strip.append(button);
  }
}
const links = $('links');
const anchorLayer = svg('g');
const anchorHint = svg('circle', { class: 'link-anchor-hint', visibility: 'hidden' });
const paths = edges.map(([from, to]) => {
  const key = edgeKey(from, to);
  const path = svg('path', { class: 'link' });
  path.dataset.from = from;
  path.dataset.to = to;
  const hits = svg('g', { 'data-edge': key });
  const handles = svg('g', { 'data-edge': key });
  links.append(path, hits);
  anchorLayer.append(handles);
  return { from, to, key, path, hits, handles };
});
links.append(anchorLayer, anchorHint);

function curveSegments(points) {
  const tangents = points.map((point, i) => {
    const prev = points[i - 1], next = points[i + 1];
    if (!prev || !next) {
      const neighbor = prev ?? next;
      return { x: Math.max(20, Math.hypot(neighbor.x - point.x, neighbor.y - point.y) / 4), y: 0 };
    }
    const dx = next.x - prev.x, dy = next.y - prev.y;
    const reach = Math.min(Math.hypot(point.x - prev.x, point.y - prev.y),
      Math.hypot(next.x - point.x, next.y - point.y)) / 4;
    const scale = reach / (Math.hypot(dx, dy) || 1);
    return { x: dx * scale, y: dy * scale };
  });
  return points.slice(1).map((end, i) => {
    const start = points[i], outgoing = tangents[i], incoming = tangents[i + 1];
    const command = `C${start.x + outgoing.x},${start.y + outgoing.y} ${end.x - incoming.x},${end.y - incoming.y} ${end.x},${end.y}`;
    return { move: `M${start.x},${start.y}`, command };
  });
}
function drawLink({ from, to, key, path, hits, handles }) {
  const a = config[from], b = config[to];
  const points = anchors[key] ?? [];
  const segments = curveSegments([
    { x: a.x + a.width, y: a.y + portOffset(from, true) },
    ...points,
    { x: b.x, y: b.y + portOffset(to, false) },
  ]);
  path.setAttribute('d', `${segments[0].move} ${segments.map(segment => segment.command).join(' ')}`);
  path.style.stroke = categories[index.get(from).category].color;
  path.classList.toggle('highlight', from === selected || to === selected);

  while (hits.children.length > segments.length) hits.lastElementChild.remove();
  segments.forEach(({ move, command }, i) => {
    const hit = hits.children[i] ?? hits.appendChild(svg('path', { class: 'link-hit', 'data-segment': i }));
    hit.setAttribute('d', `${move} ${command}`);
  });
  while (handles.children.length > points.length) handles.lastElementChild.remove();
  points.forEach(({ x, y }, i) => {
    const handle = handles.children[i] ?? handles.appendChild(svg('circle', { class: 'link-anchor', 'data-anchor': i }));
    handle.setAttribute('cx', x);
    handle.setAttribute('cy', y);
    handle.setAttribute('r', 5 / camera.scale);
  });
}
function nodeHeight(id) {
  return elements.get(id)?.offsetHeight || config[id].height || 290;
}
function portOffset(id, outgoing) {
  if (config[id].collapsed) return 22;
  const port = elements.get(id)?.querySelector(outgoing ? '.port.out' : '.port');
  return port?.offsetTop ? port.offsetTop + 8 : 87;
}
function resizeNode(id, width, height) {
  const node = config[id];
  node.width = Math.round(Math.max(SIZE_LIMITS.width[0], Math.min(SIZE_LIMITS.width[1], width)));
  if (!node.collapsed && height !== null) {
    node.height = Math.round(Math.max(SIZE_LIMITS.height[0], Math.min(SIZE_LIMITS.height[1], height)));
  }
}
function resizeWithKeyboard(event, id) {
  if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) return;
  event.preventDefault();
  const before = snapshot();
  const node = config[id];
  const step = event.shiftKey ? 25 : 10;
  const dx = event.key === 'ArrowLeft' ? -step : event.key === 'ArrowRight' ? step : 0;
  const dy = event.key === 'ArrowUp' ? -step : event.key === 'ArrowDown' ? step : 0;
  resizeNode(id, node.width + dx, dy ? nodeHeight(id) + dy : null);
  commit(before);
  draw();
}
function draw() {
  $('world').style.transform = `translate(${camera.x}px,${camera.y}px) scale(${camera.scale})`;
  $('zoom').textContent = `${Math.round(camera.scale * 100)}%`;
  const gridSpacing = Math.max(10, 24 * camera.scale);
  $('canvas').style.backgroundSize = `${gridSpacing}px ${gridSpacing}px`;
  $('canvas').style.backgroundPosition = `${camera.x}px ${camera.y}px`;
  const activeNode = runResult?.state === 'running' ? runResult.node : null;
  for (const button of $('step-strip').children) {
    button.classList.toggle('is-active', runResult?.state === 'running' &&
      (runResult.active_nodes ?? [activeNode]).includes(button.dataset.step));
    if (button.dataset.step === selected) button.setAttribute('aria-current', 'step');
    else button.removeAttribute('aria-current');
  }
  for (const node of schema) {
    const item = elements.get(node.id);
    if (!item) continue;
    item.style.left = `${config[node.id].x}px`;
    const { width, height, collapsed } = config[node.id];
    item.style.top = `${config[node.id].y}px`;
    item.style.width = `${width}px`;
    item.style.height = !collapsed && height !== null ? `${height}px` : '';
    item.classList.toggle('sized', !collapsed && height !== null);
    item.classList.toggle('selected', selected === node.id);
    item.classList.toggle('collapsed', collapsed);
    const isCurrent = runResult?.node === node.id;
    const running = runResult?.state === 'running' && (runResult.active_nodes ?? [activeNode]).includes(node.id);
    const failed = isCurrent && ['blocked', 'failed'].includes(runResult.state);
    const done = runResult?.completed_nodes?.includes(node.id);
    let label = '等待运行';
    if (node.id === 'probe_input' && runResult?.phase === 'download' && runResult?.state === 'running') label = '下载原视频 · 入图准备';
    if (done) label = node.id === 'asr_diarize' ? '英文分段已就绪' : '已完成';
    const noOutput = runResult?.node_states?.[node.id] === 'no_output';
    if (noOutput) label = ['b_environment', 'mix_background'].includes(node.id)
      ? '背景处理未生效 · 继续纯中文配音' : '未产生增量 · 基础流程继续';
    if (running) label = '正在运行';
    if (failed) label = runResult.state === 'blocked' ? '尚未接入 · 已停止' : '执行失败';
    item.classList.toggle('is-active', running);
    item.classList.toggle('is-done', !!done);
    item.classList.toggle('is-blocked', failed);
    item.classList.toggle('is-returned', noOutput);
    item.querySelector('.node-state').textContent = label;
  }
  anchorHint.setAttribute('visibility', 'hidden');
  for (const path of paths) drawLink(path);
  drawMinimap(bounds());
}
function bounds() {
  const points = Object.values(anchors).flat();
  return {
    left: Math.min(...schema.map(n => config[n.id].x), ...points.map(p => p.x)) - 60,
    top: Math.min(...schema.map(n => config[n.id].y), ...points.map(p => p.y)) - 100,
    right: Math.max(...schema.map(n => config[n.id].x + config[n.id].width), ...points.map(p => p.x)) + 60,
    bottom: Math.max(...schema.map(n => config[n.id].y + nodeHeight(n.id)), ...points.map(p => p.y)) + 80,
  };
}
function drawMinimap(graph) {
  const canvas = $('canvas');
  const view = {
    x: -camera.x / camera.scale,
    y: -camera.y / camera.scale,
    width: canvas.clientWidth / camera.scale,
    height: canvas.clientHeight / camera.scale,
  };
  // Keep the viewport visible when the user pans past the graph.
  const box = {
    left: Math.min(graph.left, view.x),
    top: Math.min(graph.top, view.y),
    right: Math.max(graph.right, view.x + view.width),
    bottom: Math.max(graph.bottom, view.y + view.height),
  };
  const scale = Math.min(188 / (box.right - box.left), 128 / (box.bottom - box.top));
  // The map's coordinate system stays fixed until the pointer is released.
  minimapBounds = minimapDrag?.bounds ?? { ...box, scale };
  const { left, top, scale: mapScale } = minimapBounds;
  const map = $('minimap');
  map.replaceChildren();
  for (const node of schema) {
    const item = config[node.id];
    map.append(svg('rect', {
      x: 6 + (item.x - left) * mapScale, y: 6 + (item.y - top) * mapScale,
      width: item.width * mapScale, height: nodeHeight(node.id) * mapScale, rx: 2,
      fill: backendModes[node.id] === 'mock' ? 'var(--node-mock)' : categories[node.category].color,
      opacity: selected === node.id ? 0.9 : 0.4,
    }));
  }
  map.append(svg('rect', {
    id: 'minimap-viewport', x: 6 + (view.x - left) * mapScale, y: 6 + (view.y - top) * mapScale,
    width: view.width * mapScale, height: view.height * mapScale,
    fill: 'var(--map-window)', stroke: 'var(--map-outline)', 'stroke-width': 1,
  }));
}
function fit() {
  const box = bounds(), width = $('canvas').clientWidth, height = $('canvas').clientHeight;
  if (width < 64 || height < 120) return;
  camera.scale = Math.max(0.08, Math.min(1, (width - 48) / (box.right - box.left), (height - 95) / (box.bottom - box.top)));
  camera.x = (width - (box.right + box.left) * camera.scale) / 2;
  camera.y = (height - (box.bottom + box.top) * camera.scale) / 2 + 8;
  draw();
  scheduleViewSave();
}
function focusNode() {
  camera.scale = Math.min(1, ($('canvas').clientWidth - 54) / config[selected].width, ($('canvas').clientHeight - 110) / nodeHeight(selected));
  camera.scale = Math.max(0.3, camera.scale);
  camera.x = $('canvas').clientWidth / 2 - (config[selected].x + config[selected].width / 2) * camera.scale;
  camera.y = $('canvas').clientHeight / 2 - (config[selected].y + nodeHeight(selected) / 2) * camera.scale;
  draw();
  scheduleViewSave();
}
function zoomBy(factor, x = $('canvas').clientWidth / 2, y = $('canvas').clientHeight / 2) {
  const scale = Math.min(1.8, Math.max(0.08, camera.scale * factor));
  const ratio = scale / camera.scale;
  camera = { x: x - (x - camera.x) * ratio, y: y - (y - camera.y) * ratio, scale };
  draw();
  scheduleViewSave();
}
function rebuild() { renderNodes(); draw(); }

function pointOnLink(hit, pointer, length) {
  let distance = Infinity, nearest = 0;
  const sample = offset => {
    const point = hit.getPointAtLength(offset);
    const gap = Math.hypot(point.x - pointer.x, point.y - pointer.y);
    if (gap < distance) {
      distance = gap;
      nearest = offset;
    }
  };
  for (let i = 0; i <= 24; i++) sample(length * i / 24);
  for (let step = length / 48; step > 0.5; step /= 2) {
    const center = nearest;
    sample(Math.max(0, center - step));
    sample(Math.min(length, center + step));
  }
  return hit.getPointAtLength(nearest);
}
function linkUnderPointer(event) {
  const pointer = new DOMPoint(event.clientX, event.clientY).matrixTransform(links.getScreenCTM().inverse());
  const hits = document.elementsFromPoint(event.clientX, event.clientY).filter(el => el.matches('.link-hit'));
  const tolerance = 0.75 / camera.scale;
  let best;
  for (const hit of hits) {
    const length = hit.getTotalLength();
    const point = pointOnLink(hit, pointer, length);
    const distance = Math.hypot(point.x - pointer.x, point.y - pointer.y);
    // Coincident strokes are common in a single row. Prefer the local segment on a tie.
    if (!best || distance < best.distance - tolerance ||
        (Math.abs(distance - best.distance) <= tolerance && length < best.length)) {
      best = { hit, point, distance, length };
    }
  }
  return best;
}
const clampAnchor = n => Math.max(-10000, Math.min(10000, n));

links.addEventListener('pointermove', event => {
  if (drag || event.pointerType === 'touch' || !event.target.matches('.link-hit')) return;
  const match = linkUnderPointer(event);
  if (!match) return;
  const { x, y } = match.point;
  anchorHint.setAttribute('cx', x);
  anchorHint.setAttribute('cy', y);
  anchorHint.setAttribute('r', 4 / camera.scale);
  anchorHint.setAttribute('visibility', 'visible');
});
links.addEventListener('pointerout', () => anchorHint.setAttribute('visibility', 'hidden'));
links.addEventListener('contextmenu', event => {
  const isAnchor = event.target.matches('.link-anchor');
  if (!isAnchor && !event.target.matches('.link-hit')) return;
  event.preventDefault();
  if (drag) return;
  const match = isAnchor ? null : linkUnderPointer(event);
  const target = isAnchor ? event.target : match?.hit;
  if (!target) return;
  const key = target.parentElement.dataset.edge;
  const points = anchors[key] ?? [];
  const before = snapshot();
  if (isAnchor) {
    points.splice(Number(target.dataset.anchor), 1);
    if (!points.length) delete anchors[key];
  } else {
    if (points.length >= MAX_ANCHORS) {
      toast(`一条连线最多可添加 ${MAX_ANCHORS} 个锚点。`, true);
      return;
    }
    const { x, y } = match.point;
    points.splice(Number(target.dataset.segment), 0, { x: clampAnchor(x), y: clampAnchor(y) });
    anchors[key] = points;
  }
  commit(before);
  draw();
});

$('canvas').addEventListener('pointerdown', event => {
  const handle = event.target.closest('.node-resize');
  if (drag || minimapDrag || event.button !== 0 || (!handle && event.target.closest('input,select,textarea,button,.viewport-controls,.minimap-wrap'))) return;
  const card = event.target.closest('.node');
  if (card && !handle && !event.target.closest('.node-header')) return;
  const node = card?.dataset.node;
  const anchorHandle = event.target.closest('.link-anchor');
  const anchor = anchorHandle && anchors[anchorHandle.parentElement.dataset.edge][Number(anchorHandle.dataset.anchor)];
  if (node) selectNode(node);
  const size = handle ? { width: config[node].width, height: nodeHeight(node), y: event.clientY } : null;
  event.preventDefault();
  $('canvas').setPointerCapture(event.pointerId);
  drag = {
    pointer: event.pointerId, node, size, anchor, x: event.clientX, y: event.clientY,
    before: node || anchor ? snapshot() : null,
  };
  $('canvas').classList.add(handle ? 'resizing' : 'dragging');
});
$('canvas').addEventListener('pointermove', event => {
  if (drag?.pointer !== event.pointerId) return;
  const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
  if (drag.size) {
    const width = drag.size.width + dx / camera.scale;
    const dyTotal = event.clientY - drag.size.y;
    const height = dyTotal ? drag.size.height + dyTotal / camera.scale : drag.before.nodes[drag.node].height;
    resizeNode(drag.node, width, height);
    if (height === null) config[drag.node].height = null;
    draw();
    return;
  }
  if (drag.anchor) {
    drag.anchor.x = clampAnchor(drag.anchor.x + dx / camera.scale);
    drag.anchor.y = clampAnchor(drag.anchor.y + dy / camera.scale);
  } else if (drag.node) {
    const item = config[drag.node];
    item.x = Math.max(-10000, Math.min(10000, item.x + dx / camera.scale));
    item.y = Math.max(-10000, Math.min(10000, item.y + dy / camera.scale));
  } else { camera.x += dx; camera.y += dy; }
  drag.x = event.clientX;
  drag.y = event.clientY;
  draw();
});
for (const eventName of ['pointerup', 'pointercancel', 'lostpointercapture']) {
  $('canvas').addEventListener(eventName, event => {
    if (drag?.pointer !== event.pointerId) return;
    if (drag.before) commit(drag.before);
    else scheduleViewSave();
    drag = null;
    $('canvas').classList.remove('dragging', 'resizing');
  });
}
$('canvas').addEventListener('wheel', event => {
  if (minimapDrag) {
    event.preventDefault();
    return;
  }
  // Keep wheel input out of focused number fields to avoid accidental value edits.
  const fields = event.target.closest('.node-fields');
  if (fields && fields.scrollHeight > fields.clientHeight) {
    if (event.target.closest('input[type=number],select')) {
      fields.scrollTop += event.deltaY;
      event.preventDefault();
    }
    return;
  }
  if (event.target.closest('input,select,textarea')) { event.preventDefault(); return; }
  event.preventDefault();
  const rect = $('canvas').getBoundingClientRect();
  zoomBy(Math.exp(-event.deltaY * 0.0015), event.clientX - rect.left, event.clientY - rect.top);
}, { passive: false });
const minimap = $('minimap');
minimap.addEventListener('pointerdown', event => {
  if (event.button !== 0 || event.target.id !== 'minimap-viewport' || drag || minimapDrag) return;
  const inverse = minimap.getScreenCTM().inverse();
  const start = new DOMPoint(event.clientX, event.clientY).matrixTransform(inverse);
  minimapDrag = { pointer: event.pointerId, inverse, start, camera: { ...camera }, bounds: minimapBounds };
  event.preventDefault();
  minimap.setPointerCapture(event.pointerId);
  minimap.classList.add('dragging');
});
minimap.addEventListener('pointermove', event => {
  if (minimapDrag?.pointer !== event.pointerId) return;
  const { inverse, start, camera: origin, bounds } = minimapDrag;
  const point = new DOMPoint(event.clientX, event.clientY).matrixTransform(inverse);
  const ratio = origin.scale / bounds.scale;
  camera.x = origin.x - (point.x - start.x) * ratio;
  camera.y = origin.y - (point.y - start.y) * ratio;
  draw();
});
for (const eventName of ['pointerup', 'pointercancel', 'lostpointercapture']) {
  minimap.addEventListener(eventName, event => {
    if (minimapDrag?.pointer !== event.pointerId) return;
    const { camera: origin } = minimapDrag;
    minimapDrag = null;
    minimap.classList.remove('dragging');
    if (origin.x !== camera.x || origin.y !== camera.y) {
      draw();
      scheduleViewSave();
    }
  });
}
$('zoom-in').onclick = () => zoomBy(1.2);
$('zoom-out').onclick = () => zoomBy(1 / 1.2);
$('zoom').onclick = () => zoomBy(1 / camera.scale);
$('fit').onclick = fit;
$('focus').onclick = focusNode;
$('fullscreen').onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch { toast('此浏览器不支持全屏，请使用浏览器的全屏菜单。', true); }
};
$('undo').onclick = () => undo();
$('redo').onclick = () => undo(true);
const taskDrawer = $('node-inspector');
$('task-queue-toggle').onclick = () => {
  taskDrawer.showModal();
  void refreshTasks();
};
taskDrawer.addEventListener('click', event => {
  if (event.target === taskDrawer && event.clientX < taskDrawer.getBoundingClientRect().left) {
    taskDrawer.close();
  }
});

$('help').onclick = () => $('canvas-help').showModal();
function setConsoleTab(output) {
  $('log-tab').setAttribute('aria-selected', String(!output));
  $('output-tab').setAttribute('aria-selected', String(output));
  $('log-panel').hidden = output;
  $('output-panel').hidden = !output;
  scheduleViewSave();
}
$('log-tab').onclick = () => setConsoleTab(false);
$('output-tab').onclick = () => setConsoleTab(true);
function setConsoleCollapsed(collapsed) {
  $('console').classList.toggle('collapsed', collapsed);
  const toggle = $('console-toggle');
  toggle.setAttribute('aria-expanded', String(!collapsed));
  toggle.setAttribute('aria-label', collapsed ? '展开运行面板' : '收起运行面板');
}
$('console-toggle').onclick = () => {
  setConsoleCollapsed(!$('console').classList.contains('collapsed'));
  draw();
  scheduleViewSave();
};
function updateLogNotice() {
  const message = !consoleLog || consoleLog.jobId === runResult?.jobId ? runResult?.message : '';
  const logHint = consoleLog?.error ?? (consoleLog && !consoleLog.text && !consoleLog.offset
    ? (consoleLog.pending ? '正在等待后端输出…' : '这个任务没有后端日志。') : '');
  $('log-notice').textContent = [message, logHint].filter(Boolean).join(' · ')
    || (consoleLog ? '' : '运行工作流后，这里会显示后端终端输出。');
}

function renderConsoleLog() {
  const panel = $('log-panel');
  const follow = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 32;
  $('events').textContent = consoleLog?.text ?? '';
  updateLogNotice();
  if (follow) panel.scrollTop = panel.scrollHeight;
}

async function pollConsoleLog(log) {
  if (log.reading) return;
  log.reading = true;
  try {
    const response = await fetch(`/api/workflow-runs/${log.jobId}/logs?offset=${log.offset}`);
    if (!response.ok) throw new Error('无法读取后端日志。');
    const bytes = await response.arrayBuffer();
    log.offset += bytes.byteLength;
    log.pending = response.headers.get('X-Log-Pending') === '1';
    log.text = (log.text + log.decoder.decode(bytes, { stream: log.pending })).slice(-LOG_DISPLAY_LIMIT);
    log.error = null;
  } catch (error) {
    log.error = error.message;
    log.pending = runResult?.state === 'running' && log.jobId === runResult.jobId;
  } finally {
    log.reading = false;
  }
  if (consoleLog !== log) return;
  renderConsoleLog();
  if (log.pending) logPollTimer = setTimeout(() => void pollConsoleLog(log), 700);
}

function followTaskLog(jobId) {
  clearTimeout(logPollTimer);
  consoleLog = jobId ? { jobId, offset: 0, text: '', pending: true, decoder: new TextDecoder() } : null;
  renderConsoleLog();
  if (consoleLog) void pollConsoleLog(consoleLog);
}

$('clear-log').onclick = () => {
  if (consoleLog) consoleLog.text = '';
  renderConsoleLog();
};

document.addEventListener('open-task-log', event => {
  $('workflow-tab').click();
  if ($('console').classList.contains('collapsed')) $('console-toggle').click();
  setConsoleTab(false);
  followTaskLog(event.detail);
});

function updateOutput() {
  let output = `${index.get(selected).title}尚无运行输出。`;
  if (selected === 'probe_input' && runResult?.phase === 'download') output = runResult.message;
  else if (runResult?.node_states?.[selected] === 'no_output') output = ['b_environment', 'mix_background'].includes(selected)
    ? '背景处理未生效，本次继续使用纯中文配音。请查看后端日志中的模型或混音错误。'
    : '本次未发布增量产物，基础流程继续运行。详情见后端日志。';
  else if (selected === 'b_environment' && runResult?.completed_nodes?.includes(selected)) output = '已完成本地背景分离与非语言事件检查，发布 audio/environment.wav 和 environment.source.json；与原视频、台词时间轴绑定。';
  else if (selected === 'mix_background' && runResult?.completed_nodes?.includes(selected)) output = '已混合背景与中文配音，发布 audio/mixed.wav 和 mixed.mix.json；合成节点会验证并使用混合音轨。';
  else if (selected === 'asr_diarize' && runResult?.english_srt_ready) output = '已保存英文字幕中间产物 english.srt。';
  else if (selected === 'asr_diarize' && runResult?.english_segments_ready) output = '英文分段已就绪。';
  else if (selected === 'subtitle_cover' && runResult?.completed_nodes?.includes(selected)) {
    output = '烧录字幕 subtitles/burnin.ass 已生成。';
    if (runResult.subtitle_srt_ready) output += '原文、译文和双语 SRT 已保存在同一目录。';
  }
  else if (selected === 'subtitle_cover' && runResult?.subtitle_srt_ready) {
    output = '原文、译文和双语 SRT 已生成，等待烧录字幕 burnin.ass。';
  }
  else if (runResult?.node === selected) output = runResult.message;
  else if (runResult?.completed_nodes?.includes(selected)) output = '节点已完成。';
  const panel = $('console-output');
  panel.textContent = output;
  if (runResult?.final_video_ready && runResult.jobId) {
    const download = el('a', '', '下载成片 MP4');
    download.href = `/api/workflow-runs/${runResult.jobId}/final-video`;
    panel.append(document.createElement('br'), download);
  }
}

$('workflow-video').onchange = event => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file || busy) return;
  if (!/\.mp4$/i.test(file.name) || !file.size || file.size > 2 * 1024 ** 3) {
    toast('请选择不超过 2 GiB 的非空 MP4 文件。', true);
    return;
  }
  inputVideo = file;
  authorizeVoiceClone = false;
  setPreviewInput(file);
  renderNodes();
  draw();
};

async function workflowResponse(response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || `请求失败（HTTP ${response.status}）。`);
  return data;
}

function showRunResult(status) {
  runResult = status;
  const runStatus = $('run-status');
  runStatus.dataset.state = status.state;
  const labels = { running: '工作流运行中…', blocked: '工作流已停止',
    failed: '工作流执行失败', complete: '工作流已完成' };
  runStatus.textContent = status.state === 'running' && status.phase === 'download' ? '正在下载原视频…' : labels[status.state];
  updateLogNotice();
  const preview = elements.get('asr_diarize')?.querySelector('.node-preview-content');
  if (preview) renderPreview(preview);
  updateOutput();
  draw();
}

function setRunLock(locked) {
  busy = locked;
  if (locked) closeNodeModes();
  for (const id of ['run', 'clear-log']) {
    $(id).disabled = locked;
  }
  $('draft-state').hidden = !locked;
  $('draft-state').classList.toggle('is-locked', locked);
  syncHistory();
  renderNodes();
}

$('run').onclick = async () => {
  if (busy || savingSettings.size) return;
  if ((inputMode === 'file' && !inputVideo) || (inputMode === 'youtube' && !youtubeUrl.trim()) ||
      (inputMode === 'existing' && !selectedSourceId)) {
    selectNode('probe_input');
    focusNode();
    toast('请先选择 MP4、填写 YouTube 链接，或选择已有素材。');
    return;
  }

  setRunLock(true);
  void refreshBackendModes();
  setConsoleCollapsed(false);
  setConsoleTab(false);
  followTaskLog(null);
  const isUrl = inputMode === 'youtube';
  const isJson = inputMode !== 'file';
  showRunResult({ state: 'running', phase: isUrl ? 'download' : 'workflow',
    message: isUrl ? '正在准备原视频（已有素材将直接复用）…' : isJson ? '正在读取已有原视频…' : `正在读取 ${inputVideo.name}…` });
  try {
    const { job_id: jobId } = await workflowResponse(await fetch('/api/workflow-runs', {
      method: 'POST',
      headers: {
        'Content-Type': isJson ? 'application/json' : 'application/octet-stream',
        'X-Authorize-Voice-Clone': String(authorizeVoiceClone),
        ...(!isJson ? { 'X-Video-Name': encodeURIComponent(inputVideo.name) } : {}),
      },
      body: isJson ? JSON.stringify({ ...(isUrl ? { url: youtubeUrl.trim() } : { source_id: selectedSourceId }),
        authorize_voice_clone: authorizeVoiceClone }) : inputVideo,
    }));
    const jobUrl = `/api/workflow-runs/${jobId}`;
    runResult.jobId = jobId;
    followTaskLog(jobId);
    let previewReady = !isUrl;
    if (previewReady) setPreviewJob(jobId);
    void refreshTasks({ latest: true });
    while (true) {
      const status = await workflowResponse(await fetch(jobUrl));
      status.jobId = jobId;
      if (status.input_ready && !previewReady) {
        setPreviewJob(jobId);
        previewReady = true;
      }
      const hasNewSrt = status.english_srt_ready && !runResult.english_srt_ready;
      const completedChanged = (status.completed_nodes ?? []).join() !== (runResult.completed_nodes ?? []).join();
      if (hasNewSrt || completedChanged || status.subtitle_srt_ready !== runResult.subtitle_srt_ready ||
          JSON.stringify(status.node_states) !== JSON.stringify(runResult.node_states) ||
          status.phase !== runResult.phase || status.node !== runResult.node || status.message !== runResult.message || status.state !== runResult.state) {
        showRunResult(status);
      }
      if (status.state !== 'running') {
        refreshSubtitleReview();
        void refreshTasks();
        break;
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
  } catch (error) {
    showRunResult({ ...runResult, state: 'failed', message: error.message });
  } finally {
    setRunLock(false);
    draw();
  }
};

document.addEventListener('keydown', event => {
  const typing = event.target.closest('input,select,textarea,[contenteditable=true]');
  if (document.querySelector('dialog[open]')) return;
  if (typing || !$('subtitle-panel').hidden) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); undo(event.shiftKey); }
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.key.toLowerCase() === 'f') { event.preventDefault(); fit(); }
  if (event.key === '1' && !event.target.closest('.node-fields')) focusNode();
});
// Arrow keys follow tablist conventions, including the narrow-screen layout.
for (const tablist of document.querySelectorAll('[role=tablist]')) {
  tablist.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tabs = [...tablist.querySelectorAll('[role=tab]:not(:disabled):not([hidden])')];
    const current = tabs.indexOf(document.activeElement);
    if (current < 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[next].focus();
    tabs[next].click();
  });
}
function restoreView(view) {
  camera = view.camera;
  selected = view.selected;
  setConsoleCollapsed(view.consoleCollapsed);
  setConsoleTab(view.consoleTab === 'output');
  restoreReviewView(view.review, inputVideo);
}

async function restoreRunStatus(jobId) {
  if (!jobId) return;
  try {
    const status = await workflowResponse(await fetch(`/api/workflow-runs/${jobId}`));
    if (!runResult && getReviewView().jobId === jobId && status.state !== 'running') {
      showRunResult({ ...status, jobId });
    }
  } catch {
    // The saved task may no longer be available.
  }
}

$('status-node-count').textContent = `${schema.length} 节点`;
renderStepStrip();
new ResizeObserver(() => { if (!$('workflow-panel').hidden) draw(); }).observe($('canvas'));
document.addEventListener('canvas-view-change', scheduleViewSave);
window.addEventListener('pagehide', () => persist());
const layout = readLayout();
if (layout) ({ nodes: config, anchors } = layout);
if (location.hash.startsWith('#project=')) {
  globalThis.history.replaceState(null, '', location.pathname + location.search);
}
for (const id of ['workspace-views', 'canvas-tools', 'workspace-actions']) $(id).hidden = false;
restoreView(layout?.view ?? validateView(null));
rebuild();
syncHistory();
updateOutput();
if (!layout) {
  if (narrowScreen.matches) focusNode();
  else fit();
}
persist();
void restoreRunStatus(getReviewView().jobId);
void refreshBackendModes();
for (const node of schema) void refreshNodeSettings(node);
