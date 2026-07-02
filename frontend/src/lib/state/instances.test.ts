import { describe, expect, test } from 'bun:test';

import type { FetchLike } from '$lib/api/client';
import { createInstancesState } from './instances.svelte';

const BAZARR = {
	id: 'b0000000-0000-4000-8000-000000000001',
	name: 'main',
	url: 'http://bazarr:6767',
	enabled: true,
	version: '1.5.3',
	lingarrInstanceId: null,
	capabilities: null,
	health: {
		status: 'ok',
		latencyMs: 12,
		checkedAt: null,
		queueDepth: 0,
		version: '1.5.3',
		detail: null
	},
	createdAt: '2026-07-02T00:00:00Z'
};

const LINGARR = {
	id: 'a0000000-0000-4000-8000-000000000002',
	name: 'lingarr',
	url: 'http://lingarr:9876',
	enabled: true,
	version: '0.9.0',
	hasApiKey: true,
	health: null,
	createdAt: '2026-07-02T00:00:00Z'
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

describe('instances state', () => {
	test('load populates both instance lists', async () => {
		const state = createInstancesState(
			fetchStub({
				'GET /api/v1/instances/bazarr': () => jsonResponse([BAZARR]),
				'GET /api/v1/instances/lingarr': () => jsonResponse([LINGARR])
			})
		);
		await state.load();
		expect(state.bazarr).toHaveLength(1);
		expect(state.lingarr).toHaveLength(1);
		expect(state.loaded).toBe(true);
		expect(state.error).toBeNull();
		expect(state.lingarrName(LINGARR.id)).toBe('lingarr');
		expect(state.lingarrName(null)).toBeNull();
		expect(state.bazarrName(BAZARR.id)).toBe('main');
	});

	test('load captures failures as error state', async () => {
		const state = createInstancesState(
			fetchStub({
				'GET /api/v1/instances/bazarr': () =>
					jsonResponse({ status: 500, code: 'internal', title: 'boom' }, 500),
				'GET /api/v1/instances/lingarr': () => jsonResponse([])
			})
		);
		await state.load();
		expect(state.error).toBe('boom');
		expect(state.loaded).toBe(false);
	});

	test('setBazarrEnabled patches and replaces the row in place', async () => {
		const state = createInstancesState(
			fetchStub({
				'GET /api/v1/instances/bazarr': () => jsonResponse([BAZARR]),
				'GET /api/v1/instances/lingarr': () => jsonResponse([]),
				[`PATCH /api/v1/instances/bazarr/${BAZARR.id}`]: () =>
					jsonResponse({ ...BAZARR, enabled: false })
			})
		);
		await state.load();
		await state.setBazarrEnabled(BAZARR.id, false);
		expect(state.bazarr[0]?.enabled).toBe(false);
	});

	test('removeBazarr drops the row after a 204 delete', async () => {
		const state = createInstancesState(
			fetchStub({
				'GET /api/v1/instances/bazarr': () => jsonResponse([BAZARR]),
				'GET /api/v1/instances/lingarr': () => jsonResponse([]),
				[`DELETE /api/v1/instances/bazarr/${BAZARR.id}`]: () => new Response(null, { status: 204 })
			})
		);
		await state.load();
		await state.removeBazarr(BAZARR.id);
		expect(state.bazarr).toHaveLength(0);
	});

	test('addBazarr propagates ApiError problems (422 unsupported-version)', async () => {
		const state = createInstancesState(
			fetchStub({
				'POST /api/v1/instances/bazarr': () =>
					jsonResponse(
						{
							status: 422,
							code: 'unsupported-version',
							title: 'Unsupported Bazarr version',
							detail: 'Bazarr 1.0.0 is older than the minimum supported 1.4.0'
						},
						422
					)
			})
		);
		await expect(
			state.addBazarr({ name: 'old', url: 'http://x', apiKey: 'k', enabled: true })
		).rejects.toThrow('Bazarr 1.0.0 is older than the minimum supported 1.4.0');
	});

	test('unlinkLingarr patches lingarrInstanceId to null', async () => {
		const linked = { ...BAZARR, lingarrInstanceId: LINGARR.id };
		const patchBodies: string[] = [];
		const fetchFn = ((input: RequestInfo | URL, init?: RequestInit) => {
			const key = `${(init?.method ?? 'GET').toUpperCase()} ${String(input)}`;
			if (key === 'GET /api/v1/instances/bazarr') {
				return Promise.resolve(jsonResponse([linked]));
			}
			if (key === 'GET /api/v1/instances/lingarr') {
				return Promise.resolve(jsonResponse([LINGARR]));
			}
			if (key === `PATCH /api/v1/instances/bazarr/${BAZARR.id}`) {
				patchBodies.push(String(init?.body));
				return Promise.resolve(jsonResponse({ ...linked, lingarrInstanceId: null }));
			}
			throw new Error(`unexpected request: ${key}`);
		}) as FetchLike;
		const state = createInstancesState(fetchFn);
		await state.load();
		await state.unlinkLingarr(BAZARR.id);
		expect(patchBodies).toEqual([JSON.stringify({ lingarrInstanceId: null })]);
		expect(state.bazarr[0]?.lingarrInstanceId).toBeNull();
	});
});
