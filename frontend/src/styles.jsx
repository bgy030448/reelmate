import { useRef } from 'react';
import { ArrowRight, Download, Sparkles, Upload } from 'lucide-react';
import { Button, Empty, Field, Notice, Panel, dateText, jsonDownload, numeric, positions, time, useDraft } from './ui';

function ProfileEditor({ ctx, profile, isDraft, setId }) {
  const [draft, change, discard] = useDraft({
    ...profile, approve: Boolean(profile.approved_at),
    observations: profile.evidence.map((entry) => ({ asset_id: entry.asset_id, ...entry.manual })),
  }, profile.updated_at || ctx.project?.revision, ctx);
  const update = (key, value) => change({ ...draft, [key]: value });
  function observation(index, key, value) {
    update('observations', draft.observations.map((entry, i) => i === index ? { ...entry, [key]: value } : entry));
  }
  function save() {
    ctx.run('profile_save', { ...draft, avg_shot_length: numeric(draft.avg_shot_length),
      observations: draft.observations.map((entry) => ({ ...entry, first_product_sec: numeric(entry.first_product_sec) })),
    }, { save: true, message: '스타일을 저장하는 중', done: (_server, ack) => setId(ack.profile_id) });
  }
  return <Panel title={isDraft ? '스타일 측정 초안' : profile.name}
    description="측정 근거를 확인하고 다음 프로젝트에 적용할 편집 기준을 정리하세요."
    action={<span className={'pill ' + (profile.approved_at ? 'success' : 'warning')}>{profile.approved_at ? '승인됨' : '초안'}</span>}>
    <div className="form-stack">
      <div className="field-grid">
        <Field label="스타일 이름"><input value={draft.name} maxLength={60}
          onChange={(event) => update('name', event.target.value)} /></Field>
        <Field label="선호 평균 컷 길이 (초)"><input type="number" step="0.01" min="0.1" max="120" value={draft.avg_shot_length}
          onChange={(event) => update('avg_shot_length', event.target.value)} /></Field>
        <Field label="오프닝 스타일"><input value={draft.opening_style} maxLength={200}
          onChange={(event) => update('opening_style', event.target.value)} placeholder="예: 제품 디테일로 시작" /></Field>
        <Field label="템포 메모"><input value={draft.pacing} maxLength={200}
          onChange={(event) => update('pacing', event.target.value)} /></Field>
        <Field label="기본 자막 위치"><select value={draft.subtitle_style.position}
          onChange={(event) => update('subtitle_style', { ...draft.subtitle_style, position: event.target.value })}>
          {Object.entries(positions).map(([position, text]) => <option value={position} key={position}>{text}</option>)}
        </select></Field>
        <Field label="자막 메모"><input maxLength={250} value={draft.subtitle_style.notes}
          onChange={(event) => update('subtitle_style', { ...draft.subtitle_style, notes: event.target.value })} /></Field>
      </div>
      <div className="sequence"><span>선호 장면 순서</span>
        <div className="button-row">{draft.preferred_sequence.map((label, index) =>
          <button type="button" key={index} className="pill peach" title="클릭하여 순서에서 제거"
            onClick={() => update('preferred_sequence', draft.preferred_sequence.filter((_, i) => index !== i))}>
            {index + 1}. {ctx.server.labels[label]} ×
          </button>)}
          <select aria-label="선호 장면 추가" value="" disabled={draft.preferred_sequence.length >= 12} onChange={(event) =>
            update('preferred_sequence', [...draft.preferred_sequence, event.target.value])}>
            <option value="" disabled>장면 추가</option>
            {Object.entries(ctx.server.labels).filter(([label]) => label !== 'unknown')
              .map(([label, text]) => <option key={label} value={label}>{text}</option>)}
          </select>
        </div>
      </div>
      <Field label="스타일 요약"><textarea value={draft.summary} rows={3} maxLength={600}
        onChange={(event) => update('summary', event.target.value)} /></Field>
      {isDraft && <div className="button-row">
        <Button icon={Sparkles} disabled={ctx.dirty || !ctx.server.capabilities.gemini}
          onClick={() => ctx.run('style_summarize', {}, { message: 'Gemini가 스타일 측정값을 요약하는 중' })}>Gemini 요약 초안</Button>
        <small className="muted">측정값과 관찰 메모가 Google API에 전송됩니다.</small>
      </div>}
    </div>
    <section className="subsection">
      <div className="section-head"><div><h3>레퍼런스 근거</h3><p>컷 전환은 후보 측정값이며 오프닝·제품 노출·화면 글자는 샘플을 확인해 보완할 수 있습니다.</p></div></div>
      {profile.evidence.map((entry, index) => {
        const manual = draft.observations[index] || {};
        return <details className="details evidence" key={entry.asset_id}>
          <summary>{entry.filename} · {time(entry.duration)} · 컷 전환 {entry.cuts.length}개</summary>
          <div className="evidence-body">
            <p>{entry.width}×{entry.height} · 평균 컷 {time(entry.avg_shot_length)}</p>
            {entry.cuts.length > 0 && <p>컷 경계 · {entry.cuts.map(time).join(', ')}</p>}
            <p>오프닝 · {ctx.server.labels[entry.opening_label] || '관찰 필요'}{entry.observation_source && ' · ' + entry.observation_source}</p>
            <p>첫 제품 노출 추정 · {entry.first_product_sec == null ? '관찰 필요' : time(entry.first_product_sec)}</p>
            <p>자막 근거 · {entry.subtitle_observation || '직접 관찰 필요'}</p>
            <div className="field-grid three">
              <Field label="오프닝 관찰"><input maxLength={120} value={manual.opening || ''}
                onChange={(event) => observation(index, 'opening', event.target.value)} /></Field>
              <Field label="첫 제품 노출 관찰 (초)"><input type="number" min="0" max={entry.duration} step="0.001"
                value={manual.first_product_sec ?? ''} onChange={(event) => observation(index, 'first_product_sec', event.target.value)} /></Field>
              <Field label="자막 위치·밀도 관찰"><input maxLength={200} value={manual.subtitle || ''}
                onChange={(event) => observation(index, 'subtitle', event.target.value)} /></Field>
            </div>
          </div>
        </details>;
      })}
      {!profile.evidence.length && <Notice>이 프로필에는 레퍼런스 관찰 기록이 없습니다.</Notice>}
    </section>
    <div className="edit-actions">
      <label className="check-label"><input type="checkbox" checked={draft.approve}
        onChange={(event) => update('approve', event.target.checked)} />검토한 스타일을 프로젝트에 사용하도록 승인</label>
      {ctx.dirty && <Button onClick={discard}>변경 취소</Button>}
      <Button variant="primary" onClick={save}>스타일 저장</Button>
    </div>
  </Panel>;
}

