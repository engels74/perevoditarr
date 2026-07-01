import { sveltekit } from '@sveltejs/kit/vite';
import UnoCSS from 'unocss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	// UnoCSS must run before sveltekit
	plugins: [UnoCSS(), sveltekit()],
	server: {
		proxy: {
			'/api': 'http://localhost:8000',
			'/sse': 'http://localhost:8000'
		}
	}
});
