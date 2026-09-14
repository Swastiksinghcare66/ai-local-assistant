# SIA firmware market-validation gates

The source is production-oriented. These gates must pass before calling the device commercially production-ready.

## Gate A — Electrical / audio integrity
- 0 relay single-pole mismatches across 10,000 route changes
- no BTL output tied to ground
- no speaker pop exceeding product SPL limit
- no I2S framing errors in 24 h soak
- no USB buffer overruns in 24 h soak

## Gate B — AEC
Measure with final enclosure:
- ERLE during far-end-only playback
- residual echo during double talk
- near-end speech attenuation
- convergence after route/session changes
- performance at multiple speaker volumes

Do not increase AEC NLP from NORMAL to AGGR until double-talk speech damage has been measured.

## Gate C — STT
Compare Parakeet WER:
- raw mic
- old PC V3
- ESP-SR AFE output
- ESP-SR + light PC post-stage

Conditions:
- quiet
- fan/AC
- TV/background speech
- near field
- far field
- TTS playing while user interrupts

The lowest real WER wins; "cleaner sounding" audio is not the objective.

## Gate D — Reliability
- 1000 boot cycles
- USB unplug/replug
- host crash/restart
- TTS packet loss
- malformed packet/CRC fuzzing
- brownout
- relay switching under idle and load
- 24–72 hour soak

## Gate E — Product security
Only after firmware is frozen:
- unique device identity
- secure boot
- flash encryption
- signed OTA
- anti-rollback
- manufacturing key provisioning
- no hard-coded secrets

Do not burn irreversible security eFuses during development.

## Gate F — Regulatory / manufacturing
Depends on country/market:
- EMC/EMI
- ESD
- radio certification for Wi-Fi/BLE
- battery and charger safety
- transport tests for lithium cells
- thermal / flammability requirements
- production audio fixture and golden-unit limits
