import { getReviewView, openSubtitleReview, refreshSubtitleReview, restoreReviewView, setPreviewInput, setPreviewJob } from './subtitle-review.js';
import { refreshTasks, setTaskProject } from './task-queue.js';
import { schema, categories, edges, fieldsOf, defaults, arrangeLegacyNodes, subtitleCatalog } from './node-schema.js';

const $ = id => document.getElementById(id);
const themeChoices = [...document.querySelectorAll('[data-theme-choice]')];
function syncThemeChoices() {
  const theme = document.documentElement.dataset.theme ?? 'dark';
  for (const button of themeChoices) {
    button.setAttribute('aria-pressed', String(button.dataset.themeChoice === theme));
  }
}
for (const button of themeChoices) {
  button.onclick = () => {
    const theme = button.dataset.themeChoice;
    document.documentElement.dataset.theme = theme;
    syncThemeChoices();
    try { localStorage.setItem('video-localizer.theme', theme); }
    catch { /* The palette still changes for this page. */ }
  };
}
syncThemeChoices();

const NS = 'http://www.w3.org/2000/svg';
const STORAGE = 'video-localizer.project.v4';
const SESSION = 'video-localizer.open-projects.v1';
const PROJECT_FILE_LIMIT = 1024 * 1024;
const projectFileTypes = [{ description: '工程文件', accept: { 'application/json': ['.json'] } }];
const LEGACY_STORAGE = ['video-localizer.project.v3', 'video-localizer.workflow.v2'];
const ID = /^[a-f0-9]{32}$/;
const DEFAULT_CAMERA = { x: 23, y: 11, scale: 0.86 };
const PROJECT = '基于多智能体协作的英文视频本地化系统';
const index = new Map(schema.map(node => [node.id, node]));
const connected = new Set(['probe_input', 'asr_diarize']);
const narrowScreen = matchMedia('(max-width:640px)');
const MAX_ANCHORS = 16;
const edgeKey = (from, to) => `${from}:${to}`;
const edgeKeys = new Set(edges.map(([from, to]) => edgeKey(from, to)));
const SIZE_LIMITS = { width: [220, 680], height: [155, 1440] };
const replacedVideoFields = new Set(['source_type', 'source']);
const elements = new Map();
let runResult = null;
let inputVideo = null;
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
let pendingAction;
let eventCount = 0;
let projectId = null;
let viewSaveTimer = null;
let pickerRequest = 0;
const projects = new Map();
const openIds = new Set();
const newId = () => crypto.randomUUID().replaceAll('-', '');
const projectName = (name, fallback = '未命名工程') =>
  (typeof name === 'string' ? name.trim().slice(0, 80) : '') || fallback;

const LEGACY_IDS = schema.filter(node => node.id !== 'cover_localize')
  .map(node => node.id === 'subtitle_render' ? 'subtitle_cover' : node.id);
const LEGACY_EDGES = [
  ['probe_input', 'asr_diarize'], ['asr_diarize', 'build_blocks'],
  ['build_blocks', 'translate_blocks'], ['translate_blocks', 'review_blocks'],
  ['review_blocks', 'tts_align'], ['review_blocks', 'edit_assets'],
  ['review_blocks', 'subtitle_cover'], ['edit_assets', 'subtitle_cover'],
  ['tts_align', 'compose_video'], ['subtitle_cover', 'compose_video'],
  ['compose_video', 'collect_manifest'], ['collect_manifest', 'package_zip'],
  ['review_blocks', 'translate_blocks', 'demo'],
];

const LEGACY_SUBTITLE_FIELDS = new Set([
  'order', 'font', 'font_size', 'en_size', 'text_color', 'outline_color',
  'outline', 'margin', 'max_chars', 'bilingual',
]);

function splitLegacyNodes(nodes, defaultsById) {
  if (Object.keys(nodes).length !== LEGACY_IDS.length || LEGACY_IDS.some(id => !nodes[id])) {
    throw new Error('旧项目的节点不完整。');
  }
  const { subtitle_cover: merged, ...other } = nodes;
  const subtitleKeys = new Set([...LEGACY_SUBTITLE_FIELDS, ...Object.keys(defaultsById.subtitle_render.params)]);
  const coverKeys = new Set(Object.keys(defaultsById.cover_localize.params));
  if (!merged.params || Object.keys(merged.params).some(key => !subtitleKeys.has(key) && !coverKeys.has(key))) {
    throw new Error('旧项目的字幕与封面节点包含未知参数。');
  }
  const pick = keys => Object.fromEntries(Object.entries(merged.params).filter(([key]) => keys.has(key)));
  return {
    ...other,
    subtitle_render: { ...merged, params: pick(subtitleKeys) },
    cover_localize: {
      ...defaultsById.cover_localize,
      params: { ...defaultsById.cover_localize.params, ...pick(coverKeys) },
    },
  };
}

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

