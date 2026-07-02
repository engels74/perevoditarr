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
	DigestResult,
	DoctorRunRead,
	EffectivePolicyRead,
	EpisodeRead,
	ExclusionCreate,
	ExclusionRead,
	ExplainRead,
	FreshnessRead,
	IntentDetail,
	IntentRead,
	LingarrDiscoveryResult,
	LingarrInstanceCreate,
	LingarrInstanceRead,
	LingarrInstanceUpdate,
	MovieRead,
	NotificationRouteCreate,
	NotificationRouteRead,
	NotificationRouteUpdate,
	OverrideRead,
	OverrideUpsert,
	Page,
	PlanPreviewResponse,
	PolicyExport,
	PolicyImportRequest,
	PolicyImportResult,
	PresetCreate,
	PresetRead,
	PresetUpdate,
	ProfileAssignmentCreate,
	ProfileAssignmentRead,
	ProfileEditorResponse,
	ProfileValidateRequest,
	ProfileValidateResponse,
	RailStatusDto,
	RailsOverview,
	SeriesRead,
	SyncRunRead,
	TelemetryHealthResponse,
	TestFireResult,
	TranslationProfileCreate,
	TranslationProfileRead,
	TranslationProfileUpdate
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

// --- Policy -------------------------------------------------------------------

export function listPresets(fetchFn: FetchLike = fetch): Promise<PresetRead[]> {
	return apiFetch<PresetRead[]>('/api/v1/policy/presets', {}, fetchFn);
}

export function createPreset(input: PresetCreate, fetchFn: FetchLike = fetch): Promise<PresetRead> {
	return apiFetch<PresetRead>(
		'/api/v1/policy/presets',
		{ method: 'POST', body: JSON.stringify(input) },
		fetchFn
	);
}

export function updatePreset(
	id: string,
	patch: PresetUpdate,
	fetchFn: FetchLike = fetch
): Promise<PresetRead> {
	return apiFetch<PresetRead>(
		`/api/v1/policy/presets/${id}`,
		{ method: 'PATCH', body: JSON.stringify(patch) },
		fetchFn
	);
}

export function deletePreset(id: string, fetchFn: FetchLike = fetch): Promise<void> {
	return apiFetch<void>(`/api/v1/policy/presets/${id}`, { method: 'DELETE' }, fetchFn);
}

export function activatePreset(id: string, fetchFn: FetchLike = fetch): Promise<PresetRead> {
	return apiFetch<PresetRead>(
		`/api/v1/policy/presets/${id}/activate`,
		{ method: 'POST', body: '{}' },
		fetchFn
	);
}

export function forkPreset(
	id: string,
	name: string,
	fetchFn: FetchLike = fetch
): Promise<PresetRead> {
	return apiFetch<PresetRead>(
		`/api/v1/policy/presets/${id}/fork`,
		{ method: 'POST', body: JSON.stringify({ name }) },
		fetchFn
	);
}

export function exportPolicies(fetchFn: FetchLike = fetch): Promise<PolicyExport> {
	return apiFetch<PolicyExport>('/api/v1/policy/export', {}, fetchFn);
}

export function importPolicies(
	input: PolicyImportRequest,
	fetchFn: FetchLike = fetch
): Promise<PolicyImportResult> {
	return apiFetch<PolicyImportResult>(
		'/api/v1/policy/import',
		{ method: 'POST', body: JSON.stringify(input) },
		fetchFn
	);
}

export function listProfiles(fetchFn: FetchLike = fetch): Promise<TranslationProfileRead[]> {
	return apiFetch<TranslationProfileRead[]>('/api/v1/policy/profiles', {}, fetchFn);
}

export function createProfile(
	input: TranslationProfileCreate,
	fetchFn: FetchLike = fetch
): Promise<ProfileEditorResponse> {
	return apiFetch<ProfileEditorResponse>(
		'/api/v1/policy/profiles',
		{ method: 'POST', body: JSON.stringify(input) },
		fetchFn
	);
}

export function getProfile(id: string, fetchFn: FetchLike = fetch): Promise<ProfileEditorResponse> {
	return apiFetch<ProfileEditorResponse>(`/api/v1/policy/profiles/${id}`, {}, fetchFn);
}

