const $ = id => document.getElementById(id);
const video = $('review-video');
const list = $('review-cue-list');
const scroll = $('review-cue-scroll');
const status = $('review-stage-status');
const initialTab = $('review-stage-initial');
const stageTabs = [...document.querySelectorAll('[data-stage]')];
const jobKey = 'video-localizer.preview-job';
const validId = /^[0-9a-f]{32}$/;

let stage = 'segmented';
let jobId = null;
let initialCheckJob = null;
let objectUrl = null;
let request = null;
let retryTimer = null;
let cues = [];
let rows = [];
let latestEnd = [];
let active = -1;
let frame = null;

function saveJob(id) {
  try {
    if (id) sessionStorage.setItem(jobKey, id);
    else sessionStorage.removeItem(jobKey);
  } catch {
    // Playback still works when browser storage is unavailable.
  }
}

function changeJob(id) {
  if (id === jobId) return;
  jobId = id;
  initialCheckJob = null;
  initialTab.hidden = true;
  saveJob(id);
}

async function checkInitialTab() {
  if (!jobId || jobId === initialCheckJob) return;
  const id = jobId;
  initialCheckJob = id;
  try {
    const response = await fetch(`/api/workflow-runs/${id}/subtitles/initial`);
    if (!response.ok) throw new Error();
    const result = await response.json();
    if (jobId === id) initialTab.hidden = !(result.ready && result.cues.length);
  } catch {
    if (jobId === id) initialCheckJob = null;
  }
}

function reviewChanged() {
  document.dispatchEvent(new Event('canvas-view-change'));
}

export function getReviewView() {
  return {
    tab: $('subtitle-panel').hidden ? 'workflow' : 'subtitles',
    stage,
    follow: $('review-follow').checked,
    jobId,
  };
}

export function restoreReviewView(view, file) {
  if (file !== undefined || view.jobId !== jobId) {
    if (objectUrl) URL.revokeObjectURL(objectUrl);
    objectUrl = file ? URL.createObjectURL(file) : null;
    changeJob(view.jobId);
    setVideo(objectUrl ?? (jobId ? `/api/workflow-runs/${jobId}/preview-video` : null),
      file?.name ?? (jobId ? '当前任务的原视频' : ''));
  }
  $('review-follow').checked = view.follow;
  setStage(view.stage);
  showView(view.tab === 'subtitles');
}

function showView(subtitles) {
  $('subtitle-panel').hidden = !subtitles;
  $('workflow-panel').hidden = subtitles;
  for (const [id, selected] of [['subtitle-tab', subtitles], ['workflow-tab', !subtitles]]) {
    $(id).setAttribute('aria-selected', String(selected));
    $(id).tabIndex = selected ? 0 : -1;
  }
  if (subtitles) {
    refreshSubtitleReview();
  } else {
    video.pause();
    request?.abort();
    clearTimeout(retryTimer);
  }
  reviewChanged();
}

export function openTaskSubtitles(id) {
  if (!validId.test(id)) return;
  restoreReviewView({ ...getReviewView(), jobId: id, tab: 'subtitles' });
  $('subtitle-tab').focus();
}

export function openSubtitleReview() {
  showView(true);
  $('subtitle-tab').focus();
}

function setVideo(url, label) {
  if (url) video.src = url;
  else {
    video.removeAttribute('src');
    video.load();
  }
  video.hidden = !url;
  $('review-video-empty').hidden = !!url;
  $('review-source').textContent = label;
  $('review-video-error').hidden = true;
}

export function setPreviewInput(file) {
  changeJob(null);
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = file ? URL.createObjectURL(file) : null;
  setVideo(objectUrl, file?.name ?? '链接视频下载完成后可预览');
  setStage('segmented');
}

export function setPreviewJob(id) {
  if (!validId.test(id)) return;
  const isNewJob = id !== jobId;
  changeJob(id);
  if (!objectUrl) setVideo(`/api/workflow-runs/${id}/preview-video`, '当前任务的原视频');
  if (isNewJob) setStage('segmented');
  else refreshSubtitleReview();
}

function setStage(next) {
  stage = next === 'initial' && initialTab.hidden ? 'segmented' : next;
  for (const tab of stageTabs) {
    const selected = tab.dataset.stage === stage;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
  }
  $('review-stage-panel').setAttribute('aria-labelledby', `review-stage-${stage}`);
  renderCues([]);
  refreshSubtitleReview();
  reviewChanged();
}

function timestamp(ms) {
  const fraction = ms % 1000;
  const seconds = Math.floor(ms / 1000);
  const parts = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60];
  return parts.map(value => String(value).padStart(2, '0')).join(':') +
    '.' + String(fraction).padStart(3, '0');
}

