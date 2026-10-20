"""
Overflow at negative freeboard is the broad-crested weir discharge,
q = 0.54 * sqrt(g * |Rc|^3) per metre of crest.

It used to drop the cube, 0.54 * sqrt(g * |Rc|), which agrees only at
|Rc| = 1 m: four times too much water at 0.25 m over the crest, half at 2 m.
"""
import numpy as np

from stormsim.eurotop.runup_and_ot_eurotop_2018 import runup_and_ot_eurotop_2018


def test_overflow_is_weir_discharge():
    swl = np.array([2.75, 3.5, 4.5, 2.0])  # crest 2.5: 0.25, 1 and 2 m over, then below
    eurotop = runup_and_ot_eurotop_2018({
        "type": 3, "app_type": 1, "material": "concrete",
        "crest_elevation": 2.5, "toe_elevation": 0.0,
        "seaward_slope": 1.0, "crest_width": 3.0,
        "SWL": swl, "Hm0": np.full(4, 0.5), "Tm10": np.full(4, 4.0),
    })
    eurotop._negative_freeboard_influence_factor()

    over = np.array([0.25, 1.0, 2.0])
    np.testing.assert_allclose(eurotop.ifactors_q_overflow[:3], 0.54 * np.sqrt(9.81 * over**3))
    assert eurotop.ifactors_q_overflow[3] == 0
