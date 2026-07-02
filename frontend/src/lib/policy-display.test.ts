import { describe, expect, test } from 'bun:test';
import type { PolicyValuesDto } from '$lib/api/types';
import {
	GLOBAL_DEFAULTS_DISPLAY,
	inheritedResolution,
	isSetAtLayer,
	pairLabel,
	provenanceChip,
	severityBadgeVariant,
	sortFindings,
	subtitleFlags,
	withFieldCleared
} from './policy-display';

describe('provenance chips', () => {
	test('named layers carry their source name', () => {
		const chip = provenanceChip({ layer: 'preset', sourceName: 'Balanced' });
		expect(chip.label).toBe('preset · Balanced');
		expect(chip.explanation).toBe('Inherited from preset Balanced — override?');
		expect(chip.inherited).toBe(true);
	});

	test('global renders without a source name', () => {
		const chip = provenanceChip({ layer: 'global' });
		expect(chip.label).toBe('global');
		expect(chip.explanation).toContain('global defaults');
	});

	test('override is not inherited', () => {
		const chip = provenanceChip({ layer: 'override' });
		expect(chip.inherited).toBe(false);
		expect(chip.explanation).toBe('Set directly on this item');
	});
});

describe('override-layer resolution', () => {
	test('null and undefined both mean inherit', () => {
		const values: PolicyValuesDto = { dryRun: null, graceHoursEpisodes: 0 };
		expect(isSetAtLayer(values, 'dryRun')).toBe(false);
		expect(isSetAtLayer(values, 'targetLanguages')).toBe(false);
		// Zero and false are real overrides, not inherits.
		expect(isSetAtLayer(values, 'graceHoursEpisodes')).toBe(true);
	});

	test('clearing writes null so the parent layer shows through', () => {
		const values: PolicyValuesDto = { targetLanguages: ['da'] };
		const cleared = withFieldCleared(values, 'targetLanguages');
		expect(cleared.targetLanguages).toBeNull();
		expect(isSetAtLayer(cleared, 'targetLanguages')).toBe(false);
		// The original is untouched (immutable update).
		expect(values.targetLanguages).toEqual(['da']);
	});

	test('inheritedResolution prefers the active preset over globals', () => {
		const preset = { name: 'Balanced', values: { graceHoursEpisodes: 24 } };
		const fromPreset = inheritedResolution('graceHoursEpisodes', preset);
		expect(fromPreset.value).toBe(24);
		expect(fromPreset.provenance).toEqual({ layer: 'preset', sourceName: 'Balanced' });

		const fromGlobal = inheritedResolution('graceHoursMovies', preset);
		expect(fromGlobal.value).toBe(GLOBAL_DEFAULTS_DISPLAY.graceHoursMovies);
		expect(fromGlobal.provenance).toEqual({ layer: 'global' });

		const noPreset = inheritedResolution('dryRun', null);
		expect(noPreset.value).toBe(true);
		expect(noPreset.provenance.layer).toBe('global');
	});
});

describe('validation findings', () => {
	test('sortFindings orders critical → warn → info', () => {
		const sorted = sortFindings([
			{ code: 'a', severity: 'info', message: '', fixGuidance: '' },
			{ code: 'b', severity: 'critical', message: '', fixGuidance: '' },
			{ code: 'c', severity: 'warn', message: '', fixGuidance: '' }
		]);
		expect(sorted.map((finding) => finding.severity)).toEqual(['critical', 'warn', 'info']);
	});

	test('severity maps to badge variants', () => {
		expect(severityBadgeVariant('critical')).toBe('destructive');
		expect(severityBadgeVariant('warn')).toBe('secondary');
		expect(severityBadgeVariant('info')).toBe('outline');
	});
});

describe('labels', () => {
	test('pairLabel renders source → target and tolerates missing source', () => {
		expect(pairLabel('en', 'da')).toBe('en → da');
		expect(pairLabel(null, 'da')).toBe('da');
	});

	test('subtitleFlags renders forced/HI markers', () => {
		expect(subtitleFlags(false, false)).toBe('');
		expect(subtitleFlags(true, false)).toBe(' (forced)');
		expect(subtitleFlags(true, true)).toBe(' (forced, HI)');
	});
});
