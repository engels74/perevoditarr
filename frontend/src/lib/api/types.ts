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
