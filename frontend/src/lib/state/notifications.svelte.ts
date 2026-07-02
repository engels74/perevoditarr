// Notification settings state (P3-T7, FR-X1): route CRUD with per-event routing
// and the test-fire button. Fetchers injected for testability.

import type {
	NotificationRouteCreate,
	NotificationRouteRead,
	NotificationRouteUpdate,
	TestFireResult
} from '$lib/api/types';

export interface NotificationsFetchers {
	list: () => Promise<NotificationRouteRead[]>;
	create: (body: NotificationRouteCreate) => Promise<NotificationRouteRead>;
	update: (id: string, body: NotificationRouteUpdate) => Promise<NotificationRouteRead>;
	remove: (id: string) => Promise<void>;
	test: (id: string) => Promise<TestFireResult>;
}

export function createNotificationsState(fetchers: NotificationsFetchers) {
	let routes = $state<NotificationRouteRead[]>([]);
	let loading = $state(false);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let lastTest = $state<TestFireResult | null>(null);

	async function load(): Promise<void> {
		loading = true;
		error = null;
		try {
			routes = await fetchers.list();
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	async function create(body: NotificationRouteCreate): Promise<boolean> {
		return run(async () => {
			await fetchers.create(body);
		});
	}

	async function update(id: string, body: NotificationRouteUpdate): Promise<boolean> {
		return run(async () => {
			await fetchers.update(id, body);
		});
	}

	async function remove(id: string): Promise<boolean> {
		return run(async () => {
			await fetchers.remove(id);
		});
	}

	async function test(id: string): Promise<void> {
		busy = true;
		error = null;
		try {
			lastTest = await fetchers.test(id);
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			busy = false;
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
			error = cause instanceof Error ? cause.message : String(cause);
			return false;
		} finally {
			busy = false;
		}
	}

	return {
		get routes(): NotificationRouteRead[] {
			return routes;
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
		get lastTest(): TestFireResult | null {
			return lastTest;
		},
		load,
		create,
		update,
		remove,
		test
	};
}

export type NotificationsState = ReturnType<typeof createNotificationsState>;
