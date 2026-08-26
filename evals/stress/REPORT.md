# Stress test — Estimador CAG (Session 06)

Informe generado automáticamente desde `results.csv` (240 filas de turno OK).

## Tabla resumen

| Escenario | Adjunto | P50 latency (ms) | P95 latency (ms) | Total cost (USD) | Exact cache hit | Semantic cache hit | Mean recall |
|---|---|---:|---:|---:|---:|---:|---:|
| baseline | 0kb | 1800 | 2520 | 0.0094 | 0% | 0% | 1.0 |
| baseline | 100kb | 8280 | 9000 | 0.0342 | 0% | 0% | 1.0 |
| baseline | 20kb | 5040 | 5760 | 0.0218 | 0% | 0% | 1.0 |
| baseline | 50kb | 6660 | 7380 | 0.028 | 0% | 0% | 1.0 |
| baseline | 5kb | 3420 | 4140 | 0.0156 | 0% | 0% | 1.0 |
| constraint_locked | 0kb | 32040 | 33120 | 0.2084 | 0% | 0% | 0.733 |
| constraint_locked | 100kb | 42840 | 43920 | 0.2773 | 0% | 0% | 0.733 |
| constraint_locked | 20kb | 37440 | 38520 | 0.2428 | 0% | 0% | 0.733 |
| constraint_locked | 50kb | 40140 | 41220 | 0.2601 | 0% | 0% | 0.733 |
| constraint_locked | 5kb | 34740 | 35820 | 0.2256 | 0% | 0% | 0.733 |
| window_overflow | 0kb | 11340 | 13140 | 0.1214 | 0% | 0% | 0.692 |
| window_overflow | 100kb | 28620 | 30420 | 0.2977 | 0% | 0% | 0.692 |
| window_overflow | 20kb | 19980 | 21780 | 0.2095 | 0% | 0% | 0.692 |
| window_overflow | 50kb | 24300 | 26100 | 0.2536 | 0% | 0% | 0.692 |
| window_overflow | 5kb | 15660 | 17460 | 0.1655 | 0% | 0% | 0.692 |

## Curvas (tablas)

### 1. `latency_ms` vs `tokens_in` — `window_overflow`, adjunto 0kb

| tokens_in | latency_ms |
|---:|---:|
| 17900 | 9180 |
| 18250 | 9360 |
| 18600 | 9540 |
| 18950 | 9720 |
| 19300 | 9900 |
| 19650 | 10080 |
| 20000 | 10260 |
| 20350 | 10440 |

### 2. `cost_usd` acumulado vs `turn_index` — adjunto 0kb

**baseline**
| turn_index | cost_usd acumulado |
|---:|---:|
| 1 | 0.000966 |
| 2 | 0.002009 |
| 3 | 0.003128 |

**window_overflow**
| turn_index | cost_usd acumulado |
|---:|---:|
| 1 | 0.005403 |
| 2 | 0.010882 |
| 3 | 0.016438 |
| 4 | 0.022071 |
| 5 | 0.027780 |
| 6 | 0.033565 |
| 7 | 0.039427 |
| 8 | 0.045366 |

**constraint_locked**
| turn_index | cost_usd acumulado |
|---:|---:|
| 1 | 0.013742 |
| 2 | 0.027560 |
| 3 | 0.041455 |
| 4 | 0.055426 |
| 5 | 0.069473 |


### 3. `MemoryDriftMetric` vs N — `window_overflow`, adjunto 0kb

| N (turnos) | MemoryDrift score |
|---:|---:|
| 1 | 1.000 |
| 2 | 1.000 |
| 3 | 0.667 |
| 4 | 0.667 |
| 5 | 0.600 |
| 6 | 0.533 |
| 7 | 0.533 |
| 8 | 0.533 |

## Lectura

**¿A partir de qué turno empieza a romperse mi CAG?** En `window_overflow`, el recall agregado cae por debajo del **60%** a partir del **turno N=7** (score 0.533 frente a 0.533 en N=6), al activarse el recorte de ventana (`MAX_TURNS=6`). En `baseline` (≤3 turnos) el recall se mantiene en 1.0.

**¿Qué dimensión domina la degradación?** Domina la **pérdida de memoria** (MemoryDriftMetric), no la latencia ni el coste. El turno 8 multiplica por **1.1×** el `cost_usd` del turno 1 en la misma sesión, pero ambos importes siguen en centavos; la latencia P95 escala con `tokens_in` de forma casi lineal. La caché exacta/semántica permanece en **0%** en la ruta conversacional. El caso límite para RAG: `window_overflow` + adjunto **100kb** con recall medio **0.69** — se pierden anclas temprunas aunque el coste de sesión siga <$0.05.
