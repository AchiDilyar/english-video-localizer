// Requires Playwright. Start the local WebUI service before running this file.
// WEBUI_URL selects the server; WEBUI_SCREENSHOT optionally saves a desktop image.
const assert = require('node:assert/strict');
const { randomBytes } = require('node:crypto');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { chromium } = require('playwright');
const base = process.env.WEBUI_URL || 'http://127.0.0.1:8765';
(async () => {
  const browser = await chromium.launch();
  const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'localizer-webui-'));
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, reducedMotion: 'reduce' });
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const stored = () => page.evaluate(() => JSON.parse(localStorage.getItem('video-localizer.project.v4')));
    const inspect = async title => {
      await page.locator('.step-jump').filter({ hasText: title }).click();
      assert.equal(await page.locator('.node.selected .node-title').textContent(), title);
    };
    const logoAction = async id => {
      await page.locator('#product-logo').click();
      await page.locator(`#${id}`).click();
    };
    const projectTab = id => page.locator(`#project-tabs [data-project="${id}"]`);
    const input = (node, key) => page.locator(`[data-node="${node}"] [data-param="${key}"]`);
    const edit = async (node, key, value) => { await input(node, key).fill(value); await input(node, key).press('Tab'); };
    const confirm = async () => {
      const before = JSON.stringify(await stored());
      await page.locator('#dialog-confirm').click();
      await page.waitForFunction(value => localStorage.getItem('video-localizer.project.v4') !== value, before);
    };
    const assertSingleRow = async () => {
      const cards = await page.locator('.node').evaluateAll(nodes => nodes.map(node => ({
        id: node.dataset.node, x: node.offsetLeft, y: node.offsetTop, width: node.offsetWidth,
      })));
      const steps = await page.locator('.step-jump').evaluateAll(buttons => buttons.map(button => button.dataset.step));
      assert.deepEqual(cards.map(card => card.id), steps);
      assert.equal(new Set(cards.map(card => card.y)).size, 1);
      for (let i = 1; i < cards.length; i++) {
        assert.ok(cards[i].x - (cards[i - 1].x + cards[i - 1].width) >= 90, cards[i].id);
      }
    };
    await page.goto(base);
    await page.locator('#empty-project').waitFor();
    assert.equal(await page.locator('#canvas').isVisible(), false);
    assert.equal(await page.locator('#run').isVisible(), false);
    assert.equal(await page.locator('#project-tabs [role=tab]').count(), 0);
    assert.equal(await stored(), null);
    await page.locator('#empty-new').click();
    await page.locator('#canvas').waitFor();
    assert.equal(await page.locator('.node').count(), 12);
    assert.equal(await page.locator('.link').count(), 15);
    assert.equal(await page.locator('#node-library, #library-toggle').count(), 0);
    const canvas = page.locator('#canvas');
    const canvasBounds = await canvas.boundingBox();
    assert.equal(canvasBounds.x, 0);
    assert.equal(await page.locator('#node-inspector').isVisible(), false);
    await page.locator('#task-queue-toggle').click();
    const taskDrawer = page.getByRole('dialog', { name: '任务队列' });
    const drawerBounds = await taskDrawer.boundingBox();
    assert.equal(drawerBounds.x + drawerBounds.width, page.viewportSize().width);
    assert.equal(drawerBounds.height, page.viewportSize().height);
    assert.deepEqual(await canvas.boundingBox(), canvasBounds);
    await page.keyboard.press('Escape');
    assert.equal(await taskDrawer.isVisible(), false);
    assert.equal(await page.evaluate(() => getComputedStyle(document.body).margin), '0px');
    assert.match(await page.locator('#canvas').evaluate(canvas => getComputedStyle(canvas).backgroundImage), /linear-gradient.*linear-gradient/);
    assert.ok((await page.locator('.link').evaluateAll(links => links.map(link => link.getAttribute('d'))))
      .every(path => /^M-?[\d.]+,-?[\d.]+ C(?:-?[\d.]+,-?[\d.]+ ?){3}$/.test(path)));
    assert.equal(await page.locator('.node-fields').evaluateAll(fields =>
      fields.some(field => field.scrollHeight > field.clientHeight)), false);
    const starter = await stored();
    const geometry = ({ x, y, width }) => [x, y, width];
    assert.deepEqual(geometry(starter.nodes.probe_input), [-828.67, 149.25, 333]);
    assert.deepEqual(geometry(starter.nodes.tts_align), [2095.30, -338.91, 282]);
    assert.deepEqual(geometry(starter.nodes.cover_localize), [2996.24, 699.49, 282]);

    const key = 'probe_input:asr_diarize';
    const anchorsOnLink = page.locator(`[data-edge="${key}"] .link-anchor`);
    const hits = page.locator(`[data-edge="${key}"] .link-hit`);
    const wire = page.locator('[data-from="probe_input"][data-to="asr_diarize"]');
    const originalWire = await wire.getAttribute('d');
    const midpoint = segment => hits.nth(segment).evaluate(path => {
      const point = path.getPointAtLength(path.getTotalLength() / 2).matrixTransform(path.getScreenCTM());
      return { x: point.x, y: point.y };
    });
    const anchorCenter = i => anchorsOnLink.nth(i).evaluate(circle => {
      const point = new DOMPoint(circle.cx.baseVal.value, circle.cy.baseVal.value).matrixTransform(circle.getScreenCTM());
      return { x: point.x, y: point.y };
    });
    const position = await midpoint(0);
    await page.mouse.move(position.x, position.y);
    assert.equal(await page.locator('.link-anchor-hint').getAttribute('visibility'), 'visible');
    await page.mouse.click(position.x, position.y, { button: 'right' });
    assert.equal(await anchorsOnLink.count(), 1);
    assert.equal(await hits.count(), 2);
    const first = await anchorCenter(0);
    const nodesBeforeDrag = (await stored()).nodes;
    await page.mouse.move(first.x, first.y);
    await page.mouse.down();
    await page.mouse.move(first.x + 12, first.y - 76, { steps: 5 });
    await page.mouse.up();
    assert.notEqual(await wire.getAttribute('d'), originalWire);
    assert.deepEqual((await stored()).nodes, nodesBeforeDrag);
    const next = await midpoint(1);
    await page.mouse.click(next.x, next.y, { button: 'right' });
    assert.equal(await anchorsOnLink.count(), 2);
    assert.equal(await hits.count(), 3);
    const { id, anchors: savedAnchors } = await stored();
    const points = savedAnchors[key];
    await page.getByText(/草稿已备份/).waitFor();
    const disk = await (await page.request.get(new URL(`/api/projects/${id}`, base).href)).json();
    assert.deepEqual(disk.anchors[key], points);
    await page.reload();
    await page.locator('#canvas').waitFor();
    assert.deepEqual((await stored()).anchors[key], points);
    assert.equal(await anchorsOnLink.count(), 2);
    const second = await anchorCenter(1);
    await page.mouse.click(second.x, second.y, { button: 'right' });
    assert.equal(await anchorsOnLink.count(), 1);
    await page.locator('#undo').click();
    assert.equal(await anchorsOnLink.count(), 2);
    await page.locator('#redo').click();
    assert.equal(await anchorsOnLink.count(), 1);
    const last = await anchorCenter(0);
    await page.mouse.click(last.x, last.y, { button: 'right' });
    assert.equal(await anchorsOnLink.count(), 0);
    assert.equal(await wire.getAttribute('d'), originalWire);

    const oldDraft = await stored();
    delete oldDraft.anchors;
    oldDraft.nodes.subtitle_render.params = { order: '英文在上', bilingual: true, font_size: 54 };
    const oldBranches = [[40, 162], [394, 136], [748, 162], [1102, 124], [1456, 162],
      [1810, 44], [1810, 850], [2164, 350], [2164, 1030], [2518, 163], [2872, 137], [3226, 162]];
    Object.values(oldDraft.nodes).forEach((node, i) => Object.assign(node, { x: oldBranches[i][0], y: oldBranches[i][1] }));
    oldDraft.nodes.tts_align.width = 480;
    await page.evaluate(draft => localStorage.setItem('video-localizer.project.v4', JSON.stringify(draft)), oldDraft);
    await page.reload();
    await page.locator('#canvas').waitFor();
    await assertSingleRow();
    assert.equal((await stored()).nodes.tts_align.width, 480);
    assert.deepEqual((await stored()).nodes.subtitle_render.params, { style: 'clean', layout: 'zh_bottom' });

    // Moving a card across an unrelated connection leaves that curve intact.
    const coverLink = page.locator('[data-from="probe_input"][data-to="cover_localize"]');
    const directCurve = await coverLink.getAttribute('d');
    const customDraft = await stored();
    Object.assign(customDraft.nodes.translate_blocks, { x: 1190, y: 100 });
    await page.evaluate(draft => localStorage.setItem('video-localizer.project.v4', JSON.stringify(draft)), customDraft);
    await page.reload();
    await page.locator('#canvas').waitFor();
    assert.deepEqual((await stored()).nodes, customDraft.nodes);
    assert.equal(await coverLink.getAttribute('d'), directCurve);

    // Mirror edits, history, persistence and numerical bounds.
    await inspect('翻译智能体');
    await edit('translate_blocks', 'temperature', '0.65');
    assert.equal(await page.locator('.node[data-node="translate_blocks"] [data-param="temperature"]').inputValue(), '0.65');
    await page.locator('#undo').click();
    assert.equal(await input('translate_blocks', 'temperature').inputValue(), '0.3');
    await page.locator('#redo').click();
    await page.reload();
    await inspect('翻译智能体');
    assert.equal(await input('translate_blocks', 'temperature').inputValue(), '0.65');
    await edit('translate_blocks', 'temperature', '7');
    assert.equal((await stored()).nodes.translate_blocks.params.temperature, 0.65);
    assert.equal(await input('translate_blocks', 'temperature').evaluate(e => e.validity.valid), false);
    await edit('translate_blocks', 'temperature', '0.65');
    const titles = await page.locator('.step-jump .step-title').allTextContents();
    for (const title of titles) {
      await inspect(title);
      const count = await page.locator('.node.selected .param-row').count();
      assert.ok(title === '字幕样式' ? count === 2 : count >= 5);
      assert.equal(await page.locator('.node.selected input:invalid').count(), 0);
    }
    await inspect('转写与说话人');
    await edit('asr_diarize', 'min_speakers', '2');
    await edit('asr_diarize', 'max_speakers', '1');
    assert.equal((await stored()).nodes.asr_diarize.params.max_speakers, 2);
    assert.match(await page.locator('#toast').textContent(), /最少说话人数/);

    // Drag/fold/zoom/minimap, plus help without changing the layout.
    await inspect('翻译智能体');
    const before = (await stored()).nodes.translate_blocks.x;
    const rect = await page.locator('[data-node="translate_blocks"] .node-header').boundingBox();
    await page.mouse.move(rect.x + 60, rect.y + 20);
    await page.mouse.down();
    await page.mouse.move(rect.x + 120, rect.y + 45, { steps: 5 });
    await page.mouse.up();
    assert.equal(await page.evaluate(() => getSelection().toString()), '');
    assert.ok((await stored()).nodes.translate_blocks.x > before + 40);
    await page.locator('[data-node="translate_blocks"] .node-collapse').click();
    assert.equal((await stored()).nodes.translate_blocks.collapsed, true);
    await page.locator('#undo').click();
    assert.equal((await stored()).nodes.translate_blocks.collapsed, false);
    const zoom = parseInt(await page.locator('#zoom').textContent());
    await page.locator('#zoom-in').click();
    assert.ok(parseInt(await page.locator('#zoom').textContent()) > zoom);
    const cameraMatrix = () => page.locator('#world').evaluate(world => {
      const matrix = new DOMMatrixReadOnly(getComputedStyle(world).transform);
      return { x: matrix.e, y: matrix.f, scale: matrix.a };
    });
    const beforeMinimap = await cameraMatrix();
    await page.locator('#minimap').click({ position: { x: 2, y: 2 } });
    assert.deepEqual(await cameraMatrix(), beforeMinimap);
    const viewport = await page.locator('#minimap-viewport').boundingBox();
    const grab = { x: viewport.x + viewport.width / 2, y: viewport.y + viewport.height / 2 };
    await page.mouse.click(grab.x, grab.y);
    assert.deepEqual(await cameraMatrix(), beforeMinimap);
    await page.mouse.move(grab.x, grab.y);
    await page.mouse.down();
    await page.mouse.move(grab.x + 14, grab.y + 7, { steps: 5 });
    const duringMinimap = await cameraMatrix();
    assert.ok(duringMinimap.x < beforeMinimap.x && duringMinimap.y < beforeMinimap.y);
    assert.equal(duringMinimap.scale, beforeMinimap.scale);
    await page.mouse.up();
    assert.deepEqual(await cameraMatrix(), duringMinimap);
    await page.waitForFunction(expected => {
      const { camera } = JSON.parse(localStorage.getItem('video-localizer.project.v4')).view;
      return Math.abs(camera.x - expected.x) < 0.05 && Math.abs(camera.y - expected.y) < 0.05;
    }, duringMinimap);
    assert.ok((await stored()).nodes.translate_blocks.x > before + 40);
    assert.equal(await page.locator('#layout').count(), 0);
    const help = page.getByRole('dialog', { name: '画布操作' });
    const viewBeforeHelp = await page.locator('#world').evaluate(world => world.style.transform);
    await page.locator('#help').click();
    assert.equal(await help.isVisible(), true);
    assert.equal(await help.getByText('右键连线').isVisible(), true);
    assert.equal(await help.locator('kbd').getByText('Shift').isVisible(), true);
    await page.keyboard.press('f');
    assert.equal(await page.locator('#world').evaluate(world => world.style.transform), viewBeforeHelp);
    await page.keyboard.press('Escape');
    assert.equal(await help.isVisible(), false);
    assert.equal(await page.locator('#help').evaluate(button => document.activeElement === button), true);
    await page.locator('#help').click();
    await help.getByRole('button', { name: '知道了' }).click();
    assert.equal(await help.isVisible(), false);
    assert.equal((await stored()).nodes.tts_align.width, 480);

    // A stopped workflow reports the private SRT without offering a download.
    await page.locator('#run').click();
    await page.getByText('请先在「视频输入」节点选择 MP4。', { exact: true }).waitFor();
    assert.equal(await page.locator('.node.selected .node-id').textContent(), 'probe_input');
    const runEndpoint = '**/api/workflow-runs';
    const jobId = 'a'.repeat(32);
    const jobEndpoint = `${runEndpoint}/${jobId}`;
    await page.route(runEndpoint, route => route.fulfill({ status: 202, json: {job_id: jobId} }));
    let processing = true;
    await page.route(jobEndpoint, route => route.fulfill({ json: processing ? {
      state: 'running', node: 'asr_diarize', completed_nodes: ['probe_input'], message: '正在识别英文。',
    } : {
      state: 'blocked', node: 'build_blocks', completed_nodes: ['probe_input', 'asr_diarize'],
      english_srt_ready: true, message: '断句与术语节点尚未接入，工作流已停止。',
    } }));
    await page.locator('#workflow-video').setInputFiles({
      name: 'sample.mp4', mimeType: 'video/mp4', buffer: Buffer.from('mock upload'),
    });
    await page.locator('#run').click();
    await page.locator('[data-node="asr_diarize"].is-active .node-state').waitFor();
    assert.equal(await page.locator('.node.is-active').count(), 1);
    assert.equal(await page.locator('[data-step="asr_diarize"].is-active').count(), 1);
    assert.equal(await page.locator('#draft-state').textContent(), '参数已锁定');
    assert.equal(await page.locator('#nodes :is([data-param], .node-reset, .video-input-picker button):enabled').count(), 0);
    for (const id of ['open-project', 'close-project', 'exit-workspace', 'undo', 'redo']) {
      assert.equal(await page.locator(`#${id}`).isDisabled(), true);
    }
    assert.equal(await page.locator('#fit').isEnabled(), true);
    processing = false;
    await page.getByText('工作流已停止', { exact: true }).waitFor();
    assert.equal(await page.locator('.node.is-active, .step-jump.is-active').count(), 0);
    assert.equal(await input('asr_diarize', 'model').isEnabled(), true);
    assert.equal(await page.locator('#open-project').isEnabled(), true);
    assert.equal(await page.locator('[data-node="build_blocks"].is-blocked').count(), 1);
    assert.equal(await page.locator('[data-node="asr_diarize"].is-done').count(), 1);
    assert.match(await page.locator('#events').textContent(), /断句与术语节点尚未接入/);
    await inspect('转写与说话人');
    await page.locator('.node.selected .node-preview summary').click();
    assert.match(await page.locator('.node.selected .node-preview-content').textContent(), /英文字幕初稿已保存/);
    await page.locator('#output-tab').click();
    assert.match(await page.locator('#console-output').textContent(), /已保存英文字幕中间产物/);
    assert.equal(await page.getByRole('link', {name: /下载英文 SRT/}).count(), 0);
    const privateSrt = await page.request.get(new URL(`/api/workflow-runs/${jobId}/english.srt`, base).href);
    assert.equal(privateSrt.status(), 404);
    await page.unroute(runEndpoint);
    await page.route(runEndpoint, route => route.fulfill({ status: 503, json: {message: '本地识别环境不可用。'} }));
    await page.locator('#run').click();
    await page.getByText('工作流执行失败', { exact: true }).waitFor();
    assert.match(await page.locator('#events').textContent(), /本地识别环境不可用/);
    assert.doesNotMatch(await page.locator('#events').textContent(), /英文字幕初稿已保存/);
    assert.equal(await page.locator('#run').isEnabled(), true);
    assert.equal(await input('asr_diarize', 'model').isEnabled(), true);
    await page.unroute(runEndpoint);

    // Both E nodes have separate output paths and previews.
    assert.equal(await page.locator('[data-from=subtitle_render][data-to=compose_video]').count(), 1);
    assert.equal(await page.locator('[data-from=cover_localize][data-to=collect_manifest]').count(), 1);
    assert.equal(await page.locator('[data-from=cover_localize][data-to=compose_video]').count(), 0);
    await inspect('字幕样式');
    await page.locator('.node.selected .node-preview summary').click();
    assert.equal(await page.locator('.subtitle-preview').isVisible(), true);
    const subtitleLines = page.locator('.subtitle-preview .subtitle-line');
    assert.match(await subtitleLines.first().textContent(), /Let knowledge/);
    await input('subtitle_render', 'layout').selectOption('zh_only');
    assert.deepEqual(await subtitleLines.allTextContents(), ['让知识跨越语言']);
    await input('subtitle_render', 'style').selectOption('contrast');
    assert.match(await page.locator('.node.selected .preview-heading').textContent(), /高对比底框/);
    await input('subtitle_render', 'layout').selectOption('zh_top');
    assert.deepEqual(await subtitleLines.allTextContents(), ['让知识跨越语言', 'Let knowledge cross languages.']);
    assert.equal(await page.locator('.node.selected .cover-preview').count(), 0);
    assert.equal((await stored()).nodes.cover_localize.params.enabled, false);

    // Preview uses configured colors and safely renders arbitrary title text.
    await inspect('封面本地化');
        await edit('cover_localize', 'cover_title', '<img src=x onerror=alert(1)>');
    await input('cover_localize', 'cover_color').fill('#224466');
    await input('cover_localize', 'cover_color').dispatchEvent('change');
    await page.locator('.node.selected .node-preview summary').click();
    assert.equal(await page.locator('.cover-preview h3').textContent(), '<img src=x onerror=alert(1)>');
    assert.equal(await page.locator('.cover-preview img').count(), 0);
    assert.equal(await page.locator('.node.selected .subtitle-preview').count(), 0);
    assert.equal(await page.locator('.cover-preview').evaluate(e => getComputedStyle(e).backgroundColor), 'rgb(34, 68, 102)');

    // Opening an engineering file creates an independent tab with fixed dependencies.
    assert.equal(await page.locator('.topbar #save, .topbar #export, .topbar #import').count(), 0);
    const original = await stored();
    assert.equal(original.version, 4);
    assert.equal(Object.keys(original.nodes).length, 12);
    assert.equal(original.edges.length, 15);
    const copyId = randomBytes(16).toString('hex');
    const draft = { ...structuredClone(original), id: copyId, name: '第二工程' };
    const filename = path.join(temp, 'workflow.json');
    await fs.writeFile(filename, JSON.stringify(draft));
    await logoAction('open-project');
    await page.locator('#project-file').setInputFiles(filename);
    await projectTab(copyId).waitFor();
    assert.equal(await projectTab(copyId).textContent(), '第二工程');
    assert.equal((await stored()).id, copyId);
    await edit('cover_localize', 'cover_title', '第二工程标题');
    await page.getByText(/草稿已备份/).waitFor();
    await projectTab(original.id).click();
    assert.equal((await stored()).nodes.cover_localize.params.cover_title, '<img src=x onerror=alert(1)>');
    await projectTab(copyId).click();
    assert.equal((await stored()).nodes.cover_localize.params.cover_title, '第二工程标题');
    await page.reload();
    await projectTab(copyId).waitFor();
    assert.equal(await page.locator('#project-tabs [role=tab]').count(), 2);
    assert.equal(await projectTab(copyId).getAttribute('aria-selected'), 'true');
    await page.getByRole('button', { name: '关闭工程 第二工程' }).click();
    assert.equal(await projectTab(copyId).count(), 0);
    assert.equal((await stored()).id, original.id);
    await logoAction('open-project');
    await page.getByText('暂无已关联本地文件的工程。', { exact: true }).waitFor();
    assert.equal(await page.locator('#saved-projects .saved-project').count(), 0);
    await page.locator('#project-file').setInputFiles(filename);
    await page.locator(`#project-tabs [data-project="${copyId}"][aria-selected="true"]`).waitFor();
    assert.equal((await stored()).nodes.cover_localize.params.cover_title, '<img src=x onerror=alert(1)>');

    const openInvalid = data => page.locator('#project-file').setInputFiles({
      name: 'invalid.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(data)),
    });
    await logoAction('open-project');
    const invalid = structuredClone(draft);
    invalid.nodes.tts_align.params.max_speedup = 2;
    await openInvalid(invalid);
    await page.getByText(/打开失败：配音与对齐/).waitFor();
    invalid.nodes.tts_align.params.max_speedup = 1.15;
    invalid.edges.pop();
    await openInvalid(invalid);
    await page.getByText(/连线与工作流版本不匹配/).waitFor();
    assert.equal((await stored()).id, copyId);
    await page.locator('#project-picker').getByRole('button', {name: '关闭工程选择'}).click();
    await page.locator('.node.selected .node-reset').click();
    await confirm();
    assert.equal((await stored()).nodes.cover_localize.params.cover_title, '让知识跨越语言');

    await logoAction('about-project');
    await page.getByRole('dialog', {name: '关于'}).getByRole('button', {name: '知道了'}).click();
    await logoAction('exit-workspace');
    await page.locator('#dialog-confirm').click();
    await page.locator('#empty-project').waitFor();
    await page.reload();
    assert.equal(await page.locator('#project-tabs [role=tab]').count(), 0);
    await page.locator('#empty-open').click();
    await page.getByText('暂无已关联本地文件的工程。', { exact: true }).waitFor();
    assert.equal(await page.locator('#saved-projects .saved-project').count(), 0);
    await page.locator('#project-file').setInputFiles(filename);
    await page.locator(`#project-tabs [data-project="${copyId}"][aria-selected="true"]`).waitFor();
    assert.equal((await stored()).id, copyId);
    await logoAction('open-project');
    await page.locator('#new-project-name').fill('新工程');
    await page.getByRole('dialog', {name: '打开工程'}).getByRole('button', {name: '新建工程'}).click();
    const another = await stored();
    assert.equal(another.name, '新工程');
    assert.deepEqual(another.nodes, starter.nodes);
    await logoAction('close-project');
    assert.equal((await stored()).id, copyId);
    assert.deepEqual(errors, []);
    await page.reload();
    if (process.env.WEBUI_SCREENSHOT) await page.screenshot({ path: process.env.WEBUI_SCREENSHOT });

    // Exercise real writable handles in Chromium's isolated origin storage.
    const filePage = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await filePage.addInitScript(() => {
      window.showSaveFilePicker = async () => {
        const picks = Number(sessionStorage.getItem('test-file-picks') || 0) + 1;
        sessionStorage.setItem('test-file-picks', String(picks));
        const filename = picks === 1 ? '文件工程.json' : '第二份.json';
        return (await navigator.storage.getDirectory()).getFileHandle(filename, { create: true });
      };
      window.showOpenFilePicker = async () => [
        await (await navigator.storage.getDirectory()).getFileHandle('文件工程.json'),
      ];
    });
    await filePage.goto(base);
    await filePage.locator('#empty-new').click();
    const fileTitle = filePage.locator('[data-node="cover_localize"] [data-param="cover_title"]');
    const readSavedFile = () => filePage.evaluate(async () => {
      const handle = await (await navigator.storage.getDirectory()).getFileHandle('文件工程.json');
      return JSON.parse(await (await handle.getFile()).text());
    });
    const saveFile = async () => {
      await filePage.keyboard.press('Meta+s');
      await filePage.getByText('已保存到 文件工程.json', { exact: true }).waitFor();
    };
    const editFileTitle = async value => {
      await filePage.locator('[data-step="cover_localize"]').click();
      await fileTitle.fill(value);
      await fileTitle.press('Tab');
      await filePage.getByText('有改动待保存到 文件工程.json', { exact: true }).waitFor();
    };
    await saveFile();
    assert.equal((await readSavedFile()).name, '文件工程');
    await editFileTitle('本地保存后的封面');
    await saveFile();
    assert.equal((await readSavedFile()).nodes.cover_localize.params.cover_title, '本地保存后的封面');
    await filePage.reload();
    await filePage.locator('[data-step="cover_localize"]').click();
    await fileTitle.fill('刷新后写回原文件');
    await filePage.keyboard.press('Meta+s');
    await filePage.waitForFunction(async () => {
      const handle = await (await navigator.storage.getDirectory()).getFileHandle('文件工程.json');
      const data = JSON.parse(await (await handle.getFile()).text());
      return data.nodes.cover_localize.params.cover_title === '刷新后写回原文件';
    });
    assert.equal(await filePage.evaluate(() => sessionStorage.getItem('test-file-picks')), '1');
    await filePage.evaluate(async () => {
      const handle = await (await navigator.storage.getDirectory()).getFileHandle('文件工程.json');
      const data = JSON.parse(await (await handle.getFile()).text());
      data.nodes.cover_localize.params.cover_title = '外部文件的新内容';
      const writer = await handle.createWritable();
      await writer.write(JSON.stringify(data));
      await writer.close();
    });
    await editFileTitle('内部草稿');
    await filePage.keyboard.press('Meta+s');
    await filePage.getByText(/工程文件已在外部修改/).waitFor();
    assert.equal((await readSavedFile()).nodes.cover_localize.params.cover_title, '外部文件的新内容');
    await filePage.getByRole('button', { name: '关闭工程 文件工程' }).click();
    await filePage.locator('#empty-open').click();
    await filePage.locator('#choose-project-file').click();
    await fileTitle.waitFor({ state: 'attached' });
    assert.equal(await fileTitle.inputValue(), '外部文件的新内容');
    const fileLogoAction = async id => {
      await filePage.locator('#product-logo').click();
      await filePage.locator(`#${id}`).click();
    };
    const checkRecent = async names => {
      await fileLogoAction('open-project');
      const recent = filePage.locator('#saved-projects .saved-project');
      await recent.first().waitFor();
      assert.deepEqual(await recent.allTextContents(), names);
    };
    await fileLogoAction('new-project');
    await filePage.keyboard.press('Meta+s');
    await filePage.getByText('已保存到 第二份.json', { exact: true }).waitFor();
    await fileLogoAction('new-project');
    await checkRecent(['第二份', '文件工程']);
    await filePage.locator('#saved-projects').getByRole('button', { name: '文件工程', exact: true }).click();
    await filePage.getByRole('dialog', { name: '打开工程' }).waitFor({ state: 'hidden' });
    await checkRecent(['文件工程', '第二份']);
    await filePage.reload();
    await filePage.locator('#canvas').waitFor();
    await checkRecent(['文件工程', '第二份']);
    await filePage.close();

    const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, reducedMotion: 'reduce' });
    await mobile.goto(base);
    assert.equal(await mobile.evaluate(() => document.documentElement.scrollWidth), 390);
    await mobile.locator('#empty-project').waitFor();
    assert.equal(await mobile.locator('#canvas').isVisible(), false);
    await mobile.locator('#empty-new').click();
    await mobile.locator('#canvas').waitFor();
    assert.equal(await mobile.locator('#node-library, #library-toggle').count(), 0);
    await mobile.locator('#help').click();
    const mobileHelp = mobile.getByRole('dialog', { name: '画布操作' });
    assert.equal(await mobileHelp.isVisible(), true);
    await mobileHelp.getByRole('button', { name: '关闭画布帮助' }).click();
    assert.equal(await mobileHelp.isVisible(), false);
    await mobile.locator('.step-jump').filter({ hasText: '封面本地化' }).click();
    assert.equal(await mobile.locator('#node-inspector').isVisible(), false);
    await mobile.locator('.node.selected .node-preview summary').click();
    assert.equal(await mobile.locator('.cover-preview').isVisible(), true);
    await mobile.locator('#task-queue-toggle').click();
    assert.equal(await mobile.locator('#node-inspector').isVisible(), true);
    await mobile.locator('#inspector-close').click();
    assert.equal(await mobile.locator('#node-inspector').isVisible(), false);
    await mobile.locator('#run').click();
    await mobile.getByText('请先在「视频输入」节点选择 MP4。', { exact: true }).waitFor();
    assert.equal(await mobile.locator('[data-node=probe_input]').getByRole('button', {name: '选择视频', exact: true}).isVisible(), true);
    if (process.env.WEBUI_SCREENSHOT) await mobile.screenshot({ path: process.env.WEBUI_SCREENSHOT.replace('.png', '-mobile.png') });
    console.log('PASS: node schemas, parameter validation, persistence/history, canvas, project tabs, workflow stop/API failure, previews and desktop/mobile.');
  } finally {
    await browser.close();
    await fs.rm(temp, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
