// Doctor panel state (P1-T9): latest run plus on-demand execution.

import type { FetchLike } from '$lib/api/client';
import { getLatestDoctorRun, runDoctor } from '$lib/api/endpoints';
import type { DoctorFindingRead, DoctorRunRead } from '$lib/api/types';

const SEVERITY_ORDER = ['critical', 'warn', 'info'] as const;

export function groupFindingsBySeverity(
	run: DoctorRunRead | null
): Array<{ severity: string; findings: DoctorFindingRead[] }> {
	if (run === null) {
		return [];
	}
	const known: Array<{ severity: string; findings: DoctorFindingRead[] }> = SEVERITY_ORDER.map(
		(severity) => ({
			severity,
			findings: run.findings.filter((finding) => finding.severity === severity)
		})
	);
	const other = run.findings.filter(
		(finding) => !(SEVERITY_ORDER as readonly string[]).includes(finding.severity)
	);
	if (other.length > 0) {
		known.push({ severity: 'other', findings: other });
	}
	return known.filter((group) => group.findings.length > 0);
}

export function createDoctorState(fetchFn: FetchLike = fetch) {
	let latest = $state<DoctorRunRead | null>(null);
	let loading = $state(false);
	let running = $state(false);
	let error = $state<string | null>(null);

	async function loadLatest(): Promise<void> {
		loading = true;
		error = null;
		try {
			latest = await getLatestDoctorRun(fetchFn);
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			loading = false;
		}
	}

	async function run(): Promise<void> {
		running = true;
		error = null;
		try {
			latest = await runDoctor(fetchFn);
		} catch (cause) {
			error = cause instanceof Error ? cause.message : String(cause);
		} finally {
			running = false;
		}
	}

	return {
		get latest() {
			return latest;
		},
		get loading() {
			return loading;
		},
		get running() {
			return running;
		},
		get error() {
			return error;
		},
		get grouped() {
			return groupFindingsBySeverity(latest);
		},
		loadLatest,
		run
	};
}

export type DoctorState = ReturnType<typeof createDoctorState>;
