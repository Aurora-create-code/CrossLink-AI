import { useEffect, useState } from 'react';
import './ReportPanel.css';

export const DEMO_REPORT_ID = '74d147f4570446e9b6bc75d04493beb7';
export function reportHref(id: string) { return `/?report=${encodeURIComponent(id)}#report`; }

type ReviewStatus = 'pending' | 'confirmed' | 'rejected';
type Source = {
  id: string; content: string; quote: string; document_id: string; page_number: number;
  review_status: ReviewStatus; snapshot_review_status: ReviewStatus; changed: boolean;
};
type Report = {
  candidate_id: string; batch_id: string; model: string; title: string; introduction: string;
  sections: { heading: string; body: string }[]; sources: Source[];
  basis_changed: boolean; status: 'unverified'; warning: string;
};
type State = { phase: 'loading' } | { phase: 'error'; message: string } | { phase: 'ready'; report: Report };
const reviewLabels: Record<ReviewStatus, string> = { pending: '待审核', confirmed: '已确认', rejected: '已拒绝' };
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function strings(value: Record<string, unknown>, keys: string[]) {
  return keys.every((key) => typeof value[key] === 'string');
}
function isReview(value: unknown): value is ReviewStatus {
  return value === 'pending' || value === 'confirmed' || value === 'rejected';
}
function isSource(value: unknown): value is Source {
  return record(value) && strings(value, ['id', 'content', 'quote', 'document_id']) &&
    typeof value.page_number === 'number' && Number.isSafeInteger(value.page_number) && value.page_number > 0 &&
    isReview(value.review_status) && isReview(value.snapshot_review_status) && typeof value.changed === 'boolean';
}
function isReport(value: unknown): value is Report {
  return record(value) && strings(value, ['candidate_id', 'batch_id', 'model', 'title', 'introduction', 'warning']) &&
    Array.isArray(value.sections) && value.sections.every((section) => record(section) && strings(section, ['heading', 'body'])) &&
    Array.isArray(value.sources) && value.sources.every(isSource) && typeof value.basis_changed === 'boolean' && value.status === 'unverified';
}
function readReportId() {
  const params = new URLSearchParams(window.location.search);
  return params.has('report') ? (params.get('report') ?? '').trim() : DEMO_REPORT_ID;
}

