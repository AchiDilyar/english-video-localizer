// Requires Playwright. Start the local WebUI service before running this file.
// WEBUI_URL selects the server; WEBUI_SCREENSHOT optionally saves a desktop image.
const assert = require('node:assert/strict');
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
    const stored = () => page.evaluate(() => JSON.parse(localStorage.getItem('video-localizer.workflow.v2')));
    const inspect = async title => {
      await page.locator('.library-item').filter({ hasText: title }).click();
      assert.equal(await page.locator('#detail-name').textContent(), title);
    };
    const input = (node, key) => page.locator(`#inspector-content [data-owner="${node}"][data-param="${key}"]`);
    const edit = async (node, key, value) => { await input(node, key).fill(value); await input(node, key).press('Tab'); };
    const confirm = async () => {
      const before = JSON.stringify(await stored());
      await page.locator('#dialog-confirm').click();
      await page.waitForFunction(value => localStorage.getItem('video-localizer.workflow.v2') !== value, before);
    };
    await page.goto(base);
    assert.equal(await page.locator('.node').count(), 11);
    assert.equal(await page.locator('.link').count(), 13);
    assert.equal(await page.evaluate(() => getComputedStyle(document.body).margin), '0px');

    // Mirror edits, history, persistence and numerical bounds.
    await edit('translate_blocks', 'temperature', '0.65');
    assert.equal(await page.locator('.node[data-node="translate_blocks"] [data-param="temperature"]').inputValue(), '0.65');
    await page.locator('#undo').click();
    assert.equal(await input('translate_blocks', 'temperature').inputValue(), '0.3');
    await page.locator('#redo').click();
    await page.reload();
    assert.equal(await input('translate_blocks', 'temperature').inputValue(), '0.65');
    await edit('translate_blocks', 'temperature', '7');
    assert.equal((await stored()).nodes.translate_blocks.params.temperature, 0.65);
    assert.equal(await input('translate_blocks', 'temperature').evaluate(e => e.validity.valid), false);
    await edit('translate_blocks', 'temperature', '0.65');
    const titles = await page.locator('.library-item > span:nth-child(2)').allTextContents();
    for (const title of titles) {
      await inspect(title);
      assert.ok(await page.locator('.param-row').count() >= 7);
      assert.equal(await page.locator('#inspector-content input:invalid').count(), 0);
    }
    await inspect('转写与说话人');
    await edit('asr_diarize', 'min_speakers', '2');
    await edit('asr_diarize', 'max_speakers', '1');
    assert.equal((await stored()).nodes.asr_diarize.params.max_speakers, 2);
    assert.match(await page.locator('#toast').textContent(), /最少说话人数/);

    // Drag/fold/zoom/minimap/layout.
    await inspect('翻译智能体');
    const before = (await stored()).nodes.translate_blocks.x;
    const rect = await page.locator('[data-node="translate_blocks"] .node-header').boundingBox();
    await page.mouse.move(rect.x + 60, rect.y + 20);
    await page.mouse.down();
    await page.mouse.move(rect.x + 120, rect.y + 45, { steps: 5 });
    await page.mouse.up();
    assert.ok((await stored()).nodes.translate_blocks.x > before + 40);
    await page.locator('[data-node="translate_blocks"] .node-collapse').click();
    assert.equal((await stored()).nodes.translate_blocks.collapsed, true);
    await page.locator('#undo').click();
    assert.equal((await stored()).nodes.translate_blocks.collapsed, false);
    const zoom = parseInt(await page.locator('#zoom').textContent());
    await page.locator('#zoom-in').click();
    assert.ok(parseInt(await page.locator('#zoom').textContent()) > zoom);
    await page.locator('#minimap').click({ position: { x: 50, y: 50 } });
    await page.locator('#layout').click();
    assert.equal((await stored()).nodes.translate_blocks.x, 430);

    // Real LangGraph mock updates and API failure recovery.
    await page.locator('#run').click();
    await page.getByText('模拟完成 · 4 次节点更新', { exact: true }).waitFor();
    assert.equal(await page.locator('#events li').count(), 5);
    assert.match(await page.locator('#events').textContent(), /审校退回.*请勿拔下线缆.*审校通过/);
    await inspect('翻译智能体');
    await page.locator('[data-inspect-tab="preview"]').click();
    assert.match(await page.locator('#inspector-content').textContent(), /请勿拔下线缆/);
    await page.locator('#output-tab').click();
    assert.match(await page.locator('#console-output').textContent(), /fixed-mock-demo/);
    await page.route('**/api/demo', route => route.fulfill({ status: 503, body: 'unavailable' }));
    await page.locator('#run').click();
    await page.getByText('模拟失败', { exact: true }).waitFor();
    assert.match(await page.locator('#events').textContent(), /503/);
    assert.equal(await page.locator('#run').isEnabled(), true);
    await page.unroute('**/api/demo');

    // Preview uses configured colors and safely renders arbitrary title text.
    await inspect('字幕与封面');
    await page.locator('[data-inspect-tab="params"]').click();
    await edit('subtitle_cover', 'cover_title', '<img src=x onerror=alert(1)>');
    await input('subtitle_cover', 'cover_color').fill('#224466');
    await input('subtitle_cover', 'cover_color').dispatchEvent('change');
    await page.locator('[data-inspect-tab="preview"]').click();
    assert.equal(await page.locator('.cover-preview h3').textContent(), '<img src=x onerror=alert(1)>');
    assert.equal(await page.locator('.cover-preview img').count(), 0);
    assert.equal(await page.locator('.cover-preview').evaluate(e => getComputedStyle(e).backgroundColor), 'rgb(34, 68, 102)');

    // Export/import round trip, invalid imports, preset/reset and searching.
    const pending = page.waitForEvent('download');
    await page.locator('#export').click();
    const filename = path.join(temp, 'workflow.json');
    await (await pending).saveAs(filename);
    const draft = JSON.parse(await fs.readFile(filename, 'utf8'));
    assert.equal(Object.keys(draft.nodes).length, 11);
    await page.locator('#preset').selectOption('quick');
    await page.locator('#apply-preset').click();
    await confirm();
    assert.equal((await stored()).nodes.asr_diarize.params.model, 'base.en');
    await page.locator('#import-file').setInputFiles(filename);
    await confirm();
    assert.equal((await stored()).nodes.asr_diarize.params.model, 'large-v3');
    assert.equal((await stored()).nodes.subtitle_cover.params.cover_title, '<img src=x onerror=alert(1)>');
    const importObject = data => page.locator('#import-file').setInputFiles({ name: 'invalid.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(data)) });
    draft.nodes.tts_align.params.max_speedup = 2;
    await importObject(draft);
    await page.getByText(/导入失败：配音与对齐/).waitFor();
    assert.equal((await stored()).nodes.tts_align.params.max_speedup, 1.15);
    draft.nodes.tts_align.params.max_speedup = 1.15;
    draft.nodes.translate_blocks.params.api_key = 'unknown-field';
    await importObject(draft);
    await page.getByText(/包含未知参数/).waitFor();
    await page.locator('#reset-node').click();
    await confirm();
    assert.equal((await stored()).nodes.subtitle_cover.params.cover_title, '让知识跨越语言');
    await page.locator('#search').fill('tts');
    assert.equal(await page.locator('.library-item').count(), 1);
    await page.locator('#search').fill('不存在的节点');
    assert.match(await page.locator('#library-list').textContent(), /没有匹配/);
    await page.locator('#search').fill('');
    assert.deepEqual(errors, []);
    await page.reload();
    await page.locator('#run').click();
    await page.getByText('模拟完成 · 4 次节点更新', { exact: true }).waitFor();
    if (process.env.WEBUI_SCREENSHOT) await page.screenshot({ path: process.env.WEBUI_SCREENSHOT });

    const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, reducedMotion: 'reduce' });
    await mobile.goto(base);
    assert.equal(await mobile.evaluate(() => document.documentElement.scrollWidth), 390);
    await mobile.locator('#library-toggle').click();
    await mobile.locator('.library-item').filter({ hasText: '字幕与封面' }).click();
    assert.equal(await mobile.locator('.inspector').isVisible(), true);
    await mobile.locator('[data-inspect-tab="preview"]').click();
    assert.equal(await mobile.locator('.cover-preview').isVisible(), true);
    await mobile.locator('#inspector-close').click();
    assert.equal(await mobile.locator('.inspector').isVisible(), false);
    await mobile.locator('#run').click();
    await mobile.getByText('模拟完成 · 4 次节点更新', { exact: true }).waitFor();
    if (process.env.WEBUI_SCREENSHOT) await mobile.screenshot({ path: process.env.WEBUI_SCREENSHOT.replace('.png', '-mobile.png') });
    console.log('PASS: node schemas, parameter validation, persistence/history, canvas, import/export, mock/API failure, previews and desktop/mobile.');
  } finally {
    await browser.close();
    await fs.rm(temp, { recursive: true, force: true });
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
