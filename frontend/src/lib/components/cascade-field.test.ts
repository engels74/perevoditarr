import { describe, expect, test } from 'bun:test';
import { render, screen } from '@testing-library/svelte';
import type { PolicyValuesDto } from '$lib/api/types';
import { POLICY_FIELDS } from '$lib/policy-display';
import CascadeField from './cascade-field.svelte';

const graceSpec = POLICY_FIELDS.find((spec) => spec.key === 'graceHoursEpisodes');
if (!graceSpec) {
	throw new Error('graceHoursEpisodes spec missing');
}

describe('cascade field row', () => {
	test('inherited value shows the preview and provenance chip', () => {
		render(CascadeField, {
			props: {
				spec: graceSpec,
				values: {},
				inherited: {
					value: 24,
					provenance: { layer: 'preset' as const, sourceName: 'Balanced' }
				},
				onValuesChange: () => {}
			}
		});
		expect(screen.getByText('24')).toBeTruthy();
		expect(screen.getByText('preset · Balanced')).toBeTruthy();
		// The override toggle is off; the numeric input is not rendered.
		expect(screen.queryByLabelText(graceSpec.label)).toBeNull();
	});

	test('an overridden value renders its control instead of the chip', () => {
		const values: PolicyValuesDto = { graceHoursEpisodes: 12 };
		render(CascadeField, {
			props: {
				spec: graceSpec,
				values,
				inherited: { value: 24, provenance: { layer: 'global' as const } },
				onValuesChange: () => {}
			}
		});
		const input = screen.getByLabelText(graceSpec.label) as HTMLInputElement;
		expect(input.value).toBe('12');
		expect(screen.queryByText('global')).toBeNull();
	});
});