export function Styles({ ctx, id, setId }) {
  const file = useRef(null);
  const draft = ctx.project?.style_draft;
  const selected = ctx.server.profiles.find((profile) => profile.profile_id === id) ||
    (id && draft?.profile_id === id ? draft : null);
  function importFile(event) {
    const value = event.target.files?.[0];
    event.target.value = '';
    if (!value) return;
    ctx.run('profile_import', async () => {
      if (value.size > 1024 * 1024) throw new Error('스타일 JSON은 1MB 이하만 가져올 수 있습니다.');
      try {
        return { ...JSON.parse((await value.text()).replace(/^\uFEFF/, '')), approve: false };
      } catch {
        throw new Error('올바른 ReelMate 스타일 JSON을 선택하세요.');
      }
    }, { done: (_server, ack) => setId(ack.profile_id), message: '스타일 JSON을 불러오는 중' });
  }
  return <div className="page-stack">
    <Panel title="편집 스타일" description="완성 릴스에서 얻은 편집 기준을 보관하고 프로젝트에서 재사용하세요."
      action={<><input className="sr-only" type="file" ref={file} accept=".json" onChange={importFile} tabIndex={-1} />
        <Button icon={Upload} disabled={ctx.dirty} onClick={() => file.current.click()}>스타일 JSON 가져오기</Button></>}>
      {!ctx.server.profiles.length && !draft && <Empty icon={Sparkles} title="저장한 스타일이 없습니다"
        detail="프로젝트에 완성 릴스 3편을 등록하고 분석 단계에서 스타일을 측정하세요." />}
      <div className="project-list">
        {ctx.server.profiles.map((profile) => <article key={profile.profile_id} className="project-row">
          <div className="asset-icon"><Sparkles size={21} /></div>
          <div className="grow"><h3>{profile.name}</h3>
            <p>{profile.approved_at ? '승인됨' : '초안'} · 평균 컷 {profile.avg_shot_length}초 · {profile.evidence.length}편</p>
            <small>{dateText(profile.updated_at)}</small></div>
          <div className="button-row">
            <Button icon={Download} disabled={ctx.dirty} onClick={() => jsonDownload('ReelMate-style-' + profile.profile_id.slice(0, 8) + '.json', profile)}>JSON</Button>
            <Button disabled={ctx.dirty} onClick={() => setId(profile.profile_id)}>스타일 열기 <ArrowRight size={16} /></Button>
          </div>
        </article>)}
        {draft && !ctx.server.profiles.some((profile) => profile.profile_id === draft.profile_id) &&
          <article className="project-row">
            <div className="asset-icon"><Sparkles size={21} /></div><div className="grow"><h3>현재 프로젝트 측정 초안</h3>
              <p>{draft.evidence.length}편 · 평균 컷 {draft.avg_shot_length}초</p></div>
            <Button disabled={ctx.dirty} onClick={() => setId(draft.profile_id)}>초안 열기 <ArrowRight size={16} /></Button>
          </article>}
      </div>
    </Panel>
    {selected && <ProfileEditor key={selected.profile_id} ctx={ctx} profile={selected} isDraft={!selected.updated_at} setId={setId} />}
  </div>;
}
