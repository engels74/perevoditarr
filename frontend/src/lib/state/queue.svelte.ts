// Queue state (P3-T7, FR-U2): the four M2 queue tabs — backlog (priority-
// ordered), in-flight (live progress via telemetry SSE), needs-attention, and
// quarantine — with the per-item quarantine actions. Fetchers are injected so
// the module is testable without a network.

import type { IntentRead, Page } from '$lib/api/types';

export type QueueTab = 'backlog' | 'inFlight' | 'needsAttention' | 'quarantine';

export type QueueQuery = { instanceId?: string; limit?: number };
export type PageFetcher = (query: QueueQuery) => Promise<Page<IntentRead>>;
export type ActionFetcher = (id: string) => Promise<IntentRead>;

export interface QueueFetchers {
	backlog: PageFetcher;
	inFlight: PageFetcher;
	needsAttention: PageFetcher;
	quarantine: PageFetcher;
	retry: ActionFetcher;
	release: ActionFetcher;
	exclude: ActionFetcher;
}

export const QUEUE_DEFAULT_LIMIT = 50;

export function createQueueState(fetchers: QueueFetchers, limit = QUEUE_DEFAULT_LIMIT) {
	let tab = $state<QueueTab>('backlog');
	let items = $state<IntentRead[]>([]);
	let total = $state(0);
	let instanceId = $state('');
	let loading = $state(false);
	let acting = $state<string | null>(null);
	let error = $state<string | null>(null);

	const loaders: Record<QueueTab, PageFetcher> = {
		backlog: fetchers.backlog,
		inFlight: fetchers.inFlight,
		needsAttention: fetchers.needsAttention,
		quarantine: fetchers.quarantine
	};

	async function load(): Promise<void> {
		loading = true;
		error = null;
		try {
			const page = await loaders[tab]({ instanceId: instanceId || undefined, limit });
			items = page.items;
			total = page.total;
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	async function setTab(next: QueueTab): Promise<void> {
		if (next === tab) {
			return;
		}
		tab = next;
		await load();
	}

	async function setInstance(next: string): Promise<void> {
		instanceId = next;
		await load();
	}

	async function act(action: ActionFetcher, id: string): Promise<void> {
		acting = id;
		error = null;
		try {
			await action(id);
			await load();
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			acting = null;
		}
	}

	return {
		get tab() {
			return tab;
		},
		get items(): IntentRead[] {
			return items;
		},
		get total() {
			return total;
		},
		get instanceId() {
			return instanceId;
		},
		get loading() {
			return loading;
		},
		get acting() {
			return acting;
		},
		get error() {
			return error;
		},
		load,
		setTab,
		setInstance,
		retry: (id: string) => act(fetchers.retry, id),
		release: (id: string) => act(fetchers.release, id),
		exclude: (id: string) => act(fetchers.exclude, id)
	};
}

export type QueueState = ReturnType<typeof createQueueState>;
