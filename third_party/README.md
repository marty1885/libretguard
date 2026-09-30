# Test dependencies

- `stb/stb_image.h`: stb_image v2.30 from [nothings/stb](https://github.com/nothings/stb), dual MIT/public-domain license in the header. SHA-256: `594c2fe35d49488b4382dbfaec8f98366defca819d916ac95becf3e75f4200b3`.
- `qoi/qoi.h`: upstream [phoboslab/qoi](https://github.com/phoboslab/qoi), MIT license in the header. SHA-256: `7de6fca1a285b1c20d38f2723dec8b774eb9f144edb9710800a95feeea09375a`.
- `jsmn/jsmn.h`: [zserge/jsmn](https://github.com/zserge/jsmn/blob/25647e692c7906b96ffd2b05ca54c097948e879c/jsmn.h), pinned commit `25647e692c7906b96ffd2b05ca54c097948e879c`, MIT license in the header. SHA-256: `c04533e9181e1e33baceb0f55ac449b05145bb936e8c68cc77dfe0d8277514fb`. Benchmarks enable `JSMN_STRICT`; jsmn is a tokenizer, not a complete JSON grammar validator.
- `stb/stb_sprintf.h`: stb_sprintf v1.10 from [nothings/stb](https://github.com/nothings/stb/blob/2c980bb59875b0d32144a71867fbdebb2f77cd20/stb_sprintf.h), pinned commit `2c980bb59875b0d32144a71867fbdebb2f77cd20`, dual MIT/public-domain license in the header. SHA-256: `e0b8c56e1084602290b9a17ef59f429b5293deb8cb9d8b0f20a14abc39b56520`.

These headers are used only by the benchmark and compatibility tests.