export default function ReportPanel() {
  const [id, setId] = useState(readReportId);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<State>({ phase: 'loading' });

  useEffect(() => {
    const onPopState = () => setId(readReportId());
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    if (!id) { setState({ phase: 'error', message: '报告 ID 缺失。请从候选卡片进入，或打开下方指定演示报告。' }); return; }
    const controller = new AbortController();
    let active = true;
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    setState({ phase: 'loading' });
    async function load() {
      try {
        const response = await fetch(`/api/reports/${encodeURIComponent(id)}`, {
          method: 'GET', signal: controller.signal, cache: 'no-store', headers: { Accept: 'application/json' },
        });
        if (response.status === 404) throw new Error('报告不存在或候选已缺失（HTTP 404）。请核对候选 ID，或稍后重试。');
        if (!response.ok) throw new Error(`报告读取失败（HTTP ${response.status}），请稍后重试。`);
        const value: unknown = await response.json();
        if (!isReport(value) || value.candidate_id !== id) throw new Error('报告响应格式或候选 ID 不匹配，暂时无法展示。请重试读取。');
        if (active) setState({ phase: 'ready', report: value });
      } catch (error: unknown) {
        if (!active) return;
        setState({ phase: 'error', message: controller.signal.aborted ? '报告读取超过 15 秒，请重试。' :
          error instanceof TypeError ? '无法连接后端，请检查网络或服务后重试。' :
          error instanceof SyntaxError ? '后端未返回有效 JSON，请重试读取报告。' :
          error instanceof Error ? error.message : '报告读取失败，请重试。' });
      } finally { window.clearTimeout(timeout); }
    }
    void load();
    return () => { active = false; window.clearTimeout(timeout); controller.abort(); };
  }, [id, attempt]);

  const report = state.phase === 'ready' ? state.report : null;
  const changed = report && (report.basis_changed || report.sources.some((source) => source.changed));
  return (
    <section id="report" className="report-panel" aria-labelledby="report-title" aria-busy={state.phase === 'loading'}>
      <div className="section-heading">
        <div><p className="section-kicker">REPORT · 第五阶段</p><h2 id="report-title">候选报告</h2></div>
        <button type="button" className="refresh-button" disabled={state.phase === 'loading' || !id} onClick={() => setAttempt((value) => value + 1)}>{state.phase === 'loading' ? '正在读取' : state.phase === 'error' ? '重试读取报告' : '刷新报告'}</button>
      </div>
      <p className="report-intro">这是一份待验证的研究想法。下面分开介绍讲义依据和AI建议，尚未进行实验。</p>
      <div className="report-demo"><a href={reportHref(DEMO_REPORT_ID)}>查看指定演示报告 →</a><p>指定案例仅用于演示。</p></div>
      <p className="report-meta">当前候选 ID：<code>{id || '未提供'}</code>{id === DEMO_REPORT_ID && ' · 指定演示案例'}</p>
      {state.phase === 'loading' && <p className="report-feedback" role="status">正在读取已有报告，最长等待 15 秒…</p>}
      {state.phase === 'error' && <p className="error-message" role="alert">{state.message}</p>}
      {report && <>
        <article className="report-body">
          <div className="report-row"><h3>{report.title || '后端未提供报告标题'}</h3><span className="badge warning">AI 建议 · 未验证</span></div>
          {changed && <p className="report-changed" role="alert"><strong>依据已变化，请重新核对。</strong>来源快照与当前依据存在差异；请逐条核对原文与当前审核状态。</p>}
          <div className="report-sections"><h4>AI 分析与建议</h4>
            {!report.sections.length && <p className="report-warning">后端未提供报告章节，内容不完整。</p>}
            {report.sections.map((section, index) => <section key={index}><h5>{section.heading || `章节 ${index + 1}`}</h5><p>{section.body || '本章节暂无内容。'}</p></section>)}
          </div>
          <dl className="report-metadata"><div><dt>候选 ID</dt><dd>{report.candidate_id}</dd></div><div><dt>批次 ID</dt><dd>{report.batch_id || '未提供'}</dd></div><div><dt>候选模型</dt><dd>{report.model || '未提供'}</dd></div><div><dt>报告状态</dt><dd>未验证（{report.status}）</dd></div></dl>
          <a className="report-download" href={`/api/reports/${encodeURIComponent(id)}/markdown`} download>下载 Markdown 报告 ↓</a>
        </article>
        <section className="report-sources" aria-labelledby="report-sources-title"><h3 id="report-sources-title">讲义依据 · 完整来源（{report.sources.length}）</h3><p className="report-feedback">以下知识内容、原文引句与审核状态由后端返回，独立于 AI 建议。知识审核通过不等于候选获得认可。</p>
          {!report.sources.length && <p className="report-warning" role="alert">报告未提供来源，无法核对讲义依据。请刷新或核对候选数据。</p>}
          {report.sources.map((source, index) => <article className="report-source" key={`${source.id}-${index}`}>
            <div className="report-row"><h4>知识 ID：<code>{source.id || '未提供'}</code></h4><span className={`badge ${source.review_status === 'confirmed' ? 'success' : 'warning'}`}>当前人工：{reviewLabels[source.review_status]}</span></div>
            {source.changed && <p className="report-changed" role="alert"><strong>此来源已变化，请重新核对。</strong></p>}
            <p className="report-meta">文档 ID：<code>{source.document_id || '未提供'}</code> · 第 {source.page_number} 页 · 生成时审核快照：{reviewLabels[source.snapshot_review_status]}</p>
            <h5>来源知识内容</h5><p>{source.content || '来源知识内容缺失。'}</p>
            <h5>完整原文引句</h5><blockquote>{source.quote || '原文引句缺失，无法核对。'}</blockquote>
            {source.document_id ? <nav className="report-links" aria-label={`报告来源 ${source.id} 阅读链接`}>
              <a href={`/?document=${encodeURIComponent(source.document_id)}&page=${source.page_number}`}>阅读对应文字页 · 第 {source.page_number} 页</a>
              <a href={`/api/documents/${encodeURIComponent(source.document_id)}/original#page=${source.page_number}`} target="_blank" rel="noopener noreferrer">打开原 PDF 第 {source.page_number} 页（新窗口）↗</a>
            </nav> : <p className="report-warning">文档 ID 缺失，无法打开来源页。</p>}
          </article>)}
        </section>
      </>}
    </section>
  );
}
