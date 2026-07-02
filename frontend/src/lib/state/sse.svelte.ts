// SSE connection manager (P1-T9, FR-U7): topic subscription over one
// EventSource to /api/v1/events with auto-reconnect and capped backoff.
// This is the UI liveness plane only — never a correctness signal (PRD §7.3).

export type SseStatus = 'closed' | 'connecting' | 'open' | 'reconnecting';

export type SseHandler = (data: unknown) => void;

export interface SseSource {
	addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void;
	close(): void;
	onopen: ((event: Event) => void) | null;
	onerror: ((event: Event) => void) | null;
}

export type SseSourceFactory = (url: string) => SseSource;

export interface SseOptions {
	baseDelayMs?: number;
	maxDelayMs?: number;
}

const defaultFactory: SseSourceFactory = (url) => new EventSource(url);

export function createSseManager(
	factory: SseSourceFactory = defaultFactory,
	options: SseOptions = {}
) {
	const baseDelayMs = options.baseDelayMs ?? 1000;
	const maxDelayMs = options.maxDelayMs ?? 30000;

	let status = $state<SseStatus>('closed');
	const handlers = new Map<string, Set<SseHandler>>();
	let source: SseSource | null = null;
	let attempts = 0;
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let closedByUser = true;

	function buildUrl(): string {
		const topics = [...handlers.keys()];
		return topics.length > 0
			? `/api/v1/events?topics=${encodeURIComponent(topics.join(','))}`
			: '/api/v1/events';
	}

	function attach(target: SseSource, topic: string): void {
		target.addEventListener(topic, (event) => {
			const set = handlers.get(topic);
			if (!set) {
				return;
			}
			let data: unknown;
			try {
				data = JSON.parse(event.data) as unknown;
			} catch {
				data = event.data;
			}
			for (const handler of set) {
				handler(data);
			}
		});
	}

	function open(): void {
		source?.close();
		status = attempts === 0 ? 'connecting' : 'reconnecting';
		const next = factory(buildUrl());
		for (const topic of handlers.keys()) {
			attach(next, topic);
		}
		next.onopen = () => {
			attempts = 0;
			status = 'open';
		};
		next.onerror = () => {
			scheduleReconnect();
		};
		source = next;
	}

	function scheduleReconnect(): void {
		if (closedByUser) {
			return;
		}
		source?.close();
		source = null;
		status = 'reconnecting';
		const delay = Math.min(maxDelayMs, baseDelayMs * 2 ** attempts);
		attempts += 1;
		if (reconnectTimer !== null) {
			clearTimeout(reconnectTimer);
		}
		reconnectTimer = setTimeout(open, delay);
	}

	function connect(): void {
		if (!closedByUser && source !== null) {
			return;
		}
		closedByUser = false;
		attempts = 0;
		open();
	}

	function subscribe(topic: string, handler: SseHandler): () => void {
		let set = handlers.get(topic);
		const isNewTopic = set === undefined;
		if (set === undefined) {
			set = new Set();
			handlers.set(topic, set);
		}
		set.add(handler);
		// A new topic changes the server-side filter: renegotiate the stream.
		if (isNewTopic && !closedByUser) {
			open();
		}
		return () => {
			const current = handlers.get(topic);
			current?.delete(handler);
			if (current !== undefined && current.size === 0) {
				handlers.delete(topic);
			}
		};
	}

	function close(): void {
		closedByUser = true;
		if (reconnectTimer !== null) {
			clearTimeout(reconnectTimer);
			reconnectTimer = null;
		}
		source?.close();
		source = null;
		status = 'closed';
	}

	return {
		get status() {
			return status;
		},
		connect,
		subscribe,
		close
	};
}

export type SseManager = ReturnType<typeof createSseManager>;

// App-wide singleton: safe because the app is a pure SPA (ssr = false, ADR-0004).
export const sse = createSseManager();
