# Third-party notices

This file records the direct runtime dependencies declared in `requirements.txt` for the current DUTPilot source. It is a release checklist input, not evidence that every required license text has already been bundled.

- pySerial 3.5 — BSD-3-Clause License, Copyright (c) 2001-2020 Chris Liechti.
- TFTPy 0.8.7 — MIT License, Copyright (c) 2010+ Michael P. Soulier.
- requests 2.x — Apache-2.0 License, Copyright 2019 Kenneth Reitz.
- requests-toolbelt 1.x — Apache-2.0 License.
- Paramiko 3.x — LGPL License.
- ping3 4.x — MIT License, Copyright (c) 2016 Kyan.
- pywifi 1.x — MIT License.
- configobj 5.x — BSD-3-Clause License.
- psutil 5.x–7.x — BSD-3-Clause License.
- openpyxl 3.x — MIT License, Copyright (c) 2010-2024 openpyxl.
- xlrd 2.x — BSD-3-Clause License, Copyright (c) 2005-2024 Python Excel Team.
- comtypes 1.x (Windows Wi-Fi dependency) — MIT License.
- websockets 15.0.1 (DingTalk Stream transport, Python 3.9 compatible) — BSD-3-Clause License.
- lark-oapi 1.7.5 (Feishu application-bot transport) — MIT License.
- PyCryptodome 3.23.0 (Feishu SDK dependency) — BSD-2-Clause / public-domain components; see its bundled LICENSE.rst.
- HTTPX 0.28.1 and httpcore 1.0.9 — BSD-3-Clause License.
- h11 0.16.0 — MIT License.
- AnyIO 4.12.1, exceptiongroup 1.3.1 and typing-extensions 4.16.0 — MIT License / Python Software Foundation License (typing-extensions).

The isolated slim packaging environment is pinned in `requirements-build.txt`, including transitive dependencies and the PyInstaller toolchain. Its actual installed versions and archive checks are recorded in `PACKAGING_REPORT.json` beside each build. The slim profile excludes NumPy/OpenBLAS, lxml and PyQt5; the current legacy power-test entry uses the existing headless compatibility layer. This does not remove features from the application source.

Before distributing `DUTPilot.exe`, the release operator must verify the exact installed dependency versions, PyInstaller's applicable notice requirements, and any bundled license texts. `SdmcUbusLib` and `test_boot_upgrade/TFTPD322_NEW` are repository reference assets; they are not covered by this runtime-dependency list and must be reviewed separately before any external redistribution.
