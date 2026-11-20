import { useEffect, useRef, useState } from 'react';
import './KnowledgePanel.css';

const DOCUMENT_ID = '859cc211586147da8d4a64d881271c88';
type ReviewStatus = 'pending' | 'confirmed' | 'rejected';
type Item = {
  id: string; batch_id: string; document_id: string; page_number: number;
  content: string; quote: string; model: string; extraction_status: 'source_verified';
  review_status: ReviewStatus; created_at: string;
};
type Batch = {
  id: string; document_id: string; status: 'running' | 'completed' | 'failed';
  error: string | null; model: string; usage_json: string; created_at: string;
};
type Knowledge = { items: Item[]; batches: Batch[] };
const reviewLabels: Record<ReviewStatus, string> = { pending: '待审核', confirmed: '已确认', rejected: '已拒绝' };
const batchLabels: Record<Batch['status'], string> = { running: '运行中', completed: '已完成', failed: '失败' };
function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function strings(value: Record<string, unknown>, keys: string[]) {
  return keys.every((key) => typeof value[key] === 'string');
}
function isItem(value: unknown): value is Item {
  return record(value) && strings(value, ['id', 'batch_id', 'document_id', 'content', 'quote', 'model', 'created_at']) &&
    typeof value.page_number === 'number' && Number.isSafeInteger(value.page_number) && value.page_number > 0 &&
    value.extraction_status === 'source_verified' &&
    (value.review_status === 'pending' || value.review_status === 'confirmed' || value.review_status === 'rejected');
}
function isBatch(value: unknown): value is Batch {
  return record(value) && strings(value, ['id', 'document_id', 'model', 'usage_json', 'created_at']) &&
    (value.error === null || typeof value.error === 'string') &&
    (value.status === 'running' || value.status === 'completed' || value.status === 'failed');
}
function detailMessage(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.map(detailMessage).filter(Boolean).join('；');
  if (record(value)) return typeof value.msg === 'string' ? value.msg : JSON.stringify(value);
  return value == null ? '' : String(value);
}
async function request(url: string, options: RequestInit = {}): Promise<unknown> {
  const response = await fetch(url, { ...options, headers: { Accept: 'application/json', ...options.headers }, cache: 'no-store' });
  let data: unknown;
  try { data = await response.json(); } catch { throw new Error(`服务未返回有效 JSON（HTTP ${response.status}）。`); }
  if (!response.ok) throw new Error(`HTTP ${response.status}：${record(data) ? detailMessage(data.detail) || '请求失败。' : '请求失败。'}`);
  return data;
}
function errorMessage(error: unknown) {
  return error instanceof TypeError ? '无法连接后端，请检查网络或服务后重试。' : error instanceof Error ? error.message : '请求失败，请重试。';
}
function usageText(value: string): string {
  let parsed: unknown;
  try { parsed = JSON.parse(value); } catch { return '暂无法读取用量汇总'; }
  function counts(node: unknown): { input: number; output: number; total: number } | null {
    if (!record(node)) return null;
    const usage = record(node.usage) ? node.usage : node;
    const input = usage.prompt_tokens ?? usage.input_tokens;
    const output = usage.completion_tokens ?? usage.output_tokens;
    const total = usage.total_tokens;
    const valid = (number: unknown): number is number => typeof number === 'number' && Number.isFinite(number) && number >= 0;
    if (!valid(input) || !valid(output)) return null;
    return { input, output, total: valid(total) ? total : input + output };
  }
  const rows = (Array.isArray(parsed) ? parsed : [parsed]).map((node) => ({
    page: record(node) && typeof node.page_number === 'number' ? node.page_number : null,
    counts: counts(node),
  }));
  const validRows = rows.filter((row) => row.counts !== null);
  if (!validRows.length) return '后端未报告可汇总的 token 用量';
  const describe = (count: { input: number; output: number; total: number }) => `输入 ${count.input.toLocaleString('zh-CN')} / 输出 ${count.output.toLocaleString('zh-CN')} / 合计 ${count.total.toLocaleString('zh-CN')} token`;
  const sum = validRows.reduce((result, row) => ({ input: result.input + row.counts!.input, output: result.output + row.counts!.output, total: result.total + row.counts!.total }), { input: 0, output: 0, total: 0 });
  const lines = rows.map((row) => `${row.page === null ? '本次调用' : `第 ${row.page} 页`}：${row.counts ? describe(row.counts) : '未报告可汇总用量'}`);
  lines.push(`${validRows.length === rows.length ? '总计' : '已报告部分合计'}：${describe(sum)}`);
  return lines.join('\n');
}
function dateText(value: string): string {
  const date = new Date(/^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$/.test(value) ? `${value.replace(' ', 'T')}Z` : value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false });
}

