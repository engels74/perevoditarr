// Plan preview state (P2-T6, FR-U3): the primary Observe surface. Refreshes
// on demand and when discovery announces new intents over SSE.

import type { PlanItemDto, PlanPreviewResponse } from '$lib/api/types';

export type PlanFetcher = (query: {
	instanceId?: string;
	limit?: number;
}) => Promise<PlanPreviewResponse>;

export const PLAN_DEFAULT_LIMIT = 25;

export function createPlanState(fetchPlan: PlanFetcher, limit = PLAN_DEFAULT_LIMIT) {
	let plan = $state<PlanPreviewResponse | null>(null);
	let instanceId = $state('');
	let loading = $state(false);
	let error = $state<string | null>(null);

	const included = $derived((plan?.items ?? []).filter((item) => item.verdict.type === 'included'));
	const held = $derived((plan?.items ?? []).filter((item) => item.verdict.type === 'held'));

	async function load(): Promise<void> {
		loading = true;
		error = null;
		try {
			plan = await fetchPlan({ instanceId: instanceId || undefined, limit });
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	async function setInstance(next: string): Promise<void> {
		instanceId = next;
		await load();
	}

	return {
		get plan() {
			return plan;
		},
		get included(): PlanItemDto[] {
			return included;
		},
		get held(): PlanItemDto[] {
			return held;
		},
		get instanceId() {
			return instanceId;
		},
		get loading() {
			return loading;
		},
		get error() {
			return error;
		},
		load,
		setInstance
	};
}

export type PlanState = ReturnType<typeof createPlanState>;
