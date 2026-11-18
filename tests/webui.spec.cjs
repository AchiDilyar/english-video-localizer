// Requires Playwright. Start the local WebUI service before running this file.
// WEBUI_URL selects the server; WEBUI_SCREENSHOT optionally saves a desktop image.
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const base = process.env.WEBUI_URL || 'http://127.0.0.1:8765';
(async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, reducedMotion: 'reduce' });
    await page.addInitScript(() => {
      const data = sessionStorage.getItem('test-layout-on-reload');
      if (!data) return;
      sessionStorage.removeItem('test-layout-on-reload');
      const { layout, legacy } = JSON.parse(data);
      if (legacy) localStorage.removeItem('video-localizer.canvas.v1');
      localStorage.setItem(legacy ? 'video-localizer.project.v4' : 'video-localizer.canvas.v1', JSON.stringify(layout));
    });
    const loadLayout = async (layout, legacy = false) => {
      await page.evaluate(fixture => sessionStorage.setItem('test-layout-on-reload', JSON.stringify(fixture)), {layout, legacy});
      await page.reload();
      await page.locator('#canvas').waitFor();
    };
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    const stored = () => page.evaluate(() => JSON.parse(localStorage.getItem('video-localizer.canvas.v1')));
    const inspect = async title => {
      await page.locator('.step-jump').filter({ hasText: title }).click();
      assert.equal(await page.locator('.node.selected .node-title').textContent(), title);
    };
    const input = (node, key) => page.locator(`[data-node="${node}"] [data-param="${key}"]`);
    await page.goto(base);
    await page.locator('#canvas').waitFor();
    assert.equal(await page.locator('#run').isVisible(), true);
    assert.equal(await page.locator('#project-tabs, #project-picker, #empty-new').count(), 0);
    const retiredProjects = await page.request.get(new URL('/api/projects', base).href);
    assert.equal(retiredProjects.status(), 404);
    const graph = await (await page.request.get(new URL('/api/workflow-schema', base).href)).json();
    assert.deepEqual(await page.locator('.node').evaluateAll(cards => cards.map(card => card.dataset.node)), graph.nodes);
    assert.deepEqual(await page.locator('.link').evaluateAll(wires =>
      wires.map(wire => [wire.dataset.from, wire.dataset.to])), graph.edges);
    assert.deepEqual(graph.nodes, [
      'probe_input', 'asr_diarize', 'b_environment', 'build_blocks', 'translate_blocks', 'review_blocks',
      'repair_blocks', 'tts_align', 'subtitle_cover', 'mix_background', 'compose_video',
    ]);
    assert.deepEqual(graph.edges.slice(5), [
      ['review_blocks', 'repair_blocks'], ['repair_blocks', 'tts_align'],
      ['tts_align', 'subtitle_cover'], ['subtitle_cover', 'mix_background'],
      ['b_environment', 'mix_background'], ['mix_background', 'compose_video'],
    ]);
    const modeResponse = await page.request.get(new URL('/api/workflow-modes', base).href);
    assert.equal(modeResponse.ok(), true);
    const { modes } = await modeResponse.json();
    assert.deepEqual(Object.keys(modes), graph.nodes);
    for (const [node, mode] of Object.entries(modes)) {
      const label = mode === 'mock' ? '模拟' : '真实';
      await page.locator(`[data-node="${node}"] .node-mode[data-mode="${mode}"]`)
        .filter({ hasText: label }).waitFor();
    }
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
    assert.deepEqual(geometry(starter.nodes.subtitle_cover), [2564.34, 171.28, 282]);

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
    const { anchors: savedAnchors } = await stored();
    const points = savedAnchors[key];
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
    oldDraft.version = 4;
    oldDraft.nodes.subtitle_render = { ...oldDraft.nodes.subtitle_cover, x: 2345, y: 185,
      params: { order: '英文在上', bilingual: true, font_size: 54 } };
    oldDraft.nodes.cover_localize = { ...oldDraft.nodes.subtitle_cover };
    oldDraft.nodes.edit_assets = { ...oldDraft.nodes.subtitle_cover };
    oldDraft.nodes.collect_manifest = { ...oldDraft.nodes.subtitle_cover };
    oldDraft.nodes.package_zip = { ...oldDraft.nodes.subtitle_cover };
    delete oldDraft.nodes.subtitle_cover;
    oldDraft.nodes.tts_align.width = 480;
    oldDraft.view.selected = 'subtitle_render';
    oldDraft.anchors = {
      'subtitle_render:compose_video': [{ x: 2650, y: 160 }],
      'review_blocks:edit_assets': [{ x: 2100, y: 300 }],
      'compose_video:collect_manifest': [{ x: 3500, y: 300 }],
      'collect_manifest:package_zip': [{ x: 3800, y: 300 }],
    };
    await loadLayout(oldDraft, true);
    const migrated = await stored();
    assert.equal(migrated.nodes.tts_align.width, 480);
    assert.deepEqual(geometry(migrated.nodes.subtitle_cover), [2345, 185, 282]);
    assert.deepEqual(Object.keys(migrated.nodes), graph.nodes);
    assert.equal(migrated.nodes.subtitle_cover.params, undefined);
    assert.deepEqual(migrated.anchors, { 'subtitle_cover:compose_video': [{ x: 2650, y: 160 }] });

    // Moving a card across an unrelated connection leaves that curve intact.
    const unaffectedLink = page.locator('[data-from="review_blocks"][data-to="subtitle_cover"]');
    const directCurve = await unaffectedLink.getAttribute('d');
    const customDraft = await stored();
    Object.assign(customDraft.nodes.translate_blocks, { x: 970, y: 100 });
    await loadLayout(customDraft);
    assert.deepEqual((await stored()).nodes, customDraft.nodes);
    assert.equal(await unaffectedLink.getAttribute('d'), directCurve);

    // Editable fields and defaults come from the same backend settings snapshot.
    for (const node of ['probe_input', 'asr_diarize']) {
      const settings = await (await page.request.get(new URL(`/api/workflow-settings/${node}`, base).href)).json();
      const controls = page.locator(`[data-node="${node}"] [data-param]`);
      await controls.first().waitFor({state: 'attached'});
      assert.deepEqual(await controls.evaluateAll(elements => elements.map(el => el.name)),
        settings.fields.filter(field => !field.readonly).map(field => field.key));
    }
    await inspect('翻译智能体');
    await page.locator('.node.selected').getByText('DeepSeek 模型', {exact: true}).waitFor();
    assert.equal(await page.locator('.node.selected [data-param]').count(), 0);
    await inspect('转写与说话人');
    const endpoint = '**/api/workflow-settings/asr_diarize';
    const asrSettings = await (await page.request.get(new URL('/api/workflow-settings/asr_diarize', base).href)).json();
    const speakerField = input('asr_diarize', 'num_speakers');
    await speakerField.fill('33');
    assert.equal(await speakerField.evaluate(e => e.validity.valid), false);
    await speakerField.fill('2');
    const browserWrite = page.waitForRequest(request => request.url().endsWith('/asr_diarize') && request.method() === 'PUT');
    // Exercise the form without changing the user's shared TOML.
    await page.route(endpoint, route => route.request().method() === 'PUT'
      ? route.fulfill({ json: {...asrSettings, fields: asrSettings.fields.map(field =>
          field.key === 'num_speakers' ? {...field, value: 2} : field)} })
      : route.continue());
    await speakerField.press('Tab');
    const { revision, values } = (await browserWrite).postDataJSON();
    assert.equal(revision, asrSettings.revision);
    assert.equal(values.num_speakers, 2);
    assert.equal(values.community1_python, undefined);
    await page.waitForFunction(() => !document.querySelector('#run').disabled);
    assert.equal(await page.getByText('后端配置已保存。', {exact: true}).count(), 0);
    assert.equal(await speakerField.inputValue(), '2');
    assert.equal((await stored()).nodes.asr_diarize.params, undefined);
    await page.unroute(endpoint);

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
      const { camera } = JSON.parse(localStorage.getItem('video-localizer.canvas.v1')).view;
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
    await page.route(runEndpoint, route => {
      assert.equal(route.request().method(), 'POST');
      assert.equal(route.request().headers()['x-project-id'], undefined);
      return route.fulfill({ status: 202, json: {job_id: jobId} });
    });
    let processing = true;
    const backendLog = Buffer.from('[INFO] CLI ready\n[INFO] 后端字幕已写出\n');
    const split = Buffer.byteLength('[INFO] CLI ready\n[INFO] ') + 1;
    await page.route(`${jobEndpoint}/logs?*`, route => {
      const offset = Number(new URL(route.request().url()).searchParams.get('offset'));
      return route.fulfill({
        status: 200, headers: {'X-Log-Pending': processing ? '1' : '0'},
        body: backendLog.subarray(offset, processing ? split : backendLog.length),
      });
    });
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
    assert.equal(await page.locator('#nodes :is([data-param], .node-config-actions button, .video-input-picker button):enabled').count(), 0);
    for (const id of ['undo', 'redo']) {
      assert.equal(await page.locator(`#${id}`).isDisabled(), true);
    }
    assert.equal(await page.locator('#fit').isEnabled(), true);
    await page.locator('#events').filter({hasText:/CLI ready/}).waitFor();
    processing = false;
    await page.getByText('工作流已停止', { exact: true }).waitFor();
    assert.equal(await page.locator('.node.is-active, .step-jump.is-active').count(), 0);
    assert.equal(await input('asr_diarize', 'model_dir').isEnabled(), true);
    assert.equal(await page.locator('[data-node="build_blocks"].is-blocked').count(), 1);
    assert.equal(await page.locator('[data-node="asr_diarize"].is-done').count(), 1);
    assert.match(await page.locator('#log-notice').textContent(), /断句与术语节点尚未接入/);
    await page.locator('#events').filter({hasText:/后端字幕已写出/}).waitFor();
    assert.equal(await page.locator('#events').textContent(), backendLog.toString());
    await inspect('转写与说话人');
    assert.equal(await page.locator('.node.selected .node-preview').count(), 0);
    await page.locator('#output-tab').click();
    assert.match(await page.locator('#console-output').textContent(), /已保存英文字幕中间产物/);
    assert.equal(await page.getByRole('link', {name: /下载英文 SRT/}).count(), 0);
    const privateSrt = await page.request.get(new URL(`/api/workflow-runs/${jobId}/english.srt`, base).href);
    assert.equal(privateSrt.status(), 404);
    await page.unroute(runEndpoint);
    await page.route(runEndpoint, route => route.fulfill({ status: 503, json: {message: '本地识别环境不可用。'} }));
    await page.locator('#run').click();
    await page.getByText('工作流执行失败', { exact: true }).waitFor();
    assert.match(await page.locator('#log-notice').textContent(), /本地识别环境不可用/);
    assert.equal(await page.locator('#events').textContent(), '');
    assert.equal(await page.locator('#run').isEnabled(), true);
    assert.equal(await input('asr_diarize', 'model_dir').isEnabled(), true);
    await page.unroute(runEndpoint);

    let assReady = false;
    await page.unroute(jobEndpoint);
    await page.route(jobEndpoint, route => route.fulfill({ json: {
      state: assReady ? 'blocked' : 'running',
      completed_nodes: assReady ? ['review_blocks', 'subtitle_cover'] : ['review_blocks'],
      subtitle_srt_ready: true, final_video_ready: false,
      message: assReady ? '烧录字幕 ASS 已生成，成片尚未生成。' : '正在执行后端工作流。',
    } }));
    await page.route(runEndpoint, route => route.fulfill({ status: 202, json: { job_id: jobId } }));
    await page.locator('#run').click();
    await inspect('字幕压制准备');
    await page.locator('#output-tab').click();
    await page.locator('#console-output').filter({ hasText: '等待烧录字幕 burnin.ass' }).waitFor();
    assert.equal(await page.locator('[data-node="subtitle_cover"].is-done').count(), 0);
    assReady = true;
    await page.getByText('工作流已停止', { exact: true }).waitFor();
    await page.locator('[data-node="subtitle_cover"].is-done .node-state').filter({ hasText: '已完成' }).waitFor();
    assert.match(await page.locator('#console-output').textContent(), /subtitles\/burnin\.ass 已生成/);
    assert.equal(await page.locator('#console-output').getByRole('link', { name: '下载成片 MP4' }).count(), 0);
    await page.reload();
    await page.locator('[data-node="subtitle_cover"].is-done').waitFor();
    await page.locator('#workflow-video').setInputFiles({
      name: 'sample.mp4', mimeType: 'video/mp4', buffer: Buffer.from('mock upload'),
    });
    await page.unroute(runEndpoint);

    const completed = {
      state: 'complete', completed_nodes: graph.nodes, final_video_ready: true, message: '成片已生成。',
    };
    const videoPath = `/api/workflow-runs/${jobId}/final-video`;
    await page.unroute(jobEndpoint);
    await page.route(jobEndpoint, route => route.fulfill({ json: completed }));
    await page.route(runEndpoint, route => route.fulfill({ status: 202, json: { job_id: jobId } }));
    await page.route(`${runEndpoint}?offset=*`, route => route.fulfill({
      json: {
        jobs: [{ id: jobId, filename: 'sample.mp4', created_at: 0, ...completed }],
        total: 1, has_finished: true,
      },
    }));
    await page.locator('#run').click();
    await page.getByText('工作流已完成', { exact: true }).waitFor();
    await page.locator('#output-tab').click();
    const outputDownload = page.locator('#console-output').getByRole('link', { name: '下载成片 MP4' });
    await outputDownload.waitFor({ state: 'attached' });
    assert.equal(await outputDownload.getAttribute('href'), videoPath);
    await page.locator('#task-queue-toggle').click();
    await page.locator(`[data-job-id="${jobId}"]`).click();
    const queueDownload = taskDrawer.getByRole('link', { name: '下载成片 MP4' });
    assert.equal(await queueDownload.getAttribute('href'), videoPath);
    await page.keyboard.press('Escape');
    await page.unroute(runEndpoint);

    await inspect('字幕压制准备');
    const styleOptions = input('subtitle_cover', 'style').locator('option');
    const layoutOptions = input('subtitle_cover', 'layout').locator('option');
    await styleOptions.first().waitFor({state: 'attached'});
    assert.deepEqual(await styleOptions.allTextContents(), ['默认样式', '高对比底框', '宋体细描边', '简约精致']);
    assert.deepEqual(await layoutOptions.allTextContents(), ['仅译文', '双语 · 译文在上', '双语 · 译文在下']);
    const subtitleSettingsUrl = '**/api/workflow-settings/subtitle_cover';
    const subtitleSettings = await (await page.request.get(new URL('/api/workflow-settings/subtitle_cover', base).href)).json();
    const savedStyle = subtitleSettings.fields.find(field => field.key === 'style').value;
    const savedLayout = subtitleSettings.fields.find(field => field.key === 'layout').value;
    const savedFade = subtitleSettings.fields.find(field => field.key === 'fade_enabled').value;
    const nextLayout = savedLayout === 'zh_bottom' ? 'zh_top' : 'zh_bottom';
    await page.route(subtitleSettingsUrl, route => {
      assert.deepEqual(route.request().postDataJSON(), {
        revision: subtitleSettings.revision, values: { style: savedStyle, layout: nextLayout, fade_enabled: savedFade },
      });
      return route.fulfill({ json: {
        ...subtitleSettings,
        fields: subtitleSettings.fields.map(field => ({
          ...field, value: field.key === 'layout' ? nextLayout : field.value,
        })),
      } });
    });
    assert.equal(await page.locator('.node.selected .node-config-save').count(), 0);
    const autoSaved = page.waitForResponse(response =>
      response.url().endsWith('/api/workflow-settings/subtitle_cover') && response.request().method() === 'PUT');
    await input('subtitle_cover', 'layout').selectOption(nextLayout);
    assert.equal((await autoSaved).ok(), true);
    await page.waitForFunction(() => !document.querySelector('#run').disabled);
    assert.equal(await page.getByText('后端配置已保存。', {exact: true}).count(), 0);
    assert.equal(await input('subtitle_cover', 'layout').inputValue(), nextLayout);
    const previewLines = page.locator('[data-node="subtitle_cover"] .subtitle-style-line');
    await previewLines.nth(1).waitFor();
    assert.deepEqual(await previewLines.evaluateAll(lines => lines.map(line => line.lang)),
      nextLayout === 'zh_bottom' ? ['en', 'zh-Hans'] : ['zh-Hans', 'en']);
    await page.unroute(subtitleSettingsUrl);

    assert.equal(await page.locator('#product-logo').evaluate(logo => logo.tabIndex), -1);
    await page.locator('#product-logo').click();
    assert.equal(await page.locator('#workbench-menu, #about-dialog').count(), 0);
    for (const colorScheme of ['light', 'dark', 'light']) {
      await page.emulateMedia({ colorScheme });
      assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme), colorScheme);
    }
    assert.deepEqual(errors, []);
    if (process.env.WEBUI_SCREENSHOT) await page.screenshot({ path: process.env.WEBUI_SCREENSHOT });

    const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, reducedMotion: 'reduce' });
    await mobile.goto(base);
    assert.equal(await mobile.evaluate(() => document.documentElement.scrollWidth), 390);
    await mobile.locator('#canvas').waitFor();
    assert.equal(await mobile.locator('#node-library, #library-toggle').count(), 0);
    await mobile.locator('#help').click();
    const mobileHelp = mobile.getByRole('dialog', { name: '画布操作' });
    assert.equal(await mobileHelp.isVisible(), true);
    await mobileHelp.getByRole('button', { name: '关闭画布帮助' }).click();
    assert.equal(await mobileHelp.isVisible(), false);
    await mobile.locator('.step-jump').filter({ hasText: '字幕压制准备' }).click();
    assert.equal(await mobile.locator('#node-inspector').isVisible(), false);
    await mobile.locator('.node.selected [data-param="style"]').waitFor();
    await mobile.locator('#task-queue-toggle').click();
    assert.equal(await mobile.locator('#node-inspector').isVisible(), true);
    await mobile.locator('#inspector-close').click();
    assert.equal(await mobile.locator('#node-inspector').isVisible(), false);
    await mobile.locator('#run').click();
    await mobile.getByText('请先在「视频输入」节点选择 MP4。', { exact: true }).waitFor();
    assert.equal(await mobile.locator('[data-node=probe_input]').getByRole('button', {name: '选择视频', exact: true}).isVisible(), true);
    if (process.env.WEBUI_SCREENSHOT) await mobile.screenshot({ path: process.env.WEBUI_SCREENSHOT.replace('.png', '-mobile.png') });
    console.log('PASS: direct workbench launch, backend topology and settings, canvas persistence, task logs, subtitles and desktop/mobile.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