export default function KnowledgePanel() {
  const [knowledge, setKnowledge] = useState<Knowledge>({ items: [], batches: [] });
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState('');
  const [notice, setNotice] = useState('');
  const [reviewing, setReviewing] = useState<string[]>([]);
  const [reviewErrors, setReviewErrors] = useState<Record<string, string>>({});
  const extractLock = useRef(false);
  const reviewLocks = useRef(new Set<string>());
  const revision = useRef(0);
  const hasRunning = knowledge.batches.some((batch) => batch.status === 'running');

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    let active = true;
    const startedRevision = revision.current;
    setLoading(true);
    setListError('');
    void request(`/api/knowledge?document_id=${DOCUMENT_ID}`, { signal: controller.signal }).then((data) => {
      if (!record(data) || !Array.isArray(data.items) || !data.items.every(isItem) ||
        !Array.isArray(data.batches) || !data.batches.every(isBatch)) throw new Error('知识列表响应格式不正确。');
      // A response started before a successful mutation must not undo that mutation.
      if (active && startedRevision === revision.current) setKnowledge({ items: data.items, batches: data.batches });
    }).catch((error: unknown) => {
      if (active) setListError(controller.signal.aborted ? '知识列表读取超时，请刷新重试。' : errorMessage(error));
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

  async function extract() {
    if (extractLock.current) return;
    extractLock.current = true;
    setExtracting(true);
    setExtractError('');
    setNotice('');
    try {
      const data = await request('/api/knowledge/extract', { method: 'POST' });
      if (!record(data) || !isBatch(data.batch) || typeof data.duplicate !== 'boolean') {
        throw new Error('提取响应格式不正确。请刷新列表确认批次结果后再重试。');
      }
      const batch = data.batch;
      revision.current += 1;
      setKnowledge((current) => ({ ...current, batches: [batch, ...current.batches.filter((value) => value.id !== batch.id)] }));
      setNotice(data.duplicate ? `重复请求：已复用已有批次 ${batch.id}，未创建新批次。` : `已返回提取批次 ${batch.id}，当前状态：${batchLabels[batch.status]}。`);
    } catch (error: unknown) {
      setExtractError(`${errorMessage(error)} 请查看批次状态；结果不确定时先刷新列表。`);
    } finally {
      extractLock.current = false;
      setExtracting(false);
      setAttempt((value) => value + 1);
    }
  }

  async function review(item: Item, status: ReviewStatus) {
    if (reviewLocks.current.has(item.id)) return;
    reviewLocks.current.add(item.id);
    setReviewing((current) => [...current, item.id]);
    setReviewErrors((current) => ({ ...current, [item.id]: '' }));
    try {
      const data = await request(`/api/knowledge/${encodeURIComponent(item.id)}/review`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }),
      });
      if (!record(data) || !isItem(data.item) || data.item.id !== item.id || data.item.review_status !== status) {
        throw new Error('审核响应格式不正确，请刷新列表确认结果。');
      }
      const updated = data.item;
      revision.current += 1;
      setKnowledge((current) => ({ ...current, items: current.items.map((value) => value.id === updated.id ? updated : value) }));
    } catch (error: unknown) {
      setReviewErrors((current) => ({ ...current, [item.id]: errorMessage(error) }));
    } finally {
      reviewLocks.current.delete(item.id);
      setReviewing((current) => current.filter((id) => id !== item.id));
      setAttempt((value) => value + 1);
    }
  }

  return (
    <section className="knowledge-panel" aria-labelledby="knowledge-title">
      <div className="section-heading">
        <div><p className="section-kicker">KNOWLEDGE · 人工审核</p><h2 id="knowledge-title">知识提取与核对</h2></div>
        <button type="button" className="refresh-button" disabled={loading} onClick={() => setAttempt((value) => value + 1)}>{loading ? '正在读取' : '刷新知识列表'}</button>
      </div>
      <p className="knowledge-intro">固定从 MIT 资料第 1、5、10 页提取知识，每页最多 5 条。仅在点击按钮后发起模型提取；已存列表进入页面时自动读取。</p>
      <p className="knowledge-caution">出处存在不代表结论正确。出处校验仅表示引句可在对应页找到，内容仍需人工核对；单一讲义的待验证模型想法见下方「机会想法」。</p>
      <div className="knowledge-extract">
        <button type="button" className="primary-button" disabled={extracting || hasRunning} onClick={() => void extract()}>{extracting ? '正在请求提取…' : hasRunning ? '批次运行中，等待完成' : '提取 MIT 第 1 / 5 / 10 页（每页最多 5 条）'}</button>
        <p>文档 ID：<code>{DOCUMENT_ID}</code></p>
        <div role="status" aria-live="polite">{notice && <p className="document-notice">{notice}</p>}{extracting && <p>提取可能需要一些时间，请等待后端返回批次结果。</p>}</div>
        {extractError && <p className="error-message" role="alert">{extractError}</p>}
      </div>
      {listError && <p className="error-message" role="alert">{listError} 已有内容保留，可能不是最新状态。可刷新重试。</p>}
      {loading && <p className="knowledge-feedback" role="status">正在读取知识和批次状态…</p>}
      <div className="knowledge-batches" aria-busy={loading}>
        <h3>提取批次（{knowledge.batches.length}）</h3>
        {hasRunning && <p className="knowledge-feedback">存在运行中批次；列表读取成功后每 3 秒自动刷新，读取失败时请手动重试。</p>}
        {!loading && !listError && !knowledge.batches.length && <p className="knowledge-feedback">暂无提取批次。点击上方按钮开始。</p>}
        {knowledge.batches.map((batch) => <article className="knowledge-batch" key={batch.id}>
          <div className="knowledge-row"><strong>批次 {batch.id}</strong><span className={`badge ${batch.status === 'completed' ? 'success' : batch.status === 'failed' ? 'warning' : 'neutral'}`}>{batchLabels[batch.status]}</span></div>
          <p>文档 ID：{batch.document_id} · 模型：{batch.model} · 创建：{dateText(batch.created_at)}</p>
          {batch.error && <p className="error-message">批次错误：{batch.error}</p>}
          {batch.status === 'failed' && !batch.error && <p className="error-message">批次失败，后端未提供具体错误。</p>}
          <details><summary>查看各页与合计用量</summary><pre>{usageText(batch.usage_json)}</pre><p>服务端报告的用量不等于已核对扣费。</p></details>
        </article>)}
      </div>
      <div className="knowledge-items" aria-busy={loading}>
        <h3>知识条目（{knowledge.items.length}）</h3>
        {!loading && !listError && !knowledge.items.length && <p className="knowledge-feedback">暂无知识条目。批次完成后显示后端返回的真实提取结果。</p>}
        {knowledge.items.map((item) => <article className="knowledge-item" key={item.id} aria-busy={reviewing.includes(item.id)}>
          <div className="knowledge-row"><span className="badge success">出处已校验</span><span className={`badge ${item.review_status === 'confirmed' ? 'success' : item.review_status === 'rejected' ? 'warning' : 'neutral'}`}>人工：{reviewLabels[item.review_status]}</span></div>
          <h4>知识内容</h4><p className="knowledge-content">{item.content}</p>
          <h4>完整原文引句</h4><blockquote>{item.quote}</blockquote>
          <dl className="knowledge-metadata">
            <div><dt>文档 ID / 页码</dt><dd>{item.document_id} / 第 {item.page_number} 页</dd></div>
            <div><dt>模型</dt><dd>{item.model}</dd></div>
            <div><dt>条目 / 批次</dt><dd>{item.id} / {item.batch_id}</dd></div>
            <div><dt>创建时间</dt><dd>{dateText(item.created_at)}</dd></div>
          </dl>
          <nav className="knowledge-links" aria-label={`条目 ${item.id} 的出处`}>
            <a href={`/?document=${encodeURIComponent(item.document_id)}&page=${item.page_number}`}>到对应阅读页 · 第 {item.page_number} 页</a>
            <a href={`/api/documents/${encodeURIComponent(item.document_id)}/original#page=${item.page_number}`} target="_blank" rel="noopener noreferrer">打开原 PDF 第 {item.page_number} 页（新窗口）↗</a>
          </nav>
          <div className="knowledge-review" role="group" aria-label={`条目 ${item.id} 人工审核`}>
            {(['confirmed', 'rejected', 'pending'] as const).map((status) => <button key={status} type="button" className="refresh-button" disabled={reviewing.includes(item.id) || item.review_status === status} onClick={() => void review(item, status)}>{status === 'confirmed' ? '确认' : status === 'rejected' ? '拒绝' : '恢复待审核'}</button>)}
            <span role="status" aria-live="polite">{reviewing.includes(item.id) ? '正在保存审核状态…' : `当前：${reviewLabels[item.review_status]}`}</span>
          </div>
          {reviewErrors[item.id] && <p className="error-message" role="alert">{reviewErrors[item.id]}</p>}
        </article>)}
      </div>
    </section>
  );
}
