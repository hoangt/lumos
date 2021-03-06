#!/usr/bin/env python
import abc
import logging
from igraph import Graph, IN as GRAPH_IN
from lxml import etree
from lumos.settings import LUMOS_DEBUG
from lumos import BraceMessage as _bm_

__logger = None

if LUMOS_DEBUG and ('all' in LUMOS_DEBUG or 'app' in LUMOS_DEBUG):
    _debug_enabled = True
else:
    _debug_enabled = False


def _debug(brace_msg):
    global __logger
    if not _debug_enabled:
        return

    if not __logger:
        __logger = logging.getLogger('app')
        __logger.setLevel(logging.DEBUG)

    __logger.debug(brace_msg)


class AppError(Exception):
    pass


class BaseApp():
    __metaclass__ = abc.ABCMeta

    def __init__(self, name_, type_):
        self._name = name_
        self._type = type_

    @property
    def name(self):
        return self._name

    @property
    def type(self):
        return self._type

    @classmethod
    @abc.abstractmethod
    def load_from_xmltree(cls, xmltree, kernels):
        return


class LinearApp(BaseApp):
    def __init__(self, name):
        self._name = name
        self._kernels = dict()
        self.length = dict()
        self._num_kernels = 0

        super().__init__(name, 'linear')

    @classmethod
    def load_from_xmltree(cls, xmltree, kernels):
        pass


class SpreadApp(BaseApp):
    def __init__(self, name):
        super().__init__(name, 'spread')

    @classmethod
    def load_from_xmltree(cls, xmltree, kernels):
        pass


