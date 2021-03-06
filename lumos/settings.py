#!/usr/bin/env python
""" Lumos global settings module
"""


import os
BASE_DIR = os.path.dirname(os.path.dirname(__file__))

# set DEBUG to 'True' to enable verbose debug outputs
# DEBUG = os.getenv('LUMOS_DEBUG', False)
val = os.getenv('LUMOS_DEBUG', False)
if val:
    LUMOS_DEBUG = val.split(',')
else:
    LUMOS_DEBUG = ''


LUMOS_HOME = os.getenv('LUMOS_HOME', BASE_DIR)


# @TODO: seems obsolete, used only in ptm_mod, consider using
# CMOS_SIM_CIRCUIT/TFET_SIM_CIRCUIT instead
# LUMOS_SIM_CIRCUIT = 'adder32'

CMOS_SIM_CIRCUIT = 'rca32'
TFET_SIM_CIRCUIT = 'rca32'
FINFET_SIM_CIRCUIT = 'rca32'


# obsolete, as Lumos will always use the local circuit simulation results
# True: use remote simulation results
# Flase: use local copy in 'data'
# LUMOS_USE_REMOTE = os.getenv('LUMOS_USE_REMOTE', False)

LUMOS_ANALYSIS_DIR = os.getenv('LUMOS_ANALYSIS_DIR', os.path.join(LUMOS_HOME, 'analyses'))