export function updateProfile(
	id: string,
	patch: TranslationProfileUpdate,
	fetchFn: FetchLike = fetch
): Promise<ProfileEditorResponse> {
	return apiFetch<ProfileEditorResponse>(
		`/api/v1/policy/profiles/${id}`,
		{ method: 'PATCH', body: JSON.stringify(patch) },
		fetchFn
	);
}

export function deleteProfile(id: string, fetchFn: FetchLike = fetch): Promise<void> {
	return apiFetch<void>(`/api/v1/policy/profiles/${id}`, { method: 'DELETE' }, fetchFn);
}

export function validateProfileValues(
	input: ProfileValidateRequest,
	fetchFn: FetchLike = fetch
): Promise<ProfileValidateResponse> {
	return apiFetch<ProfileValidateResponse>(
		'/api/v1/policy/profiles/validate',
		{ method: 'POST', body: JSON.stringify(input) },
		fetchFn
	);
}

export function listAssignments(
	instanceId?: string,
	fetchFn: FetchLike = fetch
): Promise<ProfileAssignmentRead[]> {
	return apiFetch<ProfileAssignmentRead[]>(
		`/api/v1/policy/assignments${qs({ bazarr_instance_id: instanceId })}`,
		{},
		fetchFn
	);
}

export function createAssignment(
	input: ProfileAssignmentCreate,
	fetchFn: FetchLike = fetch
): Promise<ProfileAssignmentRead> {
	return apiFetch<ProfileAssignmentRead>(
		'/api/v1/policy/assignments',
		{ method: 'POST', body: JSON.stringify(input) },
		fetchFn
	);
}

export function deleteAssignment(id: string, fetchFn: FetchLike = fetch): Promise<void> {
	return apiFetch<void>(`/api/v1/policy/assignments/${id}`, { method: 'DELETE' }, fetchFn);
}

export function listExclusions(
	instanceId?: string,
	fetchFn: FetchLike = fetch
): Promise<ExclusionRead[]> {
	return apiFetch<ExclusionRead[]>(
		`/api/v1/policy/exclusions${qs({ bazarr_instance_id: instanceId })}`,
		{},
		fetchFn
	);
}

export function createExclusion(
	input: ExclusionCreate,
	fetchFn: FetchLike = fetch
): Promise<ExclusionRead> {
	return apiFetch<ExclusionRead>(
		'/api/v1/policy/exclusions',
		{ method: 'POST', body: JSON.stringify(input) },
		fetchFn
	);
}

export function deleteExclusion(id: string, fetchFn: FetchLike = fetch): Promise<void> {
	return apiFetch<void>(`/api/v1/policy/exclusions/${id}`, { method: 'DELETE' }, fetchFn);
}

export function listOverrides(
	instanceId?: string,
	fetchFn: FetchLike = fetch
): Promise<OverrideRead[]> {
	return apiFetch<OverrideRead[]>(
		`/api/v1/policy/overrides${qs({ bazarr_instance_id: instanceId })}`,
		{},
		fetchFn
	);
}

export function upsertOverride(
	input: OverrideUpsert,
	fetchFn: FetchLike = fetch
): Promise<OverrideRead> {
	return apiFetch<OverrideRead>(
		'/api/v1/policy/overrides',
		{ method: 'POST', body: JSON.stringify(input) },
		fetchFn
	);
}

export function deleteOverride(id: string, fetchFn: FetchLike = fetch): Promise<void> {
	return apiFetch<void>(`/api/v1/policy/overrides/${id}`, { method: 'DELETE' }, fetchFn);
}

export interface EffectivePolicyQuery {
	instanceId: string;
	mediaType: 'series' | 'episode' | 'movie';
	sonarrSeriesId?: number;
	sonarrEpisodeId?: number;
	radarrId?: number;
	tags?: string;
	monitored?: boolean;
}

export function getEffectivePolicy(
	query: EffectivePolicyQuery,
	fetchFn: FetchLike = fetch
): Promise<EffectivePolicyRead> {
	return apiFetch<EffectivePolicyRead>(
		`/api/v1/policy/effective${qs({
			bazarr_instance_id: query.instanceId,
			media_type: query.mediaType,
			sonarr_series_id: query.sonarrSeriesId,
			sonarr_episode_id: query.sonarrEpisodeId,
			radarr_id: query.radarrId,
			tags: query.tags,
			monitored: query.monitored
		})}`,
		{},
		fetchFn
	);
}

// --- Intents ------------------------------------------------------------------

