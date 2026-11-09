import { schema, categories, edges, fieldsOf, defaults } from './node-schema.js';

const $ = id => document.getElementById(id);
const NS = 'http://www.w3.org/2000/svg';
const STORAGE = 'video-localizer.workflow.v2';
const PROJECT = '基于多智能体协作的英文视频本地化系统';
const index = new Map(schema.map(node => [node.id, node]));
const runnable = new Set(['translate_blocks', 'review_blocks']);
const elements = new Map();
const outputs = new Map();
let bTimeline = null;
let config = defaults();
let selected = 'translate_blocks';
let inspectorTab = 'params';
let camera = { x: 0, y: 0, scale: 0.85 };
let drag = null;
let active = null;
let returning = false;
let busy = false;
let history = [];
let future = [];
let toastTimer;
let minimapBounds;
let pendingAction;
let eventCount = 0;
let storageAvailable = true;

// Treat imported files and browser storage as untrusted input. Only known,
// typed fields enter the UI. Exported drafts never contain API credentials.
function validateDraft(data) {
  if (data?.format !== 'video-localizer-ui' || data.version !== 2 || !data.nodes ||
      Object.keys(data.nodes).length !== schema.length) throw new Error('文件不是受支持的 v2 工作流草稿。');
  const clean = defaults();
  for (const node of schema) {
    const record = data.nodes[node.id];
    if (!record || !record.params || typeof record.collapsed !== 'boolean' ||
        !Number.isFinite(record.x) || !Number.isFinite(record.y) ||
        Math.abs(record.x) > 10000 || Math.abs(record.y) > 10000) throw new Error(`${node.title}：节点位置或结构无效。`);
    const known = fieldsOf(node);
    if (Object.keys(record.params).some(key => !known.some(field => field.key === key))) throw new Error(`${node.title}：包含未知参数。`);
    for (const field of known) {
      const value = record.params[field.key];
      let valid;
      if (field.type === 'boolean') valid = typeof value === 'boolean';
      else if (field.type === 'number') valid = Number.isFinite(value) && value >= field.min && value <= field.max && Math.abs((value - field.min) / field.step - Math.round((value - field.min) / field.step)) < 0.000001;
      else if (field.type === 'select') valid = field.options.includes(value);
      else if (field.type === 'color') valid = typeof value === 'string' && /^#[a-fA-F0-9]{6}$/.test(value);
      else valid = typeof value === 'string' && value.length <= (field.maxLength || (field.type === 'textarea' ? 4000 : 500));
      if (!valid) throw new Error(`${node.title}：${field.label}的值无效。`);
      clean[node.id].params[field.key] = value;
    }
    clean[node.id].x = record.x;
    clean[node.id].y = record.y;
    clean[node.id].collapsed = record.collapsed;
  }
  checkRelations(clean);
  return clean;
}
function checkRelations(value) {
  if (value.asr_diarize.params.min_speakers > value.asr_diarize.params.max_speakers) throw new Error('最少说话人数不能大于最多说话人数。');
  if (value.build_blocks.params.target_seconds > value.build_blocks.params.max_seconds) throw new Error('目标块时长不能超过最长块时长。');
}
function envelope(nodes = config) {
  return { format: 'video-localizer-ui', version: 2, project: PROJECT, execution: 'configuration-draft', nodes };
}
function toast(message, error = false) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').classList.toggle('error', error);
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 4500);
}
function persist() {
  try {
    localStorage.setItem(STORAGE, JSON.stringify(envelope()));
    storageAvailable = true;
    $('save-status').textContent = `草稿已自动保存 · ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`;
  } catch {
    storageAvailable = false;
    $('save-status').textContent = '浏览器存储不可用，请导出 JSON 保存';
  }
}
function commit(previous) {
  if (JSON.stringify(previous) === JSON.stringify(config)) return;
  history.push(previous);
  if (history.length > 50) history.shift();
  future = [];
  persist();
  syncHistory();
}
function syncHistory() {
  $('undo').disabled = history.length === 0;
  $('redo').disabled = future.length === 0;
}
function undo(redo = false) {
  const from = redo ? future : history;
  const to = redo ? history : future;
  if (!from.length) return;
  to.push(structuredClone(config));
  config = from.pop();
  rebuild();
  persist();
  syncHistory();
}
try {
  const stored = localStorage.getItem(STORAGE);
  if (stored) {
    config = validateDraft(JSON.parse(stored));
    $('save-status').textContent = '已恢复此浏览器保存的工作流草稿';
  }
} catch {
  // Do not overwrite unreadable storage until the user makes a new change.
  toast('未能读取本地草稿，已载入默认配置。', true);
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
function control(node, field, quick = false) {
  const input = document.createElement(field.type === 'select' ? 'select' : field.type === 'textarea' ? 'textarea' : 'input');
  input.dataset.param = field.key;
  input.dataset.owner = node.id;
  input.setAttribute('aria-label', `${node.title} · ${field.label}`);
  if (field.type === 'select') {
    for (const option of field.options) input.append(new Option(option, option));
  } else if (field.type !== 'textarea') input.type = field.type === 'boolean' ? 'checkbox' : field.type;
  if (field.type === 'number') {
    input.min = field.min;
    input.max = field.max;
    input.step = field.step;
    input.required = true;
  }
  if (['text', 'textarea'].includes(field.type)) input.maxLength = field.maxLength || (field.type === 'textarea' ? 4000 : 500);
  if (field.placeholder) input.placeholder = field.placeholder;
  if (field.type === 'boolean') input.checked = config[node.id].params[field.key];
  else input.value = config[node.id].params[field.key];
  input.addEventListener('input', () => {
    input.setCustomValidity('');
    // Color controls update the CSS sample while the picker is open. Other
    // values commit on change, so typing a number doesn't create 4 undo steps.
    if (field.type === 'color') updateVisualPreview(node.id, field.key, input.value);
  });
  input.addEventListener('change', () => {
    if (!input.checkValidity()) {
      input.reportValidity();
      return;
    }
    const before = structuredClone(config);
    const value = field.type === 'boolean' ? input.checked : field.type === 'number' ? Number(input.value) : input.value;
    config[node.id].params[field.key] = value;
    try { checkRelations(config); } catch (error) {
      config = before;
      input.value = before[node.id].params[field.key];
      toast(error.message, true);
      return;
    }
    // Update mirrored quick / inspector controls without replacing the focused input.
    for (const other of document.querySelectorAll(`[data-owner="${node.id}"][data-param="${field.key}"]`)) {
      if (other !== input) {
        if (field.type === 'boolean') other.checked = value;
        else other.value = value;
      }
    }
    commit(before);
    if (quick && selected === node.id && inspectorTab === 'preview') renderInspector();
  });
  return input;
}
function updateVisualPreview(id, key, value) {
  if (id !== 'subtitle_cover' || selected !== id || inspectorTab !== 'preview') return;
  renderPreview({ ...config[id].params, [key]: value });
}
function renderNodes() {
  $('nodes').replaceChildren();
  elements.clear();
  for (const node of schema) {
    const card = el('article', 'node');
    card.dataset.node = node.id;
    card.style.setProperty('--lane', categories[node.category].color);
    card.setAttribute('aria-label', node.title);
    const header = el('div', 'node-header');
    header.tabIndex = 0;
    header.setAttribute('role', 'button');
    header.setAttribute('aria-label', `选择${node.title}`);
    const collapse = el('button', 'node-collapse', config[node.id].collapsed ? '+' : '−');
    collapse.setAttribute('aria-label', `折叠或展开${node.title}`);
    collapse.setAttribute('aria-expanded', String(!config[node.id].collapsed));
    collapse.addEventListener('click', event => {
      event.stopPropagation();
      const before = structuredClone(config);
      config[node.id].collapsed = !config[node.id].collapsed;
      commit(before);
      renderNodes();
      draw();
    });
    header.append(el('span', 'node-number', node.symbol), el('h3', 'node-title', node.title), collapse);
    header.addEventListener('click', () => selectNode(node.id));
    header.addEventListener('keydown', event => {
      if (event.target !== header) return;
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectNode(node.id); }
    });
    const ports = el('div', 'ports');
    ports.append(el('span', 'port', node.input[0]), el('span', 'port out', node.output[0]));
    const fields = el('div', 'node-fields');
    for (const key of node.quick) {
      const field = fieldsOf(node).find(field => field.key === key);
      const row = el('label', 'quick-field');
      row.append(el('span', '', field.label), control(node, field, true));
      fields.append(row);
    }
    const footer = el('div', 'node-footer');
    const state = el('span', 'node-state', outputs.has(node.id) ? '示例完成' : runnable.has(node.id) ? '可运行固定模拟' : '配置待接入');
    const details = el('button', '', `${fieldsOf(node).length} 项参数 ↗`);
    details.addEventListener('click', () => { inspectorTab = 'params'; selectNode(node.id); });
    footer.append(state, details);
    card.append(header, el('div', 'node-id', node.id), ports, fields, footer);
    card.addEventListener('focusin', () => { if (selected !== node.id) selectNode(node.id, false); });
    card.addEventListener('click', event => {
      if (!event.target.closest('button,.node-header') && selected !== node.id) selectNode(node.id, false);
    });
    $('nodes').append(card);
    elements.set(node.id, card);
  }
}
function renderLibrary() {
  const query = $('search').value.trim().toLowerCase();
  $('library-list').replaceChildren();
  let count = 0;
  for (const [category, meta] of Object.entries(categories)) {
    const section = el('div', 'library-group');
    section.style.setProperty('--lane', meta.color);
    const heading = el('div', 'group-title');
    heading.append(el('i'), document.createTextNode(meta.title));
    section.append(heading);
    for (const node of schema.filter(node => node.category === category && `${node.title} ${node.id} ${node.role}`.toLowerCase().includes(query))) {
      const button = el('button', 'library-item');
      button.classList.toggle('selected', selected === node.id);
      button.setAttribute('aria-pressed', String(selected === node.id));
      button.append(el('span', 'item-icon', node.symbol), el('span', '', node.title), el('span', 'item-role', node.role));
      button.addEventListener('click', () => {
        selectNode(node.id);
        focusNode();
        $('library-list').closest('.library').classList.remove('open');
      });
      section.append(button);
      count++;
    }
    if (section.children.length > 1) $('library-list').append(section);
  }
  if (!count) $('library-list').append(el('p', 'preview-caption', '没有匹配的节点。试试“字幕”或“tts”。'));
}
function selectNode(id, open = true) {
  const changed = selected !== id;
  selected = id;
  renderLibrary();
  renderInspector();
  if (changed) $('inspector-content').scrollTop = 0;
  if (open && matchMedia('(max-width:640px)').matches) document.querySelector('.inspector').classList.add('open');
  updateOutput();
  draw();
}
function renderInspector() {
  const node = index.get(selected);
  $('detail-name').textContent = node.title;
  $('detail-id').textContent = node.id;
  $('detail-role').textContent = `成员 ${node.role}`;
  $('detail-icon').textContent = node.symbol;
  $('detail-icon').style.setProperty('--lane', categories[node.category].color);
  $('field-count').textContent = `${fieldsOf(node).length} 个可配置参数`;
  const content = $('inspector-content');
  content.style.setProperty('--lane', categories[node.category].color);
  content.replaceChildren();
  for (const tab of document.querySelectorAll('[data-inspect-tab]')) tab.setAttribute('aria-selected', String(tab.dataset.inspectTab === inspectorTab));
  if (inspectorTab === 'preview') { renderPreview(); return; }
  if (inspectorTab === 'info') {
    content.append(el('p', 'info-description', node.description));
    for (const [name, ports] of [['输入', node.input], ['输出', node.output]]) {
      content.append(el('h3', 'preview-heading', name));
      for (const port of ports) {
        const row = el('div', 'io-row');
        row.append(el('i'), document.createTextNode(port));
        content.append(row);
      }
    }
    content.append(el('h3', 'preview-heading', '参数草稿'));
    content.append(el('pre', 'info-code', JSON.stringify(config[node.id].params, null, 2)));
    content.append(el('p', 'preview-caption', '节点依赖由项目设计固定。移动位置不会改变执行顺序；此版本不支持通过连线修改后端图。'));
    return;
  }
  const notice = el('p', 'connection-note');
  notice.append(el('span', 'status-dot'), document.createTextNode(node.id === 'subtitle_cover' ? '样式可在「预览」查看；渲染参数尚待后端接入。' : runnable.has(node.id) ? '可运行固定模拟。以下配置保存为草稿，尚未传入模型调用。' : '以下配置可编辑并保存为草稿，执行模块尚待接入。'));
  content.append(notice);
  for (const group of node.groups) {
    const fieldset = el('fieldset', 'param-group');
    fieldset.append(el('legend', '', group.title));
    for (const field of group.fields) {
      const label = el('label', `param-row${field.type === 'boolean' ? ' bool' : ''}`);
      const caption = el('span', 'param-label');
      caption.append(document.createTextNode(field.label));
      if (field.unit) caption.append(el('span', 'unit', field.unit));
      label.append(caption, control(node, field));
      if (field.help) label.append(el('small', '', field.help));
      fieldset.append(label);
    }
    content.append(fieldset);
  }
}
function renderPreview(values = config[selected].params) {
  const content = $('inspector-content');
  content.replaceChildren();
  if (selected === 'asr_diarize') {
    const picker = el('input');
    picker.type = 'file';
    picker.accept = '.json,application/json';
    picker.hidden = true;
    const open = el('button', '', bTimeline ? '更换 B 时间表' : '打开 B 时间表');
    open.onclick = () => picker.click();
    picker.onchange = () => readTimelinePreview(picker.files[0]);
    content.append(el('p', 'connection-note', '选择 B 任务导出的 timetable.json。文件在浏览器内读取，预览不运行识别模型。'), open, picker);
    if (bTimeline) {
      content.append(el('h3', 'preview-heading', `${bTimeline.sentence_count} 句 · ${bTimeline.duration_ms} ms · ${bTimeline.unknown_speakers} 句说话人待确认`));
      content.append(el('p', 'preview-caption', '展示前 20 句，时间为 B 输出的毫秒时间戳。'));
      content.append(el('pre', 'info-code', JSON.stringify(bTimeline.sentences, null, 2)));
    }
  } else if (selected === 'subtitle_cover') {
    content.append(el('p', 'connection-note', '浏览器样式预览 · 示例文案 · 非最终渲染结果'));
    const screen = el('div', 'subtitle-preview');
    const scale = 0.25;
    screen.style.paddingBottom = `${values.margin * scale}px`;
    screen.style.fontFamily = values.font === '系统宋体' ? '"Songti SC", serif' : 'inherit';
    const zh = el('div', 'subtitle-line', '让知识跨越语言');
    const en = el('div', 'subtitle-line', 'Let knowledge cross languages.');
    zh.style.fontSize = `${values.font_size * scale}px`;
    en.style.fontSize = `${values.en_size * scale}px`;
    for (const line of [zh, en]) {
      line.style.color = values.text_color;
      line.style.webkitTextStroke = `${values.outline * scale}px ${values.outline_color}`;
      line.style.paintOrder = 'stroke fill';
    }
    const ordered = values.order === '中文在上' ? [zh, en] : [en, zh];
    screen.append(...(values.bilingual ? ordered : [zh]));
    content.append(el('h3', 'preview-heading', '双语字幕 / 16:9'), screen, el('p', 'preview-caption', '按 1080p 样式比例示意。实际字体与断行以 FFmpeg / libass 输出为准。'));
    const cover = el('div', 'cover-preview');
    cover.style.background = values.cover_color;
    cover.style.textAlign = values.cover_layout === '居中标题' ? 'center' : 'left';
    cover.append(el('span', '', '英文视频 · 中文译制'), el('h3', '', values.cover_title), el('span', '', '知识分享 / 中文配音 / 双语字幕'));
    content.append(el('h3', 'preview-heading', '中文封面 / 模板草图'), cover, el('p', 'preview-caption', `${values.cover_size} · ${values.cover_format} · 当前为浏览器预览，尚未生成文件。`));
  } else if (outputs.has(selected)) {
    content.append(el('p', 'connection-note', '最近一次固定模拟输出，与当前草稿参数无关。'), el('pre', 'info-code', JSON.stringify(outputs.get(selected), null, 2)));
  } else {
    const empty = el('div', 'preview-empty');
    empty.append(el('strong', '', '尚无节点产物'), document.createTextNode(runnable.has(selected) ? '运行模拟示例后，可在这里查看实际返回的 JSON。' : '模块接入并运行后，这里将展示该节点生成的产物。'));
    content.append(empty);
    content.append(el('p', 'preview-caption', index.get(selected).description));
  }
}