// Treat imported files and browser storage as untrusted input. Only known,
// typed fields enter the UI. Exported drafts never contain API credentials.
function validateDraft(data) {
  if (data?.format !== 'video-localizer-ui' || ![2, 3, 4].includes(data.version) || !data.nodes) {
    throw new Error('文件不是受支持的项目 JSON。');
  }
  if (data.version >= 3 && (!ID.test(data.id)
      || JSON.stringify(data.edges) !== JSON.stringify(data.version === 3 ? LEGACY_EDGES : edges))) {
    throw new Error('项目 ID 或节点连线与工作流版本不匹配。');
  }
  const clean = defaults();
  const nodes = data.version < 4 ? splitLegacyNodes(data.nodes, clean) : data.nodes;
  if (Object.keys(nodes).length !== schema.length) throw new Error('项目的节点不完整。');
  for (const node of schema) {
    const record = nodes[node.id];
    if (!record || !record.params || typeof record.collapsed !== 'boolean' ||
        !Number.isFinite(record.x) || !Number.isFinite(record.y) ||
        Math.abs(record.x) > 10000 || Math.abs(record.y) > 10000) throw new Error(`${node.title}：节点位置或结构无效。`);
    const known = fieldsOf(node);
    let params = record.params;
    if (node.id === 'subtitle_render' && Object.keys(params).some(key => LEGACY_SUBTITLE_FIELDS.has(key))) {
      const { bilingual, order } = params;
      params = {
        style: subtitleCatalog.default_style,
        layout: bilingual === false ? 'zh_only' : order === '英文在上' ? 'zh_bottom' : 'zh_top',
        ...Object.fromEntries(Object.entries(params).filter(([key]) => !LEGACY_SUBTITLE_FIELDS.has(key))),
      };
    }
    if (Object.keys(params).some(key => !known.some(field => field.key === key))) throw new Error(`${node.title}：包含未知参数。`);
    for (const field of known) {
      const value = params[field.key];
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
    for (const [dimension, limits] of Object.entries(SIZE_LIMITS)) {
      const value = record[dimension];
      if (value === undefined || (dimension === 'height' && value === null)) continue;
      if (!Number.isFinite(value) || value < limits[0] || value > limits[1]) {
        throw new Error(`${node.title}：节点尺寸超出允许范围。`);
      }
      clean[node.id][dimension] = value;
    }
  }
  checkRelations(clean);
  const view = data.version >= 3 ? validateView(data.view) : null;
  const oldMatrix = [[40, 80], [40, 480], [40, 880], [430, 80], [430, 480],
    [820, 80], [430, 880], [820, 880], [1210, 80], [1210, 480], [1210, 880]];
  const oldBranches = [[40, 162], [394, 136], [748, 162], [1102, 124], [1456, 162],
    [1810, 44], [1810, 464, 850], [2164, 350], [2164, 730, 1030],
    [2518, 163], [2872, 137], [3226, 162]];
  // Upgrade known default layouts without resetting manually arranged projects.
  const legacyDefault = data.version < 4 && LEGACY_IDS.every((id, i) =>
    data.nodes[id].x === oldMatrix[i][0] && data.nodes[id].y === oldMatrix[i][1]);
  const branchedDefault = data.version === 4 && schema.every(({ id }, i) => {
    const [x, ...ys] = oldBranches[i];
    return clean[id].x === x && ys.includes(clean[id].y);
  });
  if (legacyDefault || branchedDefault) {
    const previous = view && { ...clean[view.selected] };
    arrangeLegacyNodes(clean);
    if (view) {
      view.camera.x += (previous.x - clean[view.selected].x) * view.camera.scale;
      view.camera.y += (previous.y - clean[view.selected].y) * view.camera.scale;
    }
  }
  return { nodes: clean, anchors: validateAnchors(data.anchors ?? {}), view };
}

function validateView(view) {
  const c = view?.camera;
  const validCamera = c && [c.x, c.y, c.scale].every(Number.isFinite)
    && Math.abs(c.x) <= 100000 && Math.abs(c.y) <= 100000 && c.scale >= 0.08 && c.scale <= 1.8;
  const review = view?.review;
  return {
    camera: validCamera ? { x: c.x, y: c.y, scale: c.scale } : { ...DEFAULT_CAMERA },
    selected: view?.selected === 'subtitle_cover' ? 'subtitle_render' :
      index.has(view?.selected) ? view.selected : 'probe_input',
    consoleCollapsed: view?.consoleCollapsed === true,
    consoleTab: view?.consoleTab === 'output' ? 'output' : 'log',
    review: {
      tab: review?.tab === 'subtitles' ? 'subtitles' : 'workflow',
      stage: ['initial', 'segmented', 'draft', 'final'].includes(review?.stage) ? review.stage : 'initial',
      follow: review?.follow !== false,
      jobId: ID.test(review?.jobId) ? review.jobId : null,
    },
  };
}
function checkRelations(value) {
  if (value.asr_diarize.params.min_speakers > value.asr_diarize.params.max_speakers) throw new Error('最少说话人数不能大于最多说话人数。');
  if (value.build_blocks.params.target_seconds > value.build_blocks.params.max_seconds) throw new Error('目标块时长不能超过最长块时长。');
}
function envelope() {
  return {
    format: 'video-localizer-ui', version: 4, id: projectId, project: PROJECT,
    name: projects.get(projectId).name,
    nodes: config, edges, anchors,
    view: {
      camera, selected,
      consoleCollapsed: $('console').classList.contains('collapsed'),
      consoleTab: $('output-tab').getAttribute('aria-selected') === 'true' ? 'output' : 'log',
      review: getReviewView(),
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
function reportSave(project, message) {
  project.status = message;
  if (project.id === projectId) $('save-status').textContent = message;
}

function reportBackup(project, saved) {
  const { fileLink } = project;
  if (fileLink) {
    const label = fileLink.snapshot === project.serialized ? '已保存到' : '有改动待保存到';
    reportSave(project, `${label} ${fileLink.handle.name}`);
  } else {
    reportSave(project, saved ? '草稿已备份 · 按 Ctrl / ⌘ S 选择保存位置' : '正在备份草稿…');
  }
}

// The browser keeps the handle and its last known file contents on this origin.
function projectFileLink(id, link) {
  return new Promise(resolve => {
    let request;
    try { request = indexedDB.open('video-localizer-files', 1); }
    catch { resolve(null); return; }
    request.onupgradeneeded = () => request.result.createObjectStore('links');
    request.onerror = request.onblocked = () => resolve(null);
    request.onsuccess = () => {
      const db = request.result;
      try {
        const transaction = db.transaction('links', link ? 'readwrite' : 'readonly');
        const store = transaction.objectStore('links');
        const keys = id === undefined ? store.getAllKeys() : null;
        const operation = keys ? store.getAll() : link ? store.put(link, id) : store.get(id);
        transaction.oncomplete = () => {
          db.close();
          if (keys) resolve(operation.result.map((entry, index) => ({ ...entry, id: keys.result[index] })));
          else resolve(operation.result ?? null);
        };
        transaction.onabort = () => { db.close(); resolve(null); };
      } catch {
        db.close();
        resolve(null);
      }
    };
  });
}

async function readProjectFile(file) {
  if (file.size > PROJECT_FILE_LIMIT) throw new Error('工程文件不能超过 1 MB。');
  const source = await file.text();
  return { source, data: JSON.parse(source.replace(/^\uFEFF/, '')) };
}

function downloadProject(project, contents) {
  const link = el('a');
  const url = URL.createObjectURL(new Blob([contents], { type: 'application/json' }));
  link.href = url;
  link.download = `${project.name}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast('已下载工程副本。');
}

async function saveProject(saveAs = false) {
  if (!projectId) return;
  const project = projects.get(projectId);
  if (project.fileSaving) return;
  const focused = document.activeElement;
  if (focused?.matches('[data-param]')) {
    if (!focused.reportValidity()) return;
    focused.blur();
  }
  persist(true);
  if (!window.showSaveFilePicker) {
    downloadProject(project, project.serialized);
    return;
  }

  project.fileSaving = true;
  try {
    const previous = saveAs ? null : project.fileLink;
    const handle = previous?.handle ?? await window.showSaveFilePicker({
      suggestedName: `${project.name.replace(/[<>:"/\\|?*]/g, '_')}.json`,
      types: projectFileTypes,
    });
    if (previous) {
      const permission = await handle.requestPermission({ mode: 'readwrite' });
      if (permission !== 'granted') throw new Error('写入权限未授予，可再次保存或另存为。');
      const current = await readProjectFile(await handle.getFile());
      if (current.source !== previous.source) throw new Error('工程文件已在外部修改，请另存为，或关闭标签后重新打开文件。');
    }
    if (project.id === projectId) persist();
    const saved = JSON.parse(project.serialized);
    if (project.name === '未命名工程') saved.name = projectName(handle.name.replace(/\.json$/i, ''));
    const snapshot = JSON.stringify(saved);
    const source = JSON.stringify(saved, null, 2) + '\n';
    const writer = await handle.createWritable();
    try {
      await writer.write(source);
      await writer.close();
    } catch (error) {
      await writer.abort().catch(() => {});
      throw error;
    }
    project.fileLink = { handle, source, snapshot, name: saved.name, lastOpened: project.lastOpened };
    if (saved.name !== project.name) {
      project.name = saved.name;
      if (project.id === projectId) {
        persist();
        renderProjectTabs();
      } else {
        project.data.name = saved.name;
      }
    }
    await projectFileLink(project.id, project.fileLink);
    reportBackup(project, true);
    toast(`已保存 ${handle.name}`);
  } catch (error) {
    if (error.name !== 'AbortError') toast(`保存失败：${error.message}`, true);
  } finally {
    project.fileSaving = false;
  }
}

async function saveToDisk(project) {
  clearTimeout(project.timer);
  if (project.saving || !project.pending) return;
  const data = project.pending;
  project.pending = null;
  project.saving = true;
  try {
    const response = await fetch(`/api/projects/${project.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: data,
    });
    if (!response.ok) throw new Error('无法保存工程文件');
    if (!project.pending) reportBackup(project, true);
  } catch {
    if (project.fileLink) reportBackup(project, false);
    else reportSave(project, project.backedUp
      ? '草稿已备份到浏览器 · 按 Ctrl / ⌘ S 选择保存位置'
      : '草稿备份失败 · 请保存到工程文件');
  } finally {
    project.saving = false;
    if (project.pending) void saveToDisk(project);
  }
}

function persist(immediate = false, updateMirror = false) {
  if (!projectId) return;
  const project = projects.get(projectId);
  const data = JSON.stringify(envelope());
  const changed = data !== project.serialized;
  if (changed) {
    project.data = JSON.parse(data);
    project.serialized = data;
    project.pending = data;
    reportBackup(project, false);
  }
  if (changed || updateMirror) {
    try {
      localStorage.setItem(STORAGE, data);
      if (changed) localStorage.setItem(`${STORAGE}.${project.id}`, data);
      project.backedUp = true;
    } catch {
      project.backedUp = false;
    }
  }
  if (immediate) {
    project.pending ??= data;
    void saveToDisk(project);
  } else if (project.pending) {
    clearTimeout(project.timer);
    project.timer = setTimeout(() => void saveToDisk(project), 400);
  }
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
async function recentProjectEntries() {
  const stored = await projectFileLink() ?? [];
  const entries = new Map(stored.map(link => [link.id, link]));
  for (const { id, fileLink } of projects.values()) {
    if (fileLink?.handle) entries.set(id, fileLink);
  }
  return [...entries].filter(([id, link]) => ID.test(id) && link.handle)
    .sort(([, a], [, b]) => (b.lastOpened ?? 0) - (a.lastOpened ?? 0))
    .map(([id, link]) => ({ id, name: projectName(link.name, link.handle.name.replace(/\.json$/i, '')) }));
}

function markProjectOpened(id) {
  const project = projects.get(id);
  project.lastOpened = Date.now();
  if (!project.fileLink) return;
  project.fileLink.lastOpened = project.lastOpened;
  project.fileLink.name = project.name;
  // Activation records a newly opened file after normalizing its snapshot.
  if (project.fileLink.snapshot !== null) void projectFileLink(id, project.fileLink);
}

function readStored(storage, key) {
  try { return JSON.parse(storage.getItem(key) || 'null'); } catch { return null; }
}

function rememberSession() {
  try { sessionStorage.setItem(SESSION, JSON.stringify({ active: projectId, ids: [...openIds] })); }
  catch { /* In-memory tabs still work. */ }
  globalThis.history.replaceState(null, '', projectId ? `#project=${projectId}` : location.pathname + location.search);
}

function addProject(data, fallbackName, fileLink = null, replace = false) {
  const parsed = data ? validateDraft(data) : { nodes: defaults(), anchors: {}, view: null };
  const id = data?.version >= 3 ? data.id : newId();
  if (!projects.has(id) || replace) {
    const project = projects.get(id) ?? { id };
    Object.assign(project, {
      name: projectName(data?.name, fallbackName), data: parsed, fileLink,
      lastOpened: fileLink?.lastOpened ?? Date.now(), history: [], future: [],
      inputVideo: null, runResult: null, eventCount: 0, events: [], runLabel: '',
      serialized: null, status: '工程已打开',
    });
    projects.set(id, project);
  }
  openIds.add(id);
  return id;
}

async function readProject(id) {
  for (const key of [STORAGE, ...LEGACY_STORAGE]) {
    const backup = readStored(localStorage, key);
    if (backup?.id === id) return backup;
  }
  const backup = readStored(localStorage, `${STORAGE}.${id}`);
  if (backup?.id === id) return backup;
  return workflowResponse(await fetch(`/api/projects/${id}`));
}

async function loadProject(id) {
  const link = projects.get(id)?.fileLink ?? await projectFileLink(id);
  let data = await readProject(id).catch(error => {
    if (!link) throw error;
    return null;
  });
  if (link && (!data || JSON.stringify(data) === link.snapshot)) {
    try {
      const file = await link.handle.getFile();
      const latest = await readProjectFile(file);
      if (latest.source !== link.source && latest.data.id === id) {
        validateDraft(latest.data);
        return addProject(latest.data, file.name, { ...link, source: latest.source, snapshot: null }, true);
      }
      data ??= latest.data;
    } catch (error) {
      if (!data) throw error;
    }
  }
  return addProject(data, undefined, link);
}

async function restoreProjects() {
  const session = readStored(sessionStorage, SESSION);
  const requested = location.hash.match(/^#project=([a-f0-9]{32})$/)?.[1];
  const ids = new Set(Array.isArray(session?.ids) ? session.ids.filter(id => ID.test(id)) : []);
  if (requested) ids.add(requested);
  await Promise.all([...ids].map(async id => {
    try {
      await loadProject(id);
    } catch {
      if (id === requested) toast('未能读取指定工程。', true);
    }
  }));
  // Network responses may finish out of order. Restore the saved tab order.
  const restored = new Set(openIds);
  openIds.clear();
  for (const id of ids) if (restored.has(id)) openIds.add(id);
  const preferred = requested || session?.active;
  const active = openIds.has(preferred) ? preferred : openIds.values().next().value;
  activateProject(active ?? null);
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
function control(node, field) {
  const input = document.createElement(field.type === 'select' ? 'select' : field.type === 'textarea' ? 'textarea' : 'input');
  input.disabled = busy;
  input.dataset.param = field.key;
  input.dataset.owner = node.id;
  input.setAttribute('aria-label', `${node.title} · ${field.label}`);
  if (field.type === 'select') {
    for (const option of field.options) input.append(new Option(field.optionLabels?.[option] ?? option, option));
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
    if (busy) return;
    input.setCustomValidity('');
    // Color controls update the CSS sample while the picker is open. Other
    // values commit on change, so typing a number doesn't create 4 undo steps.
    if (field.type === 'color') updateVisualPreview(node.id, field.key, input.value);
  });
  input.addEventListener('change', () => {
    if (busy) return;
    if (!input.checkValidity()) {
      input.reportValidity();
      return;
    }
    const before = snapshot();
    const value = field.type === 'boolean' ? input.checked : field.type === 'number' ? Number(input.value) : input.value;
    config[node.id].params[field.key] = value;
    try { checkRelations(config); } catch (error) {
      config = before.nodes;
      input.value = before.nodes[node.id].params[field.key];
      toast(error.message, true);
      return;
    }
    commit(before);
    if (node.id === 'cover_localize' && field.key === 'enabled') draw();
    updateVisualPreview(node.id);

  });
  return input;
}
function updateVisualPreview(id, key, value) {
  const preview = elements.get(id)?.querySelector('.node-preview-content');
  if (!preview) return;
  const values = key ? { ...config[id].params, [key]: value } : config[id].params;
  renderPreview(preview, id, values);
}
function videoPicker() {
  const row = el('div', 'video-input-picker');
  const button = el('button', '', '选择视频');
  button.type = 'button';
  button.disabled = busy;
  button.onclick = () => $('workflow-video').click();
  const name = el('span', '', inputVideo?.name ?? '未选择 MP4');
  name.title = name.textContent;
  row.append(button, name);
  return row;
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
    header.title = node.description;
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
    header.append(el('span', 'node-number', node.symbol), el('h3', 'node-title', node.title), collapse);
    header.addEventListener('click', () => selectNode(node.id));
    header.addEventListener('keydown', event => {
      if (event.target !== header) return;
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectNode(node.id); }
    });
    const ports = el('div', 'ports');
    ports.append(el('span', 'port', node.input[0]), el('span', 'port out', node.output[0]));
    const fields = el('div', 'node-fields');
    fields.setAttribute('aria-label', `${node.title}参数`);
    renderNodeFields(fields, node);
    if (['asr_diarize', 'subtitle_render', 'cover_localize'].includes(node.id)) {
      const preview = el('details', 'node-preview');
      const body = el('div', 'node-preview-content');
      preview.addEventListener('toggle', draw);
      preview.append(el('summary', '', node.id === 'asr_diarize' ? '字幕查看' : '样式预览'), body);
      renderPreview(body, node.id);
      fields.append(preview);
    }
    const footer = el('div', 'node-footer');
    const state = el('span', 'node-state');
    const reset = el('button', 'node-reset', '重置参数');
    reset.disabled = busy;
    reset.addEventListener('click', () => resetNode(node.id));
    footer.append(state, reset);
    const handle = el('button', 'node-resize');
    handle.type = 'button';
    handle.title = '拖动调整节点尺寸，也可使用方向键';
    handle.setAttribute('aria-label', `调整${node.title}尺寸`);
    handle.addEventListener('keydown', event => resizeWithKeyboard(event, node.id));
    card.append(header, el('div', 'node-id', node.id), ports, fields, footer, handle);
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
function renderNodeFields(content, node) {
  if (node.id === 'probe_input') content.append(videoPicker());
  for (const group of node.groups) {
    const fieldset = el('fieldset', 'param-group');
    fieldset.append(el('legend', '', group.title));
    for (const field of group.fields) {
      if (node.id === 'probe_input' && replacedVideoFields.has(field.key)) continue;
      const label = el('label', 'param-row');
      label.classList.toggle('bool', field.type === 'boolean');
      label.classList.toggle('numeric', field.type === 'number');
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
function renderPreview(content, id, values = config[id].params) {
  content.replaceChildren();
  if (id === 'asr_diarize') {
    const open = el('button', '', '打开字幕查看');
    open.onclick = openSubtitleReview;
    const message = runResult?.english_srt_ready
      ? '英文字幕初稿已保存，可在字幕查看中对照视频复核。'
      : '运行工作流后，在字幕查看中对照视频检查各阶段字幕。';
    content.append(el('p', 'connection-note', message), open);
  } else if (id === 'subtitle_render') {
    const style = subtitleCatalog.styles[values.style];
    const layout = subtitleCatalog.layouts[values.layout];
    const screen = el('div', 'subtitle-preview');
    const scale = 0.25;
    screen.style.paddingBottom = `${style.margin_y * scale}px`;
    const samples = { zh: '让知识跨越语言', en: 'Let knowledge cross languages.' };
    for (const lang of layout.lines) {
      const line = el('div', 'subtitle-line', samples[lang]);
      line.style.fontSize = `${style[`${lang}_size`] * scale}px`;
      line.style.color = style[`${lang}_color`];
      line.style.fontWeight = style.bold ? 'bold' : 'normal';
      if (style.box) {
        line.style.backgroundColor = style.edge_color;
        line.style.paddingInline = '4px';
      } else {
        line.style.webkitTextStroke = `${style.outline * scale}px ${style.edge_color}`;
        line.style.paintOrder = 'stroke fill';
        line.style.textShadow = `${style.shadow * scale}px ${style.shadow * scale}px #0008`;
      }
      screen.append(line);
    }
    content.append(el('h3', 'preview-heading', `${style.label} · ${layout.label}`), screen,
      el('p', 'preview-caption', '横屏样式示意。压制时按视频尺寸选择 720p、1080p 或 2160p 基准。'));
  } else if (id === 'cover_localize') {
    content.append(el('p', 'connection-note', values.enabled
      ? '封面分支已启用 · 浏览器样式示意'
      : '封面分支已关闭 · 下方为样式示意'));
    const cover = el('div', 'cover-preview');
    cover.style.background = values.cover_color;
    cover.style.textAlign = values.cover_layout === '居中标题' ? 'center' : 'left';
    cover.append(el('span', '', '英文视频 · 中文译制'), el('h3', '', values.cover_title), el('span', '', '知识分享 / 中文配音 / 双语字幕'));
    content.append(el('h3', 'preview-heading', '中文封面 / 模板草图'), cover, el('p', 'preview-caption', `${values.cover_size} · ${values.cover_format} · 当前为浏览器预览，尚未生成文件。`));
  }
}

function renderStepStrip() {
  const strip = $('step-strip');
  for (const node of schema) {
    const button = el('button', 'step-jump');
    button.title = node.title;
    button.dataset.step = node.id;
    button.style.setProperty('--lane', categories[node.category].color);
    button.append(el('span', 'step-index', node.symbol), el('span', 'step-title', node.title));
    button.onclick = () => { selectNode(node.id); focusNode(); };
    strip.append(button);
  }
}
const links = $('links');
const anchorLayer = svg('g');
const anchorHint = svg('circle', { class: 'link-anchor-hint', visibility: 'hidden' });
const paths = edges.map(([from, to, type]) => {
  const key = edgeKey(from, to);
  const styles = { demo: 'link rework', optional: 'link optional' };
  const path = svg('path', { class: styles[type] ?? 'link' });
  path.dataset.from = from;
  path.dataset.to = to;
  const hits = svg('g', { 'data-edge': key });
  const handles = svg('g', { 'data-edge': key });
  links.append(path, hits);
  anchorLayer.append(handles);
  return { from, to, type, key, path, hits, handles };
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
function drawLink({ from, to, type, key, path, hits, handles }) {
  const a = config[from], b = config[to];
  const points = anchors[key] ?? [];
  const segments = curveSegments([
    { x: a.x + a.width, y: a.y + portOffset(from, true) },
    ...points,
    { x: b.x, y: b.y + portOffset(to, false) },
  ]);
  path.setAttribute('d', `${segments[0].move} ${segments.map(segment => segment.command).join(' ')}`);
  path.style.stroke = type === 'demo' || type === 'optional' ? '' : categories[index.get(from).category].color;
  path.classList.toggle('highlight', type !== 'demo' && (from === selected || to === selected));

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
    button.classList.toggle('is-active', button.dataset.step === activeNode);
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
    const running = node.id === activeNode;
    const failed = isCurrent && ['blocked', 'failed'].includes(runResult.state);
    const done = runResult?.completed_nodes?.includes(node.id);
    let label = connected.has(node.id) ? '等待运行' : '待接入';
    if (node.id === 'cover_localize') label = config[node.id].params.enabled ? '可选 · 待接入' : '可选 · 已关闭';
    if (done) label = node.id === 'asr_diarize' ? '已产出英文 SRT' : '已完成';
    if (running) label = '正在运行';
    if (failed) label = runResult.state === 'blocked' ? '尚未接入 · 已停止' : '执行失败';
    item.classList.toggle('is-active', running);
    item.classList.toggle('is-done', !!done);
    item.classList.toggle('is-blocked', failed);
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
      fill: categories[node.category].color, opacity: selected === node.id ? 0.9 : 0.4,
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

function confirm(title, message, action, label = '确认') {
  pendingAction = action;
  $('dialog-title').textContent = title;
  $('dialog-body').textContent = message;
  $('dialog-confirm').textContent = label;
  $('dialog').returnValue = '';
  $('dialog').showModal();
}
$('dialog').addEventListener('close', () => {
  if (!busy && $('dialog').returnValue === 'confirm') pendingAction?.();
  pendingAction = null;
});
function resetNode(id) {
  if (busy) return;
  confirm('重置节点参数', `将「${index.get(id).title}」恢复为默认参数，保留节点位置。可以撤销。`, () => {
    const before = snapshot();
    config[id].params = defaults()[id].params;
    commit(before);
    rebuild();
    toast('已重置节点参数。');
  }, '重置参数');
}
function renderProjectTabs() {
  const strip = $('project-tabs');
  const scroll = strip.scrollLeft;
  strip.replaceChildren();
  for (const id of openIds) {
    const { name } = projects.get(id);
    const active = id === projectId;
    const tab = el('div', 'project-tab');
    tab.classList.toggle('active', active);
    const select = el('button', 'project-tab-select', name);
    select.title = name;
    select.dataset.project = id;
    select.setAttribute('role', 'tab');
    select.setAttribute('aria-selected', String(active));
    select.setAttribute('aria-controls', 'canvas');
    select.tabIndex = active ? 0 : -1;
    select.disabled = busy && !active;
    select.onclick = () => activateProject(id);
    const close = el('button', 'project-tab-close', '×');
    close.setAttribute('aria-label', `关闭工程 ${name}`);
    close.title = '关闭工程';
    close.disabled = busy;
    close.onclick = () => closeProject(id);
    tab.append(select, close);
    strip.append(tab);
  }
  strip.scrollLeft = scroll;
  strip.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  $('new-project').disabled = busy;
  $('open-project').disabled = busy;
  $('save-project').disabled = !projectId;
  $('save-as-project').disabled = !projectId;
  $('close-project').disabled = busy || !projectId;
  $('exit-workspace').disabled = busy || !openIds.size;
}

function cacheActiveProject() {
  clearTimeout(viewSaveTimer);
  if (!projectId) return;
  const project = projects.get(projectId);
  persist(true);
  Object.assign(project, {
    history, future, inputVideo, runResult, eventCount,
    events: [...$('events').children], runLabel: $('run-status').textContent,
  });
}

function activateProject(id, reload = false) {
  if (busy || drag || (id && !openIds.has(id))) return;
  const restoreFocus = $('project-tabs').contains(document.activeElement) || $('empty-project').contains(document.activeElement);
  if (id && id === projectId && !reload) return;
  if (id !== projectId) cacheActiveProject();
  projectId = id;
  const project = projects.get(id);
  const data = project ? structuredClone(project.data) : null;
  config = data?.nodes ?? defaults();
  anchors = data?.anchors ?? {};
  history = project?.history ?? [];
  future = project?.future ?? [];
  inputVideo = project?.inputVideo ?? null;
  runResult = project?.runResult ?? null;
  eventCount = project?.eventCount ?? 0;
  $('events').replaceChildren(...(project?.events ?? []));
  $('event-count').textContent = eventCount;
  $('run-status').textContent = project?.runLabel || '尚未运行';
  if (runResult) $('run-status').dataset.state = runResult.state;
  else delete $('run-status').dataset.state;
  $('empty-project').hidden = !!project;
  $('workspace-views').hidden = !project;
  $('workspace-actions').hidden = !project;
  restoreView(data?.view ?? validateView(null));
  renderProjectTabs();
  syncHistory();
  if (project) {
    rebuild();
    updateOutput();
    $('save-status').textContent = project.status;
    if (!data.view) {
      if (narrowScreen.matches) focusNode();
      else fit();
    }
    persist(false, true);
    if (project.fileLink?.snapshot === null) {
      project.fileLink.snapshot = project.serialized;
      project.fileLink.name = project.name;
      void projectFileLink(project.id, project.fileLink);
      reportBackup(project, true);
    }
  } else {
    $('workflow-panel').hidden = true;
    $('nodes').replaceChildren();
    elements.clear();
    $('save-status').textContent = '没有打开的工程';
  }
  setTaskProject(projectId);
  if (restoreFocus) ($('project-tabs').querySelector('[aria-selected="true"]') ?? $('empty-new')).focus();
  rememberSession();
}

function closeProject(id) {
  if (busy || drag || !openIds.has(id)) return;
  const ids = [...openIds];
  openIds.delete(id);
  if (id === projectId) activateProject(ids[ids.indexOf(id) + 1] ?? ids[ids.indexOf(id) - 1] ?? null);
  else {
    renderProjectTabs();
    rememberSession();
  }
}

function openProject(data, fallbackName) {
  if (busy || drag) return;
  const id = addProject(data, fallbackName);
  markProjectOpened(id);
  activateProject(id);
  if ($('project-picker').open) $('project-picker').close();
}

async function showProjectPicker() {
  if (busy || $('project-picker').open) return;
  const picker = $('project-picker');
  const status = $('project-picker-status');
  const list = $('saved-projects');
  const request = ++pickerRequest;
  const loading = '正在读取本机工程…';
  status.textContent = loading;
  list.replaceChildren();
  picker.showModal();
  const entries = await recentProjectEntries();
  if (request !== pickerRequest || !picker.open) return;
  if (status.textContent === loading) {
    status.textContent = entries.length ? '最近打开的工程' : '暂无已关联本地文件的工程。';
  }
  for (const { id, name } of entries) {
    const item = el('li');
    const button = el('button', 'saved-project', name);
    button.title = name;
    button.dataset.project = id;
    button.onclick = async () => {
      try {
        const alreadyOpen = openIds.has(id);
        const loaded = alreadyOpen ? id : await loadProject(id);
        if (!picker.open) {
          if (!alreadyOpen) openIds.delete(loaded);
          return;
        }
        markProjectOpened(loaded);
        activateProject(loaded);
        picker.close();
      } catch (error) {
        status.textContent = `打开失败：${error.message}`;
      }
    };
    item.append(button);
    list.append(item);
  }
}

for (const [id, action] of [
  ['new-project', () => openProject()],
  ['open-project', showProjectPicker],
  ['save-project', () => void saveProject()],
  ['save-as-project', () => void saveProject(true)],
  ['close-project', () => closeProject(projectId)],
  ['exit-workspace', () => {
    confirm('退出工作台', '备份草稿并关闭当前打开的所有工程。', () => {
      openIds.clear();
      activateProject(null);
    }, '退出');
  }],
  ['about-project', () => $('about-dialog').showModal()],
]) {
  $(id).onclick = () => {
    $('project-menu').hidePopover();
    action();
  };
}
$('empty-new').onclick = () => openProject();
$('empty-open').onclick = showProjectPicker;
async function openProjectFile(file, handle = null) {
  const { data, source } = await readProjectFile(file);
  validateDraft(data);
  const existing = projects.get(data.id);
  const linked = handle && ID.test(data.id)
    ? existing?.fileLink ?? await projectFileLink(data.id)
    : null;
  if (linked) {
    if (!await handle.isSameEntry(linked.handle)) {
      // Two copies of one file get independent workspaces and queues.
      data.id = newId();
    } else if (existing && openIds.has(existing.id) &&
        (linked.source === source || linked.snapshot !== existing.serialized)) {
      openProject(data);
      return;
    }
  }
  if (busy || drag) return;
  const id = addProject(data, file.name.replace(/\.json$/i, ''),
    handle ? { handle, source, snapshot: null } : null, true);
  markProjectOpened(id);
  activateProject(id, true);
  if ($('project-picker').open) $('project-picker').close();
}

function reportOpenError(error) {
  if (error.name === 'AbortError') return;
  const message = `打开失败：${error.message}`;
  if ($('project-picker').open) $('project-picker-status').textContent = message;
  else toast(message, true);
}

$('choose-project-file').onclick = async () => {
  if (!window.showOpenFilePicker) {
    $('project-file').click();
    return;
  }
  try {
    const [handle] = await window.showOpenFilePicker({ types: projectFileTypes });
    await openProjectFile(await handle.getFile(), handle);
  } catch (error) {
    reportOpenError(error);
  }
};
$('new-project-form').onsubmit = event => {
  event.preventDefault();
  openProject(null, projectName($('new-project-name').value));
  $('new-project-name').value = '';
};
$('project-file').onchange = async event => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file || busy) return;
  try { await openProjectFile(file); }
  catch (error) { reportOpenError(error); }
};
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
$('console-toggle').onclick = () => {
  const collapsed = $('console').classList.toggle('collapsed');
  $('console-toggle').textContent = collapsed ? '⌃' : '⌄';
  $('console-toggle').setAttribute('aria-expanded', String(!collapsed));
  $('console-toggle').setAttribute('aria-label', collapsed ? '展开运行面板' : '收起运行面板');
  draw();
  scheduleViewSave();
};
function clearLog() {
  $('events').replaceChildren();
  eventCount = 0;
  $('event-count').textContent = '0';
}
$('clear-log').onclick = () => {
  clearLog();
};
function appendEvent(label, message, warning = false) {
  const item = el('li');
  item.append(el('time', '', new Date().toLocaleTimeString('zh-CN', { hour12: false })), el('span', `log-label${warning ? ' log-warning' : ''}`, label), el('span', '', message));
  $('events').append(item);
  $('event-count').textContent = String(++eventCount);
  $('log-panel').scrollTop = $('log-panel').scrollHeight;
}
function updateOutput() {
  let output = `${index.get(selected).title}尚无运行输出。`;
  if (selected === 'asr_diarize' && runResult?.english_srt_ready) output = '已保存英文字幕中间产物 english.srt。';
  else if (runResult?.node === selected) output = runResult.message;
  else if (runResult?.completed_nodes?.includes(selected)) output = '节点已完成。';
  $('console-output').textContent = output;
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
  runStatus.textContent = labels[status.state];
  if (status.message) appendEvent(index.get(status.node).title, status.message, ['blocked', 'failed'].includes(status.state));
  updateVisualPreview('asr_diarize');
  updateOutput();
  draw();
}

function setRunLock(locked) {
  busy = locked;
  for (const id of ['run', 'clear-log']) {
    $(id).disabled = locked;
  }
  $('draft-state').hidden = !locked;
  renderProjectTabs();
  $('draft-state').classList.toggle('is-locked', locked);
  syncHistory();
  renderNodes();
}

$('run').onclick = async () => {
  if (busy || !projectId) return;
  if (!inputVideo) {
    selectNode('probe_input');
    focusNode();
    toast('请先在「视频输入」节点选择 MP4。');
    return;
  }

  setRunLock(true);
  $('console').classList.remove('collapsed');
  $('console-toggle').setAttribute('aria-expanded', 'true');
  $('console-toggle').setAttribute('aria-label', '收起运行面板');
  $('console-toggle').textContent = '⌄';
  setConsoleTab(false);
  clearLog();
  showRunResult({ state: 'running', node: 'probe_input', message: `正在读取 ${inputVideo.name}…` });
  try {
    const { job_id: jobId } = await workflowResponse(await fetch('/api/workflow-runs', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/octet-stream',
        'X-Video-Name': encodeURIComponent(inputVideo.name),
        'X-Project-Id': projectId,
      },
      body: inputVideo,
    }));
    const jobUrl = `/api/workflow-runs/${jobId}`;
    setPreviewJob(jobId);
    void refreshTasks({ latest: true });
    while (true) {
      const status = await workflowResponse(await fetch(jobUrl));
      status.node ??= runResult.node;
      const hasNewSrt = status.english_srt_ready && !runResult.english_srt_ready;
      if (hasNewSrt || status.node !== runResult.node || status.message !== runResult.message || status.state !== runResult.state) {
        showRunResult(status);
        if (hasNewSrt) appendEvent('中间产物', '英文字幕初稿已保存，供后续流程使用。');
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
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') { event.preventDefault(); void saveProject(); }
  if (typing || !$('subtitle-panel').hidden || !projectId) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') { event.preventDefault(); undo(event.shiftKey); }
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  if (event.key.toLowerCase() === 'f') { event.preventDefault(); fit(); }
  if (event.key === '1' && !event.target.closest('.node-fields')) focusNode();
});
// Arrow keys follow tablist conventions, including the narrow-screen layout.
for (const tablist of document.querySelectorAll('[role=tablist]')) {
  tablist.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    const tabs = [...tablist.querySelectorAll('[role=tab]:not(:disabled)')];
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
  const collapsed = view.consoleCollapsed;
  $('console').classList.toggle('collapsed', collapsed);
  $('console-toggle').textContent = collapsed ? '⌃' : '⌄';
  $('console-toggle').setAttribute('aria-expanded', String(!collapsed));
  $('console-toggle').setAttribute('aria-label', collapsed ? '展开运行面板' : '收起运行面板');
  setConsoleTab(view.consoleTab === 'output');
  restoreReviewView(view.review, inputVideo);
}

$('status-node-count').textContent = `${schema.length} 节点`;
renderStepStrip();
new ResizeObserver(() => { if (projectId) draw(); }).observe($('canvas'));
document.addEventListener('project-view-change', scheduleViewSave);
window.addEventListener('pagehide', () => persist());
await restoreProjects();
