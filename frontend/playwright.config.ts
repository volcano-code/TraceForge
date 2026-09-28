import {defineConfig} from '@playwright/test';
const ci = Boolean(process.env.CI);
if (ci) process.env.TF_REVIEWER_TOKEN='e2e-only-reviewer-not-a-real-secret';
export default defineConfig({
 testDir:'e2e',forbidOnly:ci,retries:0,workers:1,
 reporter:[['list'],['junit',{outputFile:'test-results/e2e.xml'}]],
 use:{baseURL:process.env.TF_WEB_URL||'http://127.0.0.1:5173',trace:'retain-on-failure'},
 webServer:ci?[
  {command:'python ../scripts/ci_services.py',url:'http://127.0.0.1:8000/healthz',timeout:60000,reuseExistingServer:false},
  {command:'npm run dev -- --strictPort',url:'http://127.0.0.1:5173',timeout:60000,reuseExistingServer:false}
 ]:undefined,
});
