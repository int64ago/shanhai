import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // 浏览器端只暴露 VITE_ 前缀变量，HYPER3D_API_KEY 不会进前端包
  envPrefix: 'VITE_',
  build: {
    chunkSizeWarningLimit: 1100,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: 'three', test: /node_modules[\\/]three[\\/]/ },
            { name: 'r3f', test: /node_modules[\\/](@react-three|postprocessing|three-stdlib)[\\/]/ },
            { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler|zustand)[\\/]/ },
          ],
        },
      },
    },
  },
})
