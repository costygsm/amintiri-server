// node tests/web/sha256.test.mjs — compară cu node:crypto pe lungimi la marginea blocurilor
import { createHash, randomBytes } from 'node:crypto';
import { Sha256 } from '../../poze/web/sha256.js';

let bad = 0;
const lens = [0, 1, 3, 55, 56, 57, 63, 64, 65, 119, 120, 127, 128, 1000, 100_003];
for (const n of lens) {
  const data = randomBytes(n);
  const want = createHash('sha256').update(data).digest('hex');
  // dintr-o bucată și pe bucăți de mărimi ciudate
  const one = new Sha256().update(data).hex();
  const s = new Sha256();
  for (let i = 0, k = 1; i < n; i += k, k = (k * 7) % 97 + 1) s.update(data.subarray(i, i + k));
  const parts = s.hex();
  if (one !== want || parts !== want) { bad++; console.log('GREȘIT la', n); }
}
const t = Date.now();
const big = randomBytes(64 * 1024 * 1024);
new Sha256().update(big).hex();
console.log(bad ? `${bad} greșite` : `${lens.length} lungimi OK`, `· ${(64 / ((Date.now() - t) / 1000)).toFixed(0)} MB/s`);
process.exit(bad ? 1 : 0);
