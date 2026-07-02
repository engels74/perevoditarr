// Typed endpoint helpers over apiFetch (P1-T9). Every helper takes an
// injectable fetch so state modules stay testable without a network.

import { apiFetch, type FetchLike } from './client';
import type {
	BazarrInstanceCreate,
	BazarrInstanceRead,
	BazarrInstanceUpdate,
	ConnectionTestRequest,
	ConnectionTestResult,
	CoverageStat,
	DoctorRunRead,
	EpisodeRead,
	FreshnessRead,
	LingarrDiscoveryResult,
	LingarrInstanceCreate,
	LingarrInstanceRead,
	LingarrInstanceUpdate,
	MovieRead,
	Page,
	SeriesRead,
	SyncRunRead
} from './types';

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
	const search = new URLSearchParams();
	for (const [key, value] of Object.entries(params)) {
		if (value !== undefined && value !== null && value !== '') {
			search.set(key, String(value));
		}
	}
	const encoded = search.toString();
	return encoded ? `?${encoded}` : '';
}

// --- Mirror -----------------------------------------------------------------

export interface LibraryQuery {
	search?: string;
	missingLanguage?: string;
	instanceId?: string;
	limit?: number;
	offset?: number;
}

export function listSeries(
	query: LibraryQuery,
	fetchFn: FetchLike = fetch
): Promise<Page<SeriesRead>> {
	return apiFetch<Page<SeriesRead>>(`/api/v1/mirror/series${qs({ ...query })}`, {}, fetchFn);
}

export function listSeriesEpisodes(
	seriesId: string,
	query: { limit?: number; offset?: number },
	fetchFn: FetchLike = fetch
): Promise<Page<EpisodeRead>> {
	return apiFetch<Page<EpisodeRead>>(
		`/api/v1/mirror/series/${seriesId}/episodes${qs({ ...query })}`,
		{},
		fetchFn
	);
}

export function listMovies(
	query: LibraryQuery,
	fetchFn: FetchLike = fetch
): Promise<Page<MovieRead>> {
	return apiFetch<Page<MovieRead>>(`/api/v1/mirror/movies${qs({ ...query })}`, {}, fetchFn);
}

export function getCoverage(fetchFn: FetchLike = fetch): Promise<CoverageStat[]> {
	return apiFetch<CoverageStat[]>('/api/v1/mirror/coverage', {}, fetchFn);
}

export function getFreshness(fetchFn: FetchLike = fetch): Promise<FreshnessRead[]> {
	return apiFetch<FreshnessRead[]>('/api/v1/mirror/freshness', {}, fetchFn);
}

export function startSync(
	instanceId: string,
	full: boolean,
	fetchFn: FetchLike = fetch
): Promise<SyncRunRead> {
	return apiFetch<SyncRunRead>(
		`/api/v1/mirror/sync/${instanceId}?full=${full}`,
		{ method: 'POST', body: '{}' },
		fetchFn
	);
}

export function startWantedSync(
	instanceId: string,
	fetchFn: FetchLike = fetch
): Promise<SyncRunRead> {
	return apiFetch<SyncRunRead>(
		`/api/v1/mirror/sync/${instanceId}/wanted`,
		{ method: 'POST', body: '{}' },
		fetchFn
	);
}

// --- Instances ---------------------------------------------------------------

export function listBazarrInstances(fetchFn: FetchLike = fetch): Promise<BazarrInstanceRead[]> {
	return apiFetch<BazarrInstanceRead[]>('/api/v1/instances/bazarr', {}, fetchFn);
}

export function listLingarrInstances(fetchFn: FetchLike = fetch): Promise<LingarrInstanceRead[]> {
	return apiFetch<LingarrInstanceRead[]>('/api/v1/instances/lingarr', {}, fetchFn);
}

export function createBazarrInstance(
	input: BazarrInstanceCreate,
	fetchFn: FetchLike = fetch
): Promise<BazarrInstanceRead> {
	return apiFetch<BazarrInstanceRead>(
		'/api/v1/instances/bazarr',
		{ method: 'POST', body: JSON.stringify(input) },
		fetchFn
	);
}

