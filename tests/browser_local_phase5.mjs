// Read-only local smoke check: leaves first-owner signup for the actual user.
import { chromium, expect } from "../dashboard/node_modules/@playwright/test/index.mjs";
import { readFile, mkdir } from "node:fs/promises";
import { parseEnv } from "node:util";
const {API_KEY:key}=parseEnv(await readFile(".env","utf8"));
const response=await fetch("http://localhost:8000/api/v1/auth/status");
const status=await response.json();if(!response.ok)throw new Error("Authentication API unavailable");
const items=await (await fetch("http://localhost:8000/api/v1/discovery/items?provider=linkedin-tavily&limit=100",{headers:{"X-API-Key":key}})).json();
expect(items.length).toBeGreaterThan(0);
const browser=await chromium.launch({channel:"chrome",headless:true});
const context=await browser.newContext({viewport:{width:1100,height:1000}}),page=await context.newPage();
try{
 await page.goto("http://localhost:3000");
 await expect(page.getByLabel("Email",{exact:true})).toBeVisible();
 await expect(page.getByLabel("Password",{exact:true})).toBeVisible();
 await expect(page.getByLabel("Workspace setup key")).toHaveCount(0);
 expect((await context.request.get("http://localhost:3000/api/backend/candidates")).status()).toBe(401);
 await mkdir("storage/phase5_browser",{recursive:true});
 await page.screenshot({path:"storage/phase5_browser/account_setup.png",fullPage:true});
 console.log("Local dashboard passed: account signup/login form, protected proxy, persisted LinkedIn leads. No real owner account or password created.");
}finally{await browser.close();}
