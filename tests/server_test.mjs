// Unit tests of the library server's sign-in check (server/auth.js) and of
// its refusal of requests that did not pass Cloudflare Access (server/app.js).
// Run with: node --test tests/server_test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { authenticate, forgetKeys, verifyAccessJwt } from "../server/auth.js";
import { handle } from "../server/app.js";

const TEAM = "myteam.cloudflareaccess.com";
const AUD = "a1b2c3";

function req(headers = {}, path = "/api/books") {
  return new Request("https://library.example" + path, { headers });
}

function b64url(bytes) {
  return Buffer.from(bytes).toString("base64").replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");
}

// A key pair standing in for the Access team's, served as its certs.
const pair = await crypto.subtle.generateKey(
  { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]),
    hash: "SHA-256" }, true, ["sign", "verify"]);
const other = await crypto.subtle.generateKey(
  { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]),
    hash: "SHA-256" }, true, ["sign", "verify"]);
const jwk = { ...(await crypto.subtle.exportKey("jwk", pair.publicKey)), kid: "k1", alg: "RS256" };
let fetched = 0;
globalThis.fetch = async (url) => {
  assert.equal(String(url), `https://${TEAM}/cdn-cgi/access/certs`);
  fetched++;
  return new Response(JSON.stringify({ keys: [jwk] }), { headers: { "content-type": "application/json" } });
};

async function token(claims, key = pair.privateKey, kid = "k1") {
  const now = Math.floor(Date.now() / 1000);
  const head = b64url(Buffer.from(JSON.stringify({ alg: "RS256", kid, typ: "JWT" })));
  const body = b64url(Buffer.from(JSON.stringify({
    aud: [AUD], email: "reader@example.com", iss: `https://${TEAM}`, iat: now, nbf: now, exp: now + 600,
    ...claims })));
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(head + "." + body));
  return head + "." + body + "." + b64url(new Uint8Array(sig));
}

const ACCESS = { ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD };

test("a request without the Access header is refused", async () => {
  assert.equal(await authenticate(req(), {}), null);
  const res = await handle(req(), {});
  assert.equal(res.status, 403);
  assert.match((await res.json()).error, /Cloudflare Access/);
});

test("every address of the library is refused without Access", async () => {
  for (const path of ["/api/books", "/api/books/" + "a".repeat(64) + "/pdf", "/api/other"]) {
    for (const method of ["GET", "PUT", "DELETE"]) {
      const res = await handle(new Request("https://library.example" + path, { method }), {});
      assert.equal(res.status, 403, method + " " + path);
    }
  }
});

test("the Access header lets the user in when no team is configured", async () => {
  const user = await authenticate(req({ "Cf-Access-Authenticated-User-Email": "Reader@Example.com" }), {});
  assert.deepEqual(user, { email: "reader@example.com" });
});

test("DEV_USER lets every request in, for local development", async () => {
  assert.deepEqual(await authenticate(req(), { DEV_USER: "dev@example.com" }), { email: "dev@example.com" });
});

test("with a team configured, the header alone is refused", async () => {
  forgetKeys();
  const r = req({ "Cf-Access-Authenticated-User-Email": "reader@example.com" });
  assert.equal(await authenticate(r, ACCESS), null);
  assert.equal((await handle(r, ACCESS)).status, 403);
});

test("a valid token for the same email is accepted", async () => {
  forgetKeys();
  fetched = 0;
  const r = req({ "Cf-Access-Authenticated-User-Email": "reader@example.com",
                  "Cf-Access-Jwt-Assertion": await token({}) });
  assert.deepEqual(await authenticate(r, ACCESS), { email: "reader@example.com" });
  // the keys are fetched once and kept
  await authenticate(r, ACCESS);
  assert.equal(fetched, 1);
});

test("tokens that are not right are refused", async () => {
  forgetKeys();
  const bad = {
    "another audience": await token({ aud: ["someone-else"] }),
    "expired": await token({ exp: Math.floor(Date.now() / 1000) - 3600 }),
    "not yet valid": await token({ nbf: Math.floor(Date.now() / 1000) + 3600 }),
    "another issuer": await token({ iss: "https://elsewhere.cloudflareaccess.com" }),
    "another email": await token({ email: "someone@example.com" }),
    "signed by another key": await token({}, other.privateKey),
    "an unknown key": await token({}, pair.privateKey, "k9"),
    "garbage": "a.b.c",
  };
  for (const [why, t] of Object.entries(bad)) {
    const r = req({ "Cf-Access-Authenticated-User-Email": "reader@example.com", "Cf-Access-Jwt-Assertion": t });
    assert.equal(await authenticate(r, ACCESS), null, why);
  }
  assert.equal(await verifyAccessJwt("only.two", TEAM, AUD), null);
});
