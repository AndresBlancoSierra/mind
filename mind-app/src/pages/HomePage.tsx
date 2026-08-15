import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Plus, Loader2, Trash2 } from 'lucide-react';
import { motion } from 'framer-motion';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import type { Project } from '../types';

function MindLogo() {
  return (
    <motion.h1
      initial={{ letterSpacing: '0.12em', opacity: 0 }}
      animate={{ letterSpacing: '-0.02em', opacity: 1 }}
      transition={{ duration: 0.8, ease: [0.22, 1, 0.36, 1] }}
      className="select-none"
      style={{ fontSize: 'clamp(3rem, 8vw, 5.5rem)', fontWeight: 900, lineHeight: 1 }}
    >
      MI
      <motion.span
        className="inline-block"
        animate={{ opacity: [1, 0.2, 1] }}
        transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }}
      >
        N
      </motion.span>
      D
    </motion.h1>
  );
}

function ProjectCard({
  project,
  onDelete,
}: {
  project: Project;
  onDelete: (slug: string) => void;
}) {
  const navigate = useNavigate();
  const isBusy = project.status === 'discovering';

  return (
    <motion.div layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.25 }}>
      <button
        onClick={() => navigate(`/projects/${project.slug}`)}
        className="w-full text-left rounded-xl bg-bg-card p-5 transition-colors hover:bg-bg-elevated border border-transparent hover:border-border-hover"
        style={{ display: 'flex', flexDirection: 'column', gap: 12, cursor: 'pointer' }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8 }}>
          <div style={{ minWidth: 0 }}>
            <div className="truncate" style={{ fontSize: 15, fontWeight: 600 }}>
              {project.topic}
            </div>
            <div style={{ fontSize: 12, color: '#a3a3a3', marginTop: 2 }}>
              {project.status}
              {project.run_status ? ` · ${project.run_status}` : ''}
            </div>
          </div>
          {isBusy && <Loader2 size={16} className="animate-spin" style={{ color: '#737373', flexShrink: 0, marginTop: 2 }} />}
        </div>

        <div style={{ display: 'flex', gap: 16, fontSize: 12, color: '#525252' }}>
          <span>
            <span style={{ fontWeight: 600, color: '#0a0a0a' }}>{project.stats.search_results}</span> found
          </span>
          <span>
            <span style={{ fontWeight: 600, color: '#16a34a' }}>{project.stats.accepted}</span> accepted
          </span>
          <span>
            <span style={{ fontWeight: 600, color: '#ca8a04' }}>{project.stats.review}</span> review
          </span>
          <span>
            <span style={{ fontWeight: 600, color: '#dc2626' }}>{project.stats.rejected}</span> rejected
          </span>
        </div>
      </button>

      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 6, paddingRight: 6 }}>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete(project.slug);
          }}
          className="text-text-muted hover:text-danger transition-colors"
          aria-label={`Delete ${project.topic}`}
          title="Delete project"
          style={{ background: 'none', border: 'none', cursor: 'pointer' }}
        >
          <Trash2 size={14} />
        </button>
      </div>
    </motion.div>
  );
}

function ProjectCardSkeleton() {
  return (
    <div className="rounded-xl bg-bg-card p-5 animate-pulse">
      <div style={{ height: 16, width: '55%', background: '#e5e5e5', borderRadius: 4 }} />
      <div style={{ height: 10, width: '35%', background: '#e5e5e5', borderRadius: 4, marginTop: 8 }} />
      <div style={{ height: 10, width: '80%', background: '#e5e5e5', borderRadius: 4, marginTop: 16 }} />
    </div>
  );
}

export default function HomePage() {
  const [topic, setTopic] = useState('');
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: projects = [], isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: api.listProjects,
  });

  const create = useMutation({
    mutationFn: (name: string) => api.createProject(name),
    onSuccess: async (project) => {
      setTopic('');
      await queryClient.invalidateQueries({ queryKey: ['projects'] });
      navigate(`/projects/${project.slug}?start=1`);
    },
  });

  const remove = useMutation({
    mutationFn: (slug: string) => api.deleteProject(slug),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects'] }),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const name = topic.trim();
    if (!name) return;
    create.mutate(name);
  };

  const hasProjects = projects.length > 0;

  return (
    <div className="h-full overflow-y-auto">
      <section
        className="flex flex-col items-center justify-center"
        style={{ minHeight: hasProjects ? '50vh' : '85vh', padding: '40px 24px' }}
      >
        <div className="flex flex-col items-center" style={{ width: '100%', maxWidth: 520 }}>
          <MindLogo />

          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.5, duration: 0.5 }}
            className="text-text-muted text-sm tracking-wide"
            style={{ fontWeight: 500, marginTop: 16, marginBottom: 40 }}
          >
            Search. Download. Understand.
          </motion.p>

          <motion.form
            onSubmit={handleSubmit}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            style={{ width: '100%' }}
          >
            <div style={{ position: 'relative' }}>
              <input
                type="text"
                value={topic}
                onChange={(e) => setTopic(e.target.value)}
                placeholder="Start discovery for a topic..."
                aria-label="Mastery topic"
                style={{
                  width: '100%',
                  backgroundColor: '#f5f5f5',
                  border: '1px solid #e5e5e5',
                  borderRadius: 9999,
                  padding: '16px 60px 16px 20px',
                  fontSize: 15,
                  color: '#0a0a0a',
                  outline: 'none',
                }}
              />
              <button
                type="submit"
                aria-label="Start discovery"
                style={{
                  position: 'absolute',
                  right: 8,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  width: 40,
                  height: 40,
                  borderRadius: '50%',
                  backgroundColor: '#0a0a0a',
                  color: '#ffffff',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  border: 'none',
                  cursor: 'pointer',
                }}
              >
                {create.isPending ? <Loader2 size={18} className="animate-spin" /> : <Search size={18} />}
              </button>
            </div>
            {create.isError && (
              <p style={{ fontSize: 12, color: '#dc2626', marginTop: 8, textAlign: 'center' }}>
                {create.error instanceof Error ? create.error.message : 'Could not create project.'}
              </p>
            )}
          </motion.form>

          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ delay: 0.5, duration: 0.3 }}
            style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 20 }}
          >
            <Plus size={13} />
            <span style={{ fontSize: 12, color: '#a3a3a3' }}>
              A new discovery project is created for each topic.
            </span>
          </motion.div>
        </div>
      </section>

      {hasProjects && (
        <section style={{ padding: '0 24px 48px', maxWidth: 1024, margin: '0 auto' }}>
          <h2
            style={{
              fontSize: 11,
              fontWeight: 500,
              color: '#a3a3a3',
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              marginBottom: 20,
              textAlign: 'center',
            }}
          >
            Projects
          </h2>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
              gap: 20,
            }}
          >
            {projects.map((p) => (
              <ProjectCard key={p.slug} project={p} onDelete={(slug) => remove.mutate(slug)} />
            ))}
          </div>
        </section>
      )}

      {isLoading && (
        <section style={{ padding: '0 24px 48px', maxWidth: 1024, margin: '0 auto' }}>
          <h2
            style={{
              fontSize: 11,
              fontWeight: 500,
              color: '#a3a3a3',
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              marginBottom: 20,
              textAlign: 'center',
            }}
          >
            Projects
          </h2>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
              gap: 20,
            }}
          >
            {Array.from({ length: 3 }).map((_, i) => (
              <ProjectCardSkeleton key={i} />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
