import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import DocumentLibrary from './DocumentLibrary';
import KnowledgePanel from './KnowledgePanel';
import OpportunityPanel from './OpportunityPanel';
import ReportPanel, { DEMO_REPORT_ID, reportHref } from './ReportPanel';

type ConfigurationStatus = 'not_configured' | 'incomplete' | 'configured_unverified';

type Health = {
  status: 'ok';
  service: 'crosslink-api';
  database: { status: 'ok'; schema_version: number };
  thingo: {
    configuration_status: ConfigurationStatus;
    missing_fields: string[];
    connectivity_verified: boolean;
    protocol_implemented?: boolean;
  };
};

type HealthState =
  | { phase: 'loading' }
  | { phase: 'error'; message: string }
  | { phase: 'ready'; health: Health; checkedAt: Date };

type Tone = 'success' | 'warning' | 'neutral';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isHealth(value: unknown): value is Health {
  if (!isRecord(value) || !isRecord(value.database) || !isRecord(value.thingo)) return false;
  const { database, thingo } = value;
  return (
    value.status === 'ok' &&
    value.service === 'crosslink-api' &&
    database.status === 'ok' &&
    typeof database.schema_version === 'number' &&
    Number.isInteger(database.schema_version) &&
    database.schema_version >= 1 &&
    (thingo.configuration_status === 'not_configured' ||
      thingo.configuration_status === 'incomplete' ||
      thingo.configuration_status === 'configured_unverified') &&
    Array.isArray(thingo.missing_fields) &&
    thingo.missing_fields.every((field: unknown) => typeof field === 'string') &&
    typeof thingo.connectivity_verified === 'boolean' &&
    (thingo.protocol_implemented === undefined || typeof thingo.protocol_implemented === 'boolean')
  );
}

const configurationLabels: Record<ConfigurationStatus, string> = {
  not_configured: '尚未配置',
  incomplete: '配置不完整',
  configured_unverified: '已配置 · 未验证',
};

function StatusCard({ number, title, label, tone, children }: {
  number: string;
  title: string;
  label: string;
  tone: Tone;
  children: ReactNode;
}) {
  return (
    <article className="status-card">
      <div className="card-top"><span className="card-number">{number}</span><span className={`badge ${tone}`}><span className="status-dot" />{label}</span></div>
      <h3>{title}</h3>
      <div className="card-description">{children}</div>
    </article>
  );
}

