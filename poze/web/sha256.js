// SHA-256 incremental: crypto.subtle cere tot fișierul în memorie, iar un clip are câțiva GB.
const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
]);

export class Sha256 {
  constructor() {
    this.h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19]);
    this.w = new Uint32Array(64);
    this.buf = new Uint8Array(64);
    this.used = 0;
    this.total = 0;
  }

  update(data) {
    let i = 0;
    this.total += data.length;
    if (this.used) {
      const n = Math.min(64 - this.used, data.length);
      this.buf.set(data.subarray(0, n), this.used);
      this.used += n;
      i = n;
      if (this.used < 64) return this;
      this.block(this.buf, 0);
      this.used = 0;
    }
    for (; i + 64 <= data.length; i += 64) this.block(data, i);
    if (i < data.length) {
      this.buf.set(data.subarray(i), 0);
      this.used = data.length - i;
    }
    return this;
  }

  hex() {
    const bits = this.total * 8;
    const pad = new Uint8Array((this.used < 56 ? 64 : 128) - this.used);
    pad[0] = 0x80;
    const v = new DataView(pad.buffer);
    v.setUint32(pad.length - 8, Math.floor(bits / 2 ** 32));
    v.setUint32(pad.length - 4, bits >>> 0);
    this.total -= pad.length;  // update() îl adună la loc
    this.update(pad);
    return Array.from(this.h, (x) => x.toString(16).padStart(8, '0')).join('');
  }

  block(d, o) {
    const w = this.w;
    for (let t = 0; t < 16; t++, o += 4) w[t] = (d[o] << 24) | (d[o + 1] << 16) | (d[o + 2] << 8) | d[o + 3];
    for (let t = 16; t < 64; t++) {
      const a = w[t - 15], b = w[t - 2];
      const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
      const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
      w[t] = (w[t - 16] + s0 + w[t - 7] + s1) | 0;
    }
    let [a, b, c, e, f, g, h, dd] = [this.h[0], this.h[1], this.h[2], this.h[4], this.h[5], this.h[6], this.h[7], this.h[3]];
    for (let t = 0; t < 64; t++) {
      const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
      const t1 = (h + S1 + ((e & f) ^ (~e & g)) + K[t] + w[t]) | 0;
      const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
      const t2 = (S0 + ((a & b) ^ (a & c) ^ (b & c))) | 0;
      h = g; g = f; f = e; e = (dd + t1) | 0; dd = c; c = b; b = a; a = (t1 + t2) | 0;
    }
    const H = this.h;
    H[0] += a; H[1] += b; H[2] += c; H[3] += dd; H[4] += e; H[5] += f; H[6] += g; H[7] += h;
  }
}

/** Amprenta unui File, citit în bucăți de 4 MiB; [onProgress] primește octeții citiți. */
export async function hashFile(file, onProgress = () => {}) {
  if (file.size <= 256 * 1024 * 1024 && globalThis.crypto?.subtle) {  // nativ, de ~10 ori mai repede
    const d = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
    onProgress(file.size);
    return Array.from(new Uint8Array(d), (b) => b.toString(16).padStart(2, '0')).join('');
  }
  const s = new Sha256();
  const step = 4 * 1024 * 1024;
  for (let at = 0; at < file.size; at += step) {
    s.update(new Uint8Array(await file.slice(at, at + step).arrayBuffer()));
    onProgress(Math.min(at + step, file.size));
  }
  return s.hex();
}
