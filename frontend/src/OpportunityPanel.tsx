import { useEffect, useRef, useState } from 'react';
import './OpportunityPanel.css';
import { DEMO_REPORT_ID, reportHref } from './ReportPanel';

type Batch = {
  id: string; status: 'running' | 'completed' | 'failed'; error: string | null;
  model: string; usage_json: string; created_at: string; insufficiency: string;
};
type Source = {
  id: string; content: string; quote: string; document_id: string; page_number: number;
  review_status: 'pending' | 'confirmed' | 'rejected'; snapshot_review_status: 'confirmed'; changed: boolean;
};
type Item = {
  id: string; batch_id: string; title: string; need_hypothesis: string; knowledge_connection: string;
  proposed_solution: string; potential_value: string; validation_plan: string;
  unverified_assumptions: string[]; knowledge_ids: string[]; sources: Source[]; basis_changed: boolean; model: string;
};
type Opportunities = { items: Item[]; batches: Batch[] };
const labels: Record<Batch['status'], string> = { running: '运行中', completed: '已完成', failed: '失败' };
const reviewLabels: Record<Source['review_status'], string> = { pending: '待审核', confirmed: '已确认', rejected: '已拒绝' };
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function strings(value: Record<string, unknown>, keys: string[]) {
  return keys.every((key) => typeof value[key] === 'string');
}
function stringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === 'string');
}
function isBatch(value: unknown): value is Batch {
  return record(value) && strings(value, ['id', 'model', 'usage_json', 'created_at', 'insufficiency']) &&
    (value.error === null || typeof value.error === 'string') &&
    (value.status === 'running' || value.status === 'completed' || value.status === 'failed');
}
function isSource(value: unknown): value is Source {
  return record(value) && strings(value, ['id', 'content', 'quote', 'document_id']) &&
    typeof value.page_number === 'number' && Number.isSafeInteger(value.page_number) && value.page_number > 0 &&
    (value.review_status === 'pending' || value.review_status === 'confirmed' || value.review_status === 'rejected') &&
    value.snapshot_review_status === 'confirmed' && typeof value.changed === 'boolean';
}
function isItem(value: unknown): value is Item {
  return record(value) && strings(value, ['id', 'batch_id', 'title', 'need_hypothesis', 'knowledge_connection', 'proposed_solution', 'potential_value', 'validation_plan', 'model']) &&
    stringArray(value.unverified_assumptions) && stringArray(value.knowledge_ids) &&
    Array.isArray(value.sources) && value.sources.every(isSource) && typeof value.basis_changed === 'boolean';
}
function detail(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(detail).filter(Boolean).join('；');
  if (record(value)) return typeof value.msg === 'string' ? value.msg : JSON.stringify(value);
  return value == null ? '' : String(value);
}
async function request(url: string, options: RequestInit = {}): Promise<unknown> {
  const response = await fetch(url, { ...options, cache: 'no-store', headers: { Accept: 'application/json', ...options.headers } });
  let data: unknown;
  try { data = await response.json(); } catch { throw new Error(`服务未返回有效 JSON（HTTP ${response.status}）。`); }
  if (!response.ok) throw new Error(`HTTP ${response.status}：${record(data) ? detail(data.detail) || '请求失败。' : '请求失败。'}`);
  return data;
}
function errorText(error: unknown) {
  return error instanceof TypeError ? '无法连接后端，请检查网络或服务后重试。' : error instanceof Error ? error.message : '请求失败，请重试。';
}
function usageText(value: string): string {
  let parsed: unknown;
  try { parsed = JSON.parse(value); } catch { return '后端用量暂无法解析'; }
  const rows = Array.isArray(parsed) ? parsed : [parsed];
  let input = 0, output = 0, total = 0, count = 0;
  const valid = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;
  for (const row of rows) {
    if (!record(row)) continue;
    const usage = record(row.usage) ? row.usage : row;
    const i = usage.prompt_tokens ?? usage.input_tokens;
    const o = usage.completion_tokens ?? usage.output_tokens;
    const t = usage.total_tokens;
    if (valid(i) && valid(o)) { input += i; output += o; total += valid(t) ? t : i + o; count += 1; }
  }
  return count ? `${count < rows.length ? '已报告部分：' : ''}输入 ${input.toLocaleString('zh-CN')} / 输出 ${output.toLocaleString('zh-CN')} / 合计 ${total.toLocaleString('zh-CN')} token` : '后端未报告可汇总的 token 用量';
}
function dateText(value: string) {
  const date = new Date(/^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/.test(value) ? `${value.replace(' ', 'T')}Z` : value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

export default function OpportunityPanel() {
  const [data, setData] = useState<Opportunities>({ items: [], batches: [] });
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState('');
  const [notice, setNotice] = useState('');
  const [selectedId, setSelectedId] = useState('');
  const lock = useRef(false);
  const revision = useRef(0);
  const hasRunning = data.batches.some((batch) => batch.status === 'running');

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    let active = true;
    const startedRevision = revision.current;
    setLoading(true);
    setListError('');
    void request('/api/opportunities', { signal: controller.signal }).then((value) => {
      if (!record(value) || !Array.isArray(value.items) || !value.items.every(isItem) ||
        !Array.isArray(value.batches) || !value.batches.every(isBatch)) throw new Error('机会列表响应格式不正确。');
      if (active && startedRevision === revision.current) {
        setData({ items: value.items, batches: value.batches });
      }
    }).catch((error: unknown) => {
      if (active) setListError(controller.signal.aborted ? '机会列表读取超时，请刷新重试。' : errorText(error));
    }).finally(() => {
      window.clearTimeout(timeout);
      if (active) setLoading(false);
    });
    return () => { active = false; window.clearTimeout(timeout); controller.abort(); };
  }, [attempt]);

  useEffect(() => {
    if (!hasRunning || loading || listError) return;
    const timer = window.setTimeout(() => setAttempt((value) => value + 1), 3000);
    return () => window.clearTimeout(timer);
  }, [hasRunning, loading, listError]);

  async function generate() {
    if (lock.current) return;
    lock.current = true;
    setGenerating(true);
    setGenerateError('');
    setNotice('');
    try {
      const value = await request('/api/opportunities/generate', { method: 'POST' });
      if (!record(value) || !isBatch(value.batch) || typeof value.duplicate !== 'boolean') {
        throw new Error('生成响应格式不正确，请先刷新列表确认批次结果。');
      }
      const batch = value.batch;
      revision.current += 1;
      setData((current) => ({ ...current, batches: [batch, ...current.batches.filter((entry) => entry.id !== batch.id)] }));
      setSelectedId(batch.id);
      setNotice(value.duplicate ? `重复请求：已复用批次 ${batch.id}，未创建新批次。` : `已返回生成批次 ${batch.id}，状态：${labels[batch.status]}。`);
    } catch (error: unknown) {
      setGenerateError(`${errorText(error)} 结果不确定时请先刷新列表核对，避免重复提交。`);
    } finally {
      lock.current = false;
      setGenerating(false);
      setAttempt((value) => value + 1);
    }
  }

  const batch = data.batches.find((entry) => entry.id === selectedId) ?? data.batches[0];
  const batchItems = batch ? data.items.filter((item) => item.batch_id === batch.id) : [];
  const items = batchItems.slice(0, 3);
  return (
    <section id="opportunities" className="opportunity-panel" aria-labelledby="opportunity-title">
      <div className="section-heading">
        <div><p className="section-kicker">OPPORTUNITIES · 未验证想法</p><h2 id="opportunity-title">机会想法</h2></div>
        <button type="button" className="refresh-button" disabled={loading} onClick={() => setAttempt((value) => value + 1)}>{loading ? '正在读取' : '刷新机会列表'}</button>
      </div>
      <p className="opportunity-scope">当前仅基于单一 MIT 讲义中的已确认知识生成模型想法，每批最多 3 条。想法尚未验证，并非多领域发现；展示顺序不代表排名。</p>
      <p className="opportunity-caution">知识关联是模型推理；需求、方案、潜在价值与验证计划均是待验证假设。来源引句只用于追溯讲义依据，不证明需求或效果真实存在。</p>
      <div className="opportunity-actions">
        <button type="button" className="primary-button" disabled={generating || hasRunning} onClick={() => void generate()}>{generating ? '正在请求生成…' : hasRunning ? '批次运行中，等待完成' : '基于已确认知识生成想法（最多 3 条）'}</button>
        <div role="status" aria-live="polite">{notice && <p className="opportunity-notice">{notice}</p>}{generating && <p>正在等待后端返回批次结果，请勿重复提交。</p>}</div>
        {generateError && <p className="error-message" role="alert">{generateError}</p>}
      </div>
      {loading && <p className="opportunity-feedback" role="status">正在读取机会想法与批次状态…</p>}
      {listError && <p className="error-message" role="alert">{listError} 已有内容保留，可能不是最新状态，请刷新重试。</p>}
      {hasRunning && <p className="opportunity-feedback">存在运行中批次；列表读取成功后每 3 秒刷新，读取失败时请手动重试。</p>}
      {!loading && !listError && !data.batches.length && <p className="opportunity-empty">暂无机会批次。点击生成按钮后查看真实模型结果；当前没有预置示例或证据。</p>}
      {data.batches.length > 0 && <div className="opportunity-batches" aria-busy={loading}>
        <label htmlFor="opportunity-batch">查看批次（{data.batches.length}）</label>
        <select id="opportunity-batch" value={batch?.id ?? ''} onChange={(event) => setSelectedId(event.target.value)}>
          {data.batches.map((entry) => <option key={entry.id} value={entry.id}>{dateText(entry.created_at)} · {labels[entry.status]} · {entry.id}</option>)}
        </select>
      </div>}
      {batch && <article className="opportunity-batch">
        <div className="opportunity-row"><h3>批次状态</h3><span className={`badge ${batch.status === 'failed' ? 'warning' : batch.status === 'completed' ? 'success' : 'neutral'}`}>{labels[batch.status]}</span></div>
        <p>批次 ID：<code>{batch.id}</code> · 模型：{batch.model} · 创建：{dateText(batch.created_at)}</p>
        <p className="opportunity-usage">{usageText(batch.usage_json)}（服务端报告）</p>
        {batch.insufficiency && <p className="opportunity-caution"><strong>本批次不足说明：</strong>{batch.insufficiency}</p>}
        {(batch.error || batch.status === 'failed') && <p className="error-message" role="alert">批次错误：{batch.error || '后端未提供具体错误。'}</p>}
        {!loading && !listError && !items.length && <p className="opportunity-feedback">{batch.status === 'running' ? '批次仍在运行，尚无可展示想法。' : batch.status === 'failed' ? '本批次失败，暂无可展示想法。' : '本批次未返回想法。请核对不足说明与知识依据。'}</p>}
      </article>}
      {items.length > 0 && <p className="opportunity-feedback">本批次展示 {items.length} 条想法{batchItems.length > 3 ? '（接口返回超过 3 条，仅展示前 3 条）' : ''} · 均未验证</p>}
      <div className="opportunity-items" aria-busy={loading}>{items.map((item) => <article className="opportunity-item" key={item.id}>
        <div className="opportunity-row"><h3>{item.title}</h3><span className="badge warning">模型想法 · 未验证</span></div>
        <p className="opportunity-links"><a href={reportHref(item.id)}>查看此候选报告 →</a>{item.id === DEMO_REPORT_ID && <span>指定演示案例 · 不代表用户认可</span>}</p>
        {(item.basis_changed || item.sources.some((source) => source.changed)) && <p className="opportunity-changed" role="alert"><strong>依据已变化，需重新核对。</strong>生成时的来源快照与当前依据存在差异，使用本想法前请重新阅读原文并核对审核状态。</p>}
        <div className="opportunity-hypotheses">
          <h4>需求假设 · 待验证</h4><p>{item.need_hypothesis}</p>
          <h4>知识关联 · 模型推理</h4><p>{item.knowledge_connection}</p>
          <h4>拟议方案 · 待验证</h4><p>{item.proposed_solution}</p>
          <h4>潜在价值 · 待验证</h4><p>{item.potential_value}</p>
          <h4>验证计划 · 尚未执行</h4><p>{item.validation_plan}</p>
          <h4>未验证假设</h4>{item.unverified_assumptions.length ? <ul>{item.unverified_assumptions.map((assumption, index) => <li key={index}>{assumption}</li>)}</ul> : <p>后端未列出额外假设；这不代表以上想法已经验证。</p>}
        </div>
        <div className="opportunity-sources"><h4>讲义来源 · 原文引句独立核对</h4><p className="opportunity-feedback">以下为服务端返回的来源内容与引句。生成时来源人工审核快照为已确认，不等于机会想法已确认。</p>
          {!item.sources.length && <p className="opportunity-caution">后端未返回来源，无法核对依据。</p>}
          {item.sources.map((source) => <article className="opportunity-source" key={source.id}>
            <div className="opportunity-row"><strong>知识 ID：<code>{source.id}</code></strong><span className={`badge ${source.review_status === 'confirmed' ? 'success' : 'warning'}`}>当前人工：{reviewLabels[source.review_status]}</span></div>
            {source.changed && <p className="opportunity-changed"><strong>此来源已变化，需重新核对。</strong></p>}
            <p className="opportunity-source-meta">文档 ID：<code>{source.document_id}</code> · 第 {source.page_number} 页 · 生成时审核快照：已确认</p>
            <h5>来源知识内容</h5><p>{source.content}</p>
            <h5>原文引句</h5><blockquote>{source.quote}</blockquote>
            <nav className="opportunity-links" aria-label={`来源 ${source.id} 阅读链接`}>
              <a href={`/?document=${encodeURIComponent(source.document_id)}&page=${source.page_number}`}>阅读对应文字页 · 第 {source.page_number} 页</a>
              <a href={`/api/documents/${encodeURIComponent(source.document_id)}/original#page=${source.page_number}`} target="_blank" rel="noopener noreferrer">打开原 PDF 第 {source.page_number} 页（新窗口）↗</a>
            </nav>
          </article>)}
        </div>
        <dl className="opportunity-metadata"><div><dt>想法 / 批次 ID</dt><dd>{item.id} / {item.batch_id}</dd></div><div><dt>关联知识 ID</dt><dd>{item.knowledge_ids.join('、') || '后端未提供'}</dd></div><div><dt>模型</dt><dd>{item.model}</dd></div></dl>
      </article>)}</div>
    </section>
  );
}