class DAGApp(BaseApp):
    """An application modeled as a directed acyclic graph (DAG)

    An application is DAG of tasks/kernels. Kernels are referred by a
    handler, called `kernel index`. Internally, the kernel index is the
    node index in the DAG (represented using `igraph` library).

    Attributes
    ----------
    name : str, read-only
      The name of an application
    """

    def __init__(self, name):
        self._g = Graph(directed=True)
        self._kernels = dict()
        self._length = dict()
        self._max_depth = -1
        self._num_kernels = 0

        super().__init__(name, 'dag')

    @classmethod
    def load_from_xmltree(cls, xmltree, kernels):
        """load an application from an XML tree node

        Parameters
        ----------
        xmltree : :class:`~lxml.etree.Element`
          root node of the XML tree
        kernels : dict
          kernels dict indexed by kernel name

        Returns
        -------
        application
          application object
        """
        name = xmltree.get('name')
        if not name:
            raise AppError('No name attribute found in XML tree')
        a = cls(name)

        ks = xmltree.find('kernel_config')
        if ks is None:
            raise AppError('No kernel configs found in XML tree')

        for ele in ks:
            val_ = ele.get('index')
            if not val_:
                raise AppError('No kernel index in kernel config')
            node_id = int(val_)

            k_name = ele.get('name')
            if not k_name:
                raise AppError('no kernel name in kernel config')

            val_ = ele.get('cov')
            if not val_:
                raise AppError('No kernel length in kernel config')
            k_cov = float(val_)

            k_preds = ele.get('pred')
            if not k_preds:
                k_preds = 'None'

            kernel_idx = a._add_kernel(kernels[k_name], k_cov)
            if kernel_idx != node_id:
                raise AppError(
                    "kernel index mismatch with DAGApplication.add_kernel."
                    " Probably because the kernel is not specified in order in the XML tree.")
            if k_preds != 'None':
                preds = [int(i) for i in k_preds.split(',')]
                for _ in preds:
                    a._add_dependence(_, kernel_idx)
        a._prep_baseline()
        return a

    @property
    def depth(self):
        return self._max_depth

    def get_all_kernel_lengths(self):
        return [self._length[idx_] for idx_ in self._g.vs.indices]

    def get_kernel_length(self, kernel_idx):
        """Get the length of a kernel, indicated by kernel_idx

        Parameters
        ----------
        kernel_idx : int
          The kernel index.

        Returns
        -------
        float
          the length of the kernel
        """
        return self._length[kernel_idx]

    def _add_kernel(self, kerobj, len_):
        """Add a kernel into application.

        Parameters
        ----------
        kerobj : :class:`~lumos.model.workload.kernel.Kernel`
          The kernel object to be added
        len_ : float
          The run length of a kernel executed on a single base line core
          (BCE).

        Returns
        -------
        int
          kernel index
        """
        kernel_idx = self._g.vcount()
        self._g.add_vertex(name=kerobj.name, depth=1)
        self._kernels[kernel_idx] = kerobj
        self._length[kernel_idx] = len_
        self._num_kernels += 1
        return kernel_idx

    def _add_dependence(self, from_, to_):
        """Add kernel dependence between two kernels.

        Parameters
        ----------
        from\_, to\_: kernel index
          Precedent kernel (from\_) and the dependent kernel (to\_)
          expressed by kernel index
        """
        self._g.add_edge(from_, to_)
        self._g.vs[to_]['depth'] = max(self._g.vs[from_]['depth'] + 1,
                                       self._g.vs[to_]['depth'])
        self._max_depth = max(self._g.vs[to_]['depth'], self._max_depth)

    def get_all_kernels(self, mode='index'):
        """get all kernels

        Parameters
        ----------
        mode : str
          The mode of return value. It could be either 'index' or
          'object'. If 'index', kernel indexes will be returned. If
          'object', kernel objects will be returned.

        Returns
        -------
        list
          Depending on `mode` parameter.
        """
        if mode == 'object':
            return [self._kernels[idx_] for idx_ in self._g.vs.indices]
        else:
            return self._g.vs.indices

    def get_kernel(self, kernel_idx):
        """Get the kernel object

        Parameters
        ----------
        kernel_idx : int
          The kernel index

        Returns
        -------
        :class:`~lumos.model.Kernel`
          The kernel object.
        """
        return self._kernels[kernel_idx]

    def _prep_baseline(self):
        self._depth_sorted = [[v_.index
                               for v_ in self._g.vs.select(depth_eq=d_)]
                              for d_ in range(1, self._max_depth + 1)]
        finish_time = dict.fromkeys(self._g.vs.indices, 0)
        for l, node_list in enumerate(self._depth_sorted):
            if l == 0:
                for node in node_list:
                    finish_time[node] = self._length[node]
            else:
                for node in node_list:
                    start = max([finish_time[n_] for n_ in
                                 self._g.neighbors(node,
                                                   mode=GRAPH_IN)])
                    finish_time[node] = start + self._length[node]
        self._baseline_runtime = max(finish_time.values())

    def get_kernel_depth(self, kernel_idx):
        return self._g.vs[kernel_idx]['depth']

    def get_all_kernel_depth(self):
        return self._g.vs['depth']

    def kernels_topo_sort(self):
        """sort kernels in a topological order.

        Returns
        -------
        list
          kernel indexes in a topological sort order
        """
        return self._g.topological_sorting()

    def get_precedent_kernel(self, kernel_idx):
        """Get the precedent (pre-requisite) kernels.

        Returns
        -------
        list
          A list of kernel indexes that precedent the given kernel. None
          if no precedent kernels exist, e.g. the starting kernel.
        """
        return self._g.neighbors(kernel_idx, mode=GRAPH_IN)

    def kernels_depth_sort(self):
        """sort kernels by their depth.

        Returns
        -------
        list
          kernel indexes grouped by its depth in the DAG. An example output looks
          like::

            [
               [0,1],   # depth == 0
               [2,3,4], # depth == 1
               [5,6],   # depth == 2
            ]
        """
        try:
            return self._depth_sorted
        except AttributeError:
            raise AppError('App not initiliazed properly')

    def get_speedup(self, speedup_dict):
        """Get the speedup of an application by given a speedup vector of each kernel.

        Parameters
        ----------
        speedup_dict : dict
          provides speedup indexed by kernel index, an example of
          speedup_dict would be::

            {
              0: 1.2, # kernel 0 has speedup of 1.2x, or a run time of 1/1.2
              1: 0.8, # kernel 1 has speedup of 0.8x, and this is actually a slowdown
            }

          kernels not specified will be assumed to have a speedup of 1x,
          e.g. not speedup
        """
        speedups = [speedup_dict[idx_] if idx_ in speedup_dict else 1
                    for idx_ in self._g.vs.indices]
        kernel_runtime = [self._length[idx_] / speedups[idx_]
                          for idx_ in self._g.vs.indices]
        finish_time = dict.fromkeys(self._g.vs.indices, 0)
        for l, node_list in enumerate(self._depth_sorted):
            if l == 0:
                for node in node_list:
                    finish_time[node] = kernel_runtime[node]
            else:
                for node in node_list:
                    start = max([finish_time[n_] for n_ in
                                 self._g.neighbors(node,
                                                   mode=GRAPH_IN)])
                    finish_time[node] = start + kernel_runtime[node]
        app_runtime = max(finish_time.values())
        return self._baseline_runtime / app_runtime


