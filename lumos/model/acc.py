#!/usr/bin/env python
"""Models application-specific hardware accelerators (ASAcc).

The model parameters are similar to u-core described in Chung's paper:

    *Sing-Chip Heterogenerous Computing: Does the Future Include Custom Logic,
    FPGAs, and GPGPUs?*, Eric S. Chung, et al., MICRO'10

"""

import sys
from lumos import settings
from .core.io_cmos import PERF_BASE

import logging
_logger_asacc = logging.getLogger('ASAcc')
_logger_asacc.setLevel(logging.INFO)
if settings.LUMOS_DEBUG and (
        'all' in settings.LUMOS_DEBUG or 'asacc' in settings.LUMOS_DEBUG):
    _logger_asacc.setLevel(logging.DEBUG)

_logger_rlacc = logging.getLogger('RLAcc')
_logger_rlacc.setLevel(logging.INFO)
if settings.LUMOS_DEBUG and (
        'all' in settings.LUMOS_DEBUG or 'rlacc' in settings.LUMOS_DEBUG):
    _logger_rlacc.setLevel(logging.DEBUG)

try:
    MAXINT = sys.maxint
except AttributeError:
    MAXINT = sys.maxsize


BCE_PARAMS_DICT = {
    # CMOS-HP
    'cmos-hp': {
        # area of core i7-960, core only
        'area': 24.125,
        # SPECfp2006 of Core i7-960
        'perf': 43.5,
        # extracted from Core i7-960's TDP, 130W/4=32.5,
        # then subtract un-core components, e.g. LLC, MCs
        'dp': 20,
        'sp': 0,
        # technology nodes for BCE characteristics
        'tech': 45,
        # FIXME: adjust to more realistic values, currently not used
        'bw': 1,
        },
    # TFET-homo60nm
    'tfet-homo60nm': {
        'area': 24.125/4,
        'perf': 43.5*1.21/1.65,
        'dp': 20*0.206/2.965,
        'sp': 0,
        'tech': 22,
        'bw': 1,
        },
    # TFET-homo30nm
    'tfet-homo30nm': {
        'area': 24.125/4,
        'perf': 43.5*1.21/1.65,
        'dp': 20*0.206/2.965,
        'sp': 0,
        'tech': 22,
        'bw': 1,
        },
    # FinFET-hp
    'finfet-hp': {
        # area of core i7-960, core only
        'area': 22.125,
        # SPECfp2006 of Core i7-960
        'perf': 105,
        # extracted from Core i7-960's TDP, 130W/4=32.5,
        # then subtract un-core components, e.g. LLC, MCs
        'dp': 10.625,
        'sp': 0,
        # technology nodes for BCE characteristics
        'tech': 20,
        # FIXME: adjust to more realistic values, currently not used
        'bw': 1,
        },
    }


class ASAccError(Exception):
    pass


