// Telemetry health state (P3-T7, NFR-7): the websocket-vs-polling degradation
// indicator for the status bar. Any non-live stream means the live UI is on the
// polling fallback.

import type { TelemetryHealthResponse } from '$lib/api/types';

export type TelemetryFetcher = () => Promise<TelemetryHealthResponse>;

export function createTelemetryState(fetchHealth: TelemetryFetcher) {
	let health = $state<TelemetryHealthResponse | null>(null);
	let error = $state<string | null>(null);

	const streams = $derived((health?.instances ?? []).flatMap((instance) => instance.streams));
	const degraded = $derived(streams.some((stream) => stream.polling));
	const live = $derived(streams.length > 0 && !degraded);

	async function load(): Promise<void> {
		error = null;
		try {
			health = await fetchHealth();
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		}
	}

	return {
		get health() {
			return health;
		},
		get degraded() {
			return degraded;
		},
		get live() {
			return live;
		},
		get error() {
			return error;
		},
		load
	};
}

export type TelemetryState = ReturnType<typeof createTelemetryState>;
