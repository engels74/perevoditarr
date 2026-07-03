// Curated aliases over the generated OpenAPI types (P1-T7).
// Regenerate with `bun run generate:api`; CI fails on drift.

import type { components } from './types.gen';

type Schemas = components['schemas'];

export type SetupStatus = Schemas['SetupStatus'];
export type UserRead = Schemas['UserRead'];
export type LoginProviders = Schemas['LoginProviders'];
export type OidcPublicInfo = Schemas['OidcPublicInfo'];
export type ApiKeyRead = Schemas['ApiKeyRead'];
export type ApiKeyCreated = Schemas['ApiKeyCreated'];
export type HelloMessage = Schemas['HelloMessage'];
export type BazarrInstanceRead = Schemas['BazarrInstanceRead'];
export type BazarrInstanceCreate = Schemas['BazarrInstanceCreate'];
export type BazarrInstanceUpdate = Schemas['BazarrInstanceUpdate'];
export type LingarrInstanceRead = Schemas['LingarrInstanceRead'];
export type LingarrInstanceCreate = Schemas['LingarrInstanceCreate'];
export type LingarrInstanceUpdate = Schemas['LingarrInstanceUpdate'];
export type ConnectionTestRequest = Schemas['ConnectionTestRequest'];
export type InstanceHealth = Schemas['InstanceHealth'];
export type BazarrCapabilities = Schemas['BazarrCapabilities'];
export type ConnectionTestResult = Schemas['ConnectionTestResult'];
export type LingarrDiscoveryResult = Schemas['LingarrDiscoveryResult'];
export type SeriesRead = Schemas['SeriesRead'];
export type EpisodeRead = Schemas['EpisodeRead'];
export type MovieRead = Schemas['MovieRead'];
export type SubtitleRead = Schemas['SubtitleRead'];
export type WantedRead = Schemas['WantedRead'];
export type CoverageStat = Schemas['CoverageStat'];
export type SyncRunRead = Schemas['SyncRunRead'];
export type FreshnessRead = Schemas['FreshnessRead'];
export type DoctorRunRead = Schemas['DoctorRunRead'];
export type DoctorFindingRead = Schemas['DoctorFindingRead'];

// Policy (P2-T6)
export type PresetRead = Schemas['PresetRead'];
export type PresetCreate = Schemas['PresetCreate'];
export type PresetUpdate = Schemas['PresetUpdate'];
export type PresetFork = Schemas['PresetFork'];
export type TranslationProfileRead = Schemas['TranslationProfileRead'];
export type TranslationProfileCreate = Schemas['TranslationProfileCreate'];
export type TranslationProfileUpdate = Schemas['TranslationProfileUpdate'];
export type ProfileEditorResponse = Schemas['ProfileEditorResponse'];
export type ProfileValidateRequest = Schemas['ProfileValidateRequest'];
export type ProfileValidateResponse = Schemas['ProfileValidateResponse'];
export type PolicyFindingRead = Schemas['PolicyFindingRead'];
export type PolicyValuesDto = Schemas['PolicyValuesDto'];
export type PolicyValuesRequest = Schemas['PolicyValuesRequest'];
export type ProfileAssignmentRead = Schemas['ProfileAssignmentRead'];
export type ProfileAssignmentCreate = Schemas['ProfileAssignmentCreate'];
export type ExclusionRead = Schemas['ExclusionRead'];
export type ExclusionCreate = Schemas['ExclusionCreate'];
export type OverrideRead = Schemas['OverrideRead'];
export type OverrideUpsert = Schemas['OverrideUpsert'];
export type EffectivePolicyRead = Schemas['EffectivePolicyRead'];
export type PolicyExport = Schemas['PolicyExport'];
export type PolicyImportRequest = Schemas['PolicyImportRequest'];
export type PolicyImportResult = Schemas['PolicyImportResult'];

// Intents & plan preview (P2-T6)
export type IntentRead = Schemas['IntentRead'];
export type IntentDetail = Schemas['IntentDetail'];
export type IntentEventRead = Schemas['IntentEventRead'];
export type ExplainRead = Schemas['ExplainRead'];
export type PlanPreviewResponse = Schemas['PlanPreviewResponse'];
export type PlanItemDto = Schemas['PlanItemDto'];
export type PlanGroupDto = Schemas['PlanGroupDto'];
export type PlanTotalsDto = Schemas['PlanTotalsDto'];
export type IncludedVerdictDto = Schemas['IncludedVerdictDto'];
export type HeldVerdictDto = Schemas['HeldVerdictDto'];
export type VolumeEstimateDto = Schemas['VolumeEstimateDto'];

