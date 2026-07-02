// Session state (P1-T9): runes module with getter accessors; the fetch
// function is injectable for tests.

import { ApiError, apiFetch, type FetchLike } from '$lib/api/client';
import type { SetupStatus, UserRead } from '$lib/api/types';

export interface SetupInput {
	username: string;
	password: string;
	email?: string | null;
}

function errorMessage(cause: unknown): string {
	return cause instanceof Error ? cause.message : String(cause);
}

export function createSessionState(fetchFn: FetchLike = fetch) {
	let user = $state<UserRead | null>(null);
	let loading = $state(false);
	let initialized = $state(false);
	let error = $state<string | null>(null);
	let setupRequired = $state(false);

	async function initialize(): Promise<void> {
		loading = true;
		error = null;
		try {
			const status = await apiFetch<SetupStatus>('/api/v1/setup/status', {}, fetchFn);
			setupRequired = status.required;
			if (!status.required) {
				try {
					user = await apiFetch<UserRead>('/api/v1/auth/me', {}, fetchFn);
				} catch (cause) {
					if (cause instanceof ApiError && (cause.isUnauthorized || cause.isSetupRequired)) {
						user = null;
						setupRequired = cause.isSetupRequired;
					} else {
						throw cause;
					}
				}
			}
		} catch (cause) {
			error = errorMessage(cause);
		} finally {
			loading = false;
			initialized = true;
		}
	}

	async function login(username: string, password: string): Promise<boolean> {
		loading = true;
		error = null;
		try {
			user = await apiFetch<UserRead>(
				'/api/v1/auth/login',
				{ method: 'POST', body: JSON.stringify({ username, password }) },
				fetchFn
			);
			return true;
		} catch (cause) {
			error =
				cause instanceof ApiError && cause.isUnauthorized
					? 'Invalid username or password'
					: errorMessage(cause);
			user = null;
			return false;
		} finally {
			loading = false;
		}
	}

	async function logout(): Promise<void> {
		try {
			await apiFetch<null>('/api/v1/auth/logout', { method: 'POST', body: '{}' }, fetchFn);
		} finally {
			user = null;
		}
	}

	async function completeSetup(input: SetupInput): Promise<boolean> {
		loading = true;
		error = null;
		try {
			user = await apiFetch<UserRead>(
				'/api/v1/setup',
				{
					method: 'POST',
					body: JSON.stringify({
						username: input.username,
						password: input.password,
						email: input.email ?? null
					})
				},
				fetchFn
			);
			setupRequired = false;
			return true;
		} catch (cause) {
			error = errorMessage(cause);
			return false;
		} finally {
			loading = false;
		}
	}

	return {
		get user() {
			return user;
		},
		get loading() {
			return loading;
		},
		get initialized() {
			return initialized;
		},
		get error() {
			return error;
		},
		get setupRequired() {
			return setupRequired;
		},
		initialize,
		login,
		logout,
		completeSetup
	};
}

export type SessionState = ReturnType<typeof createSessionState>;

// App-wide singleton: safe because the app is a pure SPA (ssr = false, ADR-0004).
export const session = createSessionState();
