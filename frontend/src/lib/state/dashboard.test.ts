import { describe, expect, test } from 'bun:test';

import type { FetchLike } from '$lib/api/client';
import { createDashboardState } from './dashboard.svelte';

const INSTANCE_ID = 'b0000000-0000-4000-8000-000000000001';

const COVERAGE = [
	{
		language: 'da',
		episodesWithSubtitle: 90,
		moviesWithSubtitle: 40,
		episodesWanted: 10,
		moviesWanted: 5
	}
];

const FRESHNESS = [
	{
		bazarrInstanceId: INSTANCE_ID,
		lastFullSyncAt: '2026-07-01T00:00:00Z',
		lastWantedSyncAt: null,
		stale: true
	}
];

const DOCTOR_RUN = {
	id: 'd0000000-0000-4000-8000-000000000003',
	trigger: 'manual',
	status: 'completed',
	startedAt: '2026-07-02T00:00:00Z',
	finishedAt: '2026-07-02T00:00:05Z',
	summary: { info: 1, warn: 2, critical: 0 },
	findings: []
};

const SYNC_RUN = {
	id: 's0000000-0000-4000-8000-000000000004',
	bazarrInstanceId: INSTANCE_ID,
	kind: 'full',
	status: 'running',
	startedAt: '2026-07-02T00:00:00Z',
	finishedAt: null,
	counters: null,
	error: null
};

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

function fetchStub(routes: Record<string, () => Response>): FetchLike {
	return ((input: RequestInfo | URL, init?: RequestInit) => {
		const key = `${(init?.method ?? 'GET').toUpperCase()} ${String(input)}`;
		const route = routes[key];
		if (!route) {
			throw new Error(`unexpected request: ${key}`);
		}
		return Promise.resolve(route());
	}) as FetchLike;
}

describe('dashboard state', () => {
	test('loadAll populates coverage, freshness and the latest doctor run', async () => {
		const state = createDashboardState(
			fetchStub({
				'GET /api/v1/mirror/coverage': () => jsonResponse(COVERAGE),
				'GET /api/v1/mirror/freshness': () => jsonResponse(FRESHNESS),
				'GET /api/v1/doctor/latest': () => jsonResponse(DOCTOR_RUN)
			})
		);
		await state.loadAll();
		expect(state.coverage).toHaveLength(1);
		expect(state.freshness[0]?.stale).toBe(true);
		expect(state.doctor?.summary?.warn).toBe(2);
		expect(state.error).toBeNull();
		expect(state.loading).toBe(false);
	});

	test('a 204 from /doctor/latest reads as "no run yet"', async () => {
		const state = createDashboardState(
			fetchStub({
				'GET /api/v1/doctor/latest': () => new Response(null, { status: 204 })
			})
		);
		await state.loadDoctor();
		expect(state.doctor).toBeNull();
		expect(state.error).toBeNull();
	});

	test('triggerSync posts full=true and refreshes freshness', async () => {
		const calls: string[] = [];
		const fetchFn = ((input: RequestInfo | URL, init?: RequestInit) => {
			const key = `${(init?.method ?? 'GET').toUpperCase()} ${String(input)}`;
			calls.push(key);
			if (key === `POST /api/v1/mirror/sync/${INSTANCE_ID}?full=true`) {
				return Promise.resolve(jsonResponse(SYNC_RUN, 201));
			}
			if (key === 'GET /api/v1/mirror/freshness') {
				return Promise.resolve(jsonResponse(FRESHNESS));
			}
			throw new Error(`unexpected request: ${key}`);
		}) as FetchLike;
		const state = createDashboardState(fetchFn);
		await state.triggerSync(INSTANCE_ID, true);
		expect(calls).toContain(`POST /api/v1/mirror/sync/${INSTANCE_ID}?full=true`);
		expect(calls).toContain('GET /api/v1/mirror/freshness');
		expect(state.syncPending.has(INSTANCE_ID)).toBe(false);
		expect(state.error).toBeNull();
	});

	test('triggerWantedSync failure lands in error state and clears pending', async () => {
		const state = createDashboardState(
			fetchStub({
				[`POST /api/v1/mirror/sync/${INSTANCE_ID}/wanted`]: () =>
					jsonResponse(
						{ status: 502, code: 'upstream-unreachable', title: 'Bazarr unreachable' },
						502
					)
			})
		);
		await state.triggerWantedSync(INSTANCE_ID);
		expect(state.error).toBe('Bazarr unreachable');
		expect(state.syncPending.has(INSTANCE_ID)).toBe(false);
	});
});
