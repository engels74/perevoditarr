import extractorSvelte from '@unocss/extractor-svelte';
import presetWind4 from '@unocss/preset-wind4';
import { defineConfig, transformerVariantGroup } from 'unocss';
import presetAnimations from 'unocss-preset-animations';
import { presetShadcn } from 'unocss-preset-shadcn';

export default defineConfig({
	presets: [
		presetWind4({ preflights: { reset: true } }),
		presetAnimations(),
		presetShadcn({ color: 'zinc' })
	],
	extractors: [extractorSvelte()],
	transformers: [transformerVariantGroup()],
	theme: {
		// tweakcn modern-minimal type roles: Inter for the UI voice, JetBrains
		// Mono for the machine voice (traces, codes, scores). Vars in app.css.
		font: {
			sans: 'var(--font-sans)',
			mono: 'var(--font-mono)'
		}
	},
	content: {
		pipeline: {
			include: [
				/\.(svelte|[jt]sx?|html)($|\?)/,
				// shadcn/tailwind-variants class strings live in .ts modules too
				'src/**/*.{js,ts}'
			]
		}
	}
});
