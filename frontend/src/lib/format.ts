// Small display helpers shared by the M0 pages.

import type { SubtitleRead, WantedRead } from '$lib/api/types';
import type { BadgeVariant } from '$lib/components/ui/badge';

export function formatDateTime(iso: string | null | undefined): string {
	if (!iso) {
		return '—';
	}
	const date = new Date(iso);
	return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString();
}

export function formatLatency(ms: number | null | undefined): string {
	return ms === null || ms === undefined ? '—' : `${ms} ms`;
}

export function healthBadgeVariant(status: string | null | undefined): BadgeVariant {
	switch (status) {
		case 'ok':
			return 'default';
		case 'degraded':
			return 'secondary';
		case 'unreachable':
			return 'destructive';
		default:
			return 'outline';
	}
}

export function severityBadgeVariant(severity: string): BadgeVariant {
	switch (severity) {
		case 'critical':
			return 'destructive';
		case 'warn':
			return 'secondary';
		default:
			return 'outline';
	}
}

export function subtitleLabel(subtitle: SubtitleRead): string {
	const flags = [
		subtitle.forced ? 'forced' : null,
		subtitle.hi ? 'hi' : null,
		subtitle.isEmbedded ? 'emb' : null
	].filter(Boolean);
	return flags.length > 0 ? `${subtitle.language} (${flags.join(', ')})` : subtitle.language;
}

export function wantedLabel(wanted: WantedRead): string {
	const flags = [wanted.forced ? 'forced' : null, wanted.hi ? 'hi' : null].filter(Boolean);
	return flags.length > 0 ? `${wanted.language} (${flags.join(', ')})` : wanted.language;
}
