# Structure base ME bonuses (%)
STRUCTURE_BASE_ME = {
    'raitaru': 1.0,
    'azbel': 1.0,
    'sotiyo': 1.0,
    'athanor': 0.0,
    'tatara': 0.0,
}

# Rig size that fits each structure type
STRUCTURE_RIG_SIZE = {
    'raitaru': 2,
    'azbel': 3,
    'sotiyo': 4,
    'athanor': 2,
    'tatara': 3,
}

# Ship group classification sets
BASIC_SMALL_SHIP_GROUPS = {25, 420, 31, 237, 1283, 1527}
BASIC_MEDIUM_SHIP_GROUPS = {26, 419, 1201, 28, 463, 941, 1972}
BASIC_LARGE_SHIP_GROUPS = {27, 381}
ADV_SMALL_SHIP_GROUPS = {324, 830, 831, 893, 834, 1534, 541, 1305}
ADV_MEDIUM_SHIP_GROUPS = {358, 832, 906, 833, 894, 963, 540, 380, 1202, 543}
ADV_LARGE_SHIP_GROUPS = {900, 898}
CAPITAL_SHIP_GROUPS = {30, 485, 513, 547, 659, 883, 902, 1538, 4594}

# Rig groupID -> set of product rig categories covered
# M-Set (rig size 2)
RIG_GROUP_TO_CATEGORIES = {
    1816: {'equipment'},
    1820: {'ammunition'},
    1822: {'drone_fighter'},
    1824: {'basic_small_ship'},
    1826: {'basic_medium_ship'},
    1828: {'basic_large_ship'},
    1830: {'adv_small_ship'},
    1832: {'adv_medium_ship'},
    1834: {'adv_large_ship'},
    1836: {'adv_component'},
    1839: {'basic_capital_component'},
    1840: {'structure'},
    # L-Set (rig size 3)
    1850: {'equipment'},
    1851: {'ammunition'},
    1852: {'drone_fighter'},
    1853: {'basic_small_ship'},
    1854: {'basic_medium_ship'},
    1855: {'basic_large_ship'},
    1856: {'adv_small_ship'},
    1857: {'adv_medium_ship'},
    1858: {'adv_large_ship'},
    1859: {'capital_ship'},
    1860: {'adv_component'},
    1861: {'basic_capital_component'},
    1862: {'structure'},
    # XL-Set (rig size 4)
    1867: {'equipment', 'ammunition'},
    1868: {
        'basic_small_ship', 'basic_medium_ship', 'basic_large_ship',
        'adv_small_ship', 'adv_medium_ship', 'adv_large_ship',
        'capital_ship',
    },
    1869: {'structure', 'adv_component', 'basic_capital_component'},
}

# All rig group IDs (for querying dgmTypeAttributes)
ALL_ME_RIG_GROUPS = set(RIG_GROUP_TO_CATEGORIES.keys())

# Dogma attribute IDs
ATTR_ME_BONUS = 2594           # Material Reduction Bonus (e.g. -2.0)
ATTR_HIGHSEC_MODIFIER = 2355   # highSecModifier
ATTR_LOWSEC_MODIFIER = 2356    # lowSecModifier
ATTR_NULLSEC_MODIFIER = 2357   # nullSecModifier / WH modifier
