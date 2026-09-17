# Vamp Fatale Bard Kill-Time Analysis

This measures death time against each Bard's actual final Battle Voice/Radiant Finale window, not merely `duration % 120`.

## Summary

- Parses analyzed: 40
- Parses with a resolved final burst anchor: 40
- Median death after final buff anchor: 22.026s
- Range: 8.337s to 78.305s

## Distribution

| Window | Parses |
|---|---:|
| <20s | 14 |
| 20-30s | 13 |
| 31-45s | 8 |
| 46-60s | 2 |
| 61+s | 3 |
| missing | 0 |

## Broad timing-band aDPS

| Death after final anchor | Parses | Mean aDPS |
|---|---:|---:|
| <20s | 14 | 33927.7 |
| 20-30s | 13 | 34240.3 |
| 31+s | 13 | 34074.4 |

## Parse-level timings

| Rank | Player | Duration | Final BV | Final RF | Death after anchor | aDPS | rDPS |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | Hide Elder | 509.942 | 489.128 | 489.802 | 20.814 | 35131.971 | 41540.641 |
| 2 | Lefiena Riliales | 512.738 | 490.543 | 491.213 | 22.195 | 34915.710 | 40105.937 |
| 3 | Sakura Fleur | 532.070 | 492.849 | 493.521 | 39.221 | 34858.860 | 40928.248 |
| 4 | Ara Ban | 507.403 | 487.051 | 487.720 | 20.352 | 34748.518 | 43365.153 |
| 5 | Anonymous | 502.584 | 485.003 | 485.581 | 17.581 | 34644.589 | 40252.007 |
| 6 | Mee Anist | 507.728 | 485.871 | 487.300 | 21.857 | 34432.713 | 40685.700 |
| 7 | Hemera Mictlan | 550.583 | 491.287 | 492.001 | 59.296 | 34426.507 | 38972.993 |
| 8 | Elessar Kairi | 520.358 | 490.886 | 490.131 | 30.227 | 34416.824 | 40330.655 |
| 9 | Nihilis Nil | 525.928 | 487.540 | 486.873 | 39.055 | 34394.724 | 39107.479 |
| 10 | Miliam Guropius | 514.443 | 486.859 | 488.864 | 27.584 | 34363.492 | 40802.782 |
| 11 | Lancia Stratos | 522.018 | 487.594 | 488.264 | 34.424 | 34359.136 | 39480.348 |
| 12 | Lavshuca Poirot | 506.371 | 494.112 | 492.058 | 14.313 | 34348.673 | 39890.809 |
| 13 | Vincent Kline | 527.533 | 492.703 | 494.356 | 34.830 | 34294.171 | 38933.371 |
| 14 | Haase Latreia | 510.870 | 488.871 | 488.205 | 22.665 | 34263.931 | 41262.840 |
| 15 | Miroq Ray | 500.986 | 490.914 | 489.088 | 11.898 | 34243.102 | 39703.005 |
| 16 | Torha Nox | 510.869 | 490.223 | 489.561 | 21.308 | 34220.372 | 40110.081 |
| 17 | Nalshe Falkner | 508.654 | 487.661 | 485.608 | 23.046 | 34156.325 | 39454.379 |
| 18 | Rhaygea Menphina | 501.573 | 489.388 | 488.322 | 13.251 | 34123.078 | 39687.061 |
| 19 | Mao Mizuno | 510.002 | 487.089 | 487.755 | 22.913 | 34036.286 | 39134.215 |
| 20 | Haruta Natsuki | 506.222 | 491.367 | 491.991 | 14.855 | 34020.901 | 39587.386 |
| 21 | Baru Hachiware | 557.573 | 488.553 | 486.866 | 70.707 | 33944.877 | 38841.965 |
| 22 | Evans Mm | 506.191 | 487.776 | 487.107 | 19.084 | 33912.735 | 40073.183 |
| 23 | I'tuva Yatra | 506.136 | 490.701 | 490.034 | 16.102 | 33896.544 | 40634.788 |
| 24 | Ohana Matsumae | 511.822 | 492.389 | 490.473 | 21.349 | 33868.240 | 41109.350 |
| 25 | Yuki Ortiz | 543.700 | 490.405 | 489.828 | 53.872 | 33851.423 | 38490.507 |
| 26 | Zaps Bleps | 505.126 | 488.413 | 486.945 | 18.181 | 33765.127 | 40236.920 |
| 27 | Chloe Kisaka | 568.601 | 490.966 | 490.296 | 78.305 | 33755.437 | 37793.198 |
| 28 | Charlie Knight | 508.814 | 490.216 | 490.840 | 18.598 | 33744.390 | 39443.853 |
| 29 | Areko Nariva | 521.626 | 487.461 | 485.812 | 35.814 | 33739.865 | 39225.928 |
| 30 | Isalania Oarburghe | 517.009 | 490.817 | 488.412 | 28.597 | 33707.709 | 39629.787 |
| 31 | Ayaka Taki | 496.107 | 487.770 | 488.393 | 8.337 | 33706.373 | 40351.857 |
| 32 | King's Row | 503.255 | 494.814 | 493.209 | 10.046 | 33670.683 | 38823.606 |
| 33 | Haggis Mchaggis | 511.230 | 490.046 | 487.733 | 23.497 | 33660.112 | 39916.256 |
| 34 | Aslan Miller | 503.526 | 490.643 | 489.973 | 13.553 | 33659.398 | 39804.016 |
| 35 | Smol Mayar | 559.472 | 490.671 | 490.046 | 69.426 | 33647.458 | 38718.332 |
| 36 | Kou Koko | 528.877 | 488.235 | 486.541 | 42.336 | 33641.508 | 39194.268 |
| 37 | Rindera Graem | 509.040 | 492.153 | 490.413 | 18.627 | 33640.294 | 39640.954 |
| 38 | Aisaka Sora | 527.477 | 488.732 | 487.306 | 40.171 | 33635.950 | 39164.721 |
| 39 | Arsye Monat | 509.670 | 487.822 | 489.250 | 21.848 | 33617.982 | 40458.438 |
| 40 | Choco Madeleine | 503.482 | 488.731 | 488.061 | 15.421 | 33611.966 | 38802.169 |

## Interpretation guardrails

- The anchor is the earlier of the Bard's final Battle Voice and Radiant Finale casts.
- This identifies burst-window truncation/dilution; it does not by itself prove causality.
- Final recommendations must be merged with action timelines, party buffs, RNG, and encounter downtime.
- Anonymous/private reports can be unavailable or actor resolution can be ambiguous; failures are retained separately.
