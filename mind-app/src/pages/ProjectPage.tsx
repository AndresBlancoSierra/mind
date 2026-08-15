import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowUpRight,
  Check,
  Circle,
  ExternalLink,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Trash2,
  X,
} from 'lucide-react';
import { motion } from 'framer-motion';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Project, RunProgress, Source, StageStatus } from '../types';

const STAGE_ORDER = ['search', 'download', 'validate', 'extract', 'ocr', 'filter'];

function stageIcon(stage: StageStatus) {
  if (stage.status === 'completed') return <Check size={14} style={{ color: '#16a34a' }} />;
  if (stage.status === 'running') return <Loader2 size={14} className="animate-spin" style={{ color: '#0a0a0a' }} />;
  if (stage.status === 'failed') return <X size={14} style={{ color: '#dc2626' }} />;
  return <Circle size={14} style={{ color: '#d4d4d4' }} />;
}

function StatsPanel({ project }: { project: Project }) {
  const rows: Array<[string, number, string]> = [
    ['Search results', project.stats.search_results, '#525252'],
    ['Candidate documents', project.stats.candidates, '#525252'],
    ['Downloaded', project.stats.downloaded, '#525252'],
    ['Valid PDFs', project.stats.valid_pdfs, '#525252'],
    ['Duplicates removed', project.stats.duplicates_removed, '#525252'],
    ['Text extracted', project.stats.text_extracted, '#525252'],
    ['OCR required', project.stats.ocr_required, '#ca8a04'],
    ['Accepted', project.stats.accepted, '#16a34a'],
    ['Review', project.stats.review, '#ca8a04'],
    ['Rejected', project.stats.rejected, '#dc2626'],
  ];
  return (
    <div className="grid grid-cols-2 md:grid-cols-5 gap-px overflow-hidden rounded-xl bg-border" style={{ border: '1px solid #e5e5e5' }}>
      {rows.map(([label, value, color]) => (
        <div key={label} className="bg-bg-card p-4">
          <div style={{ fontSize: 22, fontWeight: 700, color }}>{value}</div>
          <div style={{ fontSize: 11, color: '#a3a3a3', marginTop: 2, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            {label}
          </div>
        </div>
      ))}
    </div>
  );
}

function StageProgress({ stages }: { stages: StageStatus[] }) {
  const ordered = useMemo(() => {
    const byName = new Map(stages.map((s) => [s.name, s]));
    return STAGE_ORDER.map((name) => byName.get(name)).filter(Boolean) as StageStatus[];
  }, [stages]);

  return (
    <div
      className="rounded-xl bg-bg-card"
      style={{ border: '1px solid #e5e5e5', padding: '16px 20px', display: 'flex', alignItems: 'center', gap: 24, flexWrap: 'wrap' }}
    >
      {ordered.map((stage) => (
        <div key={stage.name} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {stageIcon(stage)}
          <span
            style={{
              fontSize: 13,
              fontWeight: stage.status === 'running' ? 600 : 500,
              color: stage.status === 'pending' ? '#a3a3a3' : '#0a0a0a',
            }}
          >
            {stage.label}
          </span>
        </div>
      ))}
    </div>
  );
}

function LogPanel({ logs }: { logs: RunProgress['logs'] }) {
  if (!logs.length) return null;
  return (
    <div
      className="rounded-xl bg-bg-card"
      style={{ border: '1px solid #e5e5e5', padding: '12px 16px', maxHeight: 160, overflowY: 'auto' }}
    >
      {logs.slice(-20).map((log) => (
        <div key={log.id} style={{ fontSize: 12, color: '#525252', padding: '2px 0', fontFamily: 'monospace' }}>
          <span style={{ color: '#a3a3a3' }}>
            {log.created_at.slice(11, 19)}
          </span>
          {'  '}
          {log.message}
        </div>
      ))}
    </div>
  );
}

type FilterTab = 'all' | 'accepted' | 'review' | 'rejected' | 'failed';

const FILTERS: Array<{ id: FilterTab; label: string; decision?: string; status?: string }> = [
  { id: 'all', label: 'All' },
  { id: 'accepted', label: 'Accepted', decision: 'ACCEPT' },
  { id: 'review', label: 'Review', decision: 'REVIEW' },
  { id: 'rejected', label: 'Rejected', decision: 'REJECT' },
  { id: 'failed', label: 'Failed', status: 'failed' },
];

function SourceRow({
  source,
  active,
  onClick,
}: {
  source: Source;
  active: boolean;
  onClick: () => void;
}) {
  const decisionColor =
    source.ai_decision === 'ACCEPT' ? '#16a34a'
    : source.ai_decision === 'REVIEW' ? '#ca8a04'
    : source.ai_decision === 'REJECT' ? '#dc2626'
    : '#a3a3a3';
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-4 py-3 transition-colors ${active ? 'bg-bg-elevated' : 'hover:bg-bg-elevated'}`}
      style={{ display: 'flex', alignItems: 'center', gap: 12, borderBottom: '1px solid #e5e5e5', cursor: 'pointer' }}
    >
      <span
        style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          backgroundColor: decisionColor,
          flexShrink: 0,
        }}
      />
      <span style={{ flex: 1, minWidth: 0 }}>
        <span className="block truncate" style={{ fontSize: 14, fontWeight: 500 }}>
          {source.title || '(untitled)'}
        </span>
        <span className="block truncate" style={{ fontSize: 12, color: '#a3a3a3', marginTop: 1 }}>
          {source.source_domain || source.url}
        </span>
      </span>
      {source.similarity !== null && (
        <span style={{ fontSize: 12, color: '#525252', flexShrink: 0 }}>
          {source.similarity.toFixed(2)}
        </span>
      )}
      <span
        style={{
          fontSize: 11,
          color: '#525252',
          backgroundColor: '#eeeeee',
          borderRadius: 9999,
          padding: '2px 8px',
          flexShrink: 0,
        }}
      >
        {source.status}
      </span>
    </button>
  );
}

function SourceDetail({ slug, source }: { slug: string; source: Source }) {
  const { data: detail } = useQuery({
    queryKey: ['source', slug, source.id],
    queryFn: () => api.getSource(slug, source.id),
    enabled: !source.has_processed && !source.content,
  });
  const full = source.content ? source : detail ?? source;

  const decisionColor =
    full.ai_decision === 'ACCEPT' ? '#16a34a'
    : full.ai_decision === 'REVIEW' ? '#ca8a04'
    : full.ai_decision === 'REJECT' ? '#dc2626'
    : '#a3a3a3';

  const meta: Array<[string, string]> = [];
  if (full.page_count != null) meta.push(['Pages', String(full.page_count)]);
  if (full.language) meta.push(['Language', full.language]);
  if (full.text_chars != null) meta.push(['Chars', String(full.text_chars)]);
  if (full.extraction_method) meta.push(['Extraction', full.extraction_method]);
  if (full.ai_confidence != null) meta.push(['Confidence', full.ai_confidence.toFixed(2)]);
  if (full.ai_document_type) meta.push(['Type', full.ai_document_type]);
  if (full.ai_topic_match) meta.push(['Topic match', full.ai_topic_match]);
  if (full.rejection_reason) meta.push(['Rejected', full.rejection_reason]);

  return (
    <div
      className="rounded-xl bg-bg-card"
      style={{ border: '1px solid #e5e5e5', padding: 20, display: 'flex', flexDirection: 'column', gap: 14 }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
        <h3 style={{ fontSize: 16, fontWeight: 700, lineHeight: 1.3 }}>{full.title || '(untitled)'}</h3>
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            color: decisionColor,
            border: `1px solid ${decisionColor}`,
            borderRadius: 9999,
            padding: '2px 10px',
            flexShrink: 0,
          }}
        >
          {full.ai_decision || full.status}
        </span>
      </div>

      {full.ai_reason && (
        <p style={{ fontSize: 13, color: '#525252' }}>{full.ai_reason}</p>
      )}

      {meta.length > 0 && (
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12, color: '#525252' }}>
          {meta.map(([k, v]) => (
            <span key={k}>
              <span style={{ color: '#a3a3a3' }}>{k}:</span> {v}
            </span>
          ))}
        </div>
      )}

      {full.snippet && (
        <p style={{ fontSize: 13, color: '#525252', borderLeft: '2px solid #e5e5e5', paddingLeft: 12 }}>
          {full.snippet}
        </p>
      )}

      <div style={{ display: 'flex', gap: 10 }}>
        <a
          href={full.url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-2 text-text-secondary hover:text-text transition-colors"
          style={{ fontSize: 13, fontWeight: 500, textDecoration: 'none' }}
        >
          <ExternalLink size={14} /> Open original
        </a>
        {full.has_processed && (
          <a
            href={api.getSourceUrl(slug, full.id)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-2 text-text-secondary hover:text-text transition-colors"
            style={{ fontSize: 13, fontWeight: 500, textDecoration: 'none' }}
          >
            <ArrowUpRight size={14} /> PDF
          </a>
        )}
      </div>

      {full.content && (
        <pre
          style={{
            fontSize: 12,
            lineHeight: 1.5,
            color: '#525252',
            whiteSpace: 'pre-wrap',
            backgroundColor: '#ffffff',
            border: '1px solid #e5e5e5',
            borderRadius: 8,
            padding: 14,
            maxHeight: 320,
            overflowY: 'auto',
          }}
        >
          {full.content}
        </pre>
      )}
    </div>
  );
}

export default function ProjectPage() {
  const { slug = '' } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState<FilterTab>('all');
  const [q, setQ] = useState('');
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const { data: project } = useQuery({
    queryKey: ['project', slug],
    queryFn: () => api.getProject(slug),
  });

  const { data: progress } = useQuery({
    queryKey: ['progress', slug],
    queryFn: () => api.getProgress(slug),
  });

  const filters = FILTERS.find((f) => f.id === tab);
  const { data: sources } = useQuery({
    queryKey: ['sources', slug, tab, q],
    queryFn: () =>
      api.listSources(slug, {
        status: filters?.status,
        decision: filters?.decision,
        q: q.trim() || undefined,
        limit: 200,
      }),
  });

  const start = useMutation({
    mutationFn: () => api.startDiscovery(slug, false),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['progress', slug] });
      queryClient.invalidateQueries({ queryKey: ['project', slug] });
    },
  });

  const remove = useMutation({
    mutationFn: () => api.deleteProject(slug),
    onSuccess: () => navigate('/'),
  });

  useEffect(() => {
    if (searchParams.get('start') === '1' && project && project.status === 'created') {
      start.mutate();
      setSearchParams({}, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.status]);

  const discovering =
    project?.status === 'discovering' ||
    progress?.status === 'discovering' ||
    start.isPending;

  const selected = selectedId != null ? sources?.items.find((s) => s.id === selectedId) : null;

  if (!project) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 size={20} className="animate-spin" style={{ color: '#a3a3a3' }} />
      </div>
    );
  }

  return (
    <div className="h-full overflow-y-auto">
      <header
        style={{
          padding: '24px 24px 0',
          maxWidth: 1024,
          margin: '0 auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <button
            onClick={() => navigate('/')}
            className="inline-flex items-center gap-2 text-text-muted hover:text-text transition-colors"
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 13 }}
          >
            <ArrowLeft size={16} /> Projects
          </button>
          <button
            onClick={() => remove.mutate()}
            className="inline-flex items-center gap-1.5 text-text-muted hover:text-danger transition-colors"
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 13 }}
          >
            <Trash2 size={14} /> Delete
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 800, letterSpacing: '-0.02em' }}>{project.topic}</h1>
            <p style={{ fontSize: 13, color: '#a3a3a3', marginTop: 4 }}>
              {project.slug} · {project.status}
            </p>
          </div>
          {project.status !== 'discovering' ? (
            <button
              onClick={() => start.mutate()}
              className="inline-flex items-center gap-2 rounded-full text-white transition-opacity hover:opacity-80"
              style={{ backgroundColor: '#0a0a0a', padding: '10px 20px', fontSize: 13, fontWeight: 600, border: 'none', cursor: 'pointer' }}
            >
              {start.isPending ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              {project.status === 'created' ? 'Start discovery' : 'Run again'}
            </button>
          ) : (
            <span className="inline-flex items-center gap-2 rounded-full bg-bg-card" style={{ padding: '10px 20px', fontSize: 13, fontWeight: 600 }}>
              <Loader2 size={14} className="animate-spin" /> Discovering…
            </span>
          )}
        </div>
      </header>

      <div style={{ padding: '16px 24px 48px', maxWidth: 1024, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
        {progress && progress.stages.length > 0 && <StageProgress stages={progress.stages} />}
        {progress && progress.logs.length > 0 && <LogPanel logs={progress.logs} />}
        <StatsPanel project={project} />

        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 }}>
          <div
            style={{
              display: 'flex',
              gap: 4,
              backgroundColor: '#f5f5f5',
              borderRadius: 9999,
              padding: 4,
            }}
          >
            {FILTERS.map((f) => {
              const count =
                f.id === 'all' ? (sources?.stats.search_results ?? 0)
                : f.id === 'accepted' ? (sources?.stats.accepted ?? 0)
                : f.id === 'review' ? (sources?.stats.review ?? 0)
                : f.id === 'rejected' ? (sources?.stats.rejected ?? 0)
                : 0;
              return (
                <button
                  key={f.id}
                  onClick={() => setTab(f.id)}
                  className="transition-colors"
                  style={{
                    background: tab === f.id ? '#0a0a0a' : 'transparent',
                    color: tab === f.id ? '#ffffff' : '#525252',
                    border: 'none',
                    borderRadius: 9999,
                    padding: '6px 14px',
                    fontSize: 12,
                    fontWeight: 600,
                    cursor: 'pointer',
                  }}
                >
                  {f.label} {count > 0 && <span style={{ opacity: 0.7 }}>{count}</span>}
                </button>
              );
            })}
          </div>
          <div style={{ position: 'relative', flex: 1, maxWidth: 280, marginLeft: 'auto' }}>
            <Search size={14} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: '#a3a3a3' }} />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Filter sources…"
              style={{
                width: '100%',
                backgroundColor: '#f5f5f5',
                border: '1px solid #e5e5e5',
                borderRadius: 9999,
                padding: '8px 14px 8px 34px',
                fontSize: 13,
                color: '#0a0a0a',
                outline: 'none',
              }}
            />
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: selected ? '1fr 380px' : '1fr', gap: 16, alignItems: 'start' }}>
          <div className="rounded-xl bg-white" style={{ border: '1px solid #e5e5e5', overflow: 'hidden' }}>
            {sources && sources.items.length === 0 && (
              <div style={{ padding: 40, textAlign: 'center', color: '#a3a3a3', fontSize: 13 }}>
                {discovering ? 'Discovering sources…' : 'No sources yet. Run discovery to begin.'}
              </div>
            )}
            {sources?.items.map((s) => (
              <SourceRow
                key={s.id}
                source={s}
                active={selectedId === s.id}
                onClick={() => setSelectedId(selectedId === s.id ? null : s.id)}
              />
            ))}
          </div>

          {selected && (
            <motion.div
              initial={{ opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2 }}
              style={{ position: 'sticky', top: 16 }}
            >
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 6 }}>
                <button
                  onClick={() => setSelectedId(null)}
                  className="text-text-muted hover:text-text transition-colors"
                  style={{ background: 'none', border: 'none', cursor: 'pointer' }}
                  aria-label="Close detail"
                >
                  <X size={16} />
                </button>
              </div>
              <SourceDetail slug={slug} source={selected} />
            </motion.div>
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 8 }}>
          <button
            onClick={() => {
              queryClient.invalidateQueries({ queryKey: ['project', slug] });
              queryClient.invalidateQueries({ queryKey: ['progress', slug] });
              queryClient.invalidateQueries({ queryKey: ['sources', slug] });
            }}
            className="inline-flex items-center gap-2 text-text-muted hover:text-text transition-colors"
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 13 }}
          >
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>
    </div>
  );
}