class ASAcc(object):
    """Model an application-specific hardware accelerator, or ASIC accelerator.


    Attributes
    ----------
    acc_id : str
      Accelerator identifier, this is in line with the acc_id in kernel
      description. This property is used to model alternate accelerators for the
      same computing kernel

    ker_obj : :class:`~lumos.model.Kernel`
      The kernel object, for which the accelerator is designed.

    area : float
      The area of the accelerator, a metric of allocated resources.

    tech : int
      The technology nodes, e.g. 22(nm).

    tech_model : :class:`~lumos.model.BaseTechModel`
      The technology model, it could be CMOSTechModel or TFETTechModel.

    vdd : int
      The working supply voltage, it is initialized to the nominal supply of the
      associated technology node. The unit is mV.

    """
    def __init__(self, acc_id, ker_obj, area, tech, tech_model):
        self._acc_id = acc_id
        self._ker_obj = ker_obj
        self._area = area
        self._tech = tech

        self._tech_model = tech_model
        self._vdd_mv = tech_model.vnom_dict[tech]

        try:
            bce_params = BCE_PARAMS_DICT[tech_model.mnemonic]
        except KeyError:
            raise ASAccError(
                'No BCE_PARAMS for technology model {0}'.format(tech_model.mnemonic))
        tech_base = bce_params['tech']
        area_base = bce_params['area']
        perf_base = bce_params['perf']
        dp_base = bce_params['dp']
        sp_base = bce_params['sp']
        bw_base = bce_params['bw']
        if tech == tech_base:
            self._a0, self._perf0, self._bw0 = area_base, perf_base, bw_base
            self._dp0, self._sp0 = dp_base, sp_base
        else:
            self._a0 = area_base * tech_model.area_scale[tech] / \
                tech_model.area_scale[tech_base]
            self._perf0 = perf_base * tech_model.perf_scale[tech] / \
                tech_model.perf_scale[tech_base]
            self._dp0 = dp_base * tech_model.dynamic_power_scale[tech] / \
                tech_model.dynamic_power_scale[tech_base]
            self._sp0 = sp_base * tech_model.static_power_scale[tech] / \
                tech_model.static_power_scale[tech_base]
            self._bw0 = bw_base * tech_model.fnom_scale[tech] / \
                tech_model.fnom_scale[tech_base]
        self._v0 = tech_model.vnom(tech)

    def perf(self, power=None, bandwidth=None):
        kernel = self._ker_obj
        uparam = kernel.get_kernel_param(self._acc_id)

        _logger_asacc.debug('power budget: {0}, acc power: {1}'.format(power, self.power))
        if power:
            area_p = (power / self.power) * self.area
        else:
            area_p = MAXINT

        if bandwidth:
            area_b = (bandwidth / self._bw0 / uparam.bw) * self._a0
        else:
            area_b = MAXINT

        self.area_eff = min(area_p, area_b, self._area)
        self.power_eff = self.area_eff / self.area * self.power

        freq_factor = (self._tech_model.freq(self._tech, self._vdd_mv) /
                       self._tech_model.freq(self._tech, self._tech_model.vnom(self._tech)))
        area_factor = self.area_eff / self._a0
        abs_perf = self._perf0 * area_factor * freq_factor * uparam.perf
        return abs_perf

    def bandwidth(self, app):
        """Calculate the bandwith consumed by the accelerator

        Parameters
        ----------
        app : :class:`~lumos.model.Application`
          target application

        Returns
        -------
        float: the resulting bandwidth consumed by the accelerator

        """
        raise NotImplementedError('Accelerator\'s bandwidth method is not implemented yet')
        return self._bw0 * (self._area/self._a0) * app[self._acc_id].bw

    @property
    def power(self):
        return self.dp + self.sp

    @property
    def dp(self):
        kernel = self._ker_obj
        uparam = kernel.get_kernel_param(self._acc_id)
        return self._dp0 * (self._area/self._a0) * uparam.power * \
            self._tech_model.dynamic_power(self._tech, self._vdd_mv)

    @property
    def sp(self):
        return self._sp0 * (self._area/self._a0) * \
            self._tech_model.static_power(self._tech, self._vdd_mv)

    @property
    def vdd(self):
        return self._vdd_mv

    @vdd.setter
    def vdd(self, vdd_mv):
        self._vdd_mv = vdd_mv

    @property
    def area(self):
        """ Get the area of the core """
        return self._area

    @area.setter
    def area(self, new_area):
        self._area = new_area

    @property
    def tech(self):
        """ Get the technology node, in nm """
        return self._tech

    @property
    def tech_vmax(self):
        return self._tech_model.vmax(self._tech)

    @property
    def tech_vmin(self):
        return self._tech_model.vmin(self._tech)

    @property
    def tech_vnom(self):
        return self._tech_model.vnom(self._tech)

    @property
    def kernel(self):
        """ The kernel object that this accelerator targets at. This is a read-only property.
        """
        return self._ker_obj


class RLAccError(Exception):
    pass


