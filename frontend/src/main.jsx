import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  ArrowRight, Check, Clapperboard, FolderOpen, HardDrive, PlusCircle, Settings, Sparkles, X,
} from 'lucide-react';
import { ProjectForm, ProjectList, SettingsPage } from './projects';
import { Materials, Analysis } from './materials';
import { Review, ExportPage } from './review';
import { Styles } from './styles';
import { Busy, Notice, newKey, stepNames } from './ui';
import './style.css';

const send = (type, fields = {}) => window.parent.postMessage(
  { isStreamlitMessage: true, type, ...fields }, window.location.origin,
);

const hasUsableCandidates = (project) => Boolean(project?.segments.some((segment) => !segment.excluded));

function suggestedStep(project) {
  if (!project) return 1;
  if (project.plan) {
    const hasCurrentOutput = [...project.outputs, ...project.capcut_exports].some((output) =>
      output.version === project.plan.version);
    return hasCurrentOutput ? 5 : 4;
  }
  if (hasUsableCandidates(project) && project.history.some((entry) => entry.action === 'candidates_save')) return 4;
  return project.assets.length ? 3 : 2;
}

function Hero() {
  return <header className="hero">
    <div>
      <span className="eyebrow"><span /> CREATOR WORKSPACE</span>
      <h1>내 스타일로, <em>협업 릴스 초안 생성하기</em></h1>
      <p>촬영 원본과 브랜드 가이드에서 컷과 자막을 구성하고, 내 편집 스타일을 다시 사용하세요.</p>
    </div>
    <svg className="hero-art" viewBox="0 0 256 150" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="clap" x1="48" y1="36" x2="201" y2="137" gradientUnits="userSpaceOnUse">
          <stop stopColor="#ffc084"/><stop offset="1" stopColor="#ff8a3b"/>
        </linearGradient>
        <linearGradient id="hero-bg" x1="30" y1="116" x2="230" y2="20" gradientUnits="userSpaceOnUse">
          <stop stopColor="#fff5eb"/><stop offset="1" stopColor="#ffdfc0"/>
        </linearGradient>
      </defs>
      <rect x="18" y="15" width="219" height="119" rx="24" fill="url(#hero-bg)" fillOpacity=".65"/>
      <path d="M31 123c24-35 40-8 56-33s39-25 51-10 32 16 50-8c13-17 32-19 48-12v50a24 24 0 0 1-24 24H55c-10 0-19-5-24-11Z" fill="#ffe6cf"/>
      <path d="M213 25v16m-8-8h16M42 52v10m-5-5h10M197 109v12m-6-6h12" stroke="#ee954d" strokeWidth="2.5" strokeLinecap="round"/>
      <g transform="rotate(-11 126 80)">
        <rect x="68" y="54" width="112" height="66" rx="12" fill="url(#clap)"/>
        <rect x="68" y="48" width="112" height="14" rx="3" fill="#f68a3d"/>
        <path d="m86 48 12 14m13-14 12 14m13-14 12 14m13-14 12 14" stroke="#ffeedf" strokeWidth="7"/>
        <g transform="rotate(-11 70 54)">
          <rect x="68" y="33" width="112" height="15" rx="3" fill="#ffab6b"/>
          <path d="m85 33 12 15m13-15 12 15m13-15 12 15m13-15 12 15" stroke="#fff6ec" strokeWidth="7"/>
        </g>
        <path d="M118 77c0-2 2.2-3.3 4-2.2l20 12c1.7 1 1.7 3.5 0 4.5l-20 12c-1.8 1.1-4-.2-4-2.2V77Z" fill="#fff"/>
      </g>
    </svg>
  </header>;
}

