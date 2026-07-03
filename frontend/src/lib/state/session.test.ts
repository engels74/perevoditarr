import { describe, expect, test } from 'bun:test';

import type { FetchLike } from '$lib/api/client';
import { createSessionState } from './session.svelte';

const USER = {
	id: '9f0d0cbe-0000-4000-8000-000000000001',
	username: 'admin',
	email: null,
	isAdmin: true,
	createdAt: '2026-07-02T00:00:00Z'
};

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

type Phase = 'admin' | 'bazarr' | 'lingarr' | 'policy' | 'notifications' | 'finish' | 'done';

function statusBody(
	phase: Phase,
	checklist: Partial<{
		hasAdmin: boolean;
		bazarrCount: number;
		lingarrCount: number;
		notificationCount: number;
	}> = {}
): Record<string, unknown> {
	return {
		required: phase !== 'done',
		bootstrapRequired: phase === 'admin',
		completed: phase === 'done',
		phase,
		checklist: {
			hasAdmin: phase !== 'admin',
			bazarrCount: 0,
			lingarrCount: 0,
			notificationCount: 0,
			...checklist
		}
	};
}

function sequence(responses: (() => Response)[]): () => Response {
	let index = 0;
	return () => {
		const next = responses[Math.min(index, responses.length - 1)];
		index += 1;
		return next();
	};
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

describe('session state', () => {
	test('initialize surfaces first-run setup', async () => {
		const state = createSessionState(
			fetchStub({
				'GET /api/v1/setup/status': () => jsonResponse(statusBody('admin'))
			})
		);
		await state.initialize();
		expect(state.setupRequired).toBe(true);
		expect(state.user).toBeNull();
		expect(state.initialized).toBe(true);
		expect(state.error).toBeNull();
	});

	test('initialize restores an existing session', async () => {
		const state = createSessionState(
			fetchStub({
				'GET /api/v1/setup/status': () => jsonResponse(statusBody('done')),
				'GET /api/v1/auth/me': () => jsonResponse(USER)
			})
		);
		await state.initialize();
		expect(state.user?.username).toBe('admin');
		expect(state.setupRequired).toBe(false);
	});

	test('initialize treats 401 as signed-out, not an error', async () => {
		const state = createSessionState(
			fetchStub({
				'GET /api/v1/setup/status': () => jsonResponse(statusBody('done')),
				'GET /api/v1/auth/me': () =>
					jsonResponse({ status: 401, code: 'unauthorized', title: 'Unauthorized' }, 401)
			})
		);
		await state.initialize();
		expect(state.user).toBeNull();
		expect(state.error).toBeNull();
		expect(state.initialized).toBe(true);
	});

	test('login success sets the user', async () => {
		const state = createSessionState(
			fetchStub({
				'POST /api/v1/auth/login': () => jsonResponse(USER)
			})
		);
		expect(await state.login('admin', 'pw')).toBe(true);
		expect(state.user?.username).toBe('admin');
		expect(state.error).toBeNull();
	});

	test('login failure produces a friendly error', async () => {
		const state = createSessionState(
			fetchStub({
				'POST /api/v1/auth/login': () =>
					jsonResponse({ status: 401, code: 'unauthorized', title: 'Unauthorized' }, 401)
			})
		);
		expect(await state.login('admin', 'wrong')).toBe(false);
		expect(state.user).toBeNull();
		expect(state.error).toBe('Invalid username or password');
	});

	test('logout clears the user even when the request fails', async () => {
		const state = createSessionState(
			fetchStub({
				'POST /api/v1/auth/login': () => jsonResponse(USER),
				'POST /api/v1/auth/logout': () =>
					jsonResponse({ status: 500, code: 'internal-error', title: 'Internal error' }, 500)
			})
		);
		await state.login('admin', 'pw');
		await state.logout().catch(() => {
			// error propagates, but the local session must still be cleared
		});
		expect(state.user).toBeNull();
	});

	test('initialize stores phase and checklist', async () => {
		const state = createSessionState(
			fetchStub({
				'GET /api/v1/setup/status': () =>
					jsonResponse(statusBody('bazarr', { hasAdmin: true, bazarrCount: 0 })),
				// An admin exists (bootstrap done), so initialize now probes /auth/me;
				// nobody is signed in yet during the wizard, so it 401s.
				'GET /api/v1/auth/me': () =>
					jsonResponse({ status: 401, code: 'unauthorized', title: 'Unauthorized' }, 401)
			})
		);
		await state.initialize();
		expect(state.setupRequired).toBe(true);
		expect(state.user).toBeNull();
		expect(state.setupPhase).toBe('bazarr');
		expect(state.setupChecklist?.hasAdmin).toBe(true);
		expect(state.setupChecklist?.bazarrCount).toBe(0);
	});

	test('initialize restores the admin session mid-setup (before finish)', async () => {
		const state = createSessionState(
			fetchStub({
				'GET /api/v1/setup/status': () =>
					jsonResponse(statusBody('finish', { hasAdmin: true, bazarrCount: 1 })),
				'GET /api/v1/auth/me': () => jsonResponse(USER)
			})
		);
		await state.initialize();
		// Setup is not finished, but an admin exists and holds a valid session
		// cookie: /auth/me must run so finishing the wizard doesn't bounce to /login.
		expect(state.setupRequired).toBe(true);
		expect(state.user?.username).toBe('admin');
		expect(state.error).toBeNull();
	});

	test('completeSetup creates the admin and advances the wizard', async () => {
		const state = createSessionState(
			fetchStub({
				'GET /api/v1/setup/status': sequence([
					() => jsonResponse(statusBody('admin')),
					() => jsonResponse(statusBody('bazarr', { hasAdmin: true }))
				]),
				'POST /api/v1/setup': () => jsonResponse(USER)
			})
		);
		await state.initialize();
		expect(state.setupPhase).toBe('admin');
		expect(
			await state.completeSetup({
				username: 'admin',
				password: 'long-enough-pw',
				bootstrapToken: 'abcd-efgh-ijkl'
			})
		).toBe(true);
		// Admin creation keeps setup required; refreshSetup advances the phase.
		expect(state.setupRequired).toBe(true);
		expect(state.setupPhase).toBe('bazarr');
		expect(state.user?.username).toBe('admin');
	});

	test('refreshSetup updates phase and checklist', async () => {
		const state = createSessionState(
			fetchStub({
				'GET /api/v1/setup/status': () =>
					jsonResponse(statusBody('finish', { hasAdmin: true, bazarrCount: 2 }))
			})
		);
		await state.refreshSetup();
		expect(state.setupPhase).toBe('finish');
		expect(state.setupChecklist?.bazarrCount).toBe(2);
		expect(state.setupRequired).toBe(true);
	});

	test('finishSetup flips setupRequired to false', async () => {
		const state = createSessionState(
			fetchStub({
				'POST /api/v1/setup/finish': () =>
					jsonResponse(statusBody('done', { hasAdmin: true, bazarrCount: 1 }))
			})
		);
		expect(await state.finishSetup()).toBe(true);
		expect(state.setupRequired).toBe(false);
		expect(state.setupPhase).toBe('done');
	});

	test('skip-through flow reaches completion', async () => {
		const state = createSessionState(
			fetchStub({
				'GET /api/v1/setup/status': sequence([
					() => jsonResponse(statusBody('admin')),
					() => jsonResponse(statusBody('finish', { hasAdmin: true, bazarrCount: 1 }))
				]),
				'POST /api/v1/setup': () => jsonResponse(USER),
				'POST /api/v1/setup/finish': () =>
					jsonResponse(statusBody('done', { hasAdmin: true, bazarrCount: 1 }))
			})
		);
		await state.initialize();
		expect(state.setupPhase).toBe('admin');
		await state.completeSetup({
			username: 'admin',
			password: 'long-enough-pw',
			bootstrapToken: 'abcd-efgh-ijkl'
		});
		// Status now reports the finish phase (admin + a bazarr already present).
		expect(state.setupPhase).toBe('finish');
		expect(await state.finishSetup()).toBe(true);
		expect(state.setupRequired).toBe(false);
		expect(state.setupPhase).toBe('done');
	});
});
