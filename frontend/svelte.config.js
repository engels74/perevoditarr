import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		// Static SPA served same-origin by the Litestar backend (ADR-0004).
		adapter: adapter({ fallback: 'index.html' })
	},
	vitePlugin: {
		dynamicCompileOptions({ filename }) {
			// Force runes mode for project code; node_modules libraries keep auto-detect.
			if (!filename.split(/[/\\]/).includes('node_modules')) {
				return { runes: true };
			}
		}
	}
};

export default config;