class RLAcc(object):
    """Model an application-specific hardware accelerator, or ASIC accelerator.


    Attributes
    ----------
    acc_id : str
      Accelerator identifier, this is in line with the acc_id in kernel
      description. This property is used to model alternate accelerators for the
      same computing kernel

    area : float
      The area of the accelerator, a metric of allocated resources.

    tech : int
      The technology nodes, e.g. 22(nm).

    tech_model : :class:`~lumos.model.BaseTechModel`
      The technology model, it could be CMOSTechModel or TFETTechModel.

    vdd : int
      The working supply voltage, it is initialized to the nominal supply of the
      associated technology node. The unit is mV.

    """
    def __init__(self, acc_id, area, tech, tech_model):
        self._acc_id = acc_id
        self._area = area
        self._tech = tech

        self._tech_model = tech_model
        self._vdd_mv = tech_model.vnom_dict[tech]

        try:
            bce_params = BCE_PARAMS_DICT[tech_model.mnemonic]
        except KeyError:
            raise RLAccError(
                'No BCE_PARAMS for technology model {0}'.format(tech_model.mnemonic))
        tech_base = bce_params['tech']
        area_base = bce_params['area']
        perf_base = bce_params['perf']
        dp_base = bce_params['dp']
        sp_base = bce_params['sp']
        bw_base = bce_params['bw']
        if tech == tech_base:
            self._a0, self._perf0, self._bw0 = area_base, perf_base, bw_base
            self._dp0, self._sp0 = dp_base, sp_base
        else:
            self._a0 = area_base * tech_model.area_scale[tech] / \
                tech_model.area_scale[tech_base]
            self._perf0 = perf_base * tech_model.perf_scale[tech] / \
                tech_model.perf_scale[tech_base]
            self._dp0 = dp_base * tech_model.dynamic_power_scale[tech] / \
                tech_model.dynamic_power_scale[tech_base]
            self._sp0 = sp_base * tech_model.static_power_scale[tech] / \
                tech_model.static_power_scale[tech_base]
            self._bw0 = bw_base * tech_model.fnom_scale[tech] / \
                tech_model.fnom_scale[tech_base]
        self._v0 = tech_model.vnom(tech)
        _logger_rlacc.debug('a0: {0}, dp0: {1}, sp0: {2}, perf0: {3}'.format(
            self._a0, self._dp0, self._sp0, self._perf0))

    def perf(self, ker_obj, power=None, bandwidth=None):
        uparam = ker_obj.get_kernel_param(self._acc_id)

        _logger_rlacc.debug('power budget: {0}, acc power: {1}'.format(power, self.power(ker_obj)))
        if power:
            area_p = (power / self.power(ker_obj)) * self.area
        else:
            area_p = MAXINT

        if bandwidth:
            area_b = (bandwidth / self._bw0 / uparam.bw) * self._a0
        else:
            area_b = MAXINT

        self.area_eff = min(area_p, area_b, self._area)
        self.power_eff = self.area_eff / self.area * self.power(ker_obj)

        freq_factor = (self._tech_model.freq(self._tech, self._vdd_mv) /
                       self._tech_model.freq(self._tech, self._tech_model.vnom(self._tech)))
        area_factor = self.area_eff / self._a0
        abs_perf = self._perf0 * area_factor * freq_factor * uparam.perf
        _logger_rlacc.debug('RLAcc perf {0}'.format(abs_perf))
        return abs_perf

    def bandwidth(self, app):
        """Calculate the bandwith consumed by the accelerator

        Parameters
        ----------
        app : :class:`~lumos.model.Application`
          target application

        Returns
        -------
        float: the resulting bandwidth consumed by the accelerator

        """
        raise NotImplementedError('Accelerator\'s bandwidth method is not implemented yet')
        return self._bw0 * (self._area/self._a0) * app[self._acc_id].bw

    def power(self, ker_obj):
        return self.dp(ker_obj) + self.sp(ker_obj)

    def dp(self, ker_obj):
        uparam = ker_obj.get_kernel_param(self._acc_id)
        return self._dp0 * (self._area/self._a0) * uparam.power * \
            self._tech_model.dynamic_power(self._tech, self._vdd_mv)

    def sp(self, ker_obj):
        return self._sp0 * (self._area/self._a0) * \
            self._tech_model.static_power(self._tech, self._vdd_mv)

    @property
    def vdd(self):
        return self._vdd_mv

    @vdd.setter
    def vdd(self, vdd_mv):
        self._vdd_mv = vdd_mv

    @property
    def area(self):
        """ Get the area of the core """
        return self._area

    @area.setter
    def area(self, new_area):
        self._area = new_area

    @property
    def tech(self):
        """ Get the technology node, in nm """
        return self._tech

    @property
    def tech_vmax(self):
        return self._tech_model.vmax(self._tech)

    @property
    def tech_vmin(self):
        return self._tech_model.vmin(self._tech)

    @property
    def tech_vnom(self):
        return self._tech_model.vnom(self._tech)
