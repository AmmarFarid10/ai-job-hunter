import {chromium,expect} from "../dashboard/node_modules/@playwright/test/index.mjs";
import {readFile} from "node:fs/promises";
import {parseEnv} from "node:util";
const origin="http://localhost:3000";
const {API_KEY:setupKey}=parseEnv(await readFile(".env","utf8"));
const browser=await chromium.launch({channel:"chrome",headless:true});
const context=await browser.newContext(),page=await context.newPage();
try{
 const status=await (await context.request.get(origin+"/api/session")).json();
 expect(status.google_available).toBe(true);
 await page.goto(origin);
 await expect(page.getByRole("button",{name:"Continue with Google"})).toBeVisible();
 await expect(page.getByRole("button",{name:"Continue with Google"})).toBeEnabled();
 const response=await context.request.post(origin+"/api/oauth/google",{headers:{origin},data:{mode:status.signup_available?"signup":"login"}});
 expect(response.status()).toBe(200);
 const result=await response.json(),url=new URL(result.url);
 expect(url.origin).toBe("https://accounts.google.com");
 expect(url.searchParams.get("redirect_uri")).toBe(origin+"/api/oauth/google/callback");
 expect(url.searchParams.get("code_challenge_method")).toBe("S256");
 expect(url.searchParams.get("scope")).toBe("openid email profile");
 const cookie=(await context.cookies()).find(c=>c.name==="job_hunter_google_state");
 expect(cookie?.httpOnly).toBe(true);
 await page.goto(result.url,{waitUntil:"domcontentloaded",timeout:45000});
 const text=await page.locator("body").innerText();
 const errors=["redirect_uri_mismatch","invalid_client","deleted_client","unauthorized_client"].filter(code=>text.includes(code));
 console.log(JSON.stringify({google_enabled:true,authorization_started:true,browser_state_cookie:true,google_page_opened:new URL(page.url()).hostname.endsWith("google.com"),configuration_errors:errors}));
 expect(errors).toEqual([]);
 console.log("No Google password entered, consent completed, or owner account created.");
}finally{await browser.close();}
