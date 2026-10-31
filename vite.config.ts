import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // 浏览器端只暴露 VITE_ 前缀变量，HYPER3D_API_KEY 不会进前端包
  envPrefix: 'VITE_',
})