export default function App() {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<HealthState>({ phase: 'loading' });

  useEffect(() => {
    const controller = new AbortController();
    let disposed = false;
    let timedOut = false;
    setState({ phase: 'loading' });
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 8000);

    async function checkHealth() {
      try {
        const response = await fetch('/api/health', {
          signal: controller.signal,
          headers: { Accept: 'application/json' },
          cache: 'no-store',
        });
        if (!response.ok) throw new Error(`后端返回 HTTP ${response.status}，暂时无法读取健康状态。`);
        const data: unknown = await response.json();
        if (!isHealth(data)) throw new Error('后端响应不符合预期的健康检查格式，无法确认当前状态。');
        if (!disposed) setState({ phase: 'ready', health: data, checkedAt: new Date() });
      } catch (error: unknown) {
        if (disposed) return;
        const message = timedOut
          ? '请求已超过 8 秒。请检查后端是否启动、代理地址是否正确，然后重试。'
          : error instanceof TypeError
            ? '无法连接后端。请检查后端服务与 Vite 的 /api 代理配置。'
            : error instanceof SyntaxError
              ? '后端未返回有效 JSON，暂时无法读取健康状态。'
              : error instanceof Error
                ? error.message
                : '健康检查失败，请稍后重试。';
        setState({ phase: 'error', message });
      } finally {
        window.clearTimeout(timeout);
      }
    }

    void checkHealth();
    return () => {
      disposed = true;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [attempt]);

  const health = state.phase === 'ready' ? state.health : undefined;
  const unavailableLabel = state.phase === 'loading' ? '读取中' : '状态未知';

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="#main" aria-label="CrossLink AI 首页"><span className="brand-mark" aria-hidden="true">↗</span><span>CrossLink <strong>AI</strong></span></a>
        <span className="header-caption">跨领域机会工作台 <span className="version">基础版 / 0.1</span></span>
      </header>

      <main id="main">
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-content">
            <p className="eyebrow"><span /> CONNECT IDEAS. DISCOVER POSSIBILITY.</p>
            <h1 id="hero-title">让知识跨界，<br />让机会<span>浮现。</span></h1>
            <p className="hero-description">上传 PDF、核对原文并审核知识，再基于单一 MIT 讲义中的已确认知识生成最多 3 条待验证想法。当前尚不构成多领域发现。</p>
            <a className="opportunity-entry" href={reportHref(DEMO_REPORT_ID)}>优先查看指定演示报告 · 未验证 →</a>
            <p className="report-feedback">指定案例仅供演示，不代表用户认可。</p>
            <a className="opportunity-entry" href="#opportunities">进入机会想法 · 查看与生成 →</a>
            <div className="hero-note"><span className="note-line" />讲义知识可追溯，模型想法需验证</div>
          </div>
          <div className="connection-map" aria-hidden="true">
            <div className="orbit orbit-one" /><div className="orbit orbit-two" />
            <span className="map-line line-one" /><span className="map-line line-two" /><span className="map-line line-three" />
            <span className="map-node node-one">知识</span><span className="map-node node-two">需求</span><span className="map-node node-three">领域</span>
            <span className="map-center">CrossLink<span>新的连接，新的可能</span></span>
            <span className="map-caption">IDEAS WITHOUT BOUNDARIES</span>
          </div>
        </section>

        <section className="health-section" aria-labelledby="health-title" aria-busy={state.phase === 'loading'}>
          <div className="section-heading">
            <div><p className="section-kicker">SYSTEM OVERVIEW</p><h2 id="health-title">服务状态</h2></div>
            <button type="button" className="refresh-button" disabled={state.phase === 'loading'} onClick={() => setAttempt((value) => value + 1)}>
              <span className={state.phase === 'loading' ? 'refresh-icon spinning' : 'refresh-icon'} aria-hidden="true">↻</span>
              {state.phase === 'loading' ? '正在检查' : state.phase === 'error' ? '重试检查' : '刷新状态'}
            </button>
          </div>
          <div className="check-feedback" aria-live="polite" role="status">
            {state.phase === 'loading' && <p>正在向后端读取实时状态，最长等待 8 秒…</p>}
            {state.phase === 'ready' && <p>最近检查：{state.checkedAt.toLocaleString('zh-CN', { hour12: false })} · 来自 GET /api/health</p>}
            {state.phase === 'error' && <p className="error-message">{state.message} 当前各项状态均未确认。</p>}
          </div>
          <div className="status-grid">
            <StatusCard number="01" title="后端服务" label={health ? '运行正常' : unavailableLabel} tone={health ? 'success' : 'neutral'}>
              <p>{health ? 'crosslink-api 已响应，健康检查结果为 ok。' : '等待后端健康检查结果，确认 API 服务是否可用。'}</p>
              <span className="card-meta">REST API · /api/health</span>
            </StatusCard>
            <StatusCard number="02" title="SQLite 数据库" label={health ? '状态正常' : unavailableLabel} tone={health ? 'success' : 'neutral'}>
              <p>{health ? `后端报告数据库状态为 ok，当前结构版本为 ${health.database.schema_version}。` : '数据库状态以健康接口返回的信息为准。'}</p>
              <span className="card-meta">SQLite · 后端状态报告</span>
            </StatusCard>
            <StatusCard number="03" title="Thingo 配置与连接" label={health ? health.thingo.connectivity_verified ? '连接已验证' : configurationLabels[health.thingo.configuration_status] : unavailableLabel} tone={health ? health.thingo.connectivity_verified ? 'success' : 'warning' : 'neutral'}>
              <p>{health ? health.thingo.connectivity_verified ? '后端报告 Thingo API 连接已验证。配置状态与连接验证分别显示。' : health.thingo.configuration_status === 'configured_unverified' ? '必需配置已填写，后端尚未报告连接验证成功。' : '配置尚未齐备，后端未报告连接验证成功。请在后端补齐必要配置。' : '读取后端返回的配置完整性与连接验证状态。'}</p>
              {health && <p>配置标签：{configurationLabels[health.thingo.configuration_status]}</p>}
              {health && health.thingo.protocol_implemented !== undefined && <p>协议实现：{health.thingo.protocol_implemented ? '已实现' : '未实现'}</p>}
              {health && health.thingo.missing_fields.length > 0 && <p className="missing-fields">缺少字段：{health.thingo.missing_fields.join('、')}</p>}
              <span className="card-meta">配置检查 ≠ 连通验证 · 浏览器不接收密钥</span>
            </StatusCard>
          </div>
          <p className="health-footnote">配置标签只反映配置完整性；连接状态依据后端 connectivity_verified 报告。连接验证成功不代表知识结论正确，也不代表已具备机会发现能力。</p>
        </section>

        <DocumentLibrary />
        <KnowledgePanel />
        <OpportunityPanel />
        <ReportPanel />

        <section className="roadmap" aria-labelledby="roadmap-title">
          <div className="roadmap-intro"><p className="section-kicker">WHAT COMES NEXT</p><h2 id="roadmap-title">从连接开始，<br />逐步走向发现。</h2><p>已提供 PDF 资料导入、知识人工审核、单一 MIT 讲义的待验证想法，以及可追溯来源的只读报告与 Markdown 下载。多领域分析与机会验证仍待实现。</p></div>
          <div className="roadmap-items">
            <article><span className="roadmap-symbol" aria-hidden="true">↥</span><div><h3>资料导入与解析 <span>本阶段已实现</span></h3><p>单份 PDF 上传、内容去重、逐页文字提取与原文核对。</p></div></article>
            <article><span className="roadmap-symbol" aria-hidden="true">⌘</span><div><h3>讲义机会想法 <span>本阶段已实现</span></h3><p>基于单一讲义的已确认知识生成模型想法；尚未验证，非多领域发现。</p></div></article>
            <article><span className="roadmap-symbol" aria-hidden="true">▤</span><div><h3>候选报告与导出 <span>本阶段已实现</span></h3><p>只读报告、完整来源追溯与 Markdown 下载；报告仍未验证。</p></div></article>
          </div>
        </section>
      </main>
      <footer><span>CrossLink AI</span><p>让每一份知识，找到新的可能。</p><span className="footer-note">基础界面 · 真实状态</span></footer>
    </div>
  );
}
