import { schema } from './node-schema.js';
import { openTaskSubtitles } from './subtitle-review.js';

const $ = id => document.getElementById(id);
const pageSize = 25;
const nodeNames = new Map(schema.map(node => [node.id, node.title]));
const states = { running: '运行中', blocked: '已停止', failed: '失败', complete: '已完成' };
let offset = 0;
let selected = null;
let jobs = [];
let sequence = 0;
let clearing = false;
const queueUrl = '/api/workflow-runs';

function el(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function duration(seconds) {
  if (!Number.isFinite(seconds)) return '未记录';
  const total = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(total / 60);
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}小时 ${minutes % 60}分 ${total % 60}秒`
    : `${minutes}分 ${String(total % 60).padStart(2, '0')}秒`;
}

function renderDetail(job) {
  const detail = el('section', undefined, 'task-detail');
  detail.setAttribute('aria-label', '任务详情');
  const node = job.phase === 'download' ? '下载原视频' : nodeNames.get(job.node) ?? job.node;
  const meta = el('dl', undefined, 'task-metadata');
  for (const [label, value] of [
    ['总用时', duration(job.elapsed_seconds)],
    ['当前阶段', node || (job.state === 'complete' ? '合成完成' : '—')],
    ['已完成', `${job.completed_nodes.length} / ${schema.length} 个节点`],
  ]) {
    const item = el('div');
    item.append(el('dt', label), el('dd', value));
    meta.append(item);
  }
  detail.append(meta);
  if (job.message) detail.append(el('p', job.message, 'task-message'));
  detail.append(el('code', job.id, 'task-id'));
  const actions = el('div', undefined, 'task-detail-actions');
  const preview = el('button', '工作预览');
  preview.type = 'button';
  preview.disabled = job.input_ready === false;
  preview.onclick = () => {
    $('node-inspector').close();
    openTaskSubtitles(job.id);
  };
  const folder = el('button', '打开输出目录');
  folder.type = 'button';
  folder.onclick = async () => {
    folder.disabled = true;
    let error = detail.querySelector('[role="alert"]');
    error?.remove();
    try {
      const response = await fetch(`${queueUrl}/${job.id}/open-output`, { method: 'POST' });
      if (!response.ok) throw new Error((await response.json()).message);
    } catch (cause) {
      error = el('p', cause.message || '无法打开输出目录。', 'task-message');
      error.setAttribute('role', 'alert');
      detail.append(error);
    } finally {
      folder.disabled = false;
    }
  };
  actions.append(preview, folder);
  detail.append(actions);
  return detail;
}

function renderList(total, hasFinished = false) {
  const list = $('task-list');
  list.replaceChildren();
  const active = jobs.filter(job => job.state === 'running').length;
  $('task-summary').textContent = total ? `${total} 次运行${active ? ` · 本页 ${active} 项运行中` : ''}` : '还没有运行任务。';
  $('tasks-clear').disabled = !hasFinished || clearing;
  $('task-pagination').hidden = total <= pageSize;
  $('task-prev').disabled = offset === 0;
  $('task-next').disabled = offset + pageSize >= total;
  $('task-page').textContent = `${Math.floor(offset / pageSize) + 1} / ${Math.max(1, Math.ceil(total / pageSize))}`;
  for (const job of jobs) {
    const li = el('li', undefined, 'task-card');
    const row = el('button', undefined, 'task-row');
    row.type = 'button';
    row.dataset.jobId = job.id;
    row.setAttribute('aria-expanded', String(job.id === selected));
    row.setAttribute('aria-controls', 'task-detail-' + job.id);
    const top = el('span', undefined, 'task-row-top');
    const badge = el('span', states[job.state] ?? '未知', 'task-badge');
    badge.dataset.state = job.state;
    top.append(el('strong', job.filename), badge);
    const date = new Date(job.created_at * 1000);
    const bottom = el('span', undefined, 'task-row-meta');
    bottom.append(
      el('time', Number.isNaN(date.valueOf()) ? job.id.slice(0, 8) : date.toLocaleString()),
      el('span', duration(job.elapsed_seconds)),
    );
    row.append(top, bottom);
    row.onclick = () => {
      selected = selected === job.id ? null : job.id;
      renderList(total, hasFinished);
      list.querySelector(`[data-job-id="${job.id}"]`)?.focus({ preventScroll: true });
    };
    li.append(row);
    if (job.id === selected) {
      const detail = renderDetail(job);
      detail.id = 'task-detail-' + job.id;
      li.append(detail);
    }
    list.append(li);
  }
}

export async function refreshTasks({ latest = false } = {}) {
  if (latest) offset = 0;
  if (clearing || !$('node-inspector').getClientRects().length) return;
  const request = ++sequence;
  try {
    const response = await fetch(`${queueUrl}?offset=${offset}`);
    if (!response.ok) throw new Error('无法读取任务记录。');
    const result = await response.json();
    if (request !== sequence) return;
    const lastOffset = Math.max(0, Math.ceil(result.total / pageSize) - 1) * pageSize;
    if (offset > lastOffset) {
      offset = lastOffset;
      void refreshTasks();
      return;
    }
    jobs = result.jobs;
    renderList(result.total, result.has_finished);
  } catch {
    if (request === sequence) $('task-summary').textContent = '任务记录读取失败，可点刷新重试。';
  }
}

$('tasks-clear').onclick = async () => {
  if (clearing || $('tasks-clear').disabled) return;
  clearing = true;
  sequence++;
  $('tasks-clear').disabled = true;
  try {
    const response = await fetch(queueUrl, { method: 'DELETE' });
    if (!response.ok) throw new Error();
    const result = await response.json();
    offset = 0;
    selected = null;
    jobs = result.jobs;
    clearing = false;
    renderList(result.total, result.has_finished);
  } catch {
    $('task-summary').textContent = '清空失败，可刷新队列后重试。';
    $('tasks-clear').disabled = false;
  } finally {
    clearing = false;
  }
};
$('tasks-refresh').onclick = () => { void refreshTasks(); };
$('task-prev').onclick = () => { offset = Math.max(0, offset - pageSize); void refreshTasks(); };
$('task-next').onclick = () => { offset += pageSize; void refreshTasks(); };
setInterval(() => { if (!document.hidden) void refreshTasks(); }, 5000);
