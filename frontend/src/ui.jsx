import { cloneElement, useEffect, useId, useRef, useState } from 'react';
import { ArrowLeft, ArrowRight, CircleAlert, Info, LoaderCircle, Play, X } from 'lucide-react';

export const stepNames = ['프로젝트', '자료', '분석', '검토', '내보내기'];
export const positions = { top: '상단', middle: '중앙', bottom: '하단' };
export const dateText = (value) => value
  ? new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
  : '';
export const numeric = (value) => value === '' || value == null ? null : Number(value);
export const time = (sec) => Number(sec).toFixed(2) + '초';
export const frame = (sec) => Math.round(sec * 30);
export const toSeconds = (frames) => Math.round(frames / 30 * 1000) / 1000;
export const newKey = () => globalThis.crypto?.randomUUID?.() || Date.now() + '-' + Math.random();

export function mediaUrl(path) {
  if (!path) return undefined;
  const base = window.parent.location.pathname.replace(/\/?$/, '/');
  return new URL(path.replace(/^\//, ''), window.location.origin + base).href;
}

export function Button({ children, icon: Icon, variant = 'secondary', className = '', type = 'button', ...props }) {
  return <button type={type} className={'button ' + variant + ' ' + className} {...props}>
    {Icon && <Icon size={17} aria-hidden="true" />}{children}
  </button>;
}

export function Panel({ step, title, description, action, children, className = '' }) {
  return <section className={'panel ' + className}>
    <header className="panel-heading">
      {step && <span className="step-marker">{step}</span>}
      <div><h2>{title}</h2>{description && <p>{description}</p>}</div>
      {action && <div className="heading-action">{action}</div>}
    </header>
    {children}
  </section>;
}

export function Notice({ children, kind = 'info' }) {
  const Icon = kind === 'error' ? CircleAlert : Info;
  return <div className={'notice ' + kind} role={kind === 'error' ? 'alert' : undefined}>
    <Icon size={17} aria-hidden="true" /><div>{children}</div>
  </div>;
}

export function Field({ label, required = false, hint, children }) {
  const id = useId();
  const hintId = id + '-hint';
  return <div className="field">
    <label htmlFor={id}>{label}{required && <b className="required" aria-hidden="true"> *</b>}</label>
    {cloneElement(children, { id, 'aria-describedby': hint ? hintId : undefined })}
    {hint && <small id={hintId}>{hint}</small>}
  </div>;
}

export function Pager({ ctx, previous, next, nextLabel = '다음 단계', reason, children }) {
  return <div className="pager">
    {previous && <Button onClick={() => ctx.goto(previous)} disabled={!ctx.canGoto(previous)} icon={ArrowLeft}>이전 단계</Button>}
    {children}
    <div className="pager-next">
      {reason && <small>{reason}</small>}
      {next && <Button onClick={() => ctx.goto(next)} disabled={!ctx.canGoto(next)} variant="primary">
        {nextLabel}<ArrowRight size={17} />
      </Button>}
    </div>
  </div>;
}

export function useDraft(value, resetKey, ctx) {
  const source = useRef(value);
  source.current = value;
  const [draft, setDraft] = useState(value);
  useEffect(() => {
    if (!ctx.dirty) setDraft(source.current);
  }, [resetKey, ctx.dirty]);
  function change(next) {
    setDraft(next);
    ctx.setDirty(true);
  }
  function discard() {
    setDraft(source.current);
    ctx.setDirty(false);
  }
  return [draft, change, discard];
}

export function EditActions({ ctx, discard, submit, label = '변경 저장' }) {
  if (!ctx.dirty) return null;
  return <div className="edit-actions">
    <span>저장하지 않은 변경이 있습니다.</span>
    <Button onClick={discard}>변경 취소</Button>
    <Button variant="primary" onClick={submit}>{label}</Button>
  </div>;
}

export function Empty({ icon: Icon, title, detail, action }) {
  return <div className="empty">
    {Icon && <span className="empty-icon"><Icon size={24} /></span>}
    <strong>{title}</strong>
    {detail && <p>{detail}</p>}
    {action}
  </div>;
}

export function InspectAsset({ asset, at = 0, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    if (ref.current?.readyState >= 1) ref.current.currentTime = at;
  }, [asset?.preview_url, at]);
  if (!asset?.preview_url) return null;
  return <section className="inspector">
    <div className="section-head"><h3>{asset.filename}</h3>
      <Button className="icon-button" icon={X} aria-label="원본 미리보기 닫기" onClick={onClose} />
    </div>
    <video ref={ref} controls playsInline preload="metadata" src={mediaUrl(asset.preview_url)}
      onLoadedMetadata={(event) => { event.currentTarget.currentTime = at; }} />
    <p className="muted small">브라우저가 재생을 지원하는 코덱의 원본을 확인할 수 있습니다.</p>
  </section>;
}

export function SourceButton({ ctx, asset, at = 0, label = '원본 보기' }) {
  return <Button icon={Play} onClick={() => {
    ctx.inspect(asset.asset_id, at);
    if (!asset.preview_url) ctx.run('asset_select', { asset_id: asset.asset_id }, {
      message: '원본을 불러오는 중', allowDirty: true,
    });
  }}>{label}</Button>;
}

export function Busy({ message }) {
  return <span className="busy"><LoaderCircle aria-hidden="true" size={16} />{message}</span>;
}

export function jsonDownload(name, value) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