class SimpleApp(BaseApp):
    """ A simple application is an abstract program partitioned into serial and
    parallel portions.

    In this abstrace model, a program(application) is partitioned ideally into
    the serial and parallel sections. The serial sections can only be executed
    on a single core, but not accelerators (may be extended to execute the
    serial section with accelerators as well in the future). The parallel
    section can be perfectly parllelized on multiple cores, e.g. the throughput
    improvment is linear to the number of cores. Besides, the parallel section
    can also be accelerated by accelerators for better performance and/or energy
    efficiency.


    Attributes
    ----------
    f: float, in the range of [0, 1]
      the fraction of parallel section.
    name: str
      the name (id) of the application
    """

    def __init__(self, f=0.9, m=0, name='app'):
        """ Initialize an application

        Parameters
        ----------
        f : float
          the fraction of parallel part of program (default 0.9)
        m : float, optional
          the factor of memory latency (default 0)
        """
        self.f = f
        self.f_noacc = f

        self.m = m

        self.kernels = dict()
        self.kernels_coverage = dict()

        self.tag = self.tag_update()

        super().__init__(name, 'simple')

    @classmethod
    def load_from_xmltree(cls, xmltree, kernels):
        name = xmltree.get('name')
        if not name:
            raise AppError("No name in app config")

        ele = xmltree.find('f_parallel')
        parallel_factor = float(ele.text)

        a_ = cls(f=parallel_factor, name=name)

        ks = xmltree.find('kernel_config')
        if ks is None:
            raise AppError('No kernel config')

        for ele in ks:
            kname = ele.get('name')
            if not kname:
                raise AppError('No name for kernel')

            val_ = ele.get('cov')
            if not val_:
                raise AppError('No covreage for kernel')
            k_cov = float(val_)
            a_.add_kernel(kernels[kname], k_cov)

        return a_

    def __repr__(self):
        return self.tag

    def tag_update(self):
        f_str = str(int((self.f - self.f_noacc) * 100))

        return '-'.join([f_str, ] + [(
            '%s-%d' % (name, int(self.kernels_coverage[name] * 100))) for name
                                     in self.kernels_coverage])

    def add_kernel(self, kernel, cov):
        """Register a kernel to be accelerate.

        The kernel could be accelerated by certain ASIC, or more
        generalized GPU/FPGA

        Parameters
        ----------
        kernel : :class:`~lumos.model.workload.kernel.Kernel`
          The kernel object
        cov : float
          The coerage of the kernel, relative to the serial execution

        Raises
        ------
        AppError
          the given coverage (cov) is larger than the overall parallel ratio

        """
        name = kernel.name
        if name in self.kernels:
            _debug(_bm_('Kernel {0} already exist', name))
            return False

        if cov > self.f_noacc:
            raise AppError(
                '[add_kernel]: cov of {0} is too large to exceed the overall '
                'parallel ratio {1}'.format(cov, self.f_noacc))

        self.kernels[name] = kernel
        self.kernels_coverage[name] = cov
        self.f_noacc = self.f_noacc - cov

        self.tag = self.tag_update()

    def set_cov(self, name, cov):
        """Set the coverage of a kernel

        Parameters
        ----------
        name : str
          The name of the kernel
        cov : float
          The coverage of the kernel to be updated

        Raises
        ------
        AppError:
          the given coverage (cov) is larger than the overall parallel ratio, or
          the kernel with 'name' is not registered with the application.
        """
        if name not in self.kernels:
            raise AppError('Kernel %s has not been registerd' % name)

        cov_old = self.kernels_coverage[name]

        if self.f_noacc + cov_old < cov:
            raise AppError('[set_cov]: cov of {0} is too large to exceed '
                           'the overall parallel ratio'.format(name))

        self.kernels_coverage[name] = cov
        self.f_noacc = self.f_noacc + cov_old - cov

        self.tag = self.tag_update()

    def get_all_kernels(self):
        """ Get all kernels within the application

        Returns
        -------
        list
          a list of names for all kernels within the application

        """
        return self.kernels.keys()

    def get_cov(self, name):
        try:
            return self.kernels_coverage[name]
        except KeyError:
            return 0

    def get_kernel(self, name):
        try:
            return self.kernels[name]
        except KeyError:
            return None


