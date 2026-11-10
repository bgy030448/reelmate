import { useEffect, useRef, useState } from 'react';
import {
  ArrowDown, ArrowRight, ArrowUp, CheckCircle2, Clapperboard, Clock3, Download, FileJson,
  FileText, Film, Lock, Plus, RefreshCcw, ShieldCheck, Sparkles, Subtitles, Trash2, Unlock,
} from 'lucide-react';
import {
  Button, EditActions, Empty, Field, InspectAsset, Notice, Pager, Panel, SourceButton,
  dateText, frame, mediaUrl, newKey, numeric, positions, time, toSeconds, useDraft,
} from './ui';

const origins = {
  local: '장면 후보 기반 수동 초안', manual: '사용자 편집', gemini: 'Gemini 제안',
  local_revision: '선택 컷 교체', gemini_revision: 'Gemini 부분 재편집', whisper: 'Whisper 자막',
};
const verdicts = { met: '충족', unmet: '미충족', review: '직접 확인 필요' };

function PlanControls({ ctx, plan }) {
  const locked = plan?.clips.some((clip) => clip.locked);
  const usable = ctx.project.segments.some((segment) => !segment.excluded);
  const create = (method) => ctx.run('plan_create', { method }, {
    message: method === 'gemini' ? 'Gemini가 편집안을 작성하는 중' : '편집 초안을 구성하는 중',
  });
  return <div className="form-stack">
    <div className="button-row">
      <Button disabled={ctx.dirty || locked || !usable} onClick={() => create('local')}>
        {plan ? '수동 초안 다시 만들기' : '수동 편집 초안'}
      </Button>
      <Button icon={Sparkles} disabled={ctx.dirty || locked || !usable || !ctx.server.capabilities.gemini}
        onClick={() => create('gemini')}>Gemini 편집안 만들기</Button>
    </div>
    {locked ? <small className="muted">잠긴 컷이 있어 전체 편집안을 교체할 수 없습니다. 잠금 해제 또는 선택 컷 재편집을 사용하세요.</small> :
      <small className="muted">초안을 다시 만들면 현재 컷·자막 초안이 교체됩니다. 저장한 출력은 버전별로 유지됩니다.</small>}
  </div>;
}

function DirectCheck({ ctx, rule, duration }) {
  const [editing, setEditing] = useState(false);
  const confirmation = ctx.project.confirmations[rule.rule_id];
  const [fields, setFields] = useState({});
  function start() {
    setFields(confirmation || { status: 'met', start: 0, end: Math.min(1, duration), note: '' });
    setEditing(true);
    ctx.setDirty(true);
  }
  function update(key, value) {
    setFields({ ...fields, [key]: value });
  }
  if (!editing) return <Button disabled={ctx.dirty || !ctx.project.rules_approved}
    onClick={start}>직접 확인 기록</Button>;
  const ready = fields.status === 'review' || Boolean(fields.note.trim() && numeric(fields.end) > numeric(fields.start));
  return <div className="direct-check form-stack">
    <div className="field-grid three">
      <Field label="직접 확인 결과"><select value={fields.status} onChange={(event) => update('status', event.target.value)}>
        {Object.entries(verdicts).map(([key, text]) => <option key={key} value={key}>{text}</option>)}
      </select></Field>
      {fields.status !== 'review' && <>
        <Field label="근거 시작 (초)"><input type="number" min="0" max={duration} step="0.001"
          value={fields.start} onChange={(event) => update('start', event.target.value)} /></Field>
        <Field label="근거 종료 (초)"><input type="number" min="0" max={duration} step="0.001"
          value={fields.end} onChange={(event) => update('end', event.target.value)} /></Field>
      </>}
    </div>
    {fields.status !== 'review' && <Field label="확인 근거"><input maxLength={400} value={fields.note}
      onChange={(event) => update('note', event.target.value)} /></Field>}
    <div className="button-row">
      <Button onClick={() => { setEditing(false); ctx.setDirty(false); }}>확인 취소</Button>
      <Button variant="primary" disabled={!ready} onClick={() => ctx.run('confirm_rule', {
        ...fields, rule_id: rule.rule_id, start: numeric(fields.start), end: numeric(fields.end),
      }, { save: true, done: () => setEditing(false) })}>확인 저장</Button>
    </div>
  </div>;
}

