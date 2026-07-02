import { describe, expect, test } from 'bun:test';

import type { FetchLike } from '$lib/api/client';
import type { DoctorFindingRead } from '$lib/api/types';
import { createDoctorState, groupFindingsBySeverity } from './doctor.svelte';

function finding(overrides: Partial<DoctorFindingRead>): DoctorFindingRead {
	return {
		id: 'f0000000-0000-4000-8000-000000000001',
		checkId: 'instances.unreachable',
		severity: 'info',
		message: 'msg',
		explanation: 'why',
		fixGuidance: 'how',
		bazarrInstanceId: null,
		lingarrInstanceId: null,
		data: null,
		...overrides
	};
}

const RUN = {
	id: 'd0000000-0000-4000-8000-000000000002',
	trigger: 'manual',
	status: 'completed',
	startedAt: '2026-07-02T00:00:00Z',
	finishedAt: '2026-07-02T00:00:04Z',
	summary: { info: 1, warn: 1, critical: 1 },
	findings: [
		finding({ severity: 'info', checkId: 'a' }),
		finding({ severity: 'critical', checkId: 'b' }),
		finding({ severity: 'warn', checkId: 'c' })
	]
};

function jsonResponse(body: unknown, status = 200): Response {
	return new Response(JSON.stringify(body), {
		status,
		headers: { 'content-type': 'application/json' }
	});
}

function fetchStub(routes: Record<string, () => Response>): FetchLike {
	return ((input: RequestInfo | URL, init?: RequestInit) => {
		const key = `${(init?.method ?? 'GET').toUpperCase()} ${String(input)}`;
		const route = routes[key];
		if (!route) {
			throw new Error(`unexpected request: ${key}`);
		}
		return Promise.resolve(route());
	}) as FetchLike;
}

describe('doctor state', () => {
	test('loadLatest handles the no-run-yet null body', async () => {
		const state = createDoctorState(
			fetchStub({ 'GET /api/v1/doctor/latest': () => jsonResponse(null) })
		);
		await state.loadLatest();
		expect(state.latest).toBeNull();
		expect(state.grouped).toHaveLength(0);
		expect(state.error).toBeNull();
	});

	test('run posts and stores the finished run', async () => {
		const state = createDoctorState(
			fetchStub({ 'POST /api/v1/doctor/run': () => jsonResponse(RUN) })
		);
		expect(state.running).toBe(false);
		await state.run();
		expect(state.running).toBe(false);
		expect(state.latest?.id).toBe(RUN.id);
		expect(state.grouped.map((group) => group.severity)).toEqual(['critical', 'warn', 'info']);
	});

	test('run failure surfaces the problem title', async () => {
		const state = createDoctorState(
			fetchStub({
				'POST /api/v1/doctor/run': () =>
					jsonResponse(
						{ status: 409, code: 'doctor-running', title: 'Doctor already running' },
						409
					)
			})
		);
		await state.run();
		expect(state.error).toBe('Doctor already running');
	});
});

describe('groupFindingsBySeverity', () => {
	test('orders critical first and drops empty groups', () => {
		const groups = groupFindingsBySeverity(RUN);
		expect(groups.map((group) => group.severity)).toEqual(['critical', 'warn', 'info']);
	});

	test('collects unknown severities under other', () => {
		const groups = groupFindingsBySeverity({
			...RUN,
			findings: [finding({ severity: 'weird' })]
		});
		expect(groups).toEqual([{ severity: 'other', findings: [finding({ severity: 'weird' })] }]);
	});
});