class SyntheticApp(BaseApp):
    def __init__(self, name):
        """A synthetic application is composed of several kernels, where each
        kernel can be accelerated by hardware accelerators or multi-core
        parallelization. Each kernel must have detaled performance
        characteristics.
        """
        super().__init__(name, 'synthetic')
        self.kernels = dict()
        self.kernels_coverage = {'__total_cov__': 0}
        self.kernels_rc_count = dict()
        self.kernels_rc_time = dict()

    def add_kernel(self, kernel, cov, rc_count=1, rc_time=0):
        """Register a kernel to be accelerated.

        The kernel could be accelerated by certain ASIC, or more
        generalized GPU/FPGA

        Parameters
        ----------
        kernel : :class:`~lumos.model.workload.kernel.Kernel`
          The kernel object
        cov : float
          The coerage of the kernel, relative to the serial execution
        rc_count: int
          The count of reconfiguration operation, it is at least 1 if cov is
          none-zero.
        rc_time: float
          Reconfiguration timing overhead for a BCE-sized FPGA, relative to the
          serial execution of the whole application, set this parameter to 0 to
          ignore the reconfiguration overhead

        Raises
        ------
        AppError
          the given coverage (cov) is larger than the overall parallel ratio

        """
        if cov < 1e-9:
            return

        name = kernel.name
        if name in self.kernels:
            raise AppError('Kernel {0} already exist'.format(name))

        total_cov = self.kernels_coverage['__total_cov__']

        # with regard to float rounding
        if total_cov + cov - 1 > 1e-6:
            raise AppError(
                'Total coverage exceed 1 after adding {0}, kernel not added'.format(
                    kernel.name))
        self.kernels[name] = kernel
        self.kernels_coverage[name] = cov
        self.kernels_coverage['__total_cov__'] = total_cov + cov
        self.kernels_rc_count[name] = rc_count
        self.kernels_rc_time[name] = rc_time

    def get_all_kernels(self):
        """ Get all kernels within the application

        Returns
        -------
        list
          a list of names for all kernels within the application

        """
        return self.kernels.keys()

    def get_cov(self, name):
        try:
            return self.kernels_coverage[name]
        except KeyError:
            return 0

    def get_rc_count(self, name):
        try:
            return self.kernels_rc_count[name]
        except KeyError:
            return 0

    def get_rc_time(self, name):
        try:
            return self.kernels_rc_time[name]
        except KeyError:
            return 0

    def get_kernel_characteristics(self, name):
        """ Get all characteristics of a kernel within an application.

        This is equivalent to call
        :func:`~lumos.model.workload.application.SyntheticApp.get_cov`,
        :func:`~lumos.model.workload.application.SyntheticApp.get_rc_count`,
        and :func:`~lumos.model.workload.application.SyntheticApp.get_rc_time`,
        then pack return values as a tuple.

        Parameters
        ----------
        name : str
          The name of the kernel

        Returns
        -------
        tuple
          a tuple of (cov, rc_count, rc_time)
        """
        try:
            return self.kernels_coverage[name], self.kernels_rc_count[
                name], self.kernels_rc_time[name]
        except KeyError:
            return 0, 0, 0

    def get_kernel(self, name):
        try:
            return self.kernels[name]
        except KeyError:
            return None

    @classmethod
    def load_from_xmltree(cls, xmltree, kernels):
        name = xmltree.get('name')
        if not name:
            raise AppError("No name in app config")

        a = cls(name)

        ks = xmltree.find('kernel_config')
        if ks is None:
            _debug(_bm_('No kernel config in {0}', name))
        else:
            for ele in ks:
                kname = ele.get('name')
                if not kname:
                    raise Exception('No name for kernel {0} in app {1}'.format(
                        kname, name))

                val_ = ele.get('cov')
                if not val_:
                    raise Exception(
                        'No covreage for kernel {0} in app {1}'.format(
                            kname, name))
                k_cov = float(val_)

                val_ = ele.get('rc_count')
                if not val_:
                    k_rc_count = 1
                else:
                    k_rc_count = int(val_)

                val_ = ele.get('rc_time')
                if not val_:
                    k_rc_time = 0
                else:
                    k_rc_time = float(val_)
                a.add_kernel(kernels[kname], k_cov, k_rc_count, k_rc_time)
                _debug(
                    _bm_('Add kernel {0}, cov {1}, rc_count {2}, rc_time {3}',
                         kname, k_cov, k_rc_count, k_rc_time))

        return a

    @classmethod
    def load_from_xmlfile(cls, xmlfile, kernels):
        tree_root = etree.parse(xmlfile)
        return cls.load_from_xmltree(tree_root.getroot(), kernels)


