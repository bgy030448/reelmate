import assert from 'node:assert/strict';
import { execFileSync, spawn } from 'node:child_process';
import { once } from 'node:events';
import { closeSync, mkdirSync, mkdtempSync, openSync, readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const require = createRequire(import.meta.url);
const { chromium } = require(process.env.REELMATE_PLAYWRIGHT || 'playwright');
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const python = process.env.REELMATE_PYTHON ||
  join(root, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
const port = Number(process.env.REELMATE_TEST_PORT || 8502);
const url = 'http://127.0.0.1:' + port;
const temporary = join(root, 'tmp');
mkdirSync(temporary, { recursive: true });
const work = mkdtempSync(join(temporary, 'browser-'));
const ffmpeg = execFileSync(python, ['-c', 'from reelmate.media import executable; print(executable("ffmpeg"))'],
  { cwd: root, encoding: 'utf8' }).trim();
const sample = (color, name, audio = false) => {
  const file = join(work, name);
  const options = ['-v', 'error', '-f', 'lavfi', '-i', 'color=' + color + ':s=320x240:d=6:r=30'];
  if (audio) options.push('-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=6');
  execFileSync(ffmpeg, [...options, '-c:v', 'libx264', '-c:a', 'aac', '-shortest', file], { cwd: root });
  return file;
};
const sources = [sample('red', '원본 레드.mp4', true), sample('blue', '원본 블루.mp4')];
const reference = sample('orange', '스타일 A.mp4');

const log = join(work, 'streamlit.log');
let server;
async function startServer() {
  const logfile = openSync(log, 'a');
  server = spawn(python, [
    '-m', 'streamlit', 'run', 'streamlit_reelmate.py', '--server.address', '127.0.0.1',
    '--server.port', String(port), '--server.fileWatcherType', 'none',
  ], {
    cwd: root, windowsHide: true, stdio: ['ignore', logfile, logfile],
    env: { ...process.env, PYTHONUTF8: '1', REELMATE_SINGLE_USER: '1', REELMATE_DATA_DIR: join(work, 'data') },
  });
  closeSync(logfile);
  for (let attempt = 0; attempt < 60; attempt++) {
    if (server.exitCode !== null) throw new Error('Streamlit exited before startup.');
    try {
      const response = await fetch(url + '/_stcore/health');
      if (response.ok) return;
    } catch {
      // Poll until the test server is ready.
    }
    await delay(250);
  }
  throw new Error('Streamlit health endpoint did not respond.');
}

async function stopServer() {
  if (server && server.exitCode === null && server.signalCode === null) {
    const exited = once(server, 'exit');
    server.kill();
    await exited;
  }
}

let browser;
let page;
try {
  await startServer();
  browser = await chromium.launch({
    headless: true, executablePath: process.env.REELMATE_TEST_BROWSER || undefined,
  });
  page = await browser.newPage({ viewport: { width: 1460, height: 950 }, acceptDownloads: true });
  page.setDefaultTimeout(25000);
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(url);
  const studio = page.frameLocator('iframe[title$=".studio"]');
  const button = (name) => studio.getByRole('button', { name, exact: true });
  const stepButton = (name) => studio.getByRole('navigation', { name: '프로젝트 단계' })
    .getByRole('button', { name: new RegExp(name + '$') });
  const field = (name) => studio.getByLabel(name, { exact: true });
  const heading = (name) => studio.getByRole('heading', { name, exact: true });
  const notice = (text) => studio.getByText(text, { exact: false }).first().waitFor();
  async function checkStepButtons(buttons, enabled) {
    for (const item of buttons) assert.equal(await item.isEnabled(), enabled, await item.textContent());
  }
  const reviewButtons = [stepButton('검토'), button('검토로 이동')];
  const exportButtons = [stepButton('내보내기'), button('내보내기로 이동')];
  async function excludeCandidates(excluded) {
    const candidates = studio.getByLabel('편집에서 제외', { exact: true });
    for (let i = 0; i < await candidates.count(); i++) await candidates.nth(i).setChecked(excluded);
  }
  async function verifyNarrowPage() {
    await page.setViewportSize({ width: 390, height: 844 });
    const widths = await studio.locator('html').evaluate((html) => [html.scrollWidth, html.clientWidth]);
    assert(widths[0] <= widths[1], 'Mobile viewport has horizontal overflow.');
    await page.setViewportSize({ width: 1460, height: 950 });
  }

  await heading('프로젝트 설정').waitFor();
  await page.screenshot({ path: join(work, 'desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await delay(400);
  const widths = await studio.locator('html').evaluate((html) => [html.scrollWidth, html.clientWidth]);
  assert(widths[0] <= widths[1], 'Mobile viewport has horizontal overflow.');
  await page.screenshot({ path: join(work, 'mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1460, height: 950 });

  await studio.getByLabel(/브랜드명/).fill('릴메이트 테스트');
  await studio.getByLabel(/제품명/).fill('수분 크림');
  await field('목표 영상 길이 (초)').fill('10');
  await button('저장하고 자료 등록').click();
  await heading('작업 자료 등록').waitFor();

  await field('촬영 원본 파일').setInputFiles(sources);
  await notice('자료 2개를 등록했습니다.');
  await field('완성 레퍼런스 파일').setInputFiles(reference);
  await heading('스타일 A.mp4').waitFor();
  await field('브랜드 가이드 파일').setInputFiles({
    name: '브랜드 가이드.txt', mimeType: 'text/plain', buffer: Buffer.from('첫 3초 내에 제품을 소개합니다.\n자막에 유료 광고를 표시합니다.'),
  });
  await notice('가이드 원문 · 브랜드 가이드.txt');

  await button('규칙 추가').click();
  await studio.locator('.rule-card').nth(0).getByLabel('규칙 유형').selectOption('product_deadline');
  await button('규칙 추가').click();
  await studio.locator('.rule-card').nth(1).getByLabel('규칙 유형').selectOption('required_text');
  await studio.locator('.rule-card').nth(1).getByLabel('규칙 내용').fill('유료 광고');
  await button('규칙 저장').click();
  await notice('브랜드 규칙을 저장했습니다.');
  await field('규칙을 확인했습니다.').check();
  await button('규칙 승인').click();
  await notice('브랜드 규칙을 승인했습니다.');
  await verifyNarrowPage();

  await button('분석으로 이동').click();
  await heading('영상 분석').waitFor();
  await stepButton('검토').click();
  await heading('편집안 검토').waitFor();
  await notice('편집안이 비어 있습니다');
  await checkStepButtons(exportButtons, false);
  await button('분석').click();
  await button('스타일 측정').click();
  await notice('레퍼런스 측정을 마쳤습니다.');
  await button('스타일 초안 열기').click();
  await heading('스타일 측정 초안').waitFor();
  await field('스타일 이름').fill('릴메이트 스타일');
  await field('검토한 스타일을 프로젝트에 사용하도록 승인').check();
  await button('스타일 저장').click();
  await heading('릴메이트 스타일').first().waitFor();
  await studio.getByRole('navigation', { name: '작업 공간' }).getByRole('button', { name: '내 프로젝트' }).click();
  await button('프로젝트 열기').click();
  await heading('영상 분석').waitFor();
  await button('프로젝트').click();
  await heading('프로젝트 설정').waitFor();
  await field('편집 스타일').selectOption({ label: '릴메이트 스타일' });
  await button('저장하고 자료 등록').click();
  await heading('작업 자료 등록').waitFor();
  await button('분석으로 이동').click();

  if (process.env.REELMATE_TEST_MODELS === '1') {
    await button('CLIP 장면 분석').click();
    await notice('CLIP으로 원본 2개를 분석했습니다.');
    await studio.getByText(/유사도 [0-9]/).first().waitFor();
  }
  await excludeCandidates(true);
  await checkStepButtons(reviewButtons, false);
  await button('변경 취소').click();
  await checkStepButtons(reviewButtons, true);
  await excludeCandidates(true);
  await button('장면 저장').click();
  await notice('장면 후보를 저장했습니다.');
  await checkStepButtons(reviewButtons, false);
  await excludeCandidates(false);
  await studio.locator('.scene-card').first().getByLabel('분류').selectOption('product');
  await studio.locator('.scene-card').first().getByLabel('라벨 확인').check();
  await button('장면 저장').click();
  await notice('장면 후보를 저장했습니다.');
  await checkStepButtons(reviewButtons, true);
  await button('내 프로젝트').click();
  await button('프로젝트 열기').click();
  await heading('편집안 검토').waitFor();
  await button('분석').click();

  await button('검토로 이동').click();
  await heading('편집안 검토').waitFor();
  await button('컷 추가').click();
  await field('원본 시작 (초)').fill('0.5');
  await field('원본 종료 (초)').fill('5.5');
  await button('컷 추가').click();
  await field('원본 시작 (초)').fill('0.5');
  await field('원본 종료 (초)').fill('5.5');
  await button('자막 추가').click();
  await studio.locator('.caption-card').nth(0).getByLabel('자막 문구').fill('사용 장면입니다');
  await studio.getByRole('button', { name: /^컷 1 0/ }).click();
  await button('자막 추가').click();
  await studio.locator('.caption-card').nth(1).getByLabel('자막 문구').fill('유료 광고 · 릴메이트');
  await studio.locator('.caption-card').nth(1).getByLabel('자막 위치').selectOption('top');
  await button('편집안 저장').click();
  await notice('편집안 v1을 저장했습니다.');
  await checkStepButtons(exportButtons, true);
  await verifyNarrowPage();
  await button('컷 잠금').click();
  await notice('컷을 잠갔습니다.');
  assert(await field('원본 시작 (초)').isDisabled(), 'Locked cut remains editable.');
  await button('미리보기 및 패키지 생성').click({ timeout: 60000 });
  await notice('MP4와 편집 패키지를 생성했습니다.');
  await studio.locator('.player-shell video').waitFor();
  const video = studio.locator('.player-shell video');
  const media = await video.evaluate((player) => new Promise((resolve, reject) => {
    const ready = () => resolve([player.duration, player.videoWidth, player.videoHeight]);
    if (player.readyState >= 1) ready();
    else {
      player.addEventListener('loadedmetadata', ready, { once: true });
      player.addEventListener('error', () => reject(new Error('Browser could not play the output.')), { once: true });
    }
  }));
  assert.deepEqual(media, [10, 540, 960]);
  await video.evaluate(async (player) => {
    player.muted = true;
    await player.play();
  });
  await studio.locator('.player-shell video').evaluate((player) => new Promise((resolve) => {
    const done = () => { player.pause(); resolve(); };
    if (player.currentTime > 0) done();
    else player.addEventListener('timeupdate', done, { once: true });
  }));
  await button('내보내기로 이동').click();
  await heading('내보내기').waitFor();
  async function download(name) {
    const link = studio.getByRole('link', { name });
    const [file] = await Promise.all([page.waitForEvent('download'), link.click()]);
    const path = join(work, file.suggestedFilename());
    await file.saveAs(path);
    return path;
  }
  await download('다운로드 미리보기 MP4');
  const bundle = await download('다운로드 대체 편집 패키지 ZIP');
  assert.equal(readFileSync(bundle).subarray(0, 2).toString('ascii'), 'PK');
  await button('CapCut 프로젝트 ZIP 생성').click();
  await notice('CapCut 프로젝트 ZIP을 생성했습니다.');
  const capcut = await download('다운로드 CapCut 프로젝트 ZIP');
  execFileSync(python, ['-c',
    'import sys; from zipfile import ZipFile; from reelmate.capcut_install import read_package, verify_media; z=ZipFile(sys.argv[1]); p=read_package(z); assert len(p["clips"])==len(p["subtitles"])==2; assert p["duration"]==300; verify_media(z,p)',
    capcut], { cwd: root });
  const subtitles = await download('다운로드 자막 SRT');
  assert(readFileSync(subtitles, 'utf8').includes('유료 광고 · 릴메이트'));
  await page.reload();
  await heading('내보내기').waitFor();
  await download('다운로드 브랜드 검수 JSON');
  await stopServer();
  await startServer();
  await page.reload();
  await heading('내보내기').waitFor();
  await download('다운로드 편집안 JSON');
  await download('다운로드 CapCut 프로젝트 ZIP');

  await stepButton('검토').click();
  await button('잠금 해제').click();
  await notice('컷 잠금을 해제했습니다.');
  await button('분석').click();
  await excludeCandidates(true);
  await button('장면 저장').click();
  await notice('장면 후보를 저장했습니다.');
  await checkStepButtons(reviewButtons, true);
  await button('검토로 이동').click();
  await heading('편집안 검토').waitFor();
  assert(await button('컷 추가').isDisabled());
  await studio.locator('.caption-card').first().getByLabel('자막 문구').fill('저장한 편집안의 자막 수정');
  await checkStepButtons(exportButtons, false);
  await button('편집안 저장').click();
  await studio.getByRole('status').filter({ hasText: /편집안 v\d+을 저장했습니다/ }).waitFor();
  await checkStepButtons(exportButtons, true);
  await button('내보내기로 이동').click();
  await heading('내보내기').waitFor();
  await notice('이전에 생성한 버전은 내려받을 수 있습니다.');
  await checkStepButtons(['현재 버전 출력 생성', 'CapCut 프로젝트 ZIP 생성'].map(button), false);
  assert(readFileSync(await download('다운로드 자막 SRT'), 'utf8').includes('유료 광고 · 릴메이트'));
  await page.reload();
  await heading('편집안 검토').waitFor();
  assert.equal(await studio.locator('.caption-card').first().getByLabel('자막 문구').inputValue(), '저장한 편집안의 자막 수정');
  await stepButton('내보내기').click();
  await download('다운로드 미리보기 MP4');
  await download('다운로드 CapCut 프로젝트 ZIP');
  assert.deepEqual(errors, [], 'Browser errors: ' + errors.join('\n'));
  console.log('Browser E2E passed (uploads, style, rules, step buttons, timeline, playback, versioned downloads, reload, restart).');
  console.log('Browser artifacts: ' + work);
} catch (error) {
  await page?.screenshot({ path: join(work, 'failure.png'), timeout: 5000 }).catch(() => {});
  console.error(readFileSync(log, 'utf8').slice(-4500));
  console.error('Browser artifacts: ' + work);
  throw error;
} finally {
  await browser?.close();
  await stopServer();
}
