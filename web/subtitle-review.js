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
let videoMode = 'original';
let finalReady = false;

function videoButtons() {
  $('review-original').setAttribute('aria-pressed', String(videoMode === 'original'));
  $('review-target').setAttribute('aria-pressed', String(videoMode === 'target'));
  $('review-target').disabled = !finalReady;
  $('review-target').title = finalReady ? '播放本任务生成的配音字幕成片' : '该任务尚未生成目标视频';
  for (const [id, mode] of [['review-original', 'original'], ['review-target', 'target']]) {
    $(id).setAttribute('aria-selected', String(videoMode === mode));
    $(id).tabIndex = videoMode === mode ? 0 : -1;
  }
}

function mediaTime(seconds) {
  const value = Math.max(0, Math.floor(seconds || 0));
  const minutes = Math.floor(value / 60);
  const tail = String(value % 60).padStart(2, '0');
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}:${tail}`
    : `${String(minutes).padStart(2, '0')}:${tail}`;
}

let scrubbing = false;
function updateMediaControls() {
  const duration = Number.isFinite(video.duration) ? video.duration : 0;
  const ready = Boolean(video.getAttribute('src')) && video.readyState >= 1 && !video.error;
  const playing = !video.paused && !video.ended;
  const play = $('review-play');
  play.disabled = !ready;
  play.classList.toggle('is-playing', playing);
  play.setAttribute('aria-label', playing ? '暂停' : '播放');
  play.title = playing ? '暂停' : '播放';
  const seek = $('review-seek');
  seek.disabled = !ready || duration <= 0;
  seek.max = String(duration);
  if (!scrubbing) seek.value = String(video.currentTime || 0);
  seek.setAttribute('aria-valuetext', `${mediaTime(video.currentTime)} / ${mediaTime(duration)}`);
  seek.style.setProperty('--played', duration ? `${Math.min(100, video.currentTime / duration * 100)}%` : '0%');
  $('review-clock').textContent = `${mediaTime(video.currentTime)} / ${mediaTime(duration)}`;
  const muted = video.muted || video.volume === 0;
  $('review-mute').disabled = !ready;
  $('review-mute').setAttribute('aria-pressed', String(muted));
  $('review-mute').setAttribute('aria-label', muted ? '取消静音' : '静音');
  $('review-mute').title = muted ? '取消静音' : '静音';
  $('review-fullscreen').disabled = !ready || !document.fullscreenEnabled;
}

async function togglePlayback() {
  if ($('review-play').disabled) return;
  if (!video.paused) video.pause();
  else {
    try {
      await video.play();
    } catch {
      $('review-video-error').textContent = '无法开始播放，请稍后重试。';
      $('review-video-error').hidden = false;
    }
  }
}

async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) await document.exitFullscreen();
    else await document.querySelector('.review-player').requestFullscreen();
  } catch {
    $('review-video-error').textContent = '当前浏览器无法进入全屏。';
    $('review-video-error').hidden = false;
  }
}

function switchVideo(mode) {
  if (mode === 'target' && !finalReady) return;
  const time = video.currentTime || 0;
  const playing = !video.paused;
  video.onloadedmetadata = null;
  videoMode = mode;
  const url = mode === 'target' ? `/api/workflow-runs/${jobId}/final-video?download=0`
    : objectUrl ?? (jobId ? `/api/workflow-runs/${jobId}/preview-video` : null);
  setVideo(url, mode === 'target' ? '当前任务的目标视频' : '当前任务的原视频');
  videoButtons();
  if (url) video.onloadedmetadata = () => {
    video.currentTime = Math.min(time, Number.isFinite(video.duration) ? video.duration : time);
    if (playing) video.play().catch(() => {});
    video.onloadedmetadata = null;
  };
}

async function checkTargetVideo() {
  const id = jobId;
  if (!id) return;
  try {
    const response = await fetch(`/api/workflow-runs/${id}`, { cache: 'no-store' });
    if (!response.ok) return;
    const result = await response.json();
    if (id !== jobId) return;
    finalReady = !!result.final_video_ready;
    videoButtons();
  } catch {
    // Original playback remains available if status polling fails.
  }
}

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
  videoMode = 'original';
  finalReady = false;
  videoButtons();
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
    follow: true,
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
    videoMode = 'original';
    videoButtons();
  }
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
  video.setAttribute('aria-label', label || '视频预览');
  $('review-video-error').hidden = true;
  scrubbing = false;
  updateMediaControls();
}

export function setPreviewInput(file) {
  changeJob(null);
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = file ? URL.createObjectURL(file) : null;
  setVideo(objectUrl, file?.name ?? '链接视频下载完成后可预览');
  videoMode = 'original';
  finalReady = false;
  videoButtons();
  setStage('segmented');
}

export function setPreviewJob(id) {
  if (!validId.test(id)) return;
  const isNewJob = id !== jobId;
  changeJob(id);
  if (!objectUrl && (isNewJob || videoMode === 'original')) setVideo(`/api/workflow-runs/${id}/preview-video`, '当前任务的原视频');
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
    row.className = 'review-cue-item';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'review-cue';
    appendText(row, 'review-time', `${timestamp(cue.start_ms)} – ${timestamp(cue.end_ms)}`);
    row.firstElementChild.id = `review-time-${rows.length}`;
    button.setAttribute('aria-describedby', row.firstElementChild.id);
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
  scrollToCue(row);
}

function scrollToCue(row) {
  const bounds = scroll.getBoundingClientRect();
  const target = row.parentElement.getBoundingClientRect();
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
  void checkTargetVideo();
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
$('review-original').onclick = () => switchVideo('original');
$('review-target').onclick = () => switchVideo('target');
$('subtitle-tab').onclick = () => showView(true);
$('review-play').onclick = togglePlayback;
video.addEventListener('click', togglePlayback);
video.addEventListener('keydown', event => {
  if (event.code === 'Space') {
    event.preventDefault();
    void togglePlayback();
  }
});
$('review-mute').onclick = () => {
  video.muted = !(video.muted || video.volume === 0);
  if (!video.muted && video.volume === 0) video.volume = 1;
};
$('review-fullscreen').onclick = toggleFullscreen;
document.addEventListener('fullscreenchange', () => {
  const label = document.fullscreenElement ? '退出全屏' : '全屏';
  $('review-fullscreen').setAttribute('aria-label', label);
  $('review-fullscreen').title = label;
});
$('review-seek').addEventListener('pointerdown', () => { scrubbing = true; });
for (const event of ['pointerup', 'pointercancel', 'blur']) {
  $('review-seek').addEventListener(event, () => { scrubbing = false; updateMediaControls(); });
}
$('review-seek').oninput = () => {
  if (Number.isFinite(video.duration)) video.currentTime = Number($('review-seek').value);
  updateMediaControls();
};
for (const event of ['timeupdate', 'loadedmetadata', 'durationchange', 'emptied', 'loadstart', 'play', 'pause', 'ended', 'volumechange', 'error']) {
  video.addEventListener(event, updateMediaControls);
}
for (const tab of stageTabs) tab.onclick = () => setStage(tab.dataset.stage);
for (const event of ['timeupdate', 'seeking', 'seeked', 'loadedmetadata']) {
  video.addEventListener(event, syncPlayback);
}
function trackPlayback() {
  frame = null;
  if (video.paused || video.ended) return;
  syncPlayback();
  updateMediaControls();
  frame = requestAnimationFrame(trackPlayback);
}
video.addEventListener('play', () => {
  if (frame === null) frame = requestAnimationFrame(trackPlayback);
});
video.addEventListener('pause', () => {
  if (frame !== null) cancelAnimationFrame(frame);
  frame = null;
});
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
