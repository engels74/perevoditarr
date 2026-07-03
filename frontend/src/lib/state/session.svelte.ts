// Session state (P1-T9): runes module with getter accessors; the fetch
// function is injectable for tests.

import { ApiError, apiFetch, type FetchLike } from '$lib/api/client';
import { finishSetup as finishSetupRequest, getSetupStatus } from '$lib/api/endpoints';
import type { SetupStatus, UserRead } from '$lib/api/types';

export interface SetupInput {
	username: string;
	password: string;
	bootstrapToken: string;
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
	let setupPhase = $state<SetupStatus['phase'] | null>(null);
	let setupChecklist = $state<SetupStatus['checklist'] | null>(null);

	async function initialize(): Promise<void> {
		loading = true;
		error = null;
		try {
			const status = await apiFetch<SetupStatus>('/api/v1/setup/status', {}, fetchFn);
			setupRequired = status.required;
			setupPhase = status.phase;
			setupChecklist = status.checklist;
			// Fetch the current user whenever an admin account exists (bootstrap no
			// longer required), not only once setup is finished: a reload mid-wizard
			// still carries a valid session cookie, and skipping /auth/me here would
			// leave user===null and bounce the admin to /login right after Finish.
			if (!status.bootstrapRequired) {
				try {
					user = await apiFetch<UserRead>('/api/v1/auth/me', {}, fetchFn);
				} catch (cause) {
					if (cause instanceof ApiError && (cause.isUnauthorized || cause.isSetupRequired)) {
						user = null;
						// A 401 here (no cookie yet) must not clear a still-required setup.
						setupRequired = status.required || cause.isSetupRequired;
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
						bootstrapToken: input.bootstrapToken,
						email: input.email ?? null
					})
				},
				fetchFn
			);
			await refreshSetup();
			return true;
		} catch (cause) {
			error = errorMessage(cause);
			return false;
		} finally {
			loading = false;
		}
	}

	async function refreshSetup(): Promise<void> {
		try {
			const status = await getSetupStatus(fetchFn);
			setupRequired = status.required;
			setupPhase = status.phase;
			setupChecklist = status.checklist;
		} catch (cause) {
			error = errorMessage(cause);
		}
	}

	async function finishSetup(): Promise<boolean> {
		loading = true;
		error = null;
		try {
			const status = await finishSetupRequest(fetchFn);
			setupRequired = status.required;
			setupPhase = status.phase;
			setupChecklist = status.checklist;
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
		get isAdmin(): boolean {
			return user?.isAdmin ?? false;
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
		get setupPhase() {
			return setupPhase;
		},
		get setupChecklist() {
			return setupChecklist;
		},
		initialize,
		login,
		logout,
		completeSetup,
		refreshSetup,
		finishSetup
	};
}

export type SessionState = ReturnType<typeof createSessionState>;

// App-wide singleton: safe because the app is a pure SPA (ssr = false, ADR-0004).
export const session = createSessionState();
