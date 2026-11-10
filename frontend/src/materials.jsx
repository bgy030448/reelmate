import { useState } from 'react';
import {
  ArrowRight, CheckCircle2, Clapperboard, FileText, Film, ScanLine, Plus, Sparkles,
  Trash2, UploadCloud,
} from 'lucide-react';
import {
  Button, EditActions, Empty, Field, InspectAsset, Notice, Pager, Panel, SourceButton,
  mediaUrl, newKey, numeric, time, useDraft,
} from './ui';

const MB = 1024 * 1024;
const mediaAccept = '.mp4,.mov,.m4v,.webm';
const layouts = {
  source: { icon: Film, title: '촬영 원본', detail: '새 릴스에 사용할 원본을 등록하세요.', label: '촬영 원본 파일' },
  reference: { icon: Sparkles, title: '완성 레퍼런스', detail: '스타일 분석에 사용할 완성본을 3편 이상 등록하세요.', label: '완성 레퍼런스 파일' },
  guide: { icon: FileText, title: '브랜드 가이드', detail: '브랜드가 전달한 가이드의 PDF 또는 텍스트를 등록하세요.', label: '브랜드 가이드 파일' },
};

function base64File(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({ name: file.name, data: String(reader.result).split(',', 2)[1] });
    reader.onerror = () => reject(new Error('파일을 읽지 못했습니다. 다시 선택하세요.'));
    reader.readAsDataURL(file);
  });
}