function BrandReview({ ctx, onSeek }) {
  const { project, server } = ctx;
  const result = project.validation;
  return <section className="subsection" aria-label="브랜드 검수">
    <div className="section-head">
      <div><h3><ShieldCheck size={20} /> 브랜드 검수</h3><p>저장한 편집안의 판정과 근거 시간입니다.</p></div>
      <span className={'pill ' + (result.valid ? 'success' : 'warning')}>{result.valid ? '내보내기 가능' : '검수 필요'}</span>
    </div>
    {result.errors.length > 0 && <Notice kind="error">
      <ul className="compact-list">{result.errors.map((error) => <li key={error}>{error}</li>)}</ul>
    </Notice>}
    {result.checks.length === 0 && !project.guide && <p className="muted">등록한 브랜드 규칙이 없습니다.</p>}
    {result.checks.map((check) => {
      const rule = project.rules.find((item) => item.rule_id === check.rule_id);
      const description = rule.description || server.labels[rule.value] || String(rule.value);
      return <article className="check-card" key={rule.rule_id}>
        <div className="section-head">
          <div><span className="overline">{server.rule_types[rule.type]} · {check.required ? '필수' : '선택'}</span>
            <h4>{description}</h4></div>
          <span className={'pill ' + ({ met: 'success', unmet: 'error', review: 'warning' }[check.status])}>
            {verdicts[check.status]}
          </span>
        </div>
        <p>{check.reason}</p>
        {check.evidence_start != null && <div className="button-row">
          <span className="mono">{time(check.evidence_start)} – {time(check.evidence_end)}</span>
          <Button disabled={ctx.dirty} onClick={() => onSeek(check.evidence_start)}>근거 구간 보기</Button>
        </div>}
        {rule.type === 'manual' && <DirectCheck ctx={ctx} rule={rule} duration={project.plan.actual_duration} />}
      </article>;
    })}
  </section>;
}

