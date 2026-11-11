import { useState } from 'react';
import {
  ArrowRight, CheckCircle2, Clapperboard, FolderOpen, HardDrive, LockKeyhole, PlusCircle,
  Settings, Sparkles, Trash2, TriangleAlert,
} from 'lucide-react';
import { Button, Empty, Field, Notice, Panel, dateText, numeric, useDraft } from './ui';

export function ProjectForm({ ctx }) {
  const { project, server } = ctx;
  const approved = server.profiles.filter((profile) => profile.approved_at);
  const value = project ? {
    brand: project.brand, product: project.product, aspect_ratio: project.aspect_ratio,
    target_duration: project.target_duration, profile_id: project.profile_id || '',
  } : { brand: '', product: '', aspect_ratio: '9:16', target_duration: 15, profile_id: '' };
  const [draft, change, discard] = useDraft(value, project?.revision, ctx);
  const update = (key, fieldValue) => change({ ...draft, [key]: fieldValue });
  const profile = approved.find((entry) => entry.profile_id === draft.profile_id);
  const ready = Boolean(draft.brand.trim() && draft.product.trim() && numeric(draft.target_duration) >= 1);
  function submit(event) {
    event.preventDefault();
    if (!ready) return;
    ctx.run(project ? 'project_settings' : 'project_create',
      { ...draft, target_duration: numeric(draft.target_duration) },
      { save: true, done: ctx.created, message: '프로젝트를 저장하는 중' });
  }
  return <Panel step={1} title="프로젝트 설정"
    description={project ? '이 프로젝트의 기본 정보와 편집 스타일을 관리합니다.' : '이번 콘텐츠의 기본 정보를 입력해 주세요.'}>
    <form onSubmit={submit}>
      <div className="project-grid">
        <div className="form-stack">
          <Field label="브랜드명" required><input required maxLength={80} value={draft.brand}
            placeholder="예: ABC 뷰티" onChange={(event) => update('brand', event.target.value)} /></Field>
          <Field label="제품명" required><input required maxLength={80} value={draft.product}
            placeholder="예: 수분 크림" onChange={(event) => update('product', event.target.value)} /></Field>
          <div className="field-grid">
            <Field label="목표 영상 길이 (초)"><input type="number" min="1" max="60" step="0.001" required
              value={draft.target_duration} onChange={(event) => update('target_duration', event.target.value)} /></Field>
            <Field label="출력 비율"><select value={draft.aspect_ratio}
              onChange={(event) => update('aspect_ratio', event.target.value)}>
              <option value="9:16">9:16 · 세로</option><option value="16:9">16:9 · 가로</option>
              <option value="1:1">1:1 · 정사각형</option>
            </select></Field>
          </div>
        </div>
        <div className="style-preview">
          <div className="style-title"><Sparkles size={21} /><h3>사용할 편집 스타일</h3></div>
          <Field label="편집 스타일"><select value={draft.profile_id} onChange={(event) => update('profile_id', event.target.value)}>
            <option value="">기본 편집 스타일</option>
            {approved.map((entry) => <option key={entry.profile_id} value={entry.profile_id}>{entry.name}</option>)}
          </select></Field>
          {profile ? <div className="style-description">
            <CheckCircle2 size={18} /><div><strong>{profile.name}</strong>
              <p>평균 컷 {profile.avg_shot_length}초 · 레퍼런스 근거 {profile.evidence.length}편</p></div>
          </div> : <div className="style-description">
            <Clapperboard size={20} /><div><strong>{approved.length ? '기본 편집 설정' : '아직 승인된 스타일이 없습니다'}</strong>
              <p>자료 단계에서 완성 릴스를 1편 이상 등록하면 편집 스타일을 측정하고 저장할 수 있습니다.</p></div>
          </div>}
        </div>
      </div>
      <div className="pager">
        {ctx.dirty && <Button onClick={discard}>변경 취소</Button>}
        <div className="pager-next">
          {!ready && <small>브랜드명과 제품명을 입력하세요.</small>}
          <Button type="submit" variant="primary" disabled={!ready}>저장하고 자료 등록 <ArrowRight size={18} /></Button>
        </div>
      </div>
    </form>
  </Panel>;
}

