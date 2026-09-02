# FlashPilot first-drive analyzer

Read-only route analyzer for the Lightning vehicle-test sequence. It accepts a
Connect route/segment range, URL, or local `rlog`/`qlog`. Full `rlog` is strongly
recommended: `qlog` may omit raw CAN confidence, sendcan path-angle, or detailed
transition data, and the report marks those fields unavailable rather than
inventing values.

```bash
cd /data/openpilot
python3 openpilot/tools/analysis/flashpilot_first_drive.py \
  --route 'A=7d40cff3aab1401c/ROUTE_ID/0:10' \
  --json /tmp/flashpilot-A.json
```

Comparison mode analyzes each route independently and prints a compact table:

```bash
python3 openpilot/tools/analysis/flashpilot_first_drive.py --compare \
  --route 'A=/logs/a-rlog.zst' \
  --route 'B2+C=/logs/b2c-rlog.zst'
```

State definitions:

- **A:** path-angle ON, vision-only longitudinal.
- **B2+C:** path-angle ON, RB5T adapter ON, shadow ON; normal second test.
- **B2:** adapter ON, shadow OFF; diagnostic fallback, not a required separate drive.
- **C-shadow:** historical alias for B2+C, still accepted. All labels are retained verbatim.

The analyzer does not write Params, start replay/control processes, or modify
the vehicle. RB5T confidence is decoded from raw `Steer_Assist_Data` (`0x3D7`),
and commanded path angle from raw `LateralMotionControl2` sendcan (`0x3D6`).
