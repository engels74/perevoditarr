// Stats dashboard state (P4-T1, FR-U8): throughput, failure rates by class,
// converged vs. superseded, per-language coverage trends, and budget actuals vs.
// heuristic. The overview response already bundles the budget reconciliation, so
// one fetch drives the whole page. Fetchers are injected for testability.

import type {
	BudgetActualsDto,
	CoverageSeriesDto,
	FailureClassDto,
	StatsOverviewResponse,
	StatsTotalsDto,
	ThroughputPointDto
} from '$lib/api/types';

export interface StatsFetchers {
	overview: (days: number, instanceId: string | null) => Promise<StatsOverviewResponse>;
}

export function createStatsState(fetchers: StatsFetchers) {
	let overview = $state<StatsOverviewResponse | null>(null);
	let days = $state(30);
	let instanceId = $state<string | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	const totals = $derived<StatsTotalsDto | null>(overview?.totals ?? null);
	const throughput = $derived<ThroughputPointDto[]>(overview?.throughput ?? []);
	const failureClasses = $derived<FailureClassDto[]>(overview?.failureClasses ?? []);
	const coverage = $derived<CoverageSeriesDto[]>(overview?.coverage ?? []);
	const budget = $derived<BudgetActualsDto[]>(overview?.budget ?? []);

	async function load(): Promise<void> {
		loading = true;
		error = null;
		try {
			overview = await fetchers.overview(days, instanceId);
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	async function setDays(next: number): Promise<void> {
		days = next;
		await load();
	}

	async function setInstance(next: string | null): Promise<void> {
		instanceId = next;
		await load();
	}

	return {
		get overview() {
			return overview;
		},
		get totals() {
			return totals;
		},
		get throughput() {
			return throughput;
		},
		get failureClasses() {
			return failureClasses;
		},
		get coverage() {
			return coverage;
		},
		get budget() {
			return budget;
		},
		get days() {
			return days;
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
		setDays,
		setInstance
	};
}

export type StatsState = ReturnType<typeof createStatsState>;
