// Shared instances state (P1-T9): powers the dashboard health cards and the
// Settings → Instances page. Getter accessors per the rules doc; fetch is
// injectable for tests. Mutations throw ApiError so callers can render the
// Problem detail (422 unsupported-version, 502 unreachable, 409 conflicts).

import type { FetchLike } from '$lib/api/client';
import {
	checkBazarrHealth,
	checkLingarrHealth,
	confirmLingarrDiscovery,
	createBazarrInstance,
	createLingarrInstance,
	deleteBazarrInstance,
	deleteLingarrInstance,
	listBazarrInstances,
	listLingarrInstances,
	updateBazarrInstance,
	updateLingarrInstance
} from '$lib/api/endpoints';
import type {
	BazarrInstanceCreate,
	BazarrInstanceRead,
	LingarrInstanceCreate,
	LingarrInstanceRead
} from '$lib/api/types';

function errorMessage(cause: unknown): string {
	return cause instanceof Error ? cause.message : String(cause);
}

export function createInstancesState(fetchFn: FetchLike = fetch) {
	let bazarr = $state<BazarrInstanceRead[]>([]);
	let lingarr = $state<LingarrInstanceRead[]>([]);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let loaded = $state(false);

	async function load(): Promise<void> {
		loading = true;
		error = null;
		try {
			const [bazarrList, lingarrList] = await Promise.all([
				listBazarrInstances(fetchFn),
				listLingarrInstances(fetchFn)
			]);
			bazarr = bazarrList;
			lingarr = lingarrList;
			loaded = true;
		} catch (cause) {
			error = errorMessage(cause);
		} finally {
			loading = false;
		}
	}

	function replaceBazarr(updated: BazarrInstanceRead): void {
		bazarr = bazarr.map((item) => (item.id === updated.id ? updated : item));
	}

	function replaceLingarr(updated: LingarrInstanceRead): void {
		lingarr = lingarr.map((item) => (item.id === updated.id ? updated : item));
	}

	async function setBazarrEnabled(id: string, enabled: boolean): Promise<void> {
		replaceBazarr(await updateBazarrInstance(id, { enabled }, fetchFn));
	}

	async function setLingarrEnabled(id: string, enabled: boolean): Promise<void> {
		replaceLingarr(await updateLingarrInstance(id, { enabled }, fetchFn));
	}

	async function addBazarr(input: BazarrInstanceCreate): Promise<void> {
		await createBazarrInstance(input, fetchFn);
		await load();
	}

	async function addLingarr(input: LingarrInstanceCreate): Promise<void> {
		await createLingarrInstance(input, fetchFn);
		await load();
	}

	async function removeBazarr(id: string): Promise<void> {
		await deleteBazarrInstance(id, fetchFn);
		bazarr = bazarr.filter((item) => item.id !== id);
	}

	async function removeLingarr(id: string): Promise<void> {
		await deleteLingarrInstance(id, fetchFn);
		lingarr = lingarr.filter((item) => item.id !== id);
	}

	async function unlinkLingarr(bazarrId: string): Promise<void> {
		replaceBazarr(await updateBazarrInstance(bazarrId, { lingarrInstanceId: null }, fetchFn));
	}

	async function confirmDiscovery(bazarrId: string, name: string): Promise<void> {
		await confirmLingarrDiscovery(bazarrId, name, fetchFn);
		await load();
	}

	async function refreshBazarrHealth(id: string): Promise<void> {
		replaceBazarr(await checkBazarrHealth(id, fetchFn));
	}

	async function refreshLingarrHealth(id: string): Promise<void> {
		replaceLingarr(await checkLingarrHealth(id, fetchFn));
	}

	function lingarrName(id: string | null): string | null {
		if (id === null) {
			return null;
		}
		return lingarr.find((item) => item.id === id)?.name ?? null;
	}

	function bazarrName(id: string): string | null {
		return bazarr.find((item) => item.id === id)?.name ?? null;
	}

	return {
		get bazarr() {
			return bazarr;
		},
		get lingarr() {
			return lingarr;
		},
		get loading() {
			return loading;
		},
		get error() {
			return error;
		},
		get loaded() {
			return loaded;
		},
		load,
		setBazarrEnabled,
		setLingarrEnabled,
		addBazarr,
		addLingarr,
		removeBazarr,
		removeLingarr,
		unlinkLingarr,
		confirmDiscovery,
		refreshBazarrHealth,
		refreshLingarrHealth,
		lingarrName,
		bazarrName
	};
}

export type InstancesState = ReturnType<typeof createInstancesState>;

// App-wide singleton: safe because the app is a pure SPA (ssr = false, ADR-0004).
export const instances = createInstancesState();
