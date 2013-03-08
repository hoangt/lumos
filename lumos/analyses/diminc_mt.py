#!/usr/bin/env python
# encoding: utf-8

import logging
import cPickle as pickle
import matplotlib.pyplot as plt

from lumos.model.system import HeterogSys
from lumos.model.application import App
from lumos.model import kernel, workload
from lumos.model.budget import *

import analysis as analysis
from analysis import plot_data, plot_twinx, plot_series, plot_series2
from analysis import try_update, parse_bw

from optparse import OptionParser, OptionGroup
import ConfigParser
from os.path import join as joinpath
import os
import string

import multiprocessing
import Queue
import scipy.stats
import numpy

ANALYSIS_NAME = 'diminc'
HOME = joinpath(analysis.HOME, ANALYSIS_NAME)
FIG_DIR,DATA_DIR = analysis.make_ws_dirs(ANALYSIS_NAME)


class DimInc(object):
    """ Single ASIC accelerator with incremental area allocation """

    class Worker(multiprocessing.Process):

        def __init__(self, work_queue, result_queue,
                budget, workload):

            multiprocessing.Process.__init__(self)

            self.work_queue = work_queue
            self.result_queue = result_queue
            self.kill_received = False

            self.budget = budget
            self.workload = workload

        def run(self):
            while not self.kill_received:

                try:
                    job = self.work_queue.get_nowait()
                except Queue.Empty:
                    break

                # the actual processing
                result = self.process(job)

                self.result_queue.put(result)

        def process(self, job):
            dim_ratio = job

            dummy_alloc = (100-dim_ratio) * 0.01

            sys = HeterogSys(self.budget)
            sys.set_mech('HKMGS')
            sys.set_tech(16)
            sys.set_asic('dummy', dummy_alloc)
            #sys.use_gpacc = True

            perfs = numpy.array([ sys.get_perf(app)['perf'] for app in self.workload ])
            mean = sys.get_perf(app)['perf']

            return (dim_ratio, mean)


    def __init__(self, options, budget):
        self.prefix = ANALYSIS_NAME
        self.fmt = options.fmt

        self.budget = budget

        self.id = self.prefix

        self.nprocs = int(options.nprocs)

        self.options = options

        kernels = kernel.load_xml(options.kernels)
        self.workload = workload.load_xml(options.workload)

        self.dim_ratio = int(options.dim_ratio)

    def analyze(self):
        dfn = joinpath(DATA_DIR, ('%s-%d.pypkl' % (self.id, self.dim_ratio)))
        f = open(dfn, 'wb')

        work_queue = multiprocessing.Queue()
        work_count = 0
        for dim_ratio in xrange(self.dim_ratio, 101):
            work_queue.put(  dim_ratio )
            work_count = work_count + 1


        result_queue = multiprocessing.Queue()

        for i in xrange(self.nprocs):
            worker = DimInc.Worker(work_queue, result_queue,
                    self.budget, self.workload)
            worker.start()

        # Collect all results
        mean_list = [ -1 for x in xrange(101)]
        for i in xrange(work_count):
            dim_alloc, mean = result_queue.get()
            mean_list[dim_alloc] = mean

        pickle.dump(mean_list, f)
        f.close()

    def plot(self):
        #self.plot_speedup()
        self.plot_derivative(step=1)


    def plot_speedup(self):
        dfn = joinpath(DATA_DIR, ('%s-%d.pypkl' % (self.id, self.dim_ratio)))
        with open(dfn, 'rb') as f:
            mean_list = pickle.load(f)

            x_lists = [x for x in xrange(self.dim_ratio, 101)]
            analysis.plot_data(x_lists, [mean_list[self.dim_ratio:],],
                    xlabel='Total ASIC allocation',
                    ylabel='Speedup (mean)',
                    title='%d%% ASIC allocation'%self.dim_ratio,
                    xlim=(self.dim_ratio, 101),
                    figdir=FIG_DIR,
                    ofn='%s-%d.%s' % (self.id, self.dim_ratio, self.fmt)
                    )

    def plot_derivative(self, step=1):
        dfn = joinpath(DATA_DIR, ('%s-%d.pypkl' % (self.id, self.dim_ratio)))
        with open(dfn, 'rb') as f:
            mean_list = pickle.load(f)

            mean_len = len(mean_list)
            deriv_list = [ (mean_list[i+step]-mean_list[i]) for i in xrange(self.dim_ratio, 100, step) ]

            x_lists = [x for x in xrange(self.dim_ratio, 100, step)]
            analysis.plot_data(x_lists, [deriv_list,],
                    xlabel='Total ASIC allocation',
                    ylabel='Speedup (derivative)',
                    title='%d%% ASIC allocation'%self.dim_ratio,
                    xlim=(self.dim_ratio, 101),
                    figdir=FIG_DIR,
                    ofn='%s-deriv-%d.%s' % (self.id, self.dim_ratio, self.fmt)
                    )

LOGGING_LEVELS = {'critical': logging.CRITICAL,
        'error': logging.ERROR,
        'warning': logging.WARNING,
        'info': logging.INFO,
        'debug': logging.DEBUG}