function App() {
  const [server, setServer] = useState(null);
  const [view, setView] = useState('workflow');
  const [step, setStep] = useState(1);
  const [newProject, setNewProject] = useState(false);
  const [dirty, markDirty] = useState(false);
  const [pending, setPending] = useState(null);
  const [notice, setNotice] = useState(null);
  const [inspected, inspect] = useState(null);
  const [styleId, setStyleId] = useState(null);
  const pendingRef = useRef(null);
  const dirtyRevision = useRef(null);
  const initialized = useRef(false);

  useEffect(() => {
    function receive(event) {
      if (event.source !== window.parent || event.origin !== window.location.origin ||
          event.data?.type !== 'streamlit:render') return;
      const next = event.data.args?.state;
      if (!next) return;
      if (!initialized.current) {
        initialized.current = true;
        setStep(suggestedStep(next.project));
      }
      setServer(next);
    }
    function resize() {
      document.documentElement.style.setProperty('--viewport', window.parent.innerHeight + 'px');
    }
    window.addEventListener('message', receive);
    window.parent.addEventListener('resize', resize);
    resize();
    const observer = new ResizeObserver(() => {
      send('streamlit:setFrameHeight', { height: document.getElementById('root').offsetHeight });
    });
    observer.observe(document.getElementById('root'));
    send('streamlit:componentReady', { apiVersion: 1 });
    return () => {
      observer.disconnect();
      window.removeEventListener('message', receive);
      window.parent.removeEventListener('resize', resize);
    };
  }, []);

  useEffect(() => {
    const ack = server?.ack;
    const current = pendingRef.current;
    if (!ack || !current || ack.id !== current.id) return;
    pendingRef.current = null;
    setPending(null);
    if (ack.message) setNotice({ ok: ack.ok, message: ack.message });
    if (ack.ok) {
      if (current.save) setDirty(false);
      current.done?.(server, ack);
    }
  }, [server]);

  function setDirty(value) {
    if (value && dirtyRevision.current === null) dirtyRevision.current = server?.project?.revision ?? 0;
    if (!value) dirtyRevision.current = null;
    markDirty(value);
  }

  async function run(action, body = {}, options = {}) {
    if (pendingRef.current || (dirty && !options.allowDirty && !options.save)) return;
    const id = newKey();
    pendingRef.current = { id, save: options.save, done: options.done };
    setPending(options.message || '저장 중');
    setNotice(null);
    try {
      const payload = typeof body === 'function' ? await body() : body;
      send('streamlit:setComponentValue', {
        dataType: 'json',
        value: { id, action, body: payload, project_id: server?.project?.project_id,
          revision: options.save && dirtyRevision.current !== null ? dirtyRevision.current : server?.project?.revision },
      });
    } catch (error) {
      pendingRef.current = null;
      setPending(null);
      setNotice({ ok: false, message: error.message || '요청을 전송하지 못했습니다.' });
    }
  }

  function navigate(destination) {
    if (dirty || pending) return;
    setNotice(null);
    inspect(null);
    if (destination === 'new') {
      setNewProject(true);
      setStep(1);
      setView('workflow');
      return;
    }
    setView(destination);
  }

  function showStep(next) {
    inspect(null);
    setStep(next);
    setView('workflow');
  }

  const project = newProject ? null : server?.project;
  const hasAssets = Boolean(project?.assets.length);
  const hasCandidates = hasUsableCandidates(project);
  const hasPlan = Boolean(project?.plan);
  const available = [true, Boolean(project), hasAssets, hasCandidates || hasPlan, hasPlan];
  const canGoto = (next) => available[next - 1] && !dirty && !pending;

  function goto(next) {
    if (!canGoto(next)) return;
    setNotice(null);
    showStep(next);
  }

  const ctx = {
    server, project, dirty, setDirty, pending, run, goto, canGoto, navigate, hasCandidates,
    inspect: (assetId, at) => inspect({ assetId, at }),
    inspected, closeInspect: () => inspect(null),
    openStyle: (id) => { setStyleId(id); navigate('styles'); },
    created: () => { setNewProject(false); showStep(2); },
    opened: (next) => {
      setNewProject(false);
      showStep(suggestedStep(next.project));
    },
    draftCreated: ({ project: savedProject }) => { if (savedProject?.plan) showStep(4); },
  };

  const currentNav = view === 'workflow' ? 'new' : view;

  if (!server) return <main className="boot"><Busy message="ReelMate 작업 공간을 여는 중" /></main>;
  return <div className="studio">
    <header className="topbar">
      <div className="wordmark"><span className="mark"><Clapperboard size={21} aria-hidden="true" /></span> ReelMate</div>
      <div className="topbar-right">
        <span className="work-badge">{pending ? <Busy message={pending} /> : <><i />{server.local ? '로컬 작업 공간' : '세션 작업 공간'}</>}</span>
      </div>
    </header>
    <div className="layout">
      <aside className="sidebar">
        <nav aria-label="작업 공간" className="sidebar-nav">
          {[
            ['new', '새 프로젝트', PlusCircle], ['projects', '내 프로젝트', FolderOpen],
            ['styles', '편집 스타일', Sparkles], ['settings', '설정', Settings],
          ].map(([id, label, Icon]) => <button key={id} type="button"
            className={currentNav === id ? 'selected' : ''} aria-current={currentNav === id ? 'page' : undefined}
            disabled={dirty || !!pending} onClick={() => navigate(id)}>
            <Icon size={20} aria-hidden="true" />{label}
          </button>)}
        </nav>
        <div className="sidebar-note"><HardDrive size={16} /><div><strong>{server.local ? '이 PC에 저장' : '세션별 저장'}</strong>
          <span>ReelMate Studio</span></div></div>
      </aside>
      <main className="workspace" aria-busy={Boolean(pending)}>
        {view === 'workflow' && <><Hero />
          <nav className="steps" aria-label="프로젝트 단계">
            {stepNames.map((name, index) => <button key={name} type="button" onClick={() => goto(index + 1)}
              aria-current={step === index + 1 ? 'step' : undefined}
              className={step === index + 1 ? 'current' : step > index + 1 ? 'complete' : ''}
              disabled={!canGoto(index + 1)}>
              <span className="step-dot">{step > index + 1 ? <Check size={15} /> : index + 1}</span>
              <span>{name}</span>
            </button>)}
          </nav>
        </>}
        {notice && <div className={'toast ' + (notice.ok ? 'ok' : 'fail')} role={notice.ok ? 'status' : 'alert'}>
          {notice.ok ? <Check size={18} /> : <span className="exclamation">!</span>}<span>{notice.message}</span>
          <button type="button" aria-label="알림 닫기" onClick={() => setNotice(null)}><X size={16} /></button>
        </div>}
        {dirty && <div className="dirty-note" role="status">변경을 저장하거나 취소하면 다른 단계로 이동할 수 있습니다.</div>}
        <fieldset className="work-fields" disabled={Boolean(pending)}>
          {view === 'workflow' && <>
            {step === 1 && <ProjectForm key={project?.project_id || 'new'} ctx={ctx} />}
            {step === 2 && project && <Materials key={project.project_id} ctx={ctx} />}
            {step === 3 && project && <Analysis key={project.project_id} ctx={ctx} />}
            {step === 4 && project && <Review key={project.project_id} ctx={ctx} />}
            {step === 5 && project && <ExportPage key={project.project_id} ctx={ctx} />}
          </>}
          {view === 'projects' && <ProjectList ctx={ctx} />}
          {view === 'styles' && <Styles ctx={ctx} id={styleId} setId={setStyleId} />}
          {view === 'settings' && <SettingsPage ctx={ctx} />}
        </fieldset>
        <footer className="footer"><span>ReelMate <b>·</b> Creator Studio</span>
          {project && <span>{project.brand} <ArrowRight size={12} /> {project.product}</span>}
        </footer>
      </main>
    </div>
  </div>;
}

createRoot(document.getElementById('root')).render(<App />);