async function readTimelinePreview(file) {
  if (!file) return;
  try {
    if (file.size > 16 * 1024 * 1024) throw new Error('时间表文件超过 16 MB。');
    const table = JSON.parse(await file.text());
    if (table?.schema_version !== 'b-sentences-2' || table.status !== 'ready_for_human_review' ||
        !Number.isSafeInteger(table.duration_ms) || table.duration_ms <= 0 ||
        !Array.isArray(table.sentences) || !table.sentences.length) {
      throw new Error('请选择已导出的 B sentence-v2 时间表。');
    }
    let previousEnd = 0;
    for (const row of table.sentences) {
      if (!row || typeof row.sentence_id !== 'string' || typeof row.en !== 'string' ||
          !Number.isSafeInteger(row.start_ms) || !Number.isSafeInteger(row.end_ms) ||
          row.start_ms < previousEnd || row.end_ms <= row.start_ms || row.end_ms > table.duration_ms ||
          (row.speaker_id !== null && typeof row.speaker_id !== 'string')) {
        throw new Error('时间表的句子或时间轴无效。');
      }
      previousEnd = row.end_ms;
    }
    bTimeline = {
      schema_version: table.schema_version,
      status: table.status,
      duration_ms: table.duration_ms,
      sentence_count: table.sentences.length,
      unknown_speakers: table.sentences.filter(row => row.speaker_id === null).length,
      sentences: table.sentences.slice(0, 20),
    };
    if (selected === 'asr_diarize' && inspectorTab === 'preview') renderInspector();
    updateOutput();
    draw();
    toast('B 时间表已载入预览。');
  } catch (error) { toast(`读取失败：${error.message}`, true); }
}

