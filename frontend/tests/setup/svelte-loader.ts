// bun:test preload — teaches Bun's runtime to compile .svelte / .svelte.ts files
// (runes) so state modules and components are testable without Vite.
//
// Components are compiled here directly (client-side, styles dropped — happy-dom
// renders no CSS) because bun-plugin-svelte's injected-CSS virtual modules lose
// their namespace prefix under `bun test` and crash the load. Registered before
// SveltePlugin so this loader wins for .svelte files; SveltePlugin still
// handles .svelte.ts modules. Pair with `bun test --conditions browser` so the
// svelte runtime resolves to its client entry.
import { plugin } from 'bun';
import { SveltePlugin } from 'bun-plugin-svelte';
import { compile } from 'svelte/compiler';

plugin({
	name: 'svelte-component-test-loader',
	setup(build) {
		build.onLoad({ filter: /\.svelte$/ }, async (args) => {
			const sourceText = await Bun.file(args.path).text();
			const result = compile(sourceText, {
				generate: 'client',
				dev: true,
				filename: args.path
			});
			return { contents: result.js.code, loader: 'ts' };
		});
	}
});

plugin(SveltePlugin({ development: true, forceSide: 'client' }));
