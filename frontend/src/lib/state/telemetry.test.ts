import { describe, expect, test } from 'bun:test';
import type { StreamHealthDto, TelemetryHealthResponse } from '$lib/api/types';
import { createTelemetryState } from './telemetry.svelte';

function stream(polling: boolean): StreamHealthDto {
	return {
		stream: 'bazarr_socketio',
		state: polling ? 'degraded' : 'live',
		polling,
		failures: polling ? 1 : 0,
		detail: null,
		since: null
	};
}

function response(streams: StreamHealthDto[]): TelemetryHealthResponse {
	return {
		generatedAt: '2026-07-02T00:00:00Z',
		instances: [{ bazarrInstanceId: 'instance-1', instanceName: 'main', streams }]
	};
}

describe('telemetry state', () => {
	test('reports live when every stream is on a socket', async () => {
		const state = createTelemetryState(() => Promise.resolve(response([stream(false)])));
		await state.load();
		expect(state.live).toBe(true);
		expect(state.degraded).toBe(false);
	});

	test('reports degraded when any stream is polling', async () => {
		const state = createTelemetryState(() =>
			Promise.resolve(response([stream(false), stream(true)]))
		);
		await state.load();
		expect(state.degraded).toBe(true);
		expect(state.live).toBe(false);
	});

	test('no streams is neither live nor degraded', async () => {
		const state = createTelemetryState(() => Promise.resolve(response([])));
		await state.load();
		expect(state.live).toBe(false);
		expect(state.degraded).toBe(false);
	});
});