class DetailedApp(BaseApp):
    def __init__(self, name):
        super().__init__(name, 'detailed')
        self.kernels = dict()
        self.kernels_coverage = dict()

    def add_kernel(self, kernel, cov):
        """Register a kernel to be accelerated.

        The kernel could be accelerated by certain ASIC, or more
        generalized GPU/FPGA

        Parameters
        ----------
        kernel : :class:`~lumos.model.workload.kernel.Kernel`
          The kernel object
        cov : float
          The coerage of the kernel, relative to the serial execution

        Raises
        ------
        AppError
          the given coverage (cov) is larger than the overall parallel ratio

        """
        name = kernel.name
        if name in self.kernels:
            raise AppError('Kernel {0} already exist'.format(name))

        f_noacc = getattr(self, 'f_noacc', None)
        if not f_noacc:
            f_noacc = self.pf

        if cov > f_noacc:
            raise AppError(
                '[add_kernel]: cov of {0} is too large to exceed the overall '
                'parallel ratio {1}'.format(cov, f_noacc))

        self.kernels[name] = kernel
        self.kernels_coverage[name] = cov
        self.f_noacc = f_noacc - cov
        _debug(_bm_('f_noacc: {0}', self.f_noacc))

    def get_all_kernels(self):
        """ Get all kernels within the application

        Returns
        -------
        list
          a list of names for all kernels within the application

        """
        return self.kernels.keys()

    def get_cov(self, name):
        return self.kernels_coverage[name]

    def get_kernel(self, name):
        return self.kernels[name]

    @classmethod
    def load_from_xmltree(cls, xmltree, kernels):
        name = xmltree.get('name')
        if not name:
            raise AppError("No name in app config")

        a = cls(name)

        ps = xmltree.find('perf_config')
        if ps is None:
            raise Exception('No performance configuration in {0}'.format(name))
        else:
            for ele in ps:
                if ele.tag is etree.Comment:
                    continue
                setattr(a, ele.tag, float(ele.text))

        ks = xmltree.find('kernel_config')
        if ks is None:
            _debug(_bm_('No kernel config in {0}', name))
        else:
            for ele in ks:
                kname = ele.get('name')
                if not kname:
                    raise Exception('No name for kernel {0} in app {1}'.format(
                        kname, name))

                val_ = ele.get('cov')
                if not val_:
                    raise Exception(
                        'No covreage for kernel {0} in app {1}'.format(
                            kname, name))
                k_cov = float(val_)
                a_.add_kernel(kernels[kname], k_cov)

        return a

    @classmethod
    def load_from_xmlfile(cls, xmlfile, kernels):
        tree_root = etree.parse(xmlfile)
        return cls.load_from_xmltree(tree_root.getroot(), kernels)


def load_suite_xmltree(xmltree, kernels):
    type_ = xmltree.get('type')
    if not type_:
        type_ = 'simple'

    applications = dict()
    if type_ == 'simple':
        for r_ in xmltree.findall('app'):
            a = SimpleApp.load_from_xmltree(r_, kernels)
            applications[a.name] = a
    elif type_ == 'dag':
        for r_ in xmltree.findall('app'):
            a = DAGApp.load_from_xmltree(r_, kernels)
            applications[a.name] = a
    elif type_ == 'detailed':
        for r_ in xmltree.findall('app'):
            a = DetailedApp.load_from_xmltree(r_, kernels)
            applications[a.name] = a
    elif type_ == 'synthetic':
        for r_ in xmltree.findall('app'):
            a = SyntheticApp.load_from_xmltree(r_, kernels)
            applications[a.name] = a
    else:
        raise AppError('Unknown app type {0}'.format(type_))
    return applications


def load_suite_xmlfile(xmlfile, kernels):
    tree_root = etree.parse(xmlfile)
    return load_suite_xmltree(tree_root.getroot(), kernels)