function renderFrames() {
  $('frames').replaceChildren();
  for (const [x, title, subtitle] of [[16, '素材与理解', '01'], [406, '语言协作', '02'], [796, '声音与视觉', '03'], [1186, '合成与交付', '04']]) {
    const frame = el('div', 'frame');
    Object.assign(frame.style, { left: `${x}px`, top: '55px', width: '330px', height: '1150px' });
    const label = el('div', 'frame-label');
    label.append(el('span', '', subtitle), document.createTextNode(title));
    frame.append(label);
    $('frames').append(frame);
  }
}
const paths = edges.map(([from, to, type]) => {
  const path = svg('path', { class: type ? 'link rework' : 'link' });
  $('links').append(path);
  return { from, to, type, path };
});
function nodeHeight(id) { return elements.get(id)?.offsetHeight || 290; }
function draw() {
  $('world').style.transform = `translate(${camera.x}px,${camera.y}px) scale(${camera.scale})`;
  $('zoom').textContent = `${Math.round(camera.scale * 100)}%`;
  $('canvas').style.backgroundSize = `${20 * camera.scale}px ${20 * camera.scale}px`;
  $('canvas').style.backgroundPosition = `${camera.x}px ${camera.y}px`;
  for (const node of schema) {
    const item = elements.get(node.id);
    if (!item) continue;
    item.style.left = `${config[node.id].x}px`;
    item.style.top = `${config[node.id].y}px`;
    item.classList.toggle('selected', selected === node.id);
    item.classList.toggle('collapsed', config[node.id].collapsed);
    item.classList.toggle('is-active', active === node.id);
    const output = outputs.get(node.id);
    item.classList.toggle('is-done', !!output && !output.issue);
    item.classList.toggle('is-returned', !!output?.issue);
    item.querySelector('.node-state').textContent = node.id === 'asr_diarize' && bTimeline ? '已载入 B 时间表' : active === node.id ? '回放节点更新…' : output?.issue ? '审校退回' : output ? '模拟完成' : runnable.has(node.id) ? '可运行固定模拟' : '配置待接入';
  }
  for (const { from, to, type, path } of paths) {
    const a = config[from], b = config[to];
    const sx = a.x + 282, sy = a.y + (a.collapsed ? 22 : 87);
    const ex = b.x, ey = b.y + (b.collapsed ? 22 : 87);
    let d;
    if (type) {
      const right = Math.max(sx, ex + 282) + 47;
      d = `M${sx},${sy} C${right},${sy} ${right},${b.y - 30} ${ex + 141},${b.y - 30} L${ex + 141},${b.y}`;
    } else if (Math.abs(a.x - b.x) < 100) {
      // Route vertical-column dependencies around the cards instead of through them.
      const rail = Math.min(a.x, b.x) - 29;
      const middleY = a.y + nodeHeight(from) + 28;
      d = `M${sx},${sy} C${sx + 28},${sy} ${sx + 28},${middleY} ${sx},${middleY} L${rail},${middleY} C${rail - 15},${middleY} ${rail - 15},${ey} ${ex},${ey}`;
    } else {
      const distance = Math.max(46, Math.abs(ex - sx) * 0.48);
      d = `M${sx},${sy} C${sx + distance},${sy} ${ex - distance},${ey} ${ex},${ey}`;
    }
    path.setAttribute('d', d);
    path.style.stroke = type ? '' : categories[index.get(from).category].color;
    path.classList.toggle('highlight', type ? returning : (from === selected || to === selected));
  }
  drawMinimap();
}
function bounds() {
  return {
    left: Math.min(...schema.map(n => config[n.id].x)) - 60,
    top: Math.min(...schema.map(n => config[n.id].y)) - 65,
    right: Math.max(...schema.map(n => config[n.id].x + 282)) + 60,
    bottom: Math.max(...schema.map(n => config[n.id].y + nodeHeight(n.id))) + 40,
  };
}
function drawMinimap() {
  const box = bounds();
  const scale = Math.min(188 / (box.right - box.left), 128 / (box.bottom - box.top));
  minimapBounds = { ...box, scale };
  const map = $('minimap');
  map.replaceChildren();
  for (const node of schema) {
    const item = config[node.id];
    map.append(svg('rect', { x: 6 + (item.x - box.left) * scale, y: 6 + (item.y - box.top) * scale, width: 282 * scale, height: nodeHeight(node.id) * scale, rx: 2, fill: categories[node.category].color, opacity: selected === node.id ? 0.9 : 0.4 }));
  }
  map.append(svg('rect', { x: 6 + (-camera.x / camera.scale - box.left) * scale, y: 6 + (-camera.y / camera.scale - box.top) * scale, width: $('canvas').clientWidth / camera.scale * scale, height: $('canvas').clientHeight / camera.scale * scale, fill: '#a6c7e31a', stroke: '#c3d3df', 'stroke-width': 1 }));
}
function fit() {
  const box = bounds(), width = $('canvas').clientWidth, height = $('canvas').clientHeight;
  camera.scale = Math.min(1, (width - 48) / (box.right - box.left), (height - 95) / (box.bottom - box.top));
  camera.x = (width - (box.right + box.left) * camera.scale) / 2;
  camera.y = (height - (box.bottom + box.top) * camera.scale) / 2 + 8;
  draw();
}
function focusNode() {
  camera.scale = Math.min(1, ($('canvas').clientWidth - 54) / 282, ($('canvas').clientHeight - 110) / nodeHeight(selected));
  camera.scale = Math.max(0.3, camera.scale);
  camera.x = $('canvas').clientWidth / 2 - (config[selected].x + 141) * camera.scale;
  camera.y = $('canvas').clientHeight / 2 - (config[selected].y + nodeHeight(selected) / 2) * camera.scale;
  draw();
}
function zoomBy(factor, x = $('canvas').clientWidth / 2, y = $('canvas').clientHeight / 2) {
  const scale = Math.min(1.8, Math.max(0.15, camera.scale * factor));
  const ratio = scale / camera.scale;
  camera = { x: x - (x - camera.x) * ratio, y: y - (y - camera.y) * ratio, scale };
  draw();
}
function rebuild() { renderNodes(); renderLibrary(); renderInspector(); draw(); }

