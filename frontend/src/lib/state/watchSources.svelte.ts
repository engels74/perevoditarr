// Watch-source settings state (P5-T1, FR-X2): Tautulli/Plex/Jellyfin CRUD,
// connection test, and cache refresh. Fetchers injected for testability.

import type {
	WatchRefreshResult,
	WatchSourceCreate,
	WatchSourceRead,
	WatchSourceTestRequest,
	WatchSourceTestResult,
	WatchSourceUpdate
} from '$lib/api/types';

export interface WatchSourcesFetchers {
	list: () => Promise<WatchSourceRead[]>;
	create: (body: WatchSourceCreate) => Promise<WatchSourceRead>;
	update: (id: string, body: WatchSourceUpdate) => Promise<WatchSourceRead>;
	remove: (id: string) => Promise<void>;
	test: (body: WatchSourceTestRequest) => Promise<WatchSourceTestResult>;
	checkHealth: (id: string) => Promise<WatchSourceRead>;
	refresh: () => Promise<WatchRefreshResult>;
}

function message(cause: unknown): string {
	return cause instanceof Error ? cause.message : String(cause);
}

export function createWatchSourcesState(fetchers: WatchSourcesFetchers) {
	let sources = $state<WatchSourceRead[]>([]);
	let loading = $state(false);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let lastTest = $state<WatchSourceTestResult | null>(null);
	let lastRefresh = $state<WatchRefreshResult | null>(null);

	async function load(): Promise<void> {
		loading = true;
		error = null;
		try {
			sources = await fetchers.list();
		} catch (cause) {
			error = message(cause);
		} finally {
			loading = false;
		}
	}

	async function run(mutate: () => Promise<void>): Promise<boolean> {
		busy = true;
		error = null;
		try {
			await mutate();
			await load();
			return true;
		} catch (cause) {
			error = message(cause);
			return false;
		} finally {
			busy = false;
		}
	}

	async function create(body: WatchSourceCreate): Promise<boolean> {
		return run(async () => {
			await fetchers.create(body);
		});
	}

	async function update(id: string, body: WatchSourceUpdate): Promise<boolean> {
		return run(async () => {
			await fetchers.update(id, body);
		});
	}

	async function remove(id: string): Promise<boolean> {
		return run(async () => {
			await fetchers.remove(id);
		});
	}

	async function test(body: WatchSourceTestRequest): Promise<void> {
		busy = true;
		error = null;
		lastTest = null;
		try {
			lastTest = await fetchers.test(body);
		} catch (cause) {
			error = message(cause);
		} finally {
			busy = false;
		}
	}

	async function checkHealth(id: string): Promise<boolean> {
		return run(async () => {
			await fetchers.checkHealth(id);
		});
	}

	async function refresh(): Promise<void> {
		busy = true;
		error = null;
		try {
			lastRefresh = await fetchers.refresh();
			await load();
		} catch (cause) {
			error = message(cause);
		} finally {
			busy = false;
		}
	}

	return {
		get sources(): WatchSourceRead[] {
			return sources;
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
		get lastTest(): WatchSourceTestResult | null {
			return lastTest;
		},
		get lastRefresh(): WatchRefreshResult | null {
			return lastRefresh;
		},
		load,
		create,
		update,
		remove,
		test,
		checkHealth,
		refresh
	};
}

export type WatchSourcesState = ReturnType<typeof createWatchSourcesState>;