function appendText(button, className, text) {
  const span = document.createElement('span');
  span.className = className;
  span.textContent = text;
  button.append(span);
}

function renderCues(items) {
  cues = items;
  latestEnd = [];
  rows = [];
  active = -1;
  const fragment = document.createDocumentFragment();
  let maxEnd = 0;
  for (const cue of cues) {
    maxEnd = Math.max(maxEnd, cue.end_ms);
    latestEnd.push(maxEnd);
    const row = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'review-cue';
    appendText(button, 'review-time', `${timestamp(cue.start_ms)} – ${timestamp(cue.end_ms)}`);
    appendText(button, 'review-original', cue.original);
    if (cue.translation !== null) appendText(button, 'review-translation', cue.translation);
    button.addEventListener('click', () => {
      video.currentTime = cue.start_ms / 1000;
      syncPlayback();
    });
    row.append(button);
    rows.push(button);
    fragment.append(row);
  }
  list.replaceChildren(fragment);
  scroll.scrollTop = 0;
  syncPlayback();
}

function syncPlayback() {
  const ms = Math.floor(video.currentTime * 1000 + 0.01);
  let low = 0, high = cues.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (cues[middle].start_ms <= ms) low = middle + 1;
    else high = middle;
  }
  let index = low - 1;
  // Prefer the most recent active cue when two original time ranges overlap.
  while (index >= 0 && latestEnd[index] > ms && cues[index].end_ms <= ms) index--;
  if (index >= 0 && cues[index].end_ms <= ms) index = -1;
  if (index === active) return;
  rows[active]?.removeAttribute('aria-current');
  active = index;
  const row = rows[active];
  if (!row) return;
  row.setAttribute('aria-current', 'true');
  if ($('review-follow').checked) scrollToCue(row);
}

function scrollToCue(row) {
  const bounds = scroll.getBoundingClientRect();
  const target = row.getBoundingClientRect();
  if (target.top < bounds.top || target.bottom > bounds.bottom) {
    scroll.scrollTop += target.top - bounds.top - (bounds.height - target.height) / 2;
  }
}

export async function refreshSubtitleReview() {
  clearTimeout(retryTimer);
  request?.abort();
  if ($('subtitle-panel').hidden) return;
  if (!jobId) {
    status.textContent = '运行工作流后，这里会显示已生成的阶段字幕。';
    return;
  }
  void checkInitialTab();
  const controller = new AbortController();
  request = controller;
  try {
    const response = await fetch(`/api/workflow-runs/${jobId}/subtitles/${stage}`, {
      signal: controller.signal,
    });
    const result = await response.json();
    if (controller.signal.aborted) return;
    if (!response.ok) throw new Error(result.message || '字幕预览读取失败。');
    renderCues(result.cues);
    status.textContent = result.ready
      ? `${result.cues.length} 个字幕块 · ${stage === 'draft' || stage === 'final' ? '英文原文 / 中文译文' : '英文原文'}`
      : '这一阶段尚未生成字幕。';
    if (!result.ready) retryTimer = setTimeout(refreshSubtitleReview, 2500);
  } catch (error) {
    if (controller.signal.aborted) return;
    renderCues([]);
    status.textContent = error.message;
  }
}

$('workflow-tab').onclick = () => showView(false);
$('subtitle-tab').onclick = () => showView(true);
for (const tab of stageTabs) tab.onclick = () => setStage(tab.dataset.stage);
for (const event of ['timeupdate', 'seeking', 'seeked', 'loadedmetadata']) {
  video.addEventListener(event, syncPlayback);
}
function trackPlayback() {
  frame = null;
  if (video.paused || video.ended) return;
  syncPlayback();
  frame = requestAnimationFrame(trackPlayback);
}
video.addEventListener('play', () => {
  if (frame === null) frame = requestAnimationFrame(trackPlayback);
});
video.addEventListener('pause', () => {
  if (frame !== null) cancelAnimationFrame(frame);
  frame = null;
});
$('review-follow').onchange = () => {
  if ($('review-follow').checked && rows[active]) scrollToCue(rows[active]);
  reviewChanged();
};
video.addEventListener('error', () => {
  $('review-video-error').textContent = '无法播放该视频。请确认文件存在且浏览器支持其视频编码。';
  $('review-video-error').hidden = false;
});

setVideo(null, '');
try {
  const saved = sessionStorage.getItem(jobKey);
  if (saved) setPreviewJob(saved);
} catch {
  // A fresh session can still choose and review a local video.
}
