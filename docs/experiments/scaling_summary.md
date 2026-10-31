# Experiment summary

Machine: Linux-6.18.54.1-microsoft-standard-WSL2-x86_64-with-glibc2.35, 10.0 CPUs

## Runtime per stage (seconds, last run of each label)

| stage | default | optimisation_opt_0 | optimisation_opt_1 | scaling_sf_0.25 | scaling_sf_0.5 | scaling_sf_1 |
|---|---|---|---|---|---|---|
| bronze_ingest | 69.3 | 223.2 | 208.5 | 146.1 | 262.8 | 397.3 |
| calendar | 3.2 |  |  | 3.6 | 3.9 | 3.8 |
| demand_and_allocation | 2.7 |  |  | 2.9 | 3.4 | 3.2 |
| detection | 12.1 |  |  | 19.9 | 23.8 | 23.0 |
| detection_evaluation | 3.0 |  |  | 6.4 | 11.6 | 9.7 |
| forecast | 73.3 |  |  | 83.0 | 87.8 | 89.4 |
| generator |  |  |  | 75.4 | 140.0 | 325.4 |
| gold_build | 31.2 | 259.9 | 221.6 | 156.3 | 305.4 | 509.3 |
| serving_export | 1.3 |  |  | 1.3 | 1.5 | 1.6 |
| silver_transform | 102.2 | 553.4 | 565.3 | 397.6 | 685.5 | 1437.8 |
| TOTAL | 298.3 | 1036.5 | 995.4 | 892.5 | 1525.7 | 2800.5 |

## Output sizes (MB)

| path | 0.25 | 0.5 | 1.0 |
|---|---|---|---|
| dashboard/data | 2.1 | 2.1 | 2.2 |
| data/lake/bronze | 146.3 | 282.0 | 552.7 |
| data/lake/gold | 7.1 | 7.7 | 8.3 |
| data/lake/silver | 593.0 | 1159.2 | 2289.0 |
| data/landing | 896.6 | 1566.8 | 2907.3 |