export function Review({ ctx }) {
  const { project, server } = ctx;
  const plan = project.plan;
  const [draft, change, discard] = useDraft(
    { clips: plan?.clips || [], subtitles: plan?.subtitles || [] }, project.revision, ctx,
  );
  const [active, setActive] = useState(0);
  const [replacement, setReplacement] = useState(false);
  const [prompt, setPrompt] = useState('');
  const [timelineDirty, setTimelineDirty] = useState(false);
  const video = useRef(null);
  const selectedAsset = project.assets.find((asset) => asset.asset_id === ctx.inspected?.assetId);
  const available = project.segments.filter((s) => !s.excluded);
  const profile = server.profiles.find((entry) => entry.profile_id === project.profile_id);
  const activeClip = draft.clips[active];
  const currentOutput = project.downloads?.version === plan?.version ? project.downloads : null;
  let cursor = 0;
  const timing = draft.clips.map((clip) => {
    const start = toSeconds(cursor);
    const length = Math.max(0, frame(numeric(clip.source_out) - numeric(clip.source_in)));
    cursor += length;
    return { start, length, end: toSeconds(cursor) };
  });
  const duration = toSeconds(cursor);
  useEffect(() => { setActive((index) => Math.min(index, Math.max(0, draft.clips.length - 1))); }, [draft.clips.length]);
  useEffect(() => { if (!ctx.dirty) setTimelineDirty(false); }, [ctx.dirty]);

  function edit(next) {
    setTimelineDirty(true);
    change(next);
  }
  function editClip(index, values) {
    edit({ ...draft, clips: draft.clips.map((clip, i) => i === index ? { ...clip, ...values } : clip) });
  }
  function editCaption(index, values) {
    edit({ ...draft, subtitles: draft.subtitles.map((caption, i) => i === index ? { ...caption, ...values } : caption) });
  }
  function addClip() {
    const segment = available.find((s) => !draft.clips.some((c) => c.segment_id === s.segment_id)) || available[0];
    if (!segment) return;
    edit({ ...draft, clips: [...draft.clips, { _key: newKey(), segment_id: segment.segment_id,
      asset_id: segment.asset_id, source_in: segment.start, source_out: segment.end }] });
    setActive(draft.clips.length);
  }
  function moveClip(index, shift) {
    const next = [...draft.clips];
    [next[index], next[index + shift]] = [next[index + shift], next[index]];
    edit({ ...draft, clips: next });
    setActive(index + shift);
  }
  function addCaption() {
    const range = timing[active] || { start: 0, end: duration };
    edit({ ...draft, subtitles: [...draft.subtitles, { _key: newKey(), text: '', start: range.start,
      end: Math.min(range.end, range.start + 2), style: { position: profile?.subtitle_style.position || 'bottom' },
    }] });
  }
  function save() {
    ctx.run('plan_save', {
      clips: draft.clips.map(({ clip_id, segment_id, asset_id, source_in, source_out }) =>
        ({ clip_id, segment_id, asset_id, source_in: numeric(source_in), source_out: numeric(source_out) })),
      subtitles: draft.subtitles.map((caption) => ({ ...caption, start: numeric(caption.start), end: numeric(caption.end) })),
    }, { save: true, message: '편집안을 저장하는 중' });
  }
  function seek(sec) {
    if (video.current?.readyState >= 1) {
      video.current.currentTime = sec;
      video.current.scrollIntoView({ block: 'nearest' });
      return;
    }
    const index = timing.findIndex((range) => range.start <= sec && range.end > sec);
    const clip = draft.clips[index];
    if (!clip) return;
    setActive(index);
    const at = Math.max(0, clip.source_in + sec - timing[index].start);
    ctx.inspect(clip.asset_id, at);
    const asset = project.assets.find((item) => item.asset_id === clip.asset_id);
    if (asset && !asset.preview_url) ctx.run('asset_select', { asset_id: asset.asset_id },
      { message: '근거 원본을 불러오는 중' });
  }
  const allowTimeline = !ctx.dirty || timelineDirty;
  const latestExists = project.outputs.some((output) => output.version === plan?.version);
  return <Panel step={4} title="편집안 검토" description="컷과 자막을 확인하고 편집안을 저장한 뒤 브랜드 조건을 검수하세요."
    action={plan && <span className="pill neutral">저장 버전 v{plan.version}</span>}>
    <div className="review-top">
      <div className="player-shell">
        {currentOutput?.urls.player ? <video ref={video} controls playsInline preload="metadata"
          src={mediaUrl(currentOutput.urls.player)} /> : <Empty icon={Clapperboard} title="미리보기"
            detail="편집안 검수를 완료하면 MP4를 생성할 수 있습니다." />}
      </div>
      <div className="review-meta">
        <span className="overline">EDIT PLAN</span>
        <h3>{project.product}</h3>
        <p>{project.aspect_ratio} · 목표 {project.target_duration}초 · 현재 {time(duration)}</p>
        {plan && <p className="muted small">{origins[plan.source] || plan.source}{plan.model ? ' · ' + plan.model : ''}</p>}
        <PlanControls ctx={ctx} plan={plan} />
        {plan && <div className="button-row">
          {latestExists && !currentOutput ? <Button disabled={ctx.dirty} onClick={() =>
            ctx.run('output_select', { version: plan.version })}>현재 버전 보기</Button> :
            <Button variant="primary" icon={Film} disabled={ctx.dirty || !project.validation.valid}
              onClick={() => ctx.run('export', {}, { message: 'FFmpeg로 MP4와 편집 패키지를 만드는 중' })}>
              {latestExists ? '저장한 출력 불러오기' : '미리보기 및 패키지 생성'}
            </Button>}
        </div>}
        {plan && !project.validation.valid && <small className="muted">아래 브랜드 검수에서 내보내기 조건을 확인하세요.</small>}
        {ctx.dirty && <small className="muted">미리보기는 저장한 출력입니다. 작성 중인 컷은 저장 후 반영됩니다.</small>}
      </div>
    </div>
    <section className="subsection">
      <div className="section-head"><div><h3>컷 타임라인</h3><p>원본 구간과 재생 순서를 편집하세요. 출력은 30fps에 맞춰 저장됩니다.</p></div>
        <Button icon={Plus} disabled={!available.length || !allowTimeline || draft.clips.length >= 120} onClick={addClip}>컷 추가</Button>
      </div>
      {!draft.clips.length && <Empty icon={Film} title="편집안이 비어 있습니다" detail="수동 초안을 만들거나 컷을 추가하세요." />}
      {draft.clips.length > 0 && <div className="timeline" role="group" aria-label="컷 타임라인">
        {draft.clips.map((clip, index) => <button key={clip.clip_id || clip._key} type="button"
          onClick={() => setActive(index)} className={active === index ? 'current' : ''}
          style={{ flexGrow: Math.max(12, timing[index].length) }} aria-pressed={active === index}
          aria-label={'컷 ' + (index + 1) + ' ' + time(timing[index].start)}>
          {clip.locked && <Lock size={13} />}<span>{String(index + 1).padStart(2, '0')}</span>
        </button>)}
      </div>}
      {activeClip && (() => {
        const asset = project.assets.find((item) => item.asset_id === activeClip.asset_id);
        const segment = project.segments.find((item) => item.segment_id === activeClip.segment_id);
        return <article className="cut-card">
          <div className="section-head"><div>
            <h4>컷 {active + 1} · {asset?.filename || '원본 없음'}</h4>
            <p>{time(timing[active].start)} – {time(timing[active].end)} · {segment ? server.labels[segment.label] : '후보 없음'}</p>
          </div><div className="button-row">
            {asset && <SourceButton ctx={ctx} asset={asset} at={numeric(activeClip.source_in) || 0} />}
            {activeClip.clip_id && <Button icon={activeClip.locked ? Unlock : Lock} disabled={ctx.dirty}
              onClick={() => ctx.run('clip_lock', { clip_id: activeClip.clip_id, locked: !activeClip.locked })}>
              {activeClip.locked ? '잠금 해제' : '컷 잠금'}
            </Button>}
          </div></div>
          <fieldset className="plain-fieldset" disabled={activeClip.locked || !allowTimeline}>
            <div className="field-grid three">
              <Field label="사용할 장면 후보"><select value={activeClip.segment_id} onChange={(event) => {
                const selected = available.find((item) => item.segment_id === event.target.value);
                if (selected) editClip(active, { segment_id: selected.segment_id, asset_id: selected.asset_id,
                  source_in: selected.start, source_out: selected.end });
              }}>
                {!available.some((item) => item.segment_id === activeClip.segment_id) &&
                  <option value={activeClip.segment_id}>현재 후보가 제외되었거나 삭제됨</option>}
                {available.map((item) => <option key={item.segment_id} value={item.segment_id}>
                  {project.assets.find((a) => a.asset_id === item.asset_id)?.filename} · {server.labels[item.label]} · {item.start}–{item.end}초
                </option>)}
              </select></Field>
              <Field label="원본 시작 (초)"><input type="number" min={segment?.start ?? 0} max={segment?.end ?? 120} step="0.001"
                value={activeClip.source_in} onChange={(event) => editClip(active, { source_in: event.target.value })} /></Field>
              <Field label="원본 종료 (초)"><input type="number" min={segment?.start ?? 0} max={segment?.end ?? 120} step="0.001"
                value={activeClip.source_out} onChange={(event) => editClip(active, { source_out: event.target.value })} /></Field>
            </div>
            <div className="button-row">
              <Button icon={ArrowUp} disabled={active === 0 || draft.clips[active - 1]?.locked}
                onClick={() => moveClip(active, -1)}>앞으로 이동</Button>
              <Button icon={ArrowDown} disabled={active === draft.clips.length - 1 || draft.clips[active + 1]?.locked}
                onClick={() => moveClip(active, 1)}>뒤로 이동</Button>
              <Button icon={Trash2} onClick={() => edit({ ...draft, clips: draft.clips.filter((_, i) => i !== active) })}>컷 제거</Button>
            </div>
          </fieldset>
          {activeClip.clip_id && !activeClip.locked && !ctx.dirty && <div className="replacement">
            <Button icon={RefreshCcw} onClick={() => setReplacement(!replacement)}>선택 컷 재편집</Button>
            {replacement && <div className="form-stack">
              <Field label="Gemini 재편집 요청" hint="같은 길이의 미사용 장면 중에서 선택합니다. Gemini를 사용하면 이 요청과 후보가 전송됩니다.">
                <input value={prompt} maxLength={400} onChange={(event) => setPrompt(event.target.value)}
                  placeholder="예: 제품을 사용하는 장면으로 교체" />
              </Field>
              <div className="button-row">
                <Button onClick={() => ctx.run('clip_replace', { clip_id: activeClip.clip_id, method: 'local' },
                  { message: '선택 컷을 교체하는 중', done: () => setReplacement(false) })}>같은 길이의 다른 컷</Button>
                <Button icon={Sparkles} disabled={!server.capabilities.gemini || !prompt.trim()} onClick={() =>
                  ctx.run('clip_replace', { clip_id: activeClip.clip_id, method: 'gemini', prompt },
                    { message: 'Gemini가 선택 컷을 검토하는 중', done: () => setReplacement(false) })}>Gemini로 교체</Button>
              </div>
            </div>}
          </div>}
        </article>;
      })()}
      <InspectAsset asset={selectedAsset} at={ctx.inspected?.at} onClose={ctx.closeInspect} />
    </section>
    <section className="subsection">
      <div className="section-head"><div><h3>자막</h3><p>문구, 타임라인 시간, 화면 위치를 개별 자막에 저장합니다.</p></div>
        <Button icon={Plus} disabled={!draft.clips.length || !allowTimeline || draft.subtitles.length >= 120}
          onClick={addCaption}>자막 추가</Button></div>
      {plan && project.assets.some((asset) => asset.transcript?.segments.length > 0) && <Button icon={Subtitles} disabled={ctx.dirty}
        onClick={() => ctx.run('transcript_apply', {}, { message: '전사를 자막으로 배치하는 중' })}>Whisper 자막 가져오기</Button>}
      {!draft.subtitles.length && <p className="muted">자막을 추가하면 MP4와 독립 SRT에 반영됩니다.</p>}
      {draft.subtitles.map((caption, index) => <article className="caption-card" key={caption.subtitle_id || caption._key}>
        <div className="section-head"><h4>자막 {index + 1}</h4>
          <Button icon={Trash2} className="icon-button" aria-label={'자막 ' + (index + 1) + ' 제거'} disabled={!allowTimeline}
            onClick={() => edit({ ...draft, subtitles: draft.subtitles.filter((_, i) => i !== index) })} />
        </div>
        <Field label="자막 문구"><textarea rows={2} maxLength={140} value={caption.text} disabled={!allowTimeline}
          onChange={(event) => editCaption(index, { text: event.target.value })} /></Field>
        <div className="field-grid three">
          <Field label="자막 시작 (초)"><input type="number" min="0" max="60" step="0.001" value={caption.start} disabled={!allowTimeline}
            onChange={(event) => editCaption(index, { start: event.target.value })} /></Field>
          <Field label="자막 종료 (초)"><input type="number" min="0" max="60" step="0.001" value={caption.end} disabled={!allowTimeline}
            onChange={(event) => editCaption(index, { end: event.target.value })} /></Field>
          <Field label="자막 위치"><select value={caption.style?.position || 'bottom'} disabled={!allowTimeline}
            onChange={(event) => editCaption(index, { style: { position: event.target.value } })}>
            {Object.entries(positions).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
          </select></Field>
        </div>
      </article>)}
      {timelineDirty && <EditActions ctx={ctx} discard={discard} submit={save} label="편집안 저장" />}
    </section>
    {plan && <BrandReview ctx={ctx} onSeek={seek} />}
    <Pager previous={() => ctx.goto(3)} next={() => ctx.goto(5)} disabled={ctx.dirty || !plan} nextLabel="내보내기로 이동" />
  </Panel>;
}

const downloadable = [
  ['preview', '미리보기 MP4', '컷·오디오·자막이 합성된 영상', Film],
  ['package', '대체 편집 패키지 ZIP', '개별 MP4 클립, SRT, 컷시트, EDL JSON', Download],
  ['subtitles', '자막 SRT', '문구와 시간 정보가 포함된 자막', Subtitles],
  ['plan', '편집안 JSON', '컷의 소스 시간과 최종 타임라인', FileJson],
  ['report', '브랜드 검수 JSON', '조건별 판정과 타임코드 근거', FileText],
];

function CapCutExport({ ctx }) {
  const { project } = ctx;
  const version = project.plan.version;
  const download = project.capcut_download;
  const saved = project.capcut_exports.some((item) => item.version === version);
  return <section className="subsection" aria-label="CapCut 편집 프로젝트">
    <div className="section-head">
      <div><h3><Clapperboard size={20} /> CapCut 편집 프로젝트</h3>
        <p>자막을 합성하지 않은 전체 길이의 MP4 소스와 독립 컷·텍스트 타이밍을 패키지에 담습니다.</p></div>
      <span className="pill warning">Windows 호환성 검증용</span>
    </div>
    <Notice>CapCut Desktop 9.x에서 만든 전용 시험용 초안에 ReelMate 적용 도구로 연결합니다. 실제 앱 열기와 저장 후 재열기는 검증 대기입니다.</Notice>
    <details className="details">
      <summary>시험용 초안 준비</summary>
      <div className="evidence-body"><p>CapCut에서 ReelMate Test라는 새 로컬 프로젝트를 만듭니다.
        메인 트랙에 영상 두 개, 별도 트랙에 기본 텍스트 두 개를 배치해 저장한 뒤 CapCut을 완전히 종료하세요.</p>
        <p>전체 앱 빌드 번호와 초안 폴더가 필요합니다. 프로젝트의 docs/capcut-validation.md에 검사·적용 명령이 있습니다.</p>
      </div>
    </details>
    <div className="button-row">
      <Button icon={Clapperboard} variant="primary" disabled={!project.validation.valid}
        onClick={() => ctx.run('capcut_export', {}, { message: 'CapCut 프로젝트용 소스를 만드는 중' })}>
        {saved ? '현재 CapCut 버전 불러오기' : 'CapCut 프로젝트 ZIP 생성'}
      </Button>
    </div>
    {download && <div className="output-controls">
      <Field label="CapCut 다운로드 버전"><select value={download.version} onChange={(event) =>
        ctx.run('capcut_select', { version: Number(event.target.value) }, { message: 'CapCut 출력을 불러오는 중' })}>
        {project.capcut_exports.map((item) => <option key={item.version} value={item.version}>
          {'v' + item.version + ' · ' + dateText(item.created_at)}
        </option>)}
      </select></Field>
      {download.url ? <a className="button secondary" href={mediaUrl(download.url)} download>
        <Download size={16} aria-hidden="true" />다운로드<span className="sr-only"> CapCut 프로젝트 ZIP</span>
      </a> : <small className="muted">저장 파일을 찾을 수 없음</small>}
      {download.version !== version && <span className="pill warning">이전 편집안 버전</span>}
    </div>}
  </section>;
}

export function ExportPage({ ctx }) {
  const { project } = ctx;
  const version = project.plan.version;
  const { downloads } = project;
  const already = project.outputs.some((output) => output.version === version);
  return <Panel step={5} title="내보내기" description="편집안 버전별 MP4, 편집 패키지와 검수 자료를 내려받으세요."
    action={<span className="pill neutral">현재 편집안 v{version}</span>}>
    <Notice>대체 편집 패키지를 사용하려면 클립을 번호 순으로 배치하고 SRT를 가져오세요.</Notice>
    <div className="section-head export-head">
      <div><h3>출력 파일</h3><p>미리보기와 편집 패키지는 같은 편집안 버전에서 생성됩니다.</p></div>
      <Button variant="primary" icon={Film} disabled={!project.validation.valid}
        onClick={() => ctx.run('export', {}, { message: 'FFmpeg로 MP4와 편집 패키지를 만드는 중' })}>
        {already ? '현재 버전 불러오기' : '현재 버전 출력 생성'}
      </Button>
    </div>
    {!project.validation.valid && <Notice kind="error">검토 단계에서 내보내기 조건을 확인하세요. 이전에 생성한 버전은 내려받을 수 있습니다.</Notice>}
    {downloads ? <>
      <div className="output-controls">
        <Field label="다운로드 버전"><select value={downloads.version} onChange={(event) =>
          ctx.run('output_select', { version: Number(event.target.value) }, { message: '출력을 불러오는 중' })}>
          {project.outputs.map((output) => <option key={output.version} value={output.version}>
            {'v' + output.version + ' · ' + dateText(output.created_at)}
          </option>)}
        </select></Field>
        <span className={'pill ' + (downloads.version === version ? 'success' : 'warning')}>
          {downloads.version === version ? '현재 버전' : '이전 편집안 버전'}
        </span>
      </div>
      <div className="download-list">{downloadable.map(([key, title, detail, Icon]) => <article key={key} className="download-row">
        <div className="asset-icon"><Icon size={22} /></div><div className="grow"><h4>{title}</h4><p>{detail}</p></div>
        {downloads.urls[key] ? <a className="button secondary" href={mediaUrl(downloads.urls[key])} download>
          <Download size={16} aria-hidden="true" />다운로드<span className="sr-only"> {title}</span></a> :
          <small className="muted">저장 파일을 찾을 수 없음</small>}
      </article>)}</div>
    </> : <Empty icon={Download} title="생성한 출력이 없습니다" detail="검수 조건을 충족한 편집안으로 출력을 생성하세요." />}
    <CapCutExport ctx={ctx} />
    <section className="subsection">
      <div className="section-head"><div><h3><Clock3 size={19} /> 작업 이력</h3><p>저장, 분석, 편집 및 내보내기 기록입니다.</p></div></div>
      <ol className="history">{[...project.history].reverse().map((entry, index) => <li key={index}>
        <CheckCircle2 size={16} /><div><strong>{entry.message}</strong>
          <span>{dateText(entry.at)}{entry.plan_version != null && ' · v' + entry.plan_version}</span></div></li>)}</ol>
    </section>
    <Pager previous={() => ctx.goto(4)} />
  </Panel>;
}
