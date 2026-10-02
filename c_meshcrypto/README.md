# meshcrypto

MicroPython bindings (`modmeshcrypto.c`) for MeshCore's Ed25519/X25519 code:
`create_keypair`, `derive_pub`, `sign`, `verify` and `key_exchange`, with MeshCore's 64-byte
private-key format.

## Origin of `ed25519/`

- Copied unchanged from MeshCore, `lib/ed25519` (https://github.com/meshcore-dev/MeshCore,
  commit a366955), except `seed.c`, which is left out (built with `ED25519_NO_SEED`).
- MeshCore's copy is an **altered version** of orlp/ed25519 (https://github.com/orlp/ed25519):
  - the header is renamed to `ed_25519.h`;
  - `ed25519_derive_pub()` is added.

  orlp/ed25519 is under the zlib licence in `ed25519/license.txt`. `ed25519/sha512.c` is
  LibTomCrypt code (public domain).
- MeshCore's licence:

```
MIT License

Copyright (c) 2025 Scott Powell / rippleradios.com

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.```
