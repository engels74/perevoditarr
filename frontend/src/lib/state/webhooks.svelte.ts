// Webhook ingestion settings state (P5-T3, FR-X4): per-instance inbound
// endpoints. The secret token is surfaced once, on creation. Fetchers injected.

import type {
	WebhookSourceCreate,
	WebhookSourceCreated,
	WebhookSourceRead,
	WebhookSourceUpdate
} from '$lib/api/types';

export interface WebhooksFetchers {
	list: () => Promise<WebhookSourceRead[]>;
	create: (body: WebhookSourceCreate) => Promise<WebhookSourceCreated>;
	update: (id: string, body: WebhookSourceUpdate) => Promise<WebhookSourceRead>;
	remove: (id: string) => Promise<void>;
}

function message(cause: unknown): string {
	return cause instanceof Error ? cause.message : String(cause);
}

export function createWebhooksState(fetchers: WebhooksFetchers) {
	let sources = $state<WebhookSourceRead[]>([]);
	let loading = $state(false);
	let busy = $state(false);
	let error = $state<string | null>(null);
	// The one-time token+URL shown right after creation.
	let lastCreated = $state<WebhookSourceCreated | null>(null);

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

	async function create(body: WebhookSourceCreate): Promise<boolean> {
		busy = true;
		error = null;
		try {
			lastCreated = await fetchers.create(body);
			await load();
			return true;
		} catch (cause) {
			error = message(cause);
			return false;
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
			error = message(cause);
			return false;
		} finally {
			busy = false;
		}
	}

	async function update(id: string, body: WebhookSourceUpdate): Promise<boolean> {
		return run(async () => {
			await fetchers.update(id, body);
		});
	}

	async function remove(id: string): Promise<boolean> {
		return run(async () => {
			await fetchers.remove(id);
		});
	}

	function dismissCreated(): void {
		lastCreated = null;
	}

	return {
		get sources(): WebhookSourceRead[] {
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
		get lastCreated(): WebhookSourceCreated | null {
			return lastCreated;
		},
		load,
		create,
		update,
		remove,
		dismissCreated
	};
}

export type WebhooksState = ReturnType<typeof createWebhooksState>;
