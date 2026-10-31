"""Stated conversion and cost assumptions (AN-6, AN-7). Change them here; every number used in the
demand conversion and the optimiser comes from this file and is shown in the report/dashboard.

Admission rates are ESTIMATED FROM THE DATA (last 52 mature weeks, per district and disease);
the per-patient consumption figures below are planning assumptions (synthetic teaching values,
to be replaced with national treatment guidelines).
"""

PLANNING_WEEKS = 4                 # demand horizon: the next 4 weeks after the data cutoff
PLANNING_QUANTILE = "q900"         # plan for the upper (90%) forecast quantile
LENGTH_OF_STAY_DAYS = {"dengue": 5, "diarrhoea": 3}

# consumption per patient
IV_SALINE_PER_ADMISSION = {"dengue": 4, "diarrhoea": 6}      # 1-litre bags
NS1_KITS_PER_DENGUE_CASE = 1.3                               # suspected cases tested incl. negatives
ORS_PER_DIARRHOEA_CASE = 4                                   # sachets

RESOURCES = ["iv_saline", "ns1_kits", "ors"]
UNIT_COST_BDT = {"iv_saline": 90, "ns1_kits": 350, "ors": 7}           # synthetic unit costs
UNIT_VOLUME_L = {"iv_saline": 1.2, "ns1_kits": 0.3, "ors": 0.03}        # litres per unit (transport)

# severity / vulnerability weight w_d = 1 + ALERT_WEIGHT*active_alert + OCCUPANCY_WEIGHT*(occupancy > 0.85)
ALERT_WEIGHT = 2.0
OCCUPANCY_WEIGHT = 1.0

DEFAULT_BUDGET_SHARE = 0.6        # default budget = 60% of the cost of covering ALL unmet need
DEFAULT_ALPHA = 0.3               # default equity floor
TRANSPORT_SLACK = 1.1             # division transport capacity = 110% of its share of the budget volume
BUDGET_LEVELS = [0.2, 0.4, 0.6, 0.8, 1.0]
ALPHA_LEVELS = [0.0, 0.1, 0.2, 0.3, 0.5]