export function updateBazarrInstance(
	id: string,
	patch: BazarrInstanceUpdate,
	fetchFn: FetchLike = fetch
): Promise<BazarrInstanceRead> {
	return apiFetch<BazarrInstanceRead>(
		`/api/v1/instances/bazarr/${id}`,
		{ method: 'PATCH', body: JSON.stringify(patch) },
		fetchFn
	);
}

export function deleteBazarrInstance(id: string, fetchFn: FetchLike = fetch): Promise<void> {
	return apiFetch<void>(`/api/v1/instances/bazarr/${id}`, { method: 'DELETE' }, fetchFn);
}

export function createLingarrInstance(
	input: LingarrInstanceCreate,
	fetchFn: FetchLike = fetch
): Promise<LingarrInstanceRead> {
	return apiFetch<LingarrInstanceRead>(
		'/api/v1/instances/lingarr',
		{ method: 'POST', body: JSON.stringify(input) },
		fetchFn
	);
}

export function updateLingarrInstance(
	id: string,
	patch: LingarrInstanceUpdate,
	fetchFn: FetchLike = fetch
): Promise<LingarrInstanceRead> {
	return apiFetch<LingarrInstanceRead>(
		`/api/v1/instances/lingarr/${id}`,
		{ method: 'PATCH', body: JSON.stringify(patch) },
		fetchFn
	);
}

export function deleteLingarrInstance(id: string, fetchFn: FetchLike = fetch): Promise<void> {
	return apiFetch<void>(`/api/v1/instances/lingarr/${id}`, { method: 'DELETE' }, fetchFn);
}

export function testConnection(
	input: ConnectionTestRequest,
	fetchFn: FetchLike = fetch
): Promise<ConnectionTestResult> {
	return apiFetch<ConnectionTestResult>(
		'/api/v1/instances/test',
		{ method: 'POST', body: JSON.stringify(input) },
		fetchFn
	);
}

export function getLingarrDiscovery(
	bazarrId: string,
	fetchFn: FetchLike = fetch
): Promise<LingarrDiscoveryResult> {
	return apiFetch<LingarrDiscoveryResult>(
		`/api/v1/instances/bazarr/${bazarrId}/lingarr-discovery`,
		{},
		fetchFn
	);
}

export function confirmLingarrDiscovery(
	bazarrId: string,
	name: string,
	fetchFn: FetchLike = fetch
): Promise<LingarrInstanceRead> {
	return apiFetch<LingarrInstanceRead>(
		`/api/v1/instances/bazarr/${bazarrId}/lingarr-discovery/confirm`,
		{ method: 'POST', body: JSON.stringify({ name }) },
		fetchFn
	);
}

export function checkBazarrHealth(
	id: string,
	fetchFn: FetchLike = fetch
): Promise<BazarrInstanceRead> {
	return apiFetch<BazarrInstanceRead>(
		`/api/v1/instances/bazarr/${id}/health-check`,
		{ method: 'POST', body: '{}' },
		fetchFn
	);
}

export function checkLingarrHealth(
	id: string,
	fetchFn: FetchLike = fetch
): Promise<LingarrInstanceRead> {
	return apiFetch<LingarrInstanceRead>(
		`/api/v1/instances/lingarr/${id}/health-check`,
		{ method: 'POST', body: '{}' },
		fetchFn
	);
}

// --- Doctor -------------------------------------------------------------------

export function runDoctor(fetchFn: FetchLike = fetch): Promise<DoctorRunRead> {
	return apiFetch<DoctorRunRead>('/api/v1/doctor/run', { method: 'POST', body: '{}' }, fetchFn);
}

export async function getLatestDoctorRun(
	fetchFn: FetchLike = fetch
): Promise<DoctorRunRead | null> {
	// The endpoint may answer 204 (undefined) or a JSON null when no run exists.
	return (await apiFetch<DoctorRunRead | null>('/api/v1/doctor/latest', {}, fetchFn)) ?? null;
}
