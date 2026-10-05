// Who is asking. Cloudflare Access stands in front of the site: it lets in
// only the email its policy names, and adds to every request it lets through
// the header Cf-Access-Authenticated-User-Email and a signed token
// (Cf-Access-Jwt-Assertion). A request without them did not pass Access and
// is refused.
//
// When the environment names the Access team (ACCESS_TEAM_DOMAIN, such as
// "myteam.cloudflareaccess.com") and the application's audience tag
// (ACCESS_AUD), the token is checked as well: signed by one of the team's
// keys, meant for this application, not expired, and for the same email.
// That protects the library even on an address that Access does not cover
// (a preview deployment), where anyone could send the header.
//
// DEV_USER (an email) lets every request in as that user, for running the
// site on one's own computer (wrangler pages dev). It is never set on the
// Cloudflare site itself.

const CERTS_SECONDS = 3600;     // how long the team's public keys are kept before fetching again
const LEEWAY = 60;              // seconds of clock difference allowed on the token's times

let certs = { team: null, keys: null, fetched: 0 };

function teamHost(domain) {
  return String(domain).trim().replace(/^https?:\/\//, "").replace(/\/+$/, "");
}

function base64url(text) {
  const b = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((text.length + 3) % 4));
  return Uint8Array.from(b, (c) => c.charCodeAt(0));
}

function jsonPart(text) {
  return JSON.parse(new TextDecoder().decode(base64url(text)));
}

// The team's public keys ({kid: CryptoKey}), fetched again after an hour or
// when a token names a key not seen yet.
async function teamKeys(host, kid) {
  const now = Date.now() / 1000;
  if (certs.team !== host || !certs.keys || now - certs.fetched > CERTS_SECONDS ||
      (kid && !(kid in certs.keys) && now - certs.fetched > 10)) {
    const res = await fetch(`https://${host}/cdn-cgi/access/certs`);
    if (!res.ok) throw new Error(`the Access keys could not be fetched (${res.status})`);
    const body = await res.json();
    const keys = {};
    for (const jwk of body.keys || []) {
      keys[jwk.kid] = await crypto.subtle.importKey(
        "jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
    }
    certs = { team: host, keys, fetched: now };
  }
  return certs.keys;
}

// The claims of an Access token when it is valid for this team and
// application, else null.
export async function verifyAccessJwt(token, teamDomain, audience) {
  const parts = String(token || "").split(".");
  if (parts.length !== 3) return null;
  let header, claims;
  try {
    header = jsonPart(parts[0]);
    claims = jsonPart(parts[1]);
  } catch (e) {
    return null;
  }
  if (header.alg !== "RS256") return null;
  const host = teamHost(teamDomain);
  const keys = await teamKeys(host, header.kid);
  const key = keys[header.kid];
  if (!key) return null;
  const signed = new TextEncoder().encode(parts[0] + "." + parts[1]);
  let good = false;
  try {
    good = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, base64url(parts[2]), signed);
  } catch (e) {
    return null;
  }
  if (!good) return null;
  const now = Date.now() / 1000;
  const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (!aud.includes(audience)) return null;
  if (typeof claims.exp !== "number" || claims.exp + LEEWAY < now) return null;
  if (typeof claims.nbf === "number" && claims.nbf - LEEWAY > now) return null;
  if (claims.iss && claims.iss !== `https://${host}`) return null;
  return claims;
}

// {email} of the person asking, or null when the request did not pass Access.
export async function authenticate(request, env) {
  if (env.DEV_USER) return { email: String(env.DEV_USER).toLowerCase() };
  const email = request.headers.get("Cf-Access-Authenticated-User-Email");
  if (!email) return null;
  if (env.ACCESS_TEAM_DOMAIN && env.ACCESS_AUD) {
    const token = request.headers.get("Cf-Access-Jwt-Assertion");
    if (!token) return null;
    let claims = null;
    try {
      claims = await verifyAccessJwt(token, env.ACCESS_TEAM_DOMAIN, env.ACCESS_AUD);
    } catch (e) {
      return null;
    }
    if (!claims || String(claims.email || "").toLowerCase() !== email.toLowerCase()) return null;
  }
  return { email: email.toLowerCase() };
}

// For the tests: forget the fetched keys.
export function forgetKeys() {
  certs = { team: null, keys: null, fetched: 0 };
}
