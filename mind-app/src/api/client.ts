import type {
  Project,
  ProjectStats,
  RunProgress,
  RuntimeStatus,
  Source,
  SourcesResponse,
} from '../types';

const BASE = '/api';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const body = await res.text();
    let detail = body;
    try {
      detail = JSON.parse(body).detail ?? body;
    } catch {
      /* keep raw body */
    }
    throw new Error(`API error ${res.status}: ${detail}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json();
}

export interface SourceFilters {
  status?: string;
  decision?: string;
  q?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  health: () => request<{ status: string; version: string }>('/health'),

  status: () => request<RuntimeStatus>('/status'),

  listProjects: () => request<Project[]>('/projects'),

  getProject: (slug: string) =>
    request<Project>(`/projects/${encodeURIComponent(slug)}`),

  createProject: (topic: string) =>
    request<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify({ topic }),
    }),

  deleteProject: (slug: string) =>
    request<{ ok: boolean }>(`/projects/${encodeURIComponent(slug)}`, {
      method: 'DELETE',
    }),

  startDiscovery: (slug: string, offline = false) =>
    request<{ ok: boolean; slug: string }>(
      `/projects/${encodeURIComponent(slug)}/discover?offline=${offline}`,
      { method: 'POST' },
    ),

  getProgress: (slug: string) =>
    request<RunProgress>(`/projects/${encodeURIComponent(slug)}/progress`),

  listSources: (slug: string, filters: SourceFilters = {}) => {
    const params = new URLSearchParams();
    if (filters.status) params.set('status', filters.status);
    if (filters.decision) params.set('decision', filters.decision);
    if (filters.q) params.set('q', filters.q);
    if (filters.limit) params.set('limit', String(filters.limit));
    if (filters.offset) params.set('offset', String(filters.offset));
    const qs = params.toString();
    return request<SourcesResponse>(
      `/projects/${encodeURIComponent(slug)}/sources${qs ? `?${qs}` : ''}`,
    );
  },

  getSource: (slug: string, sourceId: number) =>
    request<Source>(
      `/projects/${encodeURIComponent(slug)}/sources/${sourceId}`,
    ),

  getSourceUrl: (slug: string, sourceId: number) =>
    `${BASE}/projects/${encodeURIComponent(slug)}/sources/${sourceId}/file`,
};

export const emptyStats: ProjectStats = {
  search_results: 0,
  candidates: 0,
  downloaded: 0,
  valid_pdfs: 0,
  duplicates_removed: 0,
  text_extracted: 0,
  ocr_required: 0,
  accepted: 0,
  review: 0,
  rejected: 0,
};