// Rails, dispatch, activation (P3-T7 / M2)
export type RailsOverview = Schemas['RailsOverview'];
export type RailStatusDto = Schemas['RailStatusDto'];
export type CapGaugeDto = Schemas['CapGaugeDto'];
export type BudgetGaugeDto = Schemas['BudgetGaugeDto'];
export type BreakerDto = Schemas['BreakerDto'];
export type SchedulingWindowDto = Schemas['SchedulingWindowDto'];
export type SchedulingWindowInput = Schemas['SchedulingWindowInput'];
export type PauseRequest = Schemas['PauseRequest'];
export type WindowsUpdate = Schemas['WindowsUpdate'];
export type WindowKUpdate = Schemas['WindowKUpdate'];

// Notifications (P3-T5)
export type NotificationRouteRead = Schemas['NotificationRouteRead'];
export type NotificationRouteCreate = Schemas['NotificationRouteCreate'];
export type NotificationRouteUpdate = Schemas['NotificationRouteUpdate'];
export type TestFireResult = Schemas['TestFireResult'];
export type DigestResult = Schemas['DigestResult'];

// Telemetry health (P3-T4)
export type TelemetryHealthResponse = Schemas['TelemetryHealthResponse'];
export type InstanceTelemetryDto = Schemas['InstanceTelemetryDto'];
export type StreamHealthDto = Schemas['StreamHealthDto'];

// Stats & budget reconciliation (P4-T1)
export type StatsOverviewResponse = Schemas['StatsOverviewResponse'];
export type StatsTotalsDto = Schemas['StatsTotalsDto'];
export type ThroughputPointDto = Schemas['ThroughputPointDto'];
export type FailureClassDto = Schemas['FailureClassDto'];
export type CoverageSeriesDto = Schemas['CoverageSeriesDto'];
export type CoveragePointDto = Schemas['CoveragePointDto'];
export type BudgetActualsDto = Schemas['BudgetActualsDto'];

// Item timeline & Lingarr pass-through (P4-T2)
export type TimelineResponse = Schemas['TimelineResponse'];
export type TimelineIntentEventEntry = Schemas['TimelineIntentEventEntry'];
export type TimelineBazarrHistoryEntry = Schemas['TimelineBazarrHistoryEntry'];
export type TimelineLingarrRequestEntry = Schemas['TimelineLingarrRequestEntry'];
export type TimelinePassthroughEntry = Schemas['TimelinePassthroughEntry'];
export type PassthroughActionRead = Schemas['PassthroughActionRead'];

// Watch integrations (P5-T1)
export type WatchSourceRead = Schemas['WatchSourceRead'];
export type WatchSourceCreate = Schemas['WatchSourceCreate'];
export type WatchSourceUpdate = Schemas['WatchSourceUpdate'];
export type WatchSourceConfig = Schemas['WatchSourceConfig'];
export type WatchSourceHealth = Schemas['WatchSourceHealth'];
export type WatchSourceTestRequest = Schemas['WatchSourceTestRequest'];
export type WatchSourceTestResult = Schemas['WatchSourceTestResult'];
export type WatchRefreshResult = Schemas['WatchRefreshResult'];

// Roles & user management (P5-T2)
export type UserCreateRequest = Schemas['UserCreateRequest'];
export type UserRoleUpdate = Schemas['UserRoleUpdate'];
export type UserRole = UserRead['role'];
export type LdapSettingsRead = Schemas['LdapSettingsRead'];
export type LdapSettingsWrite = Schemas['LdapSettingsWrite'];

// Webhook ingestion (P5-T3)
export type WebhookSourceRead = Schemas['WebhookSourceRead'];
export type WebhookSourceCreate = Schemas['WebhookSourceCreate'];
export type WebhookSourceUpdate = Schemas['WebhookSourceUpdate'];
export type WebhookSourceCreated = Schemas['WebhookSourceCreated'];
export type WebhookAck = Schemas['WebhookAck'];

// Error problem body (core/errors.py) — not part of the OpenAPI components.
export interface Problem {
	status: number;
	code: string;
	title: string;
	detail?: string | null;
}

// Pagination envelope (core Page[T]); the generic is inlined per-operation in
// the generated file, so a hand generic stays ergonomic for list consumers.
export interface Page<T> {
	items: T[];
	total: number;
	limit: number;
	offset: number;
}