$('canvas').addEventListener('pointerdown', event => {
  if (event.button !== 0 || event.target.closest('input,select,textarea,button,.viewport-controls,.minimap-wrap')) return;
  const card = event.target.closest('.node');
  if (card && !event.target.closest('.node-header')) return;
  const node = card?.dataset.node;
  if (node) selectNode(node, false);
  $('canvas').setPointerCapture(event.pointerId);
  drag = { pointer: event.pointerId, node, x: event.clientX, y: event.clientY, before: node ? structuredClone(config) : null };
  $('canvas').classList.add('dragging');
});
$('canvas').addEventListener('pointermove', event => {
  if (drag?.pointer !== event.pointerId) return;
  const dx = event.clientX - drag.x, dy = event.clientY - drag.y;
  if (drag.node) {
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
    if (drag.node) commit(drag.before);
    drag = null;
    $('canvas').classList.remove('dragging');
  });
}
$('canvas').addEventListener('wheel', event => {
  // Keep wheel input out of focused number fields to avoid accidental value edits.
  if (event.target.closest('input,select,textarea')) { event.preventDefault(); return; }
  event.preventDefault();
  const rect = $('canvas').getBoundingClientRect();
  zoomBy(Math.exp(-event.deltaY * 0.0015), event.clientX - rect.left, event.clientY - rect.top);
}, { passive: false });
$('minimap').addEventListener('pointerdown', event => {
  event.stopPropagation();
  const rect = $('minimap').getBoundingClientRect(), b = minimapBounds;
  const x = ((event.clientX - rect.left) / rect.width * 200 - 6) / b.scale + b.left;
  const y = ((event.clientY - rect.top) / rect.height * 140 - 6) / b.scale + b.top;
  camera.x = $('canvas').clientWidth / 2 - x * camera.scale;
  camera.y = $('canvas').clientHeight / 2 - y * camera.scale;
  draw();
});
$('zoom-in').onclick = () => zoomBy(1.2);
$('zoom-out').onclick = () => zoomBy(1 / 1.2);
$('zoom').onclick = () => zoomBy(1 / camera.scale);
$('fit').onclick = fit;
$('focus').onclick = focusNode;
$('layout').onclick = () => {
  const before = structuredClone(config);
  for (const node of schema) Object.assign(config[node.id], { x: node.x, y: node.y });
  commit(before);
  fit();
  toast('已恢复默认节点布局，参数保持不变。');
};
$('fullscreen').onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.documentElement.requestFullscreen();
  } catch { toast('此浏览器不支持全屏，请使用浏览器的全屏菜单。', true); }
};
$('undo').onclick = () => undo();
$('redo').onclick = () => undo(true);
$('search').oninput = renderLibrary;
$('library-toggle').onclick = () => document.querySelector('.library').classList.toggle('open');
$('inspector-close').onclick = () => document.querySelector('.inspector').classList.remove('open');
for (const button of document.querySelectorAll('[data-inspect-tab]')) {
  button.onclick = () => { inspectorTab = button.dataset.inspectTab; renderInspector(); };
}
function confirm(title, message, action, label = '确认') {
  pendingAction = action;
  $('dialog-title').textContent = title;
  $('dialog-body').textContent = message;
  $('dialog-confirm').textContent = label;
  $('dialog').returnValue = '';
  $('dialog').showModal();
}
$('dialog').addEventListener('close', () => {
  if ($('dialog').returnValue === 'confirm') pendingAction?.();
  pendingAction = null;
});
$('reset-node').onclick = () => {
  const id = selected;
  confirm('重置节点参数', `将「${index.get(id).title}」恢复为默认参数，保留节点位置。可以撤销。`, () => {
    const before = structuredClone(config);
    config[id].params = defaults()[id].params;
    commit(before);
    rebuild();
    toast('已重置节点参数。');
  }, '重置参数');
};
$('apply-preset').onclick = () => {
  const preset = $('preset').value;
  confirm('应用工作流模板', '将替换所有节点的参数草稿，保留现有位置和折叠状态。可以撤销。', () => {
    const before = structuredClone(config), fresh = defaults();
    for (const node of schema) config[node.id].params = fresh[node.id].params;
    if (preset === 'interview') {
      Object.assign(config.asr_diarize.params, { min_speakers: 2, max_speakers: 2 });
      Object.assign(config.build_blocks.params, { target_seconds: 60 });
      config.translate_blocks.params.style = '轻松对话';
      config.edit_assets.params.tone = '轻松友好';
    } else if (preset === 'quick') {
      Object.assign(config.asr_diarize.params, { model: 'base.en', beam_size: 1, diarization: false });
      config.compose_video.params.preset = 'ultrafast';
      config.compose_video.params.crf = 26;
    }
    commit(before);
    rebuild();
    toast('已应用参数模板。运行模块尚待接入。');
  }, '应用模板');
};
$('save').onclick = () => { persist(); toast(storageAvailable ? '已保存到当前浏览器。可导出 JSON 与组员共享。' : '本地存储不可用，请导出 JSON。', !storageAvailable); };
function download(data, filename) {
  const url = URL.createObjectURL(new Blob([data], { type: 'application/json' }));
  const anchor = el('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('export').onclick = () => {
  download(JSON.stringify(envelope(), null, 2), 'localizer-workflow.json');
  toast('已导出工作流草稿。此文件不包含 API 密钥或运行产物。');
};
$('import').onclick = () => $('import-file').click();
$('import-file').onchange = async event => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file) return;
  try {
    if (file.size > 1024 * 1024) throw new Error('配置文件不能超过 1 MB。');
    const imported = validateDraft(JSON.parse(await file.text()));
    confirm('导入工作流草稿', `已验证 ${schema.length} 个节点。导入将替换当前参数和布局，可以撤销。`, () => {
      const before = structuredClone(config);
      config = imported;
      commit(before);
      rebuild();
      fit();
      toast('工作流草稿已导入。');
    }, '导入草稿');
  } catch (error) { toast(`导入失败：${error.message}`, true); }
};
$('help').onclick = () => confirm('画布操作', '拖动节点标题：移动节点\n拖动画布空白处：平移视图\n滚轮 / + −：以鼠标为中心缩放\nF：总览全部节点；1：定位选中节点\n/：搜索节点\nCtrl / ⌘ S：保存草稿\nCtrl / ⌘ Z：撤销；Shift Z：重做\n\n连线反映固定工作流依赖，不能拖拽重连。参数可编辑、保存和分享；模拟运行仍使用固定样例。', null, '知道了');
function setConsoleTab(output) {
  $('log-tab').setAttribute('aria-selected', String(!output));
  $('output-tab').setAttribute('aria-selected', String(output));
  $('log-panel').hidden = output;
  $('output-panel').hidden = !output;
}
$('log-tab').onclick = () => setConsoleTab(false);
$('output-tab').onclick = () => setConsoleTab(true);
$('console-toggle').onclick = () => {
  const collapsed = $('console').classList.toggle('collapsed');
  $('console-toggle').textContent = collapsed ? '⌃' : '⌄';
  $('console-toggle').setAttribute('aria-expanded', String(!collapsed));
  $('console-toggle').setAttribute('aria-label', collapsed ? '展开运行面板' : '收起运行面板');
  draw();
};
function clearLog() {
  $('events').replaceChildren();
  eventCount = 0;
  $('event-count').textContent = '0';
}
$('clear-log').onclick = () => {
  clearLog();
  outputs.clear();
  updateOutput();
  renderInspector();
  draw();
  $('run-status').textContent = '记录已清空';
};
function appendEvent(label, message, warning = false) {
  const item = el('li');
  item.append(el('time', '', new Date().toLocaleTimeString('zh-CN', { hour12: false })), el('span', `log-label${warning ? ' log-warning' : ''}`, label), el('span', '', message));
  $('events').append(item);
  $('event-count').textContent = String(++eventCount);
  $('log-panel').scrollTop = $('log-panel').scrollHeight;
}
function updateOutput() {
  if (selected === 'asr_diarize' && bTimeline) {
    $('console-output').textContent = JSON.stringify({ node: selected, source: 'imported-b-timetable-preview', output: bTimeline }, null, 2);
    return;
  }
  $('console-output').textContent = outputs.has(selected) ? JSON.stringify({ node: selected, source: 'fixed-mock-demo', output: outputs.get(selected) }, null, 2) : `${index.get(selected).title}尚无运行输出。`;
}
$('run').onclick = async () => {
  if (busy) return;
  busy = true;
  $('run').disabled = true;
  $('clear-log').disabled = true;
  $('run-status').textContent = '请求本地模拟…';
  $('console').classList.remove('collapsed');
  $('console-toggle').setAttribute('aria-expanded', 'true');
  $('console-toggle').textContent = '⌄';
  setConsoleTab(false);
  clearLog();
  outputs.clear();
  returning = false;
  renderInspector();
  updateOutput();
  draw();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await fetch('/api/demo', { method: 'POST', signal: controller.signal });
    if (!response.ok) throw new Error(`服务返回 HTTP ${response.status}`);
    const result = await response.json();
    if (!Array.isArray(result.events) || !result.events.length || result.events.some(event => !runnable.has(event.node) || !event.data)) throw new Error('服务返回的节点更新格式不正确');
    clearTimeout(timeout);
    appendEvent('固定样例', result.sample.en);
    $('run-status').textContent = '回放实际节点更新…';
    for (const { node, data } of result.events) {
      active = node;
      draw();
      if (!matchMedia('(prefers-reduced-motion: reduce)').matches) await new Promise(resolve => setTimeout(resolve, 550));
      outputs.set(node, data);
      returning = Boolean(data.issue);
      appendEvent(node === 'translate_blocks' ? `翻译 #${data.attempts}` : data.issue ? '审校退回' : '审校通过', node === 'translate_blocks' ? data.draft.zh_subtitle : data.issue || '未发现错漏译，固定示例结束。', !!data.issue);
      if (selected === node && inspectorTab === 'preview') renderInspector();
      updateOutput();
    }
    $('run-status').textContent = '模拟完成 · 4 次节点更新';
    toast('固定模拟完成。真实视频译制与参数执行尚待接入。');
  } catch (error) {
    $('run-status').textContent = '模拟失败';
    appendEvent('请求失败', error.name === 'AbortError' ? '请求超过 30 秒，请检查本地服务后重试。' : `${error.message}。请检查本地服务后重试。`, true);
  } finally {
    clearTimeout(timeout);
    busy = false;
    active = null;
    returning = false;
    $('run').disabled = false;
    $('clear-log').disabled = false;
    draw();
  }
};
document.addEventListener('keydown', event => {
  const typing = event.target.closest('input,select,textarea,[contenteditable=true]');
  if ($('dialog').open) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); $('save').click(); }
  if (typing) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); undo(event.shiftKey); }
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.key.toLowerCase() === 'f') { event.preventDefault(); fit(); }
  if (event.key === '1') focusNode();
  if (event.key === '/') { event.preventDefault(); document.querySelector('.library').classList.add('open'); $('search').focus(); }
  if (event.key === 'Escape') { document.querySelector('.library').classList.remove('open'); document.querySelector('.inspector').classList.remove('open'); }
});
// Arrow keys follow tablist conventions, including the narrow-screen layout.
for (const tablist of document.querySelectorAll('[role=tablist]')) {
  tablist.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tabs = [...tablist.querySelectorAll('[role=tab]')];
    const current = tabs.indexOf(document.activeElement);
    if (current < 0) return;
    event.preventDefault();
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    tabs[next].focus();
    tabs[next].click();
  });
}
renderFrames();
rebuild();
syncHistory();
// Start at a useful reading size. Overview and minimap expose the complete graph.
camera = { scale: 0.85, x: 20, y: 15 };
if (matchMedia('(max-width:640px)').matches) focusNode();
else draw();
new ResizeObserver(draw).observe($('canvas'));
