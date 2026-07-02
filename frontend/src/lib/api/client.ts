// Typed client for Perevoditarr's own /api/v1 — the UI consumes only this API
// (PRD §2.3). Generated types replace the hand-written ones in P1-T7.

import type { HelloMessage, Problem } from './types';

export type FetchLike = typeof fetch;

export class ApiError extends Error {
	readonly status: number;
	readonly problem: Problem | null;

	constructor(status: number, problem: Problem | null, fallback: string) {
		super(problem?.detail ?? problem?.title ?? fallback);
		this.name = 'ApiError';
		this.status = status;
		this.problem = problem;
	}

	get isUnauthorized(): boolean {
		return this.status === 401;
	}

	get isSetupRequired(): boolean {
		return this.status === 403 && this.problem?.code === 'setup-required';
	}
}

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

function csrfToken(): string | null {
	if (typeof document === 'undefined') {
		return null;
	}
	const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
	return match?.[1] ? decodeURIComponent(match[1]) : null;
}

export async function apiFetch<T>(
	path: string,
	init: RequestInit = {},
	fetchFn: FetchLike = fetch
): Promise<T> {
	const method = (init.method ?? 'GET').toUpperCase();
	const headers = new Headers(init.headers);
	if (init.body !== undefined && !headers.has('content-type')) {
		headers.set('content-type', 'application/json');
	}
	if (UNSAFE_METHODS.has(method)) {
		// Cookie sessions require the double-submit CSRF header; the cookie is
		// intentionally readable by the SPA.
		const token = csrfToken();
		if (token) {
			headers.set('x-csrftoken', token);
		}
	}
	const response = await fetchFn(path, {
		...init,
		method,
		headers,
		credentials: 'same-origin'
	});
	if (!response.ok) {
		let problem: Problem | null = null;
		try {
			problem = (await response.json()) as Problem;
		} catch {
			// non-JSON error body — keep the fallback message
		}
		throw new ApiError(response.status, problem, `${method} ${path} failed: ${response.status}`);
	}
	if (response.status === 204) {
		return undefined as T;
	}
	return (await response.json()) as T;
}

export async function getHello(fetchFn: FetchLike = fetch): Promise<HelloMessage> {
	return apiFetch<HelloMessage>('/api/v1/hello', {}, fetchFn);
}

export type { HelloMessage } from './types';