export function ProjectList({ ctx }) {
  const [confirm, setConfirm] = useState(false);
  const [text, setText] = useState('');
  const { server, project } = ctx;
  function open(id) {
    ctx.run('project_open', { project_id: id }, { message: '프로젝트를 여는 중', done: ctx.opened });
  }
  return <div className="page-stack">
    <Panel title="내 프로젝트" description="저장한 프로젝트를 열어 편집을 이어가세요."
      action={<Button variant="primary" icon={PlusCircle} onClick={() => ctx.navigate('new')}>새 프로젝트</Button>}>
      {!server.projects.length && <Empty icon={FolderOpen} title="저장한 프로젝트가 없습니다"
        detail="새 프로젝트에서 브랜드와 제품을 등록해 시작하세요." />}
      <div className="project-list">
        {server.projects.map((entry) => <article className="project-row" key={entry.project_id}>
          <div className="asset-icon"><Clapperboard size={23} /></div>
          <div className="grow"><h3>{entry.product}</h3><p>{entry.brand} · {entry.target_duration}초 · {entry.aspect_ratio}</p>
            <small>원본 {entry.source_count}개 · 출력 {entry.output_count}버전 · {dateText(entry.updated_at)}</small></div>
          <Button onClick={() => open(entry.project_id)}>프로젝트 열기 <ArrowRight size={16} /></Button>
        </article>)}
      </div>
    </Panel>
    {project && <Panel title="열린 프로젝트 관리" description={project.brand + ' / ' + project.product}>
      {confirm ? <div className="form-stack">
        <Notice kind="error">이 프로젝트의 원본·레퍼런스·가이드·편집안·출력·이력이 삭제됩니다. 별도로 저장한 스타일 프로필은 유지됩니다.</Notice>
        <Field label="삭제 확인용 제품명"><input value={text} onChange={(event) => setText(event.target.value)} /></Field>
        <div className="button-row"><Button onClick={() => setConfirm(false)}>취소</Button>
          <Button variant="danger" icon={Trash2} disabled={text !== project.product} onClick={() =>
            ctx.run('project_delete', { confirm: text }, { message: '프로젝트를 삭제하는 중',
              done: () => { setConfirm(false); setText(''); } })}>프로젝트와 파일 삭제</Button></div>
      </div> : <Button variant="danger" icon={Trash2} onClick={() => setConfirm(true)}>삭제 옵션 열기</Button>}
    </Panel>}
  </div>;
}

export function SettingsPage({ ctx }) {
  const { capabilities, local } = ctx.server;
  const rows = [
    ['FFmpeg · ffprobe', capabilities.ffmpeg, '메타데이터와 MP4 렌더링'],
    ['CLIP', capabilities.clip, capabilities.clip ? capabilities.clip_model + ' · 첫 실행 시 가중치 확인' : '선택 의존성 설치 필요'],
    ['Gemini', capabilities.gemini, capabilities.gemini_model || '서버 환경변수 또는 Streamlit Secrets에서 키와 모델 설정'],
    ['Whisper', capabilities.whisper, '선택형 원본 음성 전사'],
    ['Tesseract OCR', capabilities.ocr, '선택형 화면 글자 위치 분석'],
  ];
  return <div className="page-stack">
    <Panel title="설정" description="이 작업 공간에서 사용할 수 있는 기능을 확인하세요." action={<Settings size={23} />}>
      <div className="settings-list">{rows.map(([name, available, detail]) =>
        <div className="setting-row" key={name}><div><strong>{name}</strong><p>{detail}</p></div>
          <span className={'pill ' + (available ? 'success' : 'neutral')}>{available ? '사용 가능' : '설정 필요'}</span></div>)}</div>
    </Panel>
    <Panel title="자료 저장과 외부 연결">
      <div className="policy"><HardDrive size={22} /><div><strong>{local ? '개인용 로컬 저장' : '브라우저 세션별 작업 공간'}</strong>
        <p>{local ? '서버를 다시 시작해도 내 프로젝트에서 같은 저장 위치의 자료를 열 수 있습니다.' :
          '세션 종료 후 새 세션에서는 이전 작업 공간을 열 수 없습니다. 필요한 출력을 먼저 내려받으세요.'}
          {' '}파일은 프로젝트 삭제 시 정리됩니다. 자동 보관 만료 기능은 제공되지 않습니다.</p></div></div>
      <div className="policy"><LockKeyhole size={22} /><div><strong>Gemini에 전송되는 데이터</strong>
        <p>Gemini 기능을 선택하면 해당 기능의 가이드 본문, 브랜드·제품명, 후보의 라벨·시간, 규칙,
          스타일 측정값 또는 재편집 요청이 Google API로 전송됩니다. 영상과 API 키는 React 화면에서 전송하지 않습니다.</p></div></div>
      <div className="policy"><TriangleAlert size={22} /><div><strong>편집 패키지 호환성</strong>
        <p>대체 ZIP과 Windows CapCut 9.x 검증용 프로젝트 ZIP을 내보낼 수 있습니다. CapCut에서 편집·저장·재열기는 검증 대기입니다.</p></div></div>
    </Panel>
  </div>;
}
