import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      // `injectManifest` rather than `generateSW`: the service worker is our own file
      // (`src/sw.ts`), and the plugin only substitutes the list of precached assets into
      // it. ADR-0006 originally said "generated"; building it showed that the generated
      // mode leaves nowhere to hand-write the push handling the same sentence asks for,
      // and the ADR carries the refinement.
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      injectManifest: {
        // The app shell, and nothing that comes from the API.
        globPatterns: ['**/*.{js,css,html,svg,png,webmanifest}'],
      },

      // A new version waits rather than reloading the phone under a Parent's hands: a
      // half-written Answer outlives a deploy, and the update takes over the next time
      // the app is opened from the home screen.
      registerType: 'prompt',
      // `src/main.tsx` registers it out loud instead.
      injectRegister: null,

      manifest: {
        name: 'Kidiary',
        short_name: 'Kidiary',
        description: 'Das gemeinsame Tagebuch über ein Kind.',
        lang: 'de',
        // Both are '/' because the app is the whole origin (ADR-0005): the Pi serves
        // nothing else on its tailnet hostname.
        start_url: '/',
        scope: '/',
        // Pins the app's identity to the origin rather than to `start_url`, so a later
        // start URL does not install as a second app beside the first.
        id: '/',
        // What makes the installed app open without browser chrome.
        display: 'standalone',
        // The icon's own two colours, so the Android splash screen — which is the icon
        // on this background — reads as one piece with the tile that was just tapped.
        // They are not the app's colours: the app has none, and follows the phone's
        // light/dark setting instead (`index.css`). These two are the only fixed
        // colours in it, and they belong to the notebook rather than to any screen.
        background_color: '#f2e8de',
        theme_color: '#c8643c',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          // Drawn small enough to survive a launcher's mask; see `icons/icon-maskable.svg`.
          {
            src: '/icon-maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
    }),
  ],
  server: {
    // `npm run dev` serves the frontend; the API answers on its own port.
    proxy: { '/api': 'http://localhost:8000' },
  },
})
