// bun:test preload — teaches Bun's runtime to compile .svelte / .svelte.ts files
// (runes) so state modules and components are testable without Vite.
import { plugin } from 'bun';
import { SveltePlugin } from 'bun-plugin-svelte';

plugin(SveltePlugin({ development: true }));
