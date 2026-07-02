// Per-item timeline state (P4-T2, FR-V4/FR-X3): loads the stitched timeline for
// one intent and performs Lingarr pass-through actions (cancel/retry/resume/
// remove), reloading afterwards so the newly-audited action shows up. Fetchers
// are injected for testability.

import type { PassthroughActionRead, TimelineResponse } from '$lib/api/types';

export type PassthroughAction = 'cancel' | 'retry' | 'resume' | 'remove';

export interface TimelineFetchers {
	timeline: (intentId: string) => Promise<TimelineResponse>;
	passthrough: (
		intentId: string,
		lingarrRequestId: number,
		action: PassthroughAction
	) => Promise<PassthroughActionRead>;
}

export function createTimelineState(fetchers: TimelineFetchers) {
	let intentId = $state<string | null>(null);
	let timeline = $state<TimelineResponse | null>(null);
	let loading = $state(false);
	let busy = $state(false);
	let error = $state<string | null>(null);
	let lastResult = $state<PassthroughActionRead | null>(null);

	const entries = $derived(timeline?.entries ?? []);

	async function load(id: string): Promise<void> {
		intentId = id;
		loading = true;
		error = null;
		try {
			timeline = await fetchers.timeline(id);
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	async function act(lingarrRequestId: number, action: PassthroughAction): Promise<void> {
		if (intentId === null) {
			return;
		}
		busy = true;
		error = null;
		try {
			lastResult = await fetchers.passthrough(intentId, lingarrRequestId, action);
			// Reload first (it clears `error`), then surface any rejection so the
			// failed-action detail survives the refresh.
			await load(intentId);
			if (lastResult.status !== 'ok') {
				error = lastResult.detail ?? `Lingarr rejected the ${action} action`;
			}
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			busy = false;
		}
	}

	return {
		get timeline() {
			return timeline;
		},
		get entries() {
			return entries;
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
		get lastResult() {
			return lastResult;
		},
		load,
		act
	};
}

export type TimelineState = ReturnType<typeof createTimelineState>;
