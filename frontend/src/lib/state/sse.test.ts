import { describe, expect, test } from 'bun:test';

import { createSseManager, type SseSource } from './sse.svelte';

class FakeSource implements SseSource {
	readonly listeners = new Map<string, ((event: MessageEvent<string>) => void)[]>();
	onopen: ((event: Event) => void) | null = null;
	onerror: ((event: Event) => void) | null = null;
	closed = false;

	constructor(readonly url: string) {}

	addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
		const existing = this.listeners.get(type) ?? [];
		existing.push(listener);
		this.listeners.set(type, existing);
	}

	close(): void {
		this.closed = true;
	}

	emit(type: string, data: string): void {
		for (const listener of this.listeners.get(type) ?? []) {
			listener(new MessageEvent<string>(type, { data }));
		}
	}

	open(): void {
		this.onopen?.(new Event('open'));
	}

	fail(): void {
		this.onerror?.(new Event('error'));
	}
}

function makeManager(options: { baseDelayMs?: number } = {}) {
	const sources: FakeSource[] = [];
	const manager = createSseManager(
		(url) => {
			const source = new FakeSource(url);
			sources.push(source);
			return source;
		},
		{ baseDelayMs: options.baseDelayMs ?? 1, maxDelayMs: 10 }
	);
	return { manager, sources };
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

describe('sse connection manager', () => {
	test('delivers parsed topic events to subscribers', () => {
		const { manager, sources } = makeManager();
		const received: unknown[] = [];
		manager.subscribe('mirror.sync', (data) => received.push(data));
		manager.connect();

		const source = sources.at(-1);
		expect(source).toBeDefined();
		expect(source?.url).toContain('topics=mirror.sync');
		source?.open();
		expect(manager.status).toBe('open');

		source?.emit('mirror.sync', JSON.stringify({ progress: 42 }));
		expect(received).toEqual([{ progress: 42 }]);
	});

	test('unsubscribe stops delivery', () => {
		const { manager, sources } = makeManager();
		const received: unknown[] = [];
		const unsubscribe = manager.subscribe('instances.health', (data) => received.push(data));
		manager.connect();
		const source = sources.at(-1);
		unsubscribe();
		source?.emit('instances.health', '{"ok":true}');
		expect(received).toEqual([]);
	});

	test('reconnects with backoff after an error', async () => {
		const { manager, sources } = makeManager({ baseDelayMs: 1 });
		manager.subscribe('mirror.sync', () => {});
		manager.connect();
		sources.at(-1)?.open();
		expect(manager.status).toBe('open');

		sources.at(-1)?.fail();
		expect(manager.status).toBe('reconnecting');

		await sleep(10);
		expect(sources.length).toBe(2);
		sources.at(-1)?.open();
		expect(manager.status).toBe('open');
	});

	test('close stops reconnecting', async () => {
		const { manager, sources } = makeManager({ baseDelayMs: 1 });
		manager.subscribe('mirror.sync', () => {});
		manager.connect();
		sources.at(-1)?.open();
		manager.close();
		expect(manager.status).toBe('closed');

		await sleep(10);
		expect(sources.length).toBe(1);
		expect(sources[0]?.closed).toBe(true);
	});

	test('subscribing a new topic renegotiates the stream', () => {
		const { manager, sources } = makeManager();
		manager.subscribe('mirror.sync', () => {});
		manager.connect();
		expect(sources.length).toBe(1);

		manager.subscribe('instances.health', () => {});
		expect(sources.length).toBe(2);
		const url = sources.at(-1)?.url ?? '';
		expect(decodeURIComponent(url)).toContain('mirror.sync,instances.health');
		expect(sources[0]?.closed).toBe(true);
	});
});
