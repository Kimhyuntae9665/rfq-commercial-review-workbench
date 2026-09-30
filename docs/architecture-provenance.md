# Architecture diagram provenance

Browser requests the loopback Python API. Frozen text/CSV quotes are held in JSON. Optional serial Ollama/Qwen proposals extract original source cells only. Human terms confirmation is required before CPU Fraction/integer scenario cost calculation; a separate reviewer acknowledges a specific packet. SQLite stores proposals, confirmations, active scenario, packets, reviews and audits. No supplier selection, purchase write, ERP or active n8n is depicted.

PNG is the inline README asset; SVG is the editable, fully embedded source. Six compact cards use actual technology glyphs where available. JSON braces are a locally authored functional symbol. Browser contains the JavaScript glyph for the vanilla client. The undirected Ollama/Qwen link denotes runtime/model association; dashed arrows are optional requests and returned proposals, not parallel GPU workers. The solid Python/SQLite arrow denotes server-owned record persistence, including subsequent review and audit records.

Inspected source commit: 1b59f976d2e78a1bf3469ac85a886b9b15af0a73. Diagram generation does not rerun a model or change benchmark results. Final PNG pixels and an actual 360px-wide CPU browser capture were visually inspected; technology labels are 28px in the 720px source (14px at 360px display).

Reference style: user-supplied synthetic-logo-rendering-compatibility-test.png, version1, 800x510, SHA256 c6ad5fda762ea72fb40020e56e6242d74b86c9adff00d95b8027f7981e250df8. The supported Library consumer download was completed with verified identity/version metadata on Linux and its actual pixels were viewed on the consumer workspace. Windows does not support the helper extended attributes; the original Linux materialization retains them. Its synthetic model topology is not copied.

## Glyph sources

- [python](https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/python.svg) · SHA256 ad9468e1c4903f73ae7eebfbe980f0f727a10db695be3d914e7d8bd25356a862 · Simple Icons community glyph; CC0 project source. Color and size adapted for documentation.
- [javascript](https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/javascript.svg) · SHA256 c9be35a7a861ebe80ae4ee706d05004b99ee59fc63db69da6dcc10776718434b · Simple Icons community glyph; CC0 project source. Color and size adapted for documentation.
- [sqlite](https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/sqlite.svg) · SHA256 71d4153bc9661dfe6b92dad70f737ec2b6c7c839311e502b4ca66fe664fe12b6 · Simple Icons community glyph; CC0 project source. Color and size adapted for documentation.
- [ollama](https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/ollama.svg) · SHA256 9c62bf0159ee96c8b58c86a732f33b002b4b3bb165ec86e8ecca51ad6a82dab6 · Simple Icons community glyph; CC0 project source. Color and size adapted for documentation.
- [qwen](https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/qwen.svg) · SHA256 36854c60b26bfa5a0cc0d4123727c0ef559efba6f129c0dfa623f3c443fe3e5b · Simple Icons community glyph; CC0 project source. Color and size adapted for documentation.

[Simple Icons CC0 license](https://github.com/simple-icons/simple-icons/blob/develop/LICENSE.md). Technology names and marks identify components, without implying endorsement. No image/font/CDN loads are needed for these diagrams.

## Inspected implementation

- rfq_review/core.py SHA256 7ec0b85834b10a3678cb0ef7f3f9c624b47a64712d9b264ca79761bf959735db
- rfq_review/extraction.py SHA256 82c67aada471fd49005b7569185302bbba411782419f532be5bde284580aa102
- rfq_review/calculation.py SHA256 36e01c6eb68fb8974538ea10d8ab2776d2e62f2c036f079ad3be9c520251c1c9
- rfq_review/llm.py SHA256 899b45a234a2f62c3756178d28d820e7ac05cb87341d5ef0cd9f3c5d78ba7489

Logo geometry: each downloaded glyph has viewBox 0 0 24 24. The embedded path uses one uniform scale in both axes, fitted to a 68x68 box and centered in its card. SQLite retains the feather proportions; no nested SVG sizing or anisotropic scaling is used. The JavaScript glyph is uniformly fitted to its separate yellow browser tile.