def option_override(options):
    """Override cmd options by using values from configconfiguration file

    :options: option parser (already parsed from cmd line) to be overrided
    :returns: N/A

    """
    if not options.config_file:
        return

    config = ConfigParser.RawConfigParser()
    config.read(options.config_file)

    section = 'system'
    if config.has_section(section):
        try_update(config, options, section, 'budget')
        try_update(config, options, section, 'sys_area')
        try_update(config, options, section, 'sys_power')
        try_update(config, options, section, 'sys_bw')
        try_update(config, options, section, 'dim_ratio')

    section = 'app'
    if config.has_section(section):
        try_update(config, options, section, 'workload')
        try_update(config, options, section, 'kernels')

    section = 'analysis'
    if config.has_section(section):
        try_update(config, options, section, 'sec')
        try_update(config, options, section, 'action')
        try_update(config, options, section, 'fmt')
        try_update(config, options, section, 'nprocs')

def build_optparser():
    # Init command line arguments parser
    parser = OptionParser()

    sys_options = OptionGroup(parser, "System Configurations")
    budget_choices = ('large', 'medium', 'small', 'custom')
    sys_options.add_option('--budget', default='large', choices=budget_choices,
            help="choose the budget from pre-defined ("
            + ",".join(budget_choices[:-1])
            + "), or 'custom' for customized budget by specifying AREA, POWER, and BANDWIDTH")
    sys_options.add_option('--sys-area', type='int', default=400, metavar='AREA',
            help='Area budget in mm^2, default: %default. This option will be discarded when budget is NOT custom')
    sys_options.add_option('--sys-power', type='int', default=100, metavar='POWER',
            help='Power budget in Watts, default: %default. This option will be discarded when budget is NOT custom')
    sys_options.add_option('--sys-bw', metavar='BANDWIDTH',
            default='45:180,32:198,22:234,16:252',
            help='Power budget in Watts, default: {%default}. This option will be discarded when budget is NOT custom')
    sys_options.add_option('--dim-ratio', type='int',
            help='The percentage value of die area allocated to Dim Silicon. For example, --dim-raito=50 means 50% of total area budget is allocated to dim silicon')
    parser.add_option_group(sys_options)

    app_options = OptionGroup(parser, "Application Configurations")
    app_options.add_option('--workload', metavar='FILE',
            help='workload configuration file, e.g. workload.xml')
    app_options.add_option('--kernels', metavar='FILE',
            help='kernels configuration file, e.g. kernels.xml')
    parser.add_option_group(app_options)

    anal_options = OptionGroup(parser, "Analysis options")
    section_choices = ('fpga', 'asic')
    anal_options.add_option('--sec', default='fpga',
            choices=section_choices, metavar='SECTION',
            help='choose the secitons of plotting, choose from ('
            + ','.join(section_choices)
            + '), default: %default')
    action_choices = ('analysis', 'plot')
    anal_options.add_option('-a', '--action', choices=action_choices,
            help='choose the running mode, choose from ('
            + ','.join(action_choices)
            + '), or combine actions seperated by ",". default: N/A.')
    fmt_choices = ('png', 'pdf', 'eps')
    anal_options.add_option('--fmt', default='pdf',
            choices=fmt_choices, metavar='FORMAT',
            help='choose the format of output, choose from ('
            + ','.join(fmt_choices)
            + '), default: %default')
    parser.add_option_group(anal_options)

    llevel_choices = ('info', 'debug', 'error')
    parser.add_option('-l', '--logging-level', default='info',
            choices=llevel_choices, metavar='LEVEL',
            help='Logging level of LEVEL, choose from ('
            + ','.join(llevel_choices)
            + '), default: %default')
    default_cfg = joinpath(HOME, '%s.cfg' % ANALYSIS_NAME)
    parser.add_option('-f', '--config-file', default=default_cfg,
            metavar='FILE', help='Use configurations in FILE, default: %default')
    parser.add_option('-n', action='store_false', dest='override', default=True,
            help='DONOT override command line options with the same one in the configuration file. '
            + 'By default, this option is NOT set, so the configuration file will override command line options.')

    return parser


def main():
    parser = build_optparser()
    (options, args) = parser.parse_args()
    option_override(options)

    logging_level = LOGGING_LEVELS.get(options.logging_level, logging.NOTSET)
    logging.basicConfig(level=logging_level)

    if options.budget == 'large':
        budget = SysLarge
    elif options.budget == 'medium':
        budget = SysMedium
    elif options.budget == 'small':
        budget = SysSmall
    elif options.budget == 'custom':
        budget = Budget(area=float(options.sys_area),
                power=float(options.sys_power),
                bw=parse_bw(options.sys_bw))
    else:
        logging.error('unknwon budget')

    if options.action:
        actions = options.action.split(',')
    else:
        logging.error('No action specified')

    if options.sec == 'diminc':
        anl = DimInc(options,budget=budget)

        if 'analysis' in actions:
            anl.analyze()
        if 'plot' in actions:
            anl.plot()

if __name__ == '__main__':
    main()
