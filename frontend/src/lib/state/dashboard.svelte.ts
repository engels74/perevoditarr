// Dashboard state (P1-T9): coverage, mirror freshness, latest doctor run and
// manual sync triggers. Page-scoped — created per dashboard mount.

import type { FetchLike } from '$lib/api/client';
import {
	getCoverage,
	getFreshness,
	getLatestDoctorRun,
	startSync,
	startWantedSync
} from '$lib/api/endpoints';
import type { CoverageStat, DoctorRunRead, FreshnessRead } from '$lib/api/types';

function errorMessage(cause: unknown): string {
	return cause instanceof Error ? cause.message : String(cause);
}

export function createDashboardState(fetchFn: FetchLike = fetch) {
	let coverage = $state<CoverageStat[]>([]);
	let freshness = $state<FreshnessRead[]>([]);
	let doctor = $state<DoctorRunRead | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let syncPending = $state<ReadonlySet<string>>(new Set());

	async function loadCoverage(): Promise<void> {
		try {
			coverage = await getCoverage(fetchFn);
		} catch (cause) {
			error = errorMessage(cause);
		}
	}

	async function loadFreshness(): Promise<void> {
		try {
			freshness = await getFreshness(fetchFn);
		} catch (cause) {
			error = errorMessage(cause);
		}
	}

	async function loadDoctor(): Promise<void> {
		try {
			doctor = await getLatestDoctorRun(fetchFn);
		} catch (cause) {
			error = errorMessage(cause);
		}
	}

	async function loadAll(): Promise<void> {
		loading = true;
		error = null;
		try {
			await Promise.all([loadCoverage(), loadFreshness(), loadDoctor()]);
		} finally {
			loading = false;
		}
	}

	function markPending(instanceId: string, pending: boolean): void {
		const next = new Set(syncPending);
		if (pending) {
			next.add(instanceId);
		} else {
			next.delete(instanceId);
		}
		syncPending = next;
	}

	async function triggerSync(instanceId: string, full: boolean): Promise<void> {
		markPending(instanceId, true);
		error = null;
		try {
			await startSync(instanceId, full, fetchFn);
			await loadFreshness();
		} catch (cause) {
			error = errorMessage(cause);
		} finally {
			markPending(instanceId, false);
		}
	}

	async function triggerWantedSync(instanceId: string): Promise<void> {
		markPending(instanceId, true);
		error = null;
		try {
			await startWantedSync(instanceId, fetchFn);
			await loadFreshness();
		} catch (cause) {
			error = errorMessage(cause);
		} finally {
			markPending(instanceId, false);
		}
	}

	return {
		get coverage() {
			return coverage;
		},
		get freshness() {
			return freshness;
		},
		get doctor() {
			return doctor;
		},
		get loading() {
			return loading;
		},
		get error() {
			return error;
		},
		get syncPending() {
			return syncPending;
		},
		loadAll,
		loadCoverage,
		loadFreshness,
		loadDoctor,
		triggerSync,
		triggerWantedSync
	};
}

export type DashboardState = ReturnType<typeof createDashboardState>;
