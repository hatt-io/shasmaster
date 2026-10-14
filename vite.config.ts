import { defineConfig } from 'vite';
export default defineConfig({publicDir:'web/public',server:{host:'127.0.0.1',port:5173,strictPort:true,proxy:{'/api':'http://127.0.0.1:9473'}},build:{outDir:'dist',target:'es2022'}});
