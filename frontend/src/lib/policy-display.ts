// Pure cascade-display logic (P2-T6): provenance chips, override-layer
// resolution, and validation-finding presentation. Kept free of Svelte so
// bun:test covers it without a DOM.

import type { EffectivePolicyRead, PolicyFindingRead, PolicyValuesDto } from '$lib/api/types';

export type ProvenanceLayer = 'global' | 'preset' | 'profile' | 'override';

export interface ProvenanceLike {
	layer: ProvenanceLayer;
	sourceId?: string | null;
	sourceName?: string | null;
}

export interface ProvenanceChip {
	layer: ProvenanceLayer;
	/** Short chip text, e.g. "preset · Balanced" or "global". */
	label: string;
	/** Hover/long text, e.g. "Inherited from preset Balanced — override?". */
	explanation: string;
	/** True when the value is not set at the most specific layer available. */
	inherited: boolean;
}

const LAYER_NOUN: Record<ProvenanceLayer, string> = {
	global: 'global defaults',
	preset: 'preset',
	profile: 'profile',
	override: 'item override'
};

// Chart-scale CSS variables give each layer a stable hue in both modes.
export const LAYER_COLOR_VAR: Record<ProvenanceLayer, string> = {
	global: 'var(--muted-foreground)',
	preset: 'var(--chart-1)',
	profile: 'var(--chart-3)',
	override: 'var(--chart-5)'
};

export function provenanceChip(provenance: ProvenanceLike): ProvenanceChip {
	const named =
		provenance.layer === 'preset' || provenance.layer === 'profile' ? provenance.sourceName : null;
	const label = named ? `${provenance.layer} · ${named}` : provenance.layer;
	const noun = named ? `${LAYER_NOUN[provenance.layer]} ${named}` : LAYER_NOUN[provenance.layer];
	const inherited = provenance.layer !== 'override';
	return {
		layer: provenance.layer,
		label,
		explanation: inherited ? `Inherited from ${noun} — override?` : 'Set directly on this item',
		inherited
	};
}

/** The policy fields the cascade editor exposes, in display order. */
export interface PolicyFieldSpec {
	key: keyof PolicyValuesDto;
	label: string;
	kind: 'languages' | 'boolean' | 'hours' | 'weights';
	help: string;
}

export const POLICY_FIELDS: PolicyFieldSpec[] = [
	{
		key: 'dryRun',
		label: 'Dry run',
		kind: 'boolean',
		help: 'Plan and explain, but never dispatch'
	},
	{
		key: 'targetLanguages',
		label: 'Target languages',
		kind: 'languages',
		help: 'Languages to translate into (Bazarr code2)'
	},
	{
		key: 'sourcePreferences',
		label: 'Source preferences',
		kind: 'languages',
		help: 'Ordered source election — first eligible wins'
	},
	{
		key: 'allowHiSource',
		label: 'Allow HI sources',
		kind: 'boolean',
		help: 'Hearing-impaired subtitles may serve as sources'
	},
	{
		key: 'allowForcedSource',
		label: 'Allow forced sources',
		kind: 'boolean',
		help: 'Forced subtitles may serve as sources'
	},
	{
		key: 'translateHiTargets',
		label: 'Translate HI targets',
		kind: 'boolean',
		help: 'Plan hearing-impaired wanted subtitles'
	},
	{
		key: 'translateForcedTargets',
		label: 'Translate forced targets',
		kind: 'boolean',
		help: 'Plan forced wanted subtitles'
	},
	{
		key: 'graceHoursEpisodes',
		label: 'Grace period — episodes (h)',
		kind: 'hours',
		help: 'Wait for real subtitles before translating'
	},
	{
		key: 'graceHoursMovies',
		label: 'Grace period — movies (h)',
		kind: 'hours',
		help: 'Wait for real subtitles before translating'
	},
	{
		key: 'skipIfEmbeddedTarget',
		label: 'Skip when embedded target exists',
		kind: 'boolean',
		help: 'An embedded track in the target language satisfies the want'
	},
	{
		key: 'skipUnmonitored',
		label: 'Skip unmonitored',
		kind: 'boolean',
		help: 'Ignore unmonitored items'
	}
];

/**
 * Which effective value backs a given editor field. EffectivePolicyRead keys
 * match PolicyValuesDto keys except that every entry is a Resolved wrapper.
 */
export function resolvedFor(
	effective: EffectivePolicyRead,
	key: keyof PolicyValuesDto
): { value: unknown; provenance: ProvenanceLike } | null {
	const record = effective as unknown as Record<
		string,
		{ value: unknown; provenance: ProvenanceLike } | undefined
	>;
	return record[key] ?? null;
}

/**
 * A layer's editor shows a field as "overridden here" when the stored layer
 * values carry it explicitly (null/undefined means inherit).
 */
export function isSetAtLayer(values: PolicyValuesDto, key: keyof PolicyValuesDto): boolean {
	const value = values[key];
	return value !== null && value !== undefined;
}

/** Clearing an override = writing null so the parent layer shows through. */
export function withFieldCleared(
	values: PolicyValuesDto,
	key: keyof PolicyValuesDto
): PolicyValuesDto {
	return { ...values, [key]: null };
}

/**
 * Display mirror of the backend's safe-by-default global layer
 * (`policy.resolver.GLOBAL_DEFAULTS`) — used only to preview inherited values
 * in editors; the backend resolver remains the source of truth.
 */
export const GLOBAL_DEFAULTS_DISPLAY: Required<{
	[K in keyof Omit<PolicyValuesDto, 'priorityWeights'>]: NonNullable<PolicyValuesDto[K]>;
}> = {
	dryRun: true,
	targetLanguages: [],
	sourcePreferences: ['en'],
	allowHiSource: true,
	allowForcedSource: false,
	translateHiTargets: false,
	translateForcedTargets: false,
	graceHoursEpisodes: 72,
	graceHoursMovies: 168,
	skipIfEmbeddedTarget: false,
	skipUnmonitored: true
};

/**
 * What a profile-layer field inherits when unset: the active preset's value
 * when the preset sets it, else the global default.
 */
export function inheritedResolution(
	key: keyof Omit<PolicyValuesDto, 'priorityWeights'>,
	activePreset: { name: string; values: PolicyValuesDto } | null
): { value: unknown; provenance: ProvenanceLike } {
	const presetValue = activePreset?.values[key];
	if (activePreset && presetValue !== null && presetValue !== undefined) {
		return {
			value: presetValue,
			provenance: { layer: 'preset', sourceName: activePreset.name }
		};
	}
	return { value: GLOBAL_DEFAULTS_DISPLAY[key], provenance: { layer: 'global' } };
}

export type FindingSeverity = PolicyFindingRead['severity'];

export const SEVERITY_ORDER: FindingSeverity[] = ['critical', 'warn', 'info'];

export function sortFindings(findings: PolicyFindingRead[]): PolicyFindingRead[] {
	return [...findings].sort(
		(a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity)
	);
}

export function severityBadgeVariant(
	severity: FindingSeverity
): 'destructive' | 'secondary' | 'outline' {
	if (severity === 'critical') {
		return 'destructive';
	}
	return severity === 'warn' ? 'secondary' : 'outline';
}

/** "en → da" pair label used across plan, history, and the explainer. */
export function pairLabel(source: string | null, target: string): string {
	return source ? `${source} → ${target}` : target;
}

export function subtitleFlags(forced: boolean, hi: boolean): string {
	const flags = [forced ? 'forced' : null, hi ? 'HI' : null].filter(Boolean);
	return flags.length > 0 ? ` (${flags.join(', ')})` : '';
}