function UploadArea({ ctx, role }) {
  const [drag, setDrag] = useState(false);
  const entry = layouts[role];
  const Icon = entry.icon;
  const guide = role === 'guide';
  function upload(list) {
    const files = Array.from(list);
    if (!files.length || ctx.dirty || ctx.pending) return;
    ctx.run('upload', async () => {
      const count = guide ? 1 : 6;
      const size = guide ? 5 : 20;
      if (files.length > count || files.some((file) => !file.size || file.size > size * MB)) {
        throw new Error('한 번에 최대 ' + count + '개, 파일당 ' + size + 'MB까지 등록할 수 있습니다.');
      }
      const stored = ctx.project.assets.reduce((total, asset) => total + asset.size, 0);
      if (!guide && stored + files.reduce((total, file) => total + file.size, 0) > 100 * MB) {
        throw new Error('프로젝트의 영상 합계는 100MB까지 등록할 수 있습니다.');
      }
      const encoded = [];
      for (const file of files) encoded.push(await base64File(file));
      return { role, files: encoded };
    }, { message: entry.title + ' 등록 중' });
  }
  return <article className="upload-card">
    <span className="asset-icon"><Icon size={22} /></span>
    <h3>{entry.title}</h3>
    <p>{entry.detail}</p>
    <label className={'drop-zone ' + (drag ? 'drag' : '') + (ctx.dirty ? ' disabled' : '')}
      onDragOver={(event) => { event.preventDefault(); if (!ctx.dirty) setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(event) => { event.preventDefault(); setDrag(false); upload(event.dataTransfer.files); }}>
      <input type="file" aria-label={entry.label} multiple={!guide} disabled={ctx.dirty}
        accept={guide ? '.pdf,.txt' : mediaAccept}
        onChange={(event) => { upload(event.target.files); event.target.value = ''; }} />
      <UploadCloud size={19} /><strong>파일 선택</strong><small>또는 끌어 놓기</small>
    </label>
    <small>{guide ? 'PDF · TXT · 5MB 이하' : 'MP4 · MOV · M4V · WebM · 파일당 20MB'}</small>
  </article>;
}

function AssetList({ ctx, assets }) {
  if (!assets.length) return <Empty icon={Clapperboard} title="등록된 영상이 없습니다"
    detail="촬영 원본이나 완성 레퍼런스를 선택해 주세요." />;
  return <div className="asset-list">
    {assets.map((asset) => <article key={asset.asset_id} className="asset-row">
      <img className="thumb" alt="" src={mediaUrl(asset.thumbnail_url)} />
      <div className="grow">
        <span className="overline">{asset.role === 'source' ? '촬영 원본' : '완성 레퍼런스'}</span>
        <h4>{asset.filename}</h4>
        <p>{time(asset.duration)} · {asset.width}×{asset.height} · {asset.codec} · {asset.fps}fps · {asset.has_audio ? '오디오 있음' : '무음'}</p>
        {asset.transcript && <small>Whisper 전사 {asset.transcript.segments.length}개 · {asset.transcript.model}</small>}
      </div>
      <div className="button-row">
        <SourceButton ctx={ctx} asset={asset} />
        {asset.role === 'source' && asset.has_audio && ctx.server.capabilities.whisper &&
          <Button disabled={ctx.dirty} onClick={() => ctx.run('transcribe', { asset_id: asset.asset_id },
            { message: 'Whisper로 음성을 전사하는 중' })}>Whisper 전사</Button>}
      </div>
    </article>)}
  </div>;
}

function RuleEditor({ ctx }) {
  const { project, server } = ctx;
  const [rules, change, discard] = useDraft(project.rules, project.revision, ctx);
  const [confirm, setConfirm] = useState(false);
  const update = (index, value) => {
    setConfirm(false);
    change(rules.map((row, i) => i === index ? { ...row, ...value } : row));
  };
  const save = () => ctx.run('rules_save', {
    rules: rules.map((row) => ({
      ...row, deadline_sec: numeric(row.deadline_sec),
      value: ['duration', 'max_duration'].includes(row.type) ? numeric(row.value) : row.value,
    })),
  }, { save: true, message: '브랜드 규칙을 저장하는 중' });

  return <section className="subsection">
    <div className="section-head">
      <div><h3>브랜드 규칙</h3>
        <p>장면 규칙은 사람이 확인한 라벨로 검사합니다. 화면·음성 조건에는 직접 확인 규칙을 사용하세요.</p></div>
      <span className={'pill ' + (project.rules_approved ? 'success' : 'neutral')}>
        {project.rules_approved ? '승인됨' : '승인 대기'}
      </span>
    </div>
    {project.guide && <details className="details">
      <summary>가이드 원문 · {project.guide.filename}</summary><pre>{project.guide.text}</pre>
    </details>}
    <div className="button-row">
      <Button icon={Plus} disabled={rules.length >= 100} onClick={() => change([...rules, {
        _key: newKey(), type: 'scene', value: 'product', required: true, description: '', deadline_sec: null,
      }])}>규칙 추가</Button>
      {project.guide && <Button icon={Sparkles} disabled={ctx.dirty || !server.capabilities.gemini}
        title={!server.capabilities.gemini ? '서버 Gemini 설정이 필요합니다.' : undefined}
        onClick={() => ctx.run('guide_parse', {}, { message: 'Gemini가 가이드를 구조화하는 중' })}>Gemini 규칙 초안 만들기</Button>}
    </div>
    {project.guide && <p className="muted small">Gemini를 사용하면 가이드 본문이 Google API에 전송되며 현재 규칙을 새 초안으로 교체합니다.
      {!server.capabilities.gemini && ' 서버 설정 후 사용할 수 있습니다.'}</p>}
    {project.rule_source && <p className="muted small">규칙 출처 · {project.rule_source}</p>}
    {rules.map((rule, index) => {
      const scene = ['scene', 'product_deadline'].includes(rule.type);
      const duration = ['duration', 'max_duration'].includes(rule.type);
      return <div className="rule-card" key={rule.rule_id || rule._key}>
        <div className="section-head"><strong>규칙 {index + 1}</strong>
          <Button icon={Trash2} className="icon-button" aria-label={'규칙 ' + (index + 1) + ' 삭제'}
            onClick={() => change(rules.filter((_, i) => index !== i))} /></div>
        <div className="field-grid">
          <Field label="규칙 유형"><select value={rule.type} onChange={(event) => {
            const type = event.target.value;
            update(index, { type, value: ['scene', 'product_deadline'].includes(type) ? 'product' : '',
              deadline_sec: type === 'product_deadline' ? 3 : null });
          }}>{Object.entries(server.rule_types).map(([type, label]) => <option key={type} value={type}>{label}</option>)}</select></Field>
          <Field label={scene ? '장면 분류' : duration ? '기준 길이 (초)' : '규칙 내용'}>
            {scene ? <select value={rule.value} onChange={(event) => update(index, { value: event.target.value })}>
              {Object.entries(server.labels).filter(([label]) => label !== 'unknown')
                .map(([label, text]) => <option key={label} value={label}>{text}</option>)}
            </select> : <input type={duration ? 'number' : 'text'} min={duration ? '0.1' : undefined}
              max={duration ? '60' : undefined} step={duration ? '0.001' : undefined} maxLength={400}
              value={rule.value ?? ''} onChange={(event) => update(index, { value: event.target.value })} />}
          </Field>
          <Field label="규칙 설명"><input value={rule.description} maxLength={400}
            onChange={(event) => update(index, { description: event.target.value })} /></Field>
          {['scene', 'product_deadline', 'required_text'].includes(rule.type) &&
            <Field label="확인 기한 (초)" hint={rule.type === 'product_deadline' ? '필수' : '선택'}>
              <input type="number" min="0" max="60" step="0.001" value={rule.deadline_sec ?? ''}
                onChange={(event) => update(index, { deadline_sec: event.target.value })} />
            </Field>}
        </div>
        <label className="check-label"><input type="checkbox" checked={rule.required}
          onChange={(event) => update(index, { required: event.target.checked })} />필수 조건으로 검사</label>
      </div>;
    })}
    <EditActions ctx={ctx} discard={discard} submit={save} label="규칙 저장" />
    {!project.rules_approved && !ctx.dirty && (project.guide || rules.length > 0) && <div className="approval">
      <label className="check-label"><input type="checkbox" checked={confirm} onChange={(event) => setConfirm(event.target.checked)} />
        {rules.length ? '규칙을 확인했습니다.' : '가이드에 검수해야 할 조건이 없음을 확인했습니다.'}</label>
      <Button icon={CheckCircle2} disabled={!confirm} onClick={() => ctx.run('rules_approve', { confirmed: true },
        { done: () => setConfirm(false) })}>규칙 승인</Button>
    </div>}
  </section>;
}

export function Materials({ ctx }) {
  const { project } = ctx;
  const [writing, setWriting] = useState(false);
  const [guide, setGuide] = useState('');
  const selected = project.assets.find((asset) => asset.asset_id === ctx.inspected?.assetId);
  return <Panel step={2} title="작업 자료 등록" description="촬영 원본, 완성 레퍼런스, 브랜드 가이드를 용도별로 등록하세요.">
    <div className="uploads">{Object.keys(layouts).map((role) => <UploadArea key={role} ctx={ctx} role={role} />)}</div>
    <p className="muted small limits">한 번에 영상 최대 6개 · 원본당 120초 · 프로젝트 영상 합계 100MB</p>
    <div className="subsection">
      <div className="section-head"><div><h3>등록 자료</h3><p>등록한 영상의 재생 정보와 썸네일을 확인하세요.</p></div>
        <span className="pill neutral">영상 {project.assets.length}개</span>
      </div>
      <AssetList ctx={ctx} assets={project.assets} />
      <InspectAsset asset={selected} at={ctx.inspected?.at} onClose={ctx.closeInspect} />
    </div>
    {!writing && <div className="button-row">
      <Button icon={FileText} disabled={ctx.dirty} onClick={() => { setGuide(project.guide?.text || ''); setWriting(true); }}>
        브랜드 가이드 직접 입력
      </Button>
    </div>}
    {writing ? <section className="subsection form-stack">
      <Field label="브랜드 가이드 본문" hint="기존 가이드를 교체하면 이전 규칙을 다시 작성하고 승인해야 합니다.">
        <textarea rows={7} value={guide} maxLength={50000}
          onChange={(event) => { setGuide(event.target.value); ctx.setDirty(true); }} />
      </Field>
      <div className="button-row"><Button onClick={() => { setWriting(false); ctx.setDirty(false); }}>입력 취소</Button>
        <Button variant="primary" disabled={!guide.trim()} onClick={() => ctx.run('guide_text', { text: guide },
          { save: true, done: () => setWriting(false) })}>가이드 저장</Button></div>
    </section> : <RuleEditor ctx={ctx} />}
    <Pager previous={() => ctx.goto(1)} next={() => ctx.goto(3)}
      disabled={ctx.dirty || !project.assets.length} reason={!project.assets.length ? '영상 자료를 등록하면 분석할 수 있습니다.' : undefined}
      nextLabel="분석으로 이동" />
  </Panel>;
}

export function Analysis({ ctx }) {
  const { project, server } = ctx;
  const [segments, change, discard] = useDraft(project.segments, project.revision, ctx);
  const [assetId, setAssetId] = useState('');
  const [useClip, setUseClip] = useState(false);
  const [useOcr, setUseOcr] = useState(false);
  const sources = project.assets.filter((asset) => asset.role === 'source');
  const references = project.assets.filter((asset) => asset.role === 'reference');
  const current = sources.find((asset) => asset.asset_id === ctx.inspected?.assetId);
  const savedPlan = project.plan;
  function addScene() {
    const asset = sources.find((source) => source.asset_id === (assetId || sources[0]?.asset_id));
    if (!asset) return;
    change([...segments, { _key: newKey(), asset_id: asset.asset_id, start: 0, end: asset.duration,
      label: 'unknown', human_verified: false, excluded: false, source: 'manual', thumbnail_url: asset.thumbnail_url }]);
  }
  function edit(index, value) {
    change(segments.map((row, i) => i === index ? { ...row, ...value } : row));
  }
  function save() {
    ctx.run('candidates_save', { segments: segments.map((segment) => ({
      ...segment, start: numeric(segment.start), end: numeric(segment.end),
    })) }, { save: true, message: '장면 후보를 저장하는 중' });
  }
  const hasCandidates = project.segments.some((segment) => !segment.excluded);
  const create = (method) => ctx.run('plan_create', { method }, {
    message: method === 'gemini' ? 'Gemini가 편집안을 작성하는 중' : '편집 초안을 구성하는 중',
    done: () => ctx.goto(4),
  });
  return <Panel step={3} title="영상 분석" description="장면 후보를 확인하고 레퍼런스에서 내 편집 스타일을 측정하세요.">
    <div className="analysis-cards">
      <section className="mini-card">
        <div className="section-head"><span className="asset-icon"><ScanLine size={22} /></span>
          <span className="pill neutral">원본 {sources.length}개</span></div>
        <h3>촬영 원본 장면</h3><p>CLIP이 프레임을 분류하고 인접 결과를 구간으로 묶습니다.</p>
        <Button icon={ScanLine} disabled={ctx.dirty || !sources.length || !server.capabilities.clip}
          onClick={() => ctx.run('clip_analyze', {}, { message: 'CLIP으로 원본을 분석하는 중' })}>CLIP 장면 분석</Button>
        <small>{server.capabilities.clip ? '첫 분석에는 모델 다운로드가 필요할 수 있습니다.' : 'CLIP 선택 의존성을 설치하거나 장면 라벨을 직접 입력하세요.'}</small>
      </section>
      <section className="mini-card peach">
        <div className="section-head"><span className="asset-icon"><Sparkles size={22} /></span>
          <span className="pill neutral">레퍼런스 {references.length}편</span></div>
        <h3>내 편집 스타일 측정</h3><p>컷 전환과 평균 컷 길이를 측정하고 스타일 근거를 저장합니다.</p>
        <div className="button-row">
          <label className="check-label"><input type="checkbox" checked={useClip} disabled={!server.capabilities.clip}
            onChange={(event) => setUseClip(event.target.checked)} />CLIP 의미 추정</label>
          <label className="check-label"><input type="checkbox" checked={useOcr} disabled={!server.capabilities.ocr}
            onChange={(event) => setUseOcr(event.target.checked)} />OCR 화면 글자</label>
        </div>
        <div className="button-row">
          <Button icon={Sparkles} disabled={ctx.dirty || references.length < 3}
            onClick={() => ctx.run('style_measure', { clip: useClip, ocr: useOcr }, { message: '레퍼런스 스타일을 측정하는 중' })}>스타일 측정</Button>
          {project.style_draft && <Button disabled={ctx.dirty} onClick={() => ctx.openStyle(project.style_draft.profile_id)}>스타일 초안 열기</Button>}
        </div>
        {references.length < 3 && <small>완성 레퍼런스 3편을 등록하면 측정할 수 있습니다.</small>}
      </section>
    </div>
    <section className="subsection">
      <div className="section-head"><div><h3>장면 후보</h3><p>라벨을 확인하기 전에 해당 장면이 이어지는 범위로 시작·종료 시간을 좁혀 주세요. 유사도는 모델의 비교 점수입니다.</p></div>
        <span className="pill neutral">{segments.length}개</span>
      </div>
      {sources.length > 0 && <div className="inline-form">
        <Field label="새 후보의 원본"><select value={assetId || sources[0].asset_id} onChange={(event) => setAssetId(event.target.value)}>
          {sources.map((asset) => <option key={asset.asset_id} value={asset.asset_id}>{asset.filename}</option>)}
        </select></Field>
        <Button icon={Plus} onClick={addScene}>구간 추가</Button>
      </div>}
      <InspectAsset asset={current} at={ctx.inspected?.at} onClose={ctx.closeInspect} />
      {segments.length === 0 && <Empty icon={Film} title="촬영 원본을 등록하면 장면 후보가 표시됩니다" />}
      <div className="scene-list">
        {segments.map((segment, index) => {
          const asset = sources.find((entry) => entry.asset_id === segment.asset_id);
          if (!asset) return null;
          return <article className={'scene-card ' + (segment.excluded ? 'excluded' : '')} key={segment.segment_id || segment._key}>
            <img className="scene-thumb" src={mediaUrl(segment.thumbnail_url)} alt="" />
            <div className="scene-body">
              <div className="section-head"><div><h4>{asset.filename}</h4>
                <p>{segment.human_verified ? '사람 확인' : segment.source === 'clip' ? 'CLIP 후보' : '수동 검토 대기'}
                  {segment.similarity != null && ' · 유사도 ' + segment.similarity.toFixed(3)}</p></div>
                <SourceButton ctx={ctx} asset={asset} at={numeric(segment.start) || 0} />
              </div>
              <div className="scene-fields">
                <Field label="분류"><select value={segment.label} onChange={(event) =>
                  edit(index, { label: event.target.value, human_verified: false })}>
                  {Object.entries(server.labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                </select></Field>
                <Field label="시작 (초)"><input type="number" min="0" max={asset.duration} step="0.001" value={segment.start}
                  onChange={(event) => edit(index, { start: event.target.value, human_verified: false })} /></Field>
                <Field label="종료 (초)"><input type="number" min="0" max={asset.duration} step="0.001" value={segment.end}
                  onChange={(event) => edit(index, { end: event.target.value, human_verified: false })} /></Field>
              </div>
              <div className="button-row scene-controls">
                <label className="check-label"><input type="checkbox" checked={segment.human_verified}
                  disabled={segment.label === 'unknown'} onChange={(event) => edit(index, { human_verified: event.target.checked })} />라벨 확인</label>
                <label className="check-label"><input type="checkbox" checked={segment.excluded}
                  onChange={(event) => edit(index, { excluded: event.target.checked })} />편집에서 제외</label>
                <Button className="icon-button" icon={Trash2} aria-label={'구간 ' + (index + 1) + ' 삭제'}
                  onClick={() => change(segments.filter((_, i) => i !== index))} />
              </div>
              {segment.samples?.length > 0 && <details className="details">
                <summary>프레임 근거 · {segment.model}</summary>
                <ul className="compact-list">{segment.samples.map((sample) => <li key={sample.time}>
                  {time(sample.time)} · {server.labels[sample.label]} · 유사도 {sample.similarity.toFixed(3)}
                </li>)}</ul>
              </details>}
            </div>
          </article>;
        })}
      </div>
      <EditActions ctx={ctx} discard={discard} submit={save} label="장면 저장" />
    </section>
    {hasCandidates && !savedPlan && <section className="subsection">
      <div className="section-head"><div><h3>편집안 만들기</h3><p>현재 사용할 수 있는 장면 후보에서 시작합니다.</p></div></div>
      <div className="button-row">
        <Button disabled={ctx.dirty} onClick={() => create('local')}>수동 편집 초안</Button>
        <Button variant="primary" icon={Sparkles} disabled={ctx.dirty || !server.capabilities.gemini}
          onClick={() => create('gemini')}>Gemini 편집안 만들기</Button>
      </div>
      <p className="muted small">Gemini 사용 시 브랜드·제품명, 후보 시간과 라벨, 규칙 및 스타일 설정을 Google API에 전송합니다.
        {!server.capabilities.gemini && ' 서버 설정이 필요합니다.'}</p>
    </section>}
    {project.guide && !project.rules_approved && <Notice>가이드 규칙 승인 후 최종 영상을 생성할 수 있습니다.</Notice>}
    <Pager previous={() => ctx.goto(2)} next={() => ctx.goto(4)} disabled={ctx.dirty || !hasCandidates} nextLabel="검토로 이동" />
  </Panel>;
}
