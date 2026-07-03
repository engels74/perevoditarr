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
				'GET /api/v1/setup/status': () => jsonResponse({ required: true })
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
				'GET /api/v1/setup/status': () => jsonResponse({ required: false }),
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
				'GET /api/v1/setup/status': () => jsonResponse({ required: false }),
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

	test('completeSetup signs in the new admin', async () => {
		const state = createSessionState(
			fetchStub({
				'GET /api/v1/setup/status': () => jsonResponse({ required: true }),
				'POST /api/v1/setup': () => jsonResponse(USER)
			})
		);
		await state.initialize();
		expect(state.setupRequired).toBe(true);
		expect(
			await state.completeSetup({
				username: 'admin',
				password: 'long-enough-pw',
				bootstrapToken: 'abcd-efgh-ijkl'
			})
		).toBe(true);
		expect(state.setupRequired).toBe(false);
		expect(state.user?.username).toBe('admin');
	});
});
