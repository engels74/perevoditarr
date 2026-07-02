import { describe, expect, test } from 'bun:test';
import { render, screen } from '@testing-library/svelte';
import PlanVerdict from './plan-verdict.svelte';

describe('plan verdict', () => {
	test('included verdict shows the dispatch position', () => {
		render(PlanVerdict, {
			props: { verdict: { type: 'included' as const, position: 3 } }
		});
		expect(screen.getByText('would dispatch')).toBeTruthy();
		expect(screen.getByText('#3')).toBeTruthy();
	});

	test('held verdict shows the explained rail detail', () => {
		render(PlanVerdict, {
			props: {
				verdict: {
					type: 'held' as const,
					rail: 'daily_cap',
					detail: 'daily cap 200/200'
				}
			}
		});
		expect(screen.getByText('held')).toBeTruthy();
		expect(screen.getByText('daily cap 200/200')).toBeTruthy();
	});
});