export interface IntentsQuery {
	states?: string;
	instanceId?: string;
	mediaType?: 'episode' | 'movie';
	targetLanguage?: string;
	createdAfter?: string;
	createdBefore?: string;
	limit?: number;
	offset?: number;
}

export function listIntents(
	query: IntentsQuery,
	fetchFn: FetchLike = fetch
): Promise<Page<IntentRead>> {
	return apiFetch<Page<IntentRead>>(
		`/api/v1/intents${qs({
			states: query.states,
			bazarr_instance_id: query.instanceId,
			media_type: query.mediaType,
			target_language: query.targetLanguage,
			created_after: query.createdAfter,
			created_before: query.createdBefore,
			limit: query.limit,
			offset: query.offset
		})}`,
		{},
		fetchFn
	);
}

export function getIntent(id: string, fetchFn: FetchLike = fetch): Promise<IntentDetail> {
	return apiFetch<IntentDetail>(`/api/v1/intents/${id}`, {}, fetchFn);
}

export interface ExplainQuery {
	instanceId: string;
	mediaType: 'episode' | 'movie';
	externalMediaId: number;
	language: string;
	forced?: boolean;
	hi?: boolean;
}

export function explainCandidate(
	query: ExplainQuery,
	fetchFn: FetchLike = fetch
): Promise<ExplainRead> {
	return apiFetch<ExplainRead>(
		`/api/v1/intents/explain${qs({
			bazarr_instance_id: query.instanceId,
			media_type: query.mediaType,
			external_media_id: query.externalMediaId,
			language: query.language,
			forced: query.forced,
			hi: query.hi
		})}`,
		{},
		fetchFn
	);
}

// --- Plan preview ---------------------------------------------------------------

export function getPlanPreview(
	query: { instanceId?: string; limit?: number },
	fetchFn: FetchLike = fetch
): Promise<PlanPreviewResponse> {
	return apiFetch<PlanPreviewResponse>(
		`/api/v1/plan/preview${qs({ bazarr_instance_id: query.instanceId, limit: query.limit })}`,
		{},
		fetchFn
	);
}

// --- Intents backlog / in-flight (P3-T7 / M2) -------------------------------

export interface QueueQuery {
	instanceId?: string;
	limit?: number;
	offset?: number;
}

export function listBacklog(
	query: QueueQuery,
	fetchFn: FetchLike = fetch
): Promise<Page<IntentRead>> {
	return apiFetch<Page<IntentRead>>(
		`/api/v1/intents/backlog${qs({ bazarr_instance_id: query.instanceId, limit: query.limit, offset: query.offset })}`,
		{},
		fetchFn
	);
}

export function listInFlight(
	query: QueueQuery,
	fetchFn: FetchLike = fetch
): Promise<Page<IntentRead>> {
	return apiFetch<Page<IntentRead>>(
		`/api/v1/intents/in-flight${qs({ bazarr_instance_id: query.instanceId, limit: query.limit, offset: query.offset })}`,
		{},
		fetchFn
	);
}

// --- Rails, activation, pause/resume (M2) -----------------------------------

export function getRailsOverview(fetchFn: FetchLike = fetch): Promise<RailsOverview> {
	return apiFetch<RailsOverview>('/api/v1/rails/status', {}, fetchFn);
}

export function getInstanceRails(id: string, fetchFn: FetchLike = fetch): Promise<RailStatusDto> {
	return apiFetch<RailStatusDto>(`/api/v1/rails/${id}`, {}, fetchFn);
}

export function pauseRailsGlobal(
	reason: string | null,
	fetchFn: FetchLike = fetch
): Promise<RailStatusDto> {
	return apiFetch<RailStatusDto>(
		'/api/v1/rails/pause',
		{ method: 'POST', body: JSON.stringify({ reason }) },
		fetchFn
	);
}

export function resumeRailsGlobal(fetchFn: FetchLike = fetch): Promise<RailStatusDto> {
	return apiFetch<RailStatusDto>('/api/v1/rails/resume', { method: 'POST' }, fetchFn);
}

export function pauseInstanceRails(
	id: string,
	reason: string | null,
	fetchFn: FetchLike = fetch
): Promise<RailStatusDto> {
	return apiFetch<RailStatusDto>(
		`/api/v1/rails/${id}/pause`,
		{ method: 'POST', body: JSON.stringify({ reason }) },
		fetchFn
	);
}

