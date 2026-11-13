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

function renderDetail() {
  const detail = $('task-detail');
  const job = jobs.find(item => item.id === selected);
  detail.replaceChildren();
  detail.hidden = !job;
  if (!job) return;
  const status = states[job.state] ?? '未知';
  const node = nodeNames.get(job.node) ?? job.node;
  detail.append(el('h3', '任务详情'),
    el('p', [status, node].filter(Boolean).join(' · '), 'task-detail-state'));
  if (job.message) detail.append(el('p', job.message));
  if (job.completed_nodes.length) {
    detail.append(el('p', `已完成 ${job.completed_nodes.map(id => nodeNames.get(id) ?? id).join(' → ')}`));
  }
  detail.append(el('code', job.id));
  const open = el('button', job.english_srt_ready || job.english_segments_ready ? '查看视频与字幕' : '查看源视频');
  open.type = 'button';
  open.onclick = () => {
    $('node-inspector').close();
    openTaskSubtitles(job.id);
  };
  const log = el('button', '查看后端日志');
  log.type = 'button';
  log.onclick = () => {
    $('node-inspector').close();
    document.dispatchEvent(new CustomEvent('open-task-log', { detail: job.id }));
  };
  detail.append(open, log);
  if (job.final_video_ready) {
    const download = el('a', '下载成片 MP4');
    download.href = `/api/workflow-runs/${job.id}/final-video`;
    detail.append(download);
  }
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
    const li = el('li');
    const row = el('button', undefined, 'task-row');
    row.type = 'button';
    row.dataset.jobId = job.id;
    row.setAttribute('aria-pressed', String(job.id === selected));
    const top = el('span', undefined, 'task-row-top');
    const badge = el('span', states[job.state] ?? '未知', 'task-badge');
    badge.dataset.state = job.state;
    top.append(el('strong', job.filename), badge);
    const date = new Date(job.created_at * 1000);
    const time = el('time', Number.isNaN(date.valueOf()) ? job.id.slice(0, 8) : date.toLocaleString());
    row.append(top, time);
    row.onclick = () => {
      selected = job.id;
      for (const button of list.querySelectorAll('.task-row')) {
        button.setAttribute('aria-pressed', String(button.dataset.jobId === selected));
      }
      renderDetail();
    };
    li.append(row);
    list.append(li);
  }
  renderDetail();
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
