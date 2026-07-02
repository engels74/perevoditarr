// Rails state (P3-T7, FR-Q3/FR-Q1): the dashboard/queue gauges plus the
// operator controls — global + per-instance pause/resume and the safe-by-default
// Observe -> Active activation. Fetchers are injected for testability.

import type { RailStatusDto, RailsOverview } from '$lib/api/types';

export interface RailsFetchers {
	overview: () => Promise<RailsOverview>;
	pauseGlobal: (reason: string | null) => Promise<RailStatusDto>;
	resumeGlobal: () => Promise<RailStatusDto>;
	pauseInstance: (id: string, reason: string | null) => Promise<RailStatusDto>;
	resumeInstance: (id: string) => Promise<RailStatusDto>;
	activate: (id: string) => Promise<RailStatusDto>;
	deactivate: (id: string) => Promise<RailStatusDto>;
}

export function createRailsState(fetchers: RailsFetchers) {
	let overview = $state<RailsOverview | null>(null);
	let loading = $state(false);
	let busy = $state(false);
	let error = $state<string | null>(null);

	const globalRails = $derived(overview?.globalRails ?? null);
	const instances = $derived(overview?.instances ?? []);
	const anyBreakerOpen = $derived(
		instances.some((instance) => instance.breaker != null && instance.breaker.state !== 'closed')
	);

	async function load(): Promise<void> {
		loading = true;
		error = null;
		try {
			overview = await fetchers.overview();
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	async function run(action: () => Promise<RailStatusDto>): Promise<void> {
		busy = true;
		error = null;
		try {
			await action();
			await load();
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			busy = false;
		}
	}

	return {
		get overview() {
			return overview;
		},
		get globalRails(): RailStatusDto | null {
			return globalRails;
		},
		get instances(): RailStatusDto[] {
			return instances;
		},
		get anyBreakerOpen() {
			return anyBreakerOpen;
		},
		get loading() {
			return loading;
		},
		get busy() {
			return busy;
		},
		get error() {
			return error;
		},
		load,
		pauseGlobal: (reason: string | null = null) => run(() => fetchers.pauseGlobal(reason)),
		resumeGlobal: () => run(() => fetchers.resumeGlobal()),
		pauseInstance: (id: string, reason: string | null = null) =>
			run(() => fetchers.pauseInstance(id, reason)),
		resumeInstance: (id: string) => run(() => fetchers.resumeInstance(id)),
		activate: (id: string) => run(() => fetchers.activate(id)),
		deactivate: (id: string) => run(() => fetchers.deactivate(id))
	};
}

export type RailsState = ReturnType<typeof createRailsState>;