export function resumeInstanceRails(
	id: string,
	fetchFn: FetchLike = fetch
): Promise<RailStatusDto> {
	return apiFetch<RailStatusDto>(`/api/v1/rails/${id}/resume`, { method: 'POST' }, fetchFn);
}

export function activateInstance(id: string, fetchFn: FetchLike = fetch): Promise<RailStatusDto> {
	return apiFetch<RailStatusDto>(`/api/v1/rails/${id}/activate`, { method: 'POST' }, fetchFn);
}

export function deactivateInstance(id: string, fetchFn: FetchLike = fetch): Promise<RailStatusDto> {
	return apiFetch<RailStatusDto>(`/api/v1/rails/${id}/deactivate`, { method: 'POST' }, fetchFn);
}

// --- Quarantine + needs-attention (M2) --------------------------------------

export function listQuarantine(
	query: QueueQuery,
	fetchFn: FetchLike = fetch
): Promise<Page<IntentRead>> {
	return apiFetch<Page<IntentRead>>(
		`/api/v1/quarantine${qs({ bazarr_instance_id: query.instanceId, limit: query.limit, offset: query.offset })}`,
		{},
		fetchFn
	);
}

export function listNeedsAttention(
	query: QueueQuery,
	fetchFn: FetchLike = fetch
): Promise<Page<IntentRead>> {
	return apiFetch<Page<IntentRead>>(
		`/api/v1/quarantine/needs-attention${qs({ bazarr_instance_id: query.instanceId, limit: query.limit, offset: query.offset })}`,
		{},
		fetchFn
	);
}

export function retryQuarantined(id: string, fetchFn: FetchLike = fetch): Promise<IntentRead> {
	return apiFetch<IntentRead>(`/api/v1/quarantine/${id}/retry`, { method: 'POST' }, fetchFn);
}

export function releaseQuarantined(id: string, fetchFn: FetchLike = fetch): Promise<IntentRead> {
	return apiFetch<IntentRead>(`/api/v1/quarantine/${id}/release`, { method: 'POST' }, fetchFn);
}

export function excludeQuarantined(id: string, fetchFn: FetchLike = fetch): Promise<IntentRead> {
	return apiFetch<IntentRead>(`/api/v1/quarantine/${id}/exclude`, { method: 'POST' }, fetchFn);
}

// --- Notifications (M2) -----------------------------------------------------

export function listNotificationRoutes(
	fetchFn: FetchLike = fetch
): Promise<NotificationRouteRead[]> {
	return apiFetch<NotificationRouteRead[]>('/api/v1/notifications/routes', {}, fetchFn);
}

export function createNotificationRoute(
	body: NotificationRouteCreate,
	fetchFn: FetchLike = fetch
): Promise<NotificationRouteRead> {
	return apiFetch<NotificationRouteRead>(
		'/api/v1/notifications/routes',
		{ method: 'POST', body: JSON.stringify(body) },
		fetchFn
	);
}

export function updateNotificationRoute(
	id: string,
	body: NotificationRouteUpdate,
	fetchFn: FetchLike = fetch
): Promise<NotificationRouteRead> {
	return apiFetch<NotificationRouteRead>(
		`/api/v1/notifications/routes/${id}`,
		{ method: 'PATCH', body: JSON.stringify(body) },
		fetchFn
	);
}

export function deleteNotificationRoute(id: string, fetchFn: FetchLike = fetch): Promise<void> {
	return apiFetch<void>(`/api/v1/notifications/routes/${id}`, { method: 'DELETE' }, fetchFn);
}

export function testNotificationRoute(
	id: string,
	fetchFn: FetchLike = fetch
): Promise<TestFireResult> {
	return apiFetch<TestFireResult>(
		`/api/v1/notifications/routes/${id}/test`,
		{ method: 'POST' },
		fetchFn
	);
}

export function sendNotificationDigest(fetchFn: FetchLike = fetch): Promise<DigestResult> {
	return apiFetch<DigestResult>('/api/v1/notifications/digest', { method: 'POST' }, fetchFn);
}

// --- Telemetry health (M2) --------------------------------------------------

export function getTelemetryHealth(fetchFn: FetchLike = fetch): Promise<TelemetryHealthResponse> {
	return apiFetch<TelemetryHealthResponse>('/api/v1/telemetry/health', {}, fetchFn);
}
