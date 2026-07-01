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
