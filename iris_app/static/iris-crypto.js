// Iris message encryption, shared by the phone app and the JavaScript client.
//
// A tool and the phone share one 64-byte key, made by the tool and passed to the
// phone inside the pairing QR code. The first 32 bytes are the AES-256 key, the
// last 32 the HMAC-SHA256 key. A sealed message is
//   "v1." + base64url(iv[16] || AES-CBC ciphertext || HMAC(iv || ciphertext)[32])
// The same format is written by the C# and Python clients. The server never
// sees the key and stores sealed text only.
(function (root) {
  "use strict";
  const subtle = (root.crypto || {}).subtle;

  function toB64u(bytes) {
    let s = "";
    for (const b of bytes) s += String.fromCharCode(b);
    return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function fromB64u(text) {
    const s = atob(text.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((text.length + 3) % 4));
    const out = new Uint8Array(s.length);
    for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
    return out;
  }

  async function importKey(keyText) {
    const raw = fromB64u(keyText);
    if (raw.length !== 64) throw new Error("An Iris key is 64 bytes.");
    const aes = await subtle.importKey("raw", raw.slice(0, 32), { name: "AES-CBC" }, false, ["encrypt", "decrypt"]);
    const mac = await subtle.importKey("raw", raw.slice(32), { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
    return { aes, mac };
  }

  function newKey() {
    return toB64u(root.crypto.getRandomValues(new Uint8Array(64)));
  }

  async function seal(keys, value) {
    const iv = root.crypto.getRandomValues(new Uint8Array(16));
    const plain = new TextEncoder().encode(JSON.stringify(value));
    const ct = new Uint8Array(await subtle.encrypt({ name: "AES-CBC", iv }, keys.aes, plain));
    const signed = new Uint8Array(16 + ct.length);
    signed.set(iv, 0);
    signed.set(ct, 16);
    const tag = new Uint8Array(await subtle.sign("HMAC", keys.mac, signed));
    const all = new Uint8Array(signed.length + 32);
    all.set(signed, 0);
    all.set(tag, signed.length);
    return "v1." + toB64u(all);
  }

  async function open(keys, sealed) {
    if (typeof sealed !== "string" || !sealed.startsWith("v1.")) throw new Error("Not an Iris message.");
    const all = fromB64u(sealed.slice(3));
    if (all.length < 16 + 16 + 32) throw new Error("Message too short.");
    const signed = all.slice(0, all.length - 32);
    const tag = all.slice(all.length - 32);
    if (!(await subtle.verify("HMAC", keys.mac, tag, signed))) throw new Error("Message was changed or the key is wrong.");
    const plain = await subtle.decrypt({ name: "AES-CBC", iv: signed.slice(0, 16) }, keys.aes, signed.slice(16));
    return JSON.parse(new TextDecoder().decode(plain));
  }

  const api = { importKey, newKey, seal, open, toB64u, fromB64u };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.IrisCrypto = api;
})(typeof self !== "undefined" ? self : globalThis);
