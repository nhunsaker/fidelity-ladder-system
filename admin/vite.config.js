import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The demo build serves a different audience, and the browser tab is part of the surface:
// "Admin" in the title is operator vocabulary reaching a visitor before the page even paints.
const demoTitle = () => ({
  name: 'fls-demo-title',
  transformIndexHtml(html) {
    return process.env.VITE_FLS_MODE === 'demo'
      ? html.replace(/<title>[^<]*<\/title>/, '<title>Watch it build something</title>')
      : html
  },
})

export default defineConfig({
  plugins: [react(), demoTitle()],
  server: { port: 8792 },
})
