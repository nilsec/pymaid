#    This script is part of pymaid (http://www.github.com/schlegelp/pymaid).
#    Copyright (C) 2017 Philipp Schlegel
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along

""" Module contains functions to plot neurons in 2D and 3D.
"""

import random
import colorsys
import uuid
import math
import numbers
import warnings

import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import matplotlib.patches as mpatches
import mpl_toolkits
import matplotlib.colors as mcl
from mpl_toolkits.mplot3d.art3d import Line3DCollection
from mpl_toolkits.mplot3d import proj3d
from matplotlib.collections import LineCollection

import seaborn as sns
import png
import networkx as nx
import pandas as pd
import numpy as np
import scipy.cluster.hierarchy

import plotly.graph_objs as go
import plotly.offline

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import vispy
    from vispy import scene
    from vispy.geometry import create_sphere
    from vispy.gloo.util import _screenshot

from . import morpho, graph, core, fetch, graph_utils, utils, scene3d, config
from .external.visuals import MeshNeuron

try:
    # Try setting vispy backend to PyQt5
    vispy.use(app='PyQt5')
except BaseException:
    pass

__all__ = ['plot3d', 'plot2d', 'plot1d', 'plot_network',
           'clear3d', 'close3d', 'screenshot', 'get_viewer']

logger = config.logger

if utils.is_jupyter():
    plotly.offline.init_notebook_mode(connected=True)

if utils.is_jupyter() and utils.is_jupyterlab():
    if not utils.has_plotly_extension():
        logger.warning('It appears you are in a Jupyter lab and do not have '
                       'the plotly renderer installed. This is required '
                       'for pymaid.plot3d(). Please visit https://github.com'
                       '/plotly/plotly.py/blob/master/README.md#jupyterlab-'
                       'support-python-35 for instructions on how to '
                       'install it')


def screenshot(file='screenshot.png', alpha=True):
    """Save a screenshot of active vispy 3D canvas.

    Parameters
    ----------
    file :      str, optional
                Filename
    alpha :     bool, optional
                If True, alpha channel will be saved

    See Also
    --------
    :func:`pymaid.Viewer.screenshot`
                Take screenshot of specific canvas.

    """
    if alpha:
        mode = 'RGBA'
    else:
        mode = 'RGB'

    im = png.from_array(_screenshot(alpha=alpha), mode=mode)
    im.save(file)

    return


def get_viewer():
    """Return active 3D viewer.

    Returns
    -------
    :class:`~pymaid.Viewer`

    Examples
    --------
    >>> from vispy import scene
    >>> # Get and plot neuron in 3d
    >>> n = pymaid.get_neuron(12345)
    >>> n.plot3d(color = 'red')
    >>> # Plot connector IDs
    >>> cn_ids = n.connectors.connector_id.values.astype(str)
    >>> cn_co = n.connectors[['x', 'y', 'z']].values
    >>> viewer = pymaid.get_viewer()
    >>> text = scene.visuals.Text(text=cn_ids,
    ...                           pos=cn_co * scale_factor)
    >>> viewer.add(text)

    """
    return globals().get('viewer', None)


def clear3d():
    """Clear viewer 3D canvas."""
    viewer = get_viewer()

    if viewer:
        viewer.clear()


def close3d():
    """Close existing vispy 3D canvas (wipes memory)."""
    try:
        viewer = get_viewer()
        viewer.close()
        globals().pop('viewer')
        del viewer
    except BaseException:
        pass


def _orthogonal_proj(zfront, zback):
    """Get matplotlib to use orthogonal instead of perspective view.

    Examples
    --------
    proj3d.persp_transformation = _orthogonal_proj

    """
    a = (zfront + zback) / (zfront - zback)
    b = -2 * (zfront * zback) / (zfront - zback)
    # -0.0001 added for numerical stability as suggested in:
    # http://stackoverflow.com/questions/23840756
    return np.array([[1, 0, 0, 0],
                     [0, 1, 0, 0],
                     [0, 0, a, b],
                     [0, 0, -0.0001, zback]])


def plot2d(x, method='2d', **kwargs):
    """Generate 2D plots of neurons and neuropils.

    The main advantage of this is that you can save plot as vector graphics.

    Important
    ---------
    This function uses matplotlib which "fakes" 3D as it has only very limited
    control over layers. Therefore neurites aren't necessarily plotted in the
    right Z order which becomes especially troublesome when plotting a complex
    scene with lots of neurons criss-crossing. See the ``method`` parameter
    for details. All methods use orthogonal projection.

    Parameters
    ----------
    x :               skeleton IDs | CatmaidNeuron | CatmaidNeuronList | CatmaidVolume | Dotprops | np.ndarray
                      Objects to plot::

                        - int is intepreted as skeleton ID(s)
                        - str is intepreted as volume name(s)
                        - multiple objects can be passed as list (see examples)
                        - numpy array of shape (n,3) is intepreted as scatter
    method :          '2d' | '3d' | '3d_complex'
                      Method used to generate plot. Comes in three flavours:
                        1. '2d' uses normal matplotlib. Neurons are plotted in
                           the order their are provided. Well behaved when
                           plotting neuropils and connectors. Always gives
                           frontal view.
                        2. '3d' uses matplotlib's 3D axis. Here, matplotlib
                           decide the order of plotting. Can chance perspective
                           either interacively or by code (see examples).
                        3. '3d_complex' same as 3d but each neuron segment is
                           added individually. This allows for more complex
                           crossing patterns to be rendered correctly. Slows
                           down rendering though.
    remote_instance : CatmaidInstance, optional
                      Need this too if you are passing only skids
    **kwargs
                      See Notes for permissible keyword arguments.

    Examples
    --------
    >>> import matplotlib.pyplot as plt
    >>> # 1. Plot two neurons from skeleton IDs:
    >>> fig, ax = pymaid.plot2d( [12345, 45567] )
    >>> # 2. Manually download a neuron, prune it and plot it:
    >>> neuron = pymaid.get_neuron( [12345], rm )
    >>> neuron.prune_distal_to( 4567 )
    >>> fig, ax = pymaid.plot2d( neuron )
    >>> matplotlib.pyplot.show()
    >>> # 3. Plots neuropil in grey, and mushroom body in red:
    >>> neurop = pymaid.get_volume('v14.neuropil')
    >>> neurop.color = (.8,.8,.8)
    >>> mb = pymaid.get_volume('v14.MB_whole')
    >>> mb.color = (.8,0,0)
    >>> fig, ax = pymaid.plot2d(  [ 12346, neurop, mb ] )
    >>> matplotlib.pyplot.show()
    >>> # Change perspective
    >>> fig, ax = pymaid.plot2d( neuron, method='3d_complex' )
    >>> # Change view to lateral
    >>> ax.azim = 0
    >>> ax.elev = 0
    >>> # Change view to top
    >>> ax.azim = -90
    >>> ax.elev = 90
    >>> # Tilted top view
    >>> ax.azim = -135
    >>> ax.elev = 45
    >>> # Move camera closer (will make image bigger)
    >>> ax.dist = 5

    Returns
    --------
    fig, ax :      matplotlib figure and axis object

    Notes
    -----

    Optional keyword arguments:

    ``connectors`` (boolean, default = True)
       Plot connectors (synapses, gap junctions, abutting)

    ``connectors_only`` (boolean, default = False)
       Plot only connectors, not the neuron.

    ``cn_size`` (int | float, default = 1)
      Size of connectors.

    ``linewidth``/``lw`` (int | float, default = .5)
      Width of neurites.

    ``linestyle``/``ls`` (str, default = '-')
      Line style of neurites.

    ``autoscale`` (bool, default=True)
       If True, will scale the axes to fit the data.

    ``scalebar`` (int | float, default=False)
       Adds scale bar. Provide integer/float to set size of scalebar in um.
       For methods '3d' and '3d_complex', this will create an axis object.

    ``ax`` (matplotlib ax, default=None)
       Pass an ax object if you want to plot on an existing canvas.

    ``color`` (tuple | list | str | dict)
      Tuples/lists (r,g,b) and str (color name) are interpreted as a single
      colors that will be applied to all neurons. Dicts will be mapped onto
      neurons by skeleton ID.

    ``depth_coloring`` (bool, default = False)
      If True, will color encode depth (Z). Overrides ``color``. Does not work
      with ``method = '3d_complex'``.

    ``cn_mesh_colors`` (bool, default = False)
      If True, will use the neuron's color for its connectors too.

    ``group_neurons`` (bool, default = False)
      If True, neurons will be grouped. Works with SVG export (not PDF).
      Does NOT work with ``method='3d_complex'``.

    ``scatter_kws`` (dict, default = {})
      Parameters to be used when plotting points. Accepted keywords are:
      ``size`` and ``color``.

    ``figsize`` (tuple, default = (8, 8))
      Sets figure size.

    ``soma`` (bool, default = True)
      Whether to plot somata.

    ``volume_outlines`` (bool, default=True)
      If True will plot volume outline with no fill.

    See Also
    --------
    :func:`pymaid.plot3d`
            Use this if you want interactive, perspectively correct renders
            and if you don't need vector graphics as outputs.

    """
    _ACCEPTED_KWARGS = ['remote_instance', 'connectors', 'connectors_only',
                        'ax', 'color', 'colors', 'c', 'view', 'scalebar',
                        'cn_mesh_colors', 'linewidth', 'cn_size',
                        'group_neurons', 'scatter_kws', 'figsize', 'linestyle',
                        'alpha', 'depth_coloring', 'autoscale', 'depth_scale',
                        'use_neuron_color', 'ls', 'lw', 'soma',
                        'volume_outlines']
    wrong_kwargs = [a for a in kwargs if a not in _ACCEPTED_KWARGS]
    if wrong_kwargs:
        raise KeyError('Unknown kwarg(s): {0}. Currently accepted: {1}'.format(
            ','.join(wrong_kwargs), ', '.join(_ACCEPTED_KWARGS)))

    _METHOD_OPTIONS = ['2d', '3d', '3d_complex']
    if method not in _METHOD_OPTIONS:
        raise ValueError('Unknown method "{0}". Please use either: {1}'.format(
            method, _METHOD_OPTIONS))

    # Set axis to plot for method '2d'
    axis1, axis2 = 'x', 'y'

    skids, skdata, dotprops, volumes, points, visuals = utils._parse_objects(x)

    remote_instance = kwargs.get('remote_instance', None)
    connectors = kwargs.get('connectors', True)
    connectors_only = kwargs.get('connectors_only', False)
    cn_mesh_colors = kwargs.get('cn_mesh_colors', False)
    use_neuron_color = kwargs.get('use_neuron_color', False)
    ax = kwargs.get('ax', None)
    color = kwargs.get('color',
                       kwargs.get('c',
                                  kwargs.get('colors', None)))
    scalebar = kwargs.get('scalebar', None)
    group_neurons = kwargs.get('group_neurons', False)
    alpha = kwargs.get('alpha', .9)
    depth_coloring = kwargs.get('depth_coloring', False)
    depth_scale = kwargs.get('depth_scale', True)

    scatter_kws = kwargs.get('scatter_kws', {})

    linewidth = kwargs.get('linewidth', kwargs.get('lw', .5))
    cn_size = kwargs.get('cn_size', 1)
    linestyle = kwargs.get('linestyle', kwargs.get('ls', '-'))
    autoscale = kwargs.get('autoscale', True)

    remote_instance = utils._eval_remote_instance(remote_instance,
                                                  raise_error=False)

    if skids:
        skdata += fetch.get_neuron(skids,
                                   with_connectors=True,
                                   with_tags=False,
                                   with_history=False,
                                   with_abutting=True,
                                   remote_instance=remote_instance)

    # Generate the colormaps
    neuron_cmap, dotprop_cmap = _prepare_colormap(color,
                                                  skdata, dotprops,
                                                  use_neuron_color=use_neuron_color,
                                                  color_range=1)

    # Make sure axes are projected orthogonally
    if method in ['3d', '3d_complex']:
        proj3d.persp_transformation = _orthogonal_proj

    if not ax:
        if method == '2d':
            fig, ax = plt.subplots(figsize=kwargs.get('figsize', (8, 8)))
            ax.set_aspect('equal')
        elif method in ['3d', '3d_complex']:
            fig = plt.figure(figsize=kwargs.get(
                'figsize', plt.figaspect(1) * 1.5))
            ax = fig.gca(projection='3d')
            # Set projection to orthogonal
            # This sets front view
            ax.azim = -90
            ax.elev = 0
            ax.dist = 7
            # matplotlib 3.1.0 deprecated this as it was apparently broken to
            # begin with. We will just have to scale our axes appropriately.
            #ax.set_aspect('equal')
    else:
        if not isinstance(ax, mpl.axes.Axes):
            raise TypeError('Ax must be of type "mpl.axes.Axes", '
                            'not "{}"'.format(type(ax)))
        fig = ax.get_figure()
        if method in ['3d', '3d_complex']:
            if ax.name != '3d':
                raise TypeError('Axis must be 3d.')
        elif method == '2d':
            if ax.name == '3d':
                raise TypeError('Axis must be 2d.')

    # Keep track of whether ax already has data
    ax_had_data = ax.has_data()

    # Prepare some stuff for depth coloring
    if depth_coloring and method == '3d_complex':
        raise Exception('Depth coloring unavailable for method '
                        '"{}"'.format(method))
    elif depth_coloring and method == '2d':
        all_co = skdata.nodes[['x', 'y', 'z']]
        norm = plt.Normalize(vmin=all_co.z.min(), vmax=all_co.z.max())

    if volumes:
        for v in volumes:
            c = getattr(v, 'color', (0.9, 0.9, 0.9))

            if not isinstance(c, tuple):
                c = tuple(c)

            if sum(c[:3]) > 3:
                c = np.array(c)
                c[:3] = np.array(c[:3]) / 255

            if len(c) == 4:
                this_alpha = c[3]
            else:
                this_alpha = 1

            if kwargs.get('volume_outlines', False):
                fill, lw, fc, ec = False, 1, 'none', c
            else:
                fill, lw, fc, ec = True, 0, c, 'none'

            if method == '2d':
                verts = v.to_2d(view='{0}{1}'.format(axis1, axis2), invert_y=True)
                vpatch = mpatches.Polygon(verts, closed=True, lw=lw, fill=fill,
                                          fc=fc, ec=ec, alpha=this_alpha, zorder=0)
                ax.add_patch(vpatch)
            elif method in ['3d', '3d_complex']:
                if kwargs.get('volume_outlines', False):
                    # Generate outline - note that we are already inverting y
                    verts = v.to_2d(view='{0}{1}'.format(axis1, axis2), invert_y=True)
                    # Add the center of the volume as Z axis
                    verts = np.hstack((verts,
                                       np.full((len(verts), 1),
                                               v.vertices.mean(axis=0)[2])))
                    # Generate and add polygon                    
                    poly = Poly3DCollection([verts[:, [0, 2, 1]]],
                                            lw=lw,
                                            fc=(1, 1, 1, 0),  # this must not be "none"
                                            ec=c)
                    ax.add_collection3d(poly)
                else:
                    verts = np.vstack(v.vertices)
                    # Invert y-axis
                    verts[:, 1] *= -1
                    # Add alpha
                    if len(c) == 3:
                        c = (c[0], c[1], c[2], .1)
                    ts = ax.plot_trisurf(verts[:, 0], verts[:, 2], v.faces,
                                         verts[:, 1], label=v.name,
                                         color=c)
                    ts.set_gid(v.name)
                ax_had_data = _update_axes3d_bounds(ax,
                                                    verts[:, [0, 2, 1]],
                                                    had_data=ax_had_data)

    # Create lines from segments
    line3D_collections = []
    surf3D_collections = []
    for i, neuron in enumerate(config.tqdm(skdata.itertuples(),
                                           desc='Plot neurons',
                                           total=skdata.shape[0], leave=False,
                                           disable=config.pbar_hide)):
        this_color = neuron_cmap[i]
        this_alpha = this_color[3] if len(this_color) == 4 else alpha

        if neuron.nodes.empty:
            logger.warning('Skipping neuron w/o nodes: '
                           '{}'.format(neuron.neuron_name))
            continue

        if not connectors_only:
            # Now make traces (invert y axis)
            coords = _segments_to_coords(
                neuron, neuron.segments, modifier=(1, -1, 1))

            if method == '2d':
                if not depth_coloring:
                    # We have to add (None, None, None) to the end of each
                    # slab to make that line discontinuous there
                    coords = np.vstack(
                        [np.append(t, [[None] * 3], axis=0) for t in coords])

                    this_line = mlines.Line2D(coords[:, 0], coords[:, 1],
                                              lw=linewidth, ls=linestyle,
                                              alpha=this_alpha,
                                              color=this_color,
                                              label='{} - #{}'.format(neuron.neuron_name,
                                                                      neuron.skeleton_id))
                    ax.add_line(this_line)
                else:
                    coords = _tn_pairs_to_coords(neuron, modifier=(1, -1, 1))
                    lc = LineCollection(coords[:, :, [0, 1]],
                                        cmap='jet',
                                        norm=norm)
                    lc.set_array(neuron.nodes.loc[~neuron.nodes.parent_id.isnull(),
                                                  'z'].values)
                    lc.set_linewidth(linewidth)
                    lc.set_alpha(this_alpha)
                    lc.set_linestyle(linestyle)
                    lc.set_label('{} - #{}'.format(neuron.neuron_name,
                                                   neuron.skeleton_id))
                    line = ax.add_collection(lc)

                if neuron.soma and kwargs.get('soma', True):
                    for s in utils._make_iterable(neuron.soma):
                        soma = neuron.nodes.set_index('treenode_id').loc[s]
                        if depth_coloring:
                            this_color = mpl.cm.jet(norm(soma.z))

                        p = mpatches.Circle((int(soma.x), int(-soma.y)), radius=soma.radius,
                                            alpha=this_alpha, fill=True,
                                            fc=this_color,
                                            zorder=4, edgecolor='none')
                        ax.add_patch(p)

            elif method in ['3d', '3d_complex']:
                cmap = mpl.cm.jet if depth_coloring else None

                # For simple scenes, add whole neurons at a time -> will speed
                # up rendering
                if method == '3d':
                    if depth_coloring:
                        this_coords = _tn_pairs_to_coords(neuron,
                                                          modifier=(1, -1, 1))[:, :, [0, 2, 1]]
                    else:
                        this_coords = [c[:, [0, 2, 1]] for c in coords]

                    lc = Line3DCollection(this_coords,
                                          color=this_color,
                                          label=neuron.neuron_name,
                                          alpha=this_alpha,
                                          cmap=cmap,
                                          lw=linewidth,
                                          linestyle=linestyle)
                    if group_neurons:
                        lc.set_gid(neuron.neuron_name)
                    # Need to get this before adding data
                    ax.add_collection3d(lc)
                    # Update data bounds
                    ax_had_data = _update_axes3d_bounds(ax,
                                                        neuron.nodes[['x', 'z', 'y']].values * [1, 1, -1],
                                                        had_data=ax_had_data)
                    line3D_collections.append(lc)

                # For complex scenes, add each segment as a single collection
                # -> help preventing Z-order errors
                elif method == '3d_complex':
                    for c in coords:
                        lc = Line3DCollection([c[:, [0, 2, 1]]],
                                              color=this_color,
                                              lw=linewidth,
                                              alpha=this_alpha,
                                              linestyle=linestyle)
                        if group_neurons:
                            lc.set_gid(neuron.neuron_name)
                        ax.add_collection3d(lc)
                    ax_had_data = _update_axes3d_bounds(ax,
                                                        neuron.nodes[['x', 'z', 'y']].values * [1, 1, -1],
                                                        had_data=ax_had_data)

                surf3D_collections.append([])
                if neuron.soma and kwargs.get('soma', True):
                    for s in utils._make_iterable(neuron.soma):
                        soma = neuron.nodes.set_index('treenode_id').loc[s]
                        resolution = 20
                        u = np.linspace(0, 2 * np.pi, resolution)
                        v = np.linspace(0, np.pi, resolution)
                        x = soma.radius * np.outer(np.cos(u), np.sin(v)) + soma.x
                        y = soma.radius * np.outer(np.sin(u), np.sin(v)) - soma.y
                        z = soma.radius * \
                            np.outer(np.ones(np.size(u)), np.cos(v)) + soma.z
                        surf = ax.plot_surface(
                            x, z, y, color=this_color, shade=False, alpha=this_alpha)
                        if group_neurons:
                            surf.set_gid(neuron.neuron_name)

                        surf3D_collections[-1].append(surf)

        if (connectors or connectors_only) and not neuron.connectors.empty:
            if not cn_mesh_colors:
                cn_types = {0: 'red', 1: 'blue', 2: 'green', 3: 'magenta'}
            else:
                cn_types = {0: this_color, 1: this_color,
                            2: this_color, 3: this_color}
            if method == '2d':
                for c in cn_types:
                    this_cn = neuron.connectors[neuron.connectors.relation == c]
                    ax.scatter(this_cn.x.values,
                               (-this_cn.y).values,
                               c=cn_types[c], alpha=this_alpha, zorder=4,
                               edgecolor='none', s=cn_size)
                    ax.get_children(
                    )[-1].set_gid('CN_{0}'.format(neuron.neuron_name))
            elif method in ['3d', '3d_complex']:
                all_cn = neuron.connectors
                c = [cn_types[i] for i in all_cn.relation.values]
                ax.scatter(all_cn.x.values, all_cn.z.values, -all_cn.y.values,
                           c=c, s=cn_size, depthshade=False, edgecolor='none',
                           alpha=this_alpha)
                ax.get_children(
                )[-1].set_gid('CN_{0}'.format(neuron.neuron_name))
                # Update data bounds
                ax_had_data = _update_axes3d_bounds(ax,
                                                    all_cn[['x', 'z', 'y']].values * [1, 1, -1],
                                                    had_data=ax_had_data)

    for i, neuron in enumerate(config.tqdm(dotprops.itertuples(),
                                           desc='Plt dotprops',
                                           total=dotprops.shape[0],
                                           leave=False,
                                           disable=config.pbar_hide)):
        # Prepare lines - this is based on nat:::plot3d.dotprops
        halfvect = neuron.points[
            ['x_vec', 'y_vec', 'z_vec']] / 2

        starts = neuron.points[['x', 'y', 'z']
                               ].values - halfvect.values
        ends = neuron.points[['x', 'y', 'z']
                             ].values + halfvect.values

        try:
            this_color = dotprop_cmap[i]
        except BaseException:
            this_color = (.1, .1, .1)

        if method == '2d':
            # Add None between segments
            x_coords = [n for sublist in zip(
                starts[:, 0], ends[:, 0], [None] * starts.shape[0]) for n in sublist]
            y_coords = [n for sublist in zip(
                starts[:, 1] * -1, ends[:, 1] * -1, [None] * starts.shape[0]) for n in sublist]

            """
            z_coords = [n for sublist in zip(
                starts[:, 2], ends[:, 2], [None] * starts.shape[0]) for n in sublist]
            """

            this_line = mlines.Line2D(x_coords, y_coords,
                                      lw=linewidth, ls=linestyle,
                                      alpha=alpha, color=this_color,
                                      label='%s' % (neuron.gene_name))

            ax.add_line(this_line)

            # Add soma
            s = mpatches.Circle((neuron.X, -neuron.Y), radius=2,
                                alpha=alpha, fill=True, fc=this_color,
                                zorder=4, edgecolor='none')
            ax.add_patch(s)
        elif method in ['3d', '3d_complex']:
            # Combine coords by weaving starts and ends together
            coords = np.empty((starts.shape[0] * 2, 3), dtype=starts.dtype)
            coords[0::2] = starts
            coords[1::2] = ends

            # Invert y-axis
            coords[:, 1] *= -1

            # For simple scenes, add whole neurons at a time
            # -> will speed up rendering
            if method == '3d':
                lc = Line3DCollection(np.split(coords[:, [0, 2, 1]],
                                               starts.shape[0]),
                                      color=this_color,
                                      label=neuron.gene_name,
                                      lw=linewidth,
                                      alpha=alpha,
                                      linestyle=linestyle)
                if group_neurons:
                    lc.set_gid(neuron.gene_name)
                ax.add_collection3d(lc)
                ax_had_data = _update_axes3d_bounds(ax,
                                                    coords[:, [0, 2, 1]],
                                                    had_data=ax_had_data)

            # For complex scenes, add each segment as a single collection
            # -> help preventing Z-order errors
            elif method == '3d_complex':
                for c in np.split(coords[:, [0, 2, 1]], starts.shape[0]):
                    lc = Line3DCollection([c],
                                          color=this_color,
                                          lw=linewidth,
                                          alpha=alpha,
                                          linestyle=linestyle)
                    if group_neurons:
                        lc.set_gid(neuron.gene_name)
                    ax.add_collection3d(lc)
                ax_had_data = _update_axes3d_bounds(ax,
                                                    coords[:, [0, 2, 1]],
                                                    had_data=ax_had_data)

            resolution = 20
            u = np.linspace(0, 2 * np.pi, resolution)
            v = np.linspace(0, np.pi, resolution)
            x = 2 * np.outer(np.cos(u), np.sin(v)) + neuron.X
            y = 2 * np.outer(np.sin(u), np.sin(v)) - neuron.Y
            z = 2 * np.outer(np.ones(np.size(u)), np.cos(v)) + neuron.Z
            surf = ax.plot_surface(
                x, z, y, color=this_color, shade=False, alpha=alpha)
            if group_neurons:
                surf.set_gid(neuron.gene_name)

    if points:
        for p in points:
            if method == '2d':
                default_settings = dict(
                    c='black',
                    zorder=4,
                    edgecolor='none',
                    s=1
                )
                default_settings.update(scatter_kws)
                default_settings = _fix_default_dict(default_settings)

                ax.scatter(p[:, 0],
                           p[:, 1] * -1,
                           **default_settings)
            elif method in ['3d', '3d_complex']:
                default_settings = dict(
                    c='black',
                    s=1,
                    depthshade=False,
                    edgecolor='none'
                )
                default_settings.update(scatter_kws)
                default_settings = _fix_default_dict(default_settings)

                ax.scatter(p[:, 0], p[:, 2], p[:, 1] * -1,
                           **default_settings
                           )
                ax_had_data = _update_axes3d_bounds(ax,
                                                    p[:, [0, 2, 1]] * [1, 1, -1],
                                                    had_data=ax_had_data)

    if autoscale:
        if method == '2d':
            ax.autoscale(tight=True)
        elif method in ['3d', '3d_complex']:
            # First autoscale
            ax.autoscale()
            # Now we need to set equal aspect manually
            lim = np.array([ax.get_xlim(),
                            ax.get_ylim(),
                            ax.get_zlim()])
            dim = lim[:, 1] - lim[:, 0]
            center = lim[:, 0] + dim / 2
            max_dim = dim.max()

            new_min = center - max_dim / 2
            new_max = center + max_dim / 2

            ax.set_xlim(new_min[0], new_max[0])
            ax.set_ylim(new_min[1], new_max[1])
            ax.set_zlim(new_min[2], new_max[2])

    if scalebar is not None:
        # Convert sc size to nm
        sc_size = scalebar * 1000

        # Hard-coded offset from figure boundaries
        ax_offset = 1000

        if method == '2d':
            xlim = ax.get_xlim()
            ylim = ax.get_ylim()

            coords = np.array([[xlim[0] + ax_offset, ylim[0] + ax_offset],
                               [xlim[0] + ax_offset + sc_size, ylim[0] + ax_offset]
                               ])

            sbar = mlines.Line2D(
                coords[:, 0], coords[:, 1], lw=3, alpha=.9, color='black')
            sbar.set_gid('{0}_um'.format(scalebar))

            ax.add_line(sbar)
        elif method in ['3d', '3d_complex']:
            left = lim_min[0] + ax_offset
            bottom = lim_min[1] + ax_offset
            front = lim_min[2] + ax_offset

            sbar = [np.array([[left, front, bottom],
                              [left, front, bottom]]),
                    np.array([[left, front, bottom],
                              [left, front, bottom]]),
                    np.array([[left, front, bottom],
                              [left, front, bottom]])]
            sbar[0][1][0] += sc_size
            sbar[1][1][1] += sc_size
            sbar[2][1][2] += sc_size

            lc = Line3DCollection(sbar, color='black', lw=1)
            lc.set_gid('{0}_um'.format(scalebar))
            ax.add_collection3d(lc)

    def set_depth():
        """Set depth information for neurons according to camera position."""

        # Modifier for soma coordinates
        modifier = np.array([1, 1, -1])

        # Get all coordinates
        all_co = np.concatenate([lc._segments3d[:, 0, :] for lc in line3D_collections],
                                axis=0)

        # Get projected coordinates
        proj_co = mpl_toolkits.mplot3d.proj3d.proj_points(all_co, ax.get_proj())

        # Get min and max of z coordinates
        z_min, z_max = min(proj_co[:, 2]), max(proj_co[:, 2])

        # Generate a new normaliser
        norm = plt.Normalize(vmin=z_min, vmax=z_max)

        # Go over all neurons and update Z information
        for neuron, lc, surf in zip(skdata,
                                    line3D_collections,
                                    surf3D_collections):
            # Get this neurons coordinates
            this_co = lc._segments3d[:, 0, :]

            # Get projected coordinates
            this_proj = mpl_toolkits.mplot3d.proj3d.proj_points(this_co,
                                                                ax.get_proj())

            # Normalise z coordinates
            ns = norm(this_proj[:, 2]).data

            # Set array
            lc.set_array(ns)

            # No need for normaliser - already happened
            lc.set_norm(None)

            # Get depth of soma(s)
            soma_co = neuron.nodes[neuron.nodes.radius > 1][['x', 'z', 'y']].values
            soma_proj = mpl_toolkits.mplot3d.proj3d.proj_points(soma_co * modifier,
                                                                ax.get_proj())
            soma_cs = norm(soma_proj[:, 2]).data

            # Set soma color
            for cs, s in zip(soma_cs, surf):
                s.set_color(cmap(cs))

    def Update(event):
        set_depth()

    if depth_coloring:
        if method == '2d' and depth_scale:
            fig.colorbar(line, ax=ax, fraction=.075, shrink=.5, label='Depth')
        elif method == '3d':
            fig.canvas.mpl_connect('draw_event', Update)
            set_depth()

    plt.axis('off')

    logger.debug('Done. Use matplotlib.pyplot.show() to show plot.')

    return fig, ax


def _update_axes3d_bounds(ax, points, had_data=False):
    """Update axis bounds and remove default points (0,0,0) and (1,1,1)"""
    if not isinstance(points, np.ndarray):
        points = np.ndarray(points)

    # If this is the first set of points, we need to overwrite the defaults
    # That should happen automatically but for some reason doesn't for 3d axes
    if not had_data:
        mn = points.min(axis=0)
        mx = points.max(axis=0)
        new_xybounds = np.array([[mn[0], mn[1]],
                                  [mx[0], mx[1]]])
        new_zzbounds = np.array([[mn[2], mn[2]],
                                  [mx[2], mx[2]]])
        ax.xy_dataLim.set_points(new_xybounds)
        ax.zz_dataLim.set_points(new_zzbounds)
    else:
        ax.auto_scale_xyz(points[:, 0].tolist(),
                          points[:, 1].tolist(),
                          points[:, 2].tolist(),
                          had_data=True)

    return True

def _fix_default_dict(x):
    """Fix duplicate settings.

    E.g. in scatter kwargs when 'c' and 'color' is provided.

    """
    # The first entry is the "survivor"
    duplicates = [['color', 'c'], ['size', 's']]

    for dupl in duplicates:
        if sum([v in x for v in dupl]) > 1:
            to_delete = [v for v in dupl if v in x][1:]
            _ = [x.pop(v) for v in to_delete]

    return x


def _tn_pairs_to_coords(x, modifier=(1, 1, 1)):
    """Return pairs of treenode -> parent node coordinates.

    Parameters
    ----------
    x :         {pandas DataFrame, CatmaidNeuron}
                Must contain the nodes
    modifier :  ints, optional
                Use to modify/invert x/y/z axes.

    Returns
    -------
    coords :    np.array
                ``[[[x1, y1, z1], [x2, y2, z2]], [[x3, y3, y4], [x4, y4, z4]] ]``

    """
    if not isinstance(modifier, np.ndarray):
        modifier = np.array(modifier)

    nodes = x.nodes[~x.nodes.parent_id.isnull()]
    tn_co = nodes.loc[:, ['x', 'y', 'z']].values
    parent_co = x.nodes.set_index('treenode_id').loc[nodes.parent_id.values,
                                                     ['x', 'y', 'z']].values

    tn_co *= modifier
    parent_co *= modifier

    coords = np.append(tn_co, parent_co, axis=1)

    return coords.reshape((coords.shape[0], 2, 3))


def _segments_to_coords(x, segments, modifier=(1, 1, 1)):
    """Turn lists of treenode_ids into coordinates.

    Parameters
    ----------
    x :         {pandas DataFrame, CatmaidNeuron}
                Must contain the nodes
    segments :  list of treenode IDs
    modifier :  ints, optional
                Use to modify/invert x/y/z axes.

    Returns
    -------
    coords :    list of tuples
                [ (x,y,z), (x,y,z ) ]

    """
    if not isinstance(modifier, np.ndarray):
        modifier = np.array(modifier)

    locs = {r.treenode_id: (r.x, r.y, r.z) for r in x.nodes.itertuples()}

    coords = ([np.array([locs[tn] for tn in s]) * modifier for s in segments])

    return coords


def _random_colors(count, color_space='RGB', color_range=1):
    """Divides colorspace into N evenly distributed colors.

    Returns
    -------
    colormap :  list
                ``[(r, g, b), (r, g, b), ...]``

    """
    if count == 1:
        return [_eval_color(config.default_color, color_range)]

    # Make count_color an even number
    if count % 2 != 0:
        color_count = count + 1
    else:
        color_count = count

    colormap = []
    interval = 2 / color_count
    runs = int(color_count / 2)

    # Create first half with low brightness; second half with high brightness
    # and slightly shifted hue
    if color_space == 'RGB':
        for i in range(runs):
            # High brightness
            h = interval * i
            s = 1
            v = 1
            hsv = colorsys.hsv_to_rgb(h, s, v)
            colormap.append(tuple(v * color_range for v in hsv))

            # Lower brightness, but shift hue by half an interval
            h = interval * (i + 0.5)
            s = 1
            v = 0.5
            hsv = colorsys.hsv_to_rgb(h, s, v)
            colormap.append(tuple(v * color_range for v in hsv))
    elif color_space == 'Grayscale':
        h = 0
        s = 0
        for i in range(color_count):
            v = 1 / color_count * i
            hsv = colorsys.hsv_to_rgb(h, s, v)
            colormap.append(tuple(v * color_range for v in hsv))

    logger.debug('{} random colors created: {}'.format(color_count, colormap))

    # Make sure we return exactly ne number of colors requested
    return colormap[:count]


def _fibonacci_sphere(samples=1, randomize=True):
    """Calculate points on a sphere."""
    rnd = 1.
    if randomize:
        rnd = random.random() * samples

    points = []
    offset = 2. / samples
    increment = math.pi * (3. - math.sqrt(5.))

    for i in range(samples):
        y = ((i * offset) - 1) + (offset / 2)
        r = math.sqrt(1 - pow(y, 2))

        phi = ((i + rnd) % samples) * increment

        x = math.cos(phi) * r
        z = math.sin(phi) * r

        points.append([x, y, z])

    return points


def plot3d(x, **kwargs):
    """Generate 3D plot.

    Uses either `vispy <http://vispy.org>`_ (default) or
    `plotly <http://plot.ly>`_.

    Parameters
    ----------

    x :               skeleton IDs | CatmaidNeuron/List| pymaid.Dotprops | pymaid.Volume | numpy.array
                        - ``int`` is interpreted as skeleton ID(s)
                        - ``str`` is interpreted as volume name(s)
                        - ``numpy.array (N,3)`` is plotted as scatter plot
                        - multiple objects can be passed as list (see examples)
    backend :         'auto' | 'vispy' | 'plotly', default='auto'
                        - ``auto`` selects backend based on context: ``vispy``
                          for terminal and ``plotly`` for Jupyter notebooks.
                        - ``vispy`` uses OpenGL to generate high-performance
                          3D plots. Works in terminals.
                        - ``plotly`` generates 3D plots using WebGL. Works in
                          Jupyter notebooks.
    connectors :      bool, default=False
                      Plot synapses and gap junctions.
    by_strahler :     bool, default=False
                      Will shade neuron(s) by strahler index.
    by_confidence :   bool, default=False
                      Will shade neuron(s) by arbor confidence.
    cn_mesh_colors :  bool, default=False
                      Plot connectors using mesh colors.
    downsampling :    int, default=None
                      Set downsampling of neurons before plotting.
    clear3d :         bool, default=False
                      If True, canvas is cleared before plotting (only for
                      vispy).
    color :           None | str | tuple | list | dict, default=None (random)
                      Use single str (e.g. ``'red'``) or ``(r, g, b)`` tuple
                      to give all neurons the same color. Use ``list`` of
                      colors to assign colors: ``['red', (1, 0, 1), ...].
                      Use ``dict`` to map colors to neurons:
                      ``{skid: (r, g, b), ...}``. RGB must be 0-255.
    use_neuron_color : bool, default=False
                      If True, will try using the ``.color`` attribute of
                      CatmaidNeurons.
    width/height :    int, default=600
                      Use to define figure/window size.
    title :           str, default=None
                      For plotly only! Change plot title.
    fig_autosize :    bool, default=False
                      For plotly only! Autoscale figure size.
                      Attention: autoscale overrides width and height
    scatter_kws :     dict, optional
                      Use to modify scatter plots. Accepted parameters are
                        - ``size`` to adjust size of dots
                        - ``color`` to adjust color
    remote_instance : CatmaidInstance, optional
                      Will try using globally defined CatmaidInstance if not
                      provided.
    plotly_inline :   bool, default=True
                      If True and you are in an Jupyter environment, will
                      render plotly plots inline.
    soma :            bool, default=True
                      If True, will try plotting soma (if exists).

    Returns
    --------
    If ``backend='vispy'``

       Opens a 3D window and returns :class:`pymaid.Viewer`.

    If ``backend='plotly'``

        Returns either ``None`` if you are in a Jupyter notebook (see
        ``plotly_inline`` parameter) or a ``fig`` dictionary to generate
        plotly 3D figure (see examples).

    See Also
    --------
    :class:`pymaid.Viewer`
        Interactive vispy 3D viewer. Makes it easy to add/remove/select
        objects.


    Examples
    --------
    In a Jupyter notebook using plotly as backend.

    >>> import plotly.offline
    >>> plotly.offline.init_notebook_mode()
    >>> nl = pymaid.get_neuron(16)
    >>> # Backend is automatically chosen but we can set it explicitly
    >>> # Plot inline
    >>> nl.plot3d(backend='plotly')
    >>> # Plot as separate html in a new window
    >>> fig = nl.plot3d(backend='plotly', plotly_inline=False)
    >>> plotly.offline.plot(fig)

    In a terminal using vispy as backend.

    >>> # Plot single neuron
    >>> nl = pymaid.get_neuron(16)
    >>> v = pymaid.plot3d(nl, backend='vispy')
    >>> # Clear canvas
    >>> pymaid.clear3d()

    Some more advanced examples (using vispy here but also works with plotly).

    >>> # plot3d() can deal with combinations of objects
    >>> nl2 = pymaid.get_neuron('annotation:glomerulus DA1')
    >>> vol = pymaid.get_volume('v13.LH_R')
    >>> vol.color = (255, 0, 0, .5)
    >>> # This plots two neuronlists, two volumes and a single neuron
    >>> pymaid.plot3d([nl1, nl2, vol, 'v13.AL_R', 233007])
    >>> # Pass kwargs
    >>> pymaid.plot3d(nl1, connectors=True, clear3d=True)

    """
    def _plot3d_vispy():
        """
        Plot3d() helper function to generate vispy 3D plots. This is just to
        improve readability.
        """
        if kwargs.get('clear3d', False):
            clear3d()

        # If does not exists yet, initialise a canvas object and make global
        if 'viewer' not in globals():
            global viewer
            viewer = scene3d.Viewer()
        else:
            viewer = globals()['viewer']
            # Make sure viewer is visible
            viewer.show()

        if skdata:
            viewer.add(skdata, **kwargs)
        if not dotprops.empty:
            viewer.add(dotprops, **kwargs)
        if volumes:
            viewer.add(volumes, **kwargs)
        if points:
            viewer.add(points, scatter_kws=scatter_kws)

        return viewer

    def _plot3d_plotly():
        """
        Plot3d() helper function to generate plotly 3D plots. This is just to
        improve readability and structure of the code.
        """
        trace_data = []

        # Generate sphere for somas
        fib_points = _fibonacci_sphere(samples=30)

        # Generate the colormaps
        neuron_cmap, dotprop_cmap = _prepare_colormap(color,
                                                      skdata, dotprops,
                                                      use_neuron_color=use_neuron_color,
                                                      color_range=255)

        for i, neuron in enumerate(skdata.itertuples()):
            logger.debug('Working on neuron {}'.format(neuron.skeleton_id))

            neuron_name = neuron.neuron_name
            skid = neuron.skeleton_id

            if not connectors_only:
                if neuron.nodes.empty:
                    logger.warning('Neuron {} has no nodes - skipping'.format(neuron.skeleton_id))
                    continue

                # Generate coordinates along segments
                coords = _segments_to_coords(neuron, neuron.segments,
                                             modifier=(-1, -1, -1))

                # We have to add (None, None, None) to the end of each slab to
                # make that line discontinuous there
                coords = np.vstack([np.append(t, [[None] * 3], axis=0) for t in coords])

                if by_strahler:
                    if 'strahler_index' not in neuron.nodes.columns:
                        morpho.strahler_index(neuron, inplace=True)

                    # Prepare strahler indices
                    s_index = neuron.nodes.set_index('treenode_id').strahler_index.to_dict()
                    max_si = neuron.nodes.strahler_index.max()
                    s_index_norm = {k: v / max_si for k,v in s_index.items()}

                    # Get node IDs along the segments and add the "(None, None, None)"
                    node_ids = np.hstack([np.append(s, [None], axis=0) for s in neuron.segments])

                    # Get alpha values
                    alpha = [s_index_norm.get(n, 1) for n in node_ids]

                    # Generate colors
                    bc = 'rgba({:d},{:d},{:d},'.format(*neuron_cmap[i][:3])
                    c = [bc + '{:f})'.format(a) for a in alpha]
                else:
                    try:
                        c = 'rgb{}'.format(neuron_cmap[i])
                    except BaseException:
                        c = 'rgb(10,10,10)'

                trace_data.append(go.Scatter3d(x=coords[:, 0],
                                               # y and z are switched
                                               y=coords[:, 2],
                                               z=coords[:, 1],
                                               mode='lines',
                                               line=dict(color=c,
                                                         width=linewidth),
                                               name=neuron_name,
                                               legendgroup=neuron_name,
                                               showlegend=True,
                                               hoverinfo='none'
                                               ))

                # Add soma(s):
                if neuron.soma and kwargs.get('soma', True):
                    for s in utils._make_iterable(neuron.soma):
                        n = neuron.nodes.set_index('treenode_id').loc[s]
                        try:
                            c = 'rgb{}'.format(neuron_cmap[i])
                        except BaseException:
                            c = 'rgb(10,10,10)'
                        trace_data.append(go.Mesh3d(
                            x=[(v[0] * n.radius / 2) - n.x for v in fib_points],
                            # y and z are switched
                            y=[(v[1] * n.radius / 2) - n.z for v in fib_points],
                            z=[(v[2] * n.radius / 2) - n.y for v in fib_points],

                            alphahull=.5,
                            color=c,
                            name=neuron_name,
                            hoverinfo='name'))

            if connectors or connectors_only:
                for j in [0, 1, 2]:
                    if cn_mesh_colors:
                        try:
                            c = neuron_cmap[i]
                        except BaseException:
                            c = (10, 10, 10)
                    else:
                        c = syn_lay[j]['color']

                    this_cn = neuron.connectors[
                        neuron.connectors.relation == j]

                    if syn_lay['display'] == 'circles':
                        trace_data.append(go.Scatter3d(
                            x=this_cn.x.values * -1,
                            y=this_cn.z.values * -1,  # y and z are switched
                            z=this_cn.y.values * -1,
                            mode='markers',
                            marker=dict(
                                color='rgb%s' % str(c),
                                size=2
                            ),
                            name=syn_lay[j]['name'] + ' of ' + neuron_name,
                            showlegend=True,
                            hoverinfo='none'
                        ))
                    elif syn_lay['display'] == 'lines':
                        # Find associated treenode
                        tn = neuron.nodes.set_index('treenode_id').ix[this_cn.treenode_id.values]
                        x_coords = [n for sublist in zip(this_cn.x.values * -1, tn.x.values * -1, [None] * this_cn.shape[0]) for n in sublist]
                        y_coords = [n for sublist in zip(this_cn.y.values * -1, tn.y.values * -1, [None] * this_cn.shape[0]) for n in sublist]
                        z_coords = [n for sublist in zip(this_cn.z.values * -1, tn.z.values * -1, [None] * this_cn.shape[0]) for n in sublist]

                        trace_data.append(go.Scatter3d(
                            x=x_coords,
                            y=z_coords,  # y and z are switched
                            z=y_coords,
                            mode='lines',
                            line=dict(
                                color='rgb%s' % str(c),
                                width=5
                            ),
                            name=syn_lay[j]['name'] + ' of ' + neuron_name,
                            showlegend=True,
                            hoverinfo='none'
                        ))

        for i, neuron in enumerate(dotprops.itertuples()):
            # Prepare lines - this is based on nat:::plot3d.dotprops
            halfvect = neuron.points[
                ['x_vec', 'y_vec', 'z_vec']] / 2 * scale_vect

            starts = neuron.points[['x', 'y', 'z']
                                   ].values - halfvect.values
            ends = neuron.points[['x', 'y', 'z']
                                 ].values + halfvect.values

            x_coords = [n for sublist in zip(
                starts[:, 0] * -1, ends[:, 0] * -1, [None] * starts.shape[0]) for n in sublist]
            y_coords = [n for sublist in zip(
                starts[:, 1] * -1, ends[:, 1] * -1, [None] * starts.shape[0]) for n in sublist]
            z_coords = [n for sublist in zip(
                starts[:, 2] * -1, ends[:, 2] * -1, [None] * starts.shape[0]) for n in sublist]

            try:
                c = 'rgb{}'.format(dotprop_cmap[i])
            except BaseException:
                c = 'rgb(10,10,10)'

            trace_data.append(go.Scatter3d(x=x_coords, y=z_coords, z=y_coords,
                                           mode='lines',
                                           line=dict(
                                               color=c,
                                               width=5
                                           ),
                                           name=neuron.gene_name,
                                           legendgroup=neuron.gene_name,
                                           showlegend=True,
                                           hoverinfo='none'
                                           ))

            # Add soma
            rad = 4
            trace_data.append(go.Mesh3d(
                x=[(v[0] * rad / 2) - neuron.X for v in fib_points],
                # y and z are switched
                y=[(v[1] * rad / 2) - neuron.Z for v in fib_points],
                z=[(v[2] * rad / 2) - neuron.Y for v in fib_points],

                alphahull=.5,

                color=c,
                name=neuron.gene_name,
                hoverlabel='name'
            )
            )

        # Now add neuropils:
        for v in volumes_data:
            # Skip empty data
            if isinstance(volumes_data[v]['verts'], np.ndarray):
                if not volumes_data[v]['verts'].any():
                    continue
            elif not volumes_data[v]['verts']:
                continue

            c = volumes_data[v]['color']
            if len(c) == 3:
                c = (c[0], c[1], c[2], .5)

            trace_data.append(go.Mesh3d(
                x=[-v[0] for v in volumes_data[v]['verts']],
                # y and z are switched
                y=[-v[2] for v in volumes_data[v]['verts']],
                z=[-v[1] for v in volumes_data[v]['verts']],

                i=[f[0] for f in volumes_data[v]['faces']],
                j=[f[1] for f in volumes_data[v]['faces']],
                k=[f[2] for f in volumes_data[v]['faces']],

                opacity=.5,
                color='rgba' + str(c),
                name=v,
                hoverinfo='none'
            )
            )

        # Add scatter plots
        for p in points:
            trace_data.append(go.Scatter3d(x=-p[:, 0],
                                           y=-p[:, 2], # Z and Y are swapped
                                           z=-p[:, 1],
                                           mode='markers',
                                           marker=dict(
                                                       size=scatter_kws.get('size',3),
                                                       color='rgb' + str(scatter_kws.get('color',(0, 0, 0))),
                                                       opacity=scatter_kws.get('opacity',1))
                                           )
                             )

        layout = dict(
            width=width,
            height=height,
            autosize=fig_autosize,
            title=pl_title,
            scene=dict(
                xaxis=dict(
                    gridcolor='rgb(255, 255, 255)',
                    zerolinecolor='rgb(255, 255, 255)',
                    showbackground=True,
                    backgroundcolor='rgb(240, 240, 240)',
                ),
                yaxis=dict(
                    gridcolor='rgb(255, 255, 255)',
                    zerolinecolor='rgb(255, 255, 255)',
                    showbackground=True,
                    backgroundcolor='rgb(240, 240, 240)',
                ),
                zaxis=dict(
                    gridcolor='rgb(255, 255, 255)',
                    zerolinecolor='rgb(255, 255, 255)',
                    showbackground=True,
                    backgroundcolor='rgb(240, 240, 240)',
                ),
                camera=dict(up=dict(x=0,
                                    y=0,
                                    z=1
                                    ),
                            eye=dict(x=-1.7428,
                                     y=1.0707,
                                     z=0.7100,
                                     )
                            ),
                aspectratio=dict(x=1, y=1, z=1),
                aspectmode='data'
            ),
        )

        # Need to remove width and height to make autosize actually matter
        if fig_autosize:
            layout.pop('width')
            layout.pop('height')

        fig = dict(data=trace_data, layout=layout)

        logger.debug('Done. Plotted %i nodes and %i connectors' % (sum([n.nodes.shape[0] for n in skdata.itertuples() if not connectors_only] + [
            n.points.shape[0] for n in dotprops.itertuples()]), sum([n.connectors.shape[0] for n in skdata.itertuples() if connectors or connectors_only])))

        if plotly_inline and utils.is_jupyter():
            plotly.offline.iplot(fig)
            return
        else:
            logger.info('Use plotly.offline.plot(fig, filename="3d_plot.html")'
                        ' to plot. Optimized for Google Chrome.')
            return fig

    skids, skdata, dotprops, volumes, points, visual = utils._parse_objects(x)

    # Backend
    backend = kwargs.get('backend', 'auto')
    if backend == 'auto':
        if utils.is_jupyter():
            backend = 'plotly'
        else:
            backend = 'vispy'
    elif backend not in ['plotly', 'vispy']:
        raise ValueError('Unknown backend: {}. See help(plot.plot3d).'.format(backend))

    # CatmaidInstance
    remote_instance = kwargs.get('remote_instance', None)

    # Parameters for neurons
    color = kwargs.get('color',
                       kwargs.get('c',
                                  kwargs.get('colors', None)))
    downsampling = kwargs.get('downsampling', 1)
    connectors = kwargs.get('connectors', False)
    by_strahler = kwargs.get('by_strahler', False)
    by_confidence = kwargs.get('by_confidence', False)
    cn_mesh_colors = kwargs.get('cn_mesh_colors', False)
    linewidth = kwargs.get('linewidth', 2)
    connectors_only = kwargs.get('connectors_only', False)
    use_neuron_color = kwargs.get('use_neuron_color', False)
    scatter_kws = kwargs.get('scatter_kws', {})
    syn_lay_new = kwargs.get('synapse_layout', {})
    syn_lay = {0: {'name': 'Presynapses',
                   'color': (255, 0, 0)},
               1: {'name': 'Postsynapses',
                   'color': (0, 0, 255)},
               2: {'name': 'Gap junctions',
                   'color': (0, 255, 0)},
               'display': 'lines'  # 'circles'
               }
    syn_lay.update(syn_lay_new)

    # Parameters for dotprops
    scale_vect = kwargs.get('scale_vect', 1)

    # Parameters for figure
    pl_title = kwargs.get('title', None)
    width = kwargs.get('width', 1000)
    height = kwargs.get('height', 600)
    fig_autosize = kwargs.get('fig_autosize', False)
    auto_limits = kwargs.get('auto_limits', True)
    auto_limits = kwargs.get('autolimits', auto_limits)
    plotly_inline = kwargs.get('plotly_inline', True)

    if not remote_instance and isinstance(skdata, core.CatmaidNeuronList):
        try:
            remote_instance = skdata._remote_instance
        except BaseException:
            pass

    remote_instance = utils._eval_remote_instance(remote_instance,
                                                  raise_error=False)

    if skids and remote_instance:
        skdata += fetch.get_neuron(skids,
                                   with_connectors=True,
                                   with_tags=False,
                                   with_history=False,
                                   with_abutting=True,
                                   remote_instance=remote_instance)
    elif skids and not remote_instance:
        raise BaseException('You need to provide a CATMAID remote instance.')

    # Get and prepare volumes
    volumes_data = {}
    for v in volumes:
        if isinstance(v, str):
            if not remote_instance:
                logger.error('Unable to add volumes - please also pass a '
                             'CatmaidInstance using <remote_instance = ... >')
                return
            else:
                v = fetch.get_volume(v, remote_instance=remote_instance)

        volumes_data[v.name] = {'verts': v.vertices,
                                'faces': v.faces,
                                'color': v.color}

    # First downsample neurons
    if downsampling > 1 and not connectors_only and not skdata.empty:
        morpho.logger.setLevel('ERROR')
        skdata.downsample(downsampling, inplace=True)
        morpho.logger.setLevel('INFO')

    if backend == 'plotly':
        return _plot3d_plotly()
    else:
        return _plot3d_vispy()


def _prepare_colormap(colors, skdata=None, dotprops=None,
                      use_neuron_color=False, color_range=255):
    """Map color(s) to neuron/dotprop colorlists."""

    # Prepare dummies in case either no skdata or no dotprops
    if isinstance(skdata, type(None)):
        skdata = core.CatmaidNeuronList([])

    if isinstance(dotprops, type(None)):
        dotprops = core.Dotprops()
        dotprops['gene_name'] = []

    # If no colors, generate random colors
    if isinstance(colors, type(None)):
        if (skdata.shape[0] + dotprops.shape[0]) > 0:
            colors = _random_colors(skdata.shape[0] + dotprops.shape[0],
                                    color_space='RGB', color_range=color_range)
        else:
            # If no neurons to plot, just return None
            # This happens when there is only a scatter plot
            return [None], [None]
    else:
        colors = _eval_color(colors, color_range=color_range)

    # In order to cater for duplicate skeleton IDs in skdata (e.g. from
    # splitting into fragments), we will not map skids to colors but instead
    # keep colors as a list. That way users can pass a simple list of colors.

    # If dictionary, map skids to dotprops gene names and neuron skeleton IDs
    dotprop_cmap = []
    neuron_cmap = []
    if isinstance(colors, dict):
        # We will try to get the skid first as str, then as int
        neuron_cmap = [colors.get(s,
                                  colors.get(int(s),
                                             _eval_color(config.default_color,
                                                         color_range)))
                       for s in skdata.skeleton_id]
        dotprop_cmap = [colors.get(s,
                                   _eval_color(config.default_color,
                                               color_range))
                        for s in dotprops.gene_name.values]
    elif isinstance(colors, mcl.Colormap):
        neuron_cmap = [colors(i/len(skdata)) for i in range(len(skdata))]
        dotprop_cmap = [colors(i/dotprops.shape[0]) for i in range(dotprops.shape[0])]
    # If list of colors
    elif isinstance(colors, (list, tuple, np.ndarray)):
        colors_required = skdata.shape[0] + dotprops.shape[0]

        # If color is a single color, convert to list
        if all([isinstance(elem, numbers.Number) for elem in colors]):
            colors = [colors] * colors_required
        elif len(colors) < colors_required:
            raise ValueError('Need colors for {} neurons/dotprops, got '
                             '{}'.format(colors_required, len(colors)))
        elif len(colors) > colors_required:
            logger.debug('More colors than required: got {}, needed '
                         '{}'.format(len(colors), colors_required))

        if skdata.shape[0]:
            neuron_cmap = [colors[i] for i in range(skdata.shape[0])]
        if dotprops.shape[0]:
            dotprop_cmap = [colors[i + skdata.shape[0]] for i in range(dotprops.shape[0])]
    else:
        raise TypeError('Got colors of type "{}"'.format(type(colors)))

    # Override neuron cmap if we are supposed to use neuron colors
    if use_neuron_color:
        neuron_cmap = [n.getattr('color',
                                 _eval_color(config.default_color,
                                             color_range))
                       for i, n in enumerate(skdata)]

    return neuron_cmap, dotprop_cmap


def _eval_color(x, color_range=255):
    """Evaluate color and force to r/g/b tuple."""
    if color_range not in [1, 255]:
        raise ValueError('color_range must be 1 or 255')

    if isinstance(x, str):
        # Check if named color
        if mcl.is_color_like(x):
            c = mcl.to_rgb(x)
        # Assume it's a matplotlib color map
        else:
            try:
                c = plt.get_cmap(x)
            except ValueError:
                raise ValueError('Unable to interpret color "{}"'.format(x))
            except BaseException:
                raise
    elif isinstance(x, dict):
        return {k: _eval_color(v, color_range=color_range) for k, v in x.items()}
    elif isinstance(x, (list, tuple, np.ndarray)):
        # If is this is not a list of RGB values:
        if any([not isinstance(elem, numbers.Number) for elem in x]):
            return [_eval_color(c, color_range=color_range) for c in x]
        # If this is a single RGB color:
        c = x
    elif isinstance(x, type(None)):
        return None
    else:
        raise TypeError('Unable to interpret color of type '
                        '"{}"'.format(type(x)))

    if not isinstance(c, mcl.Colormap):
        # Check if we need to convert
        if not any([v > 1 for v in c]) and color_range == 255:
            c = [int(v * 255) for v in c]
        elif any([v > 1 for v in c]) and color_range == 1:
            c = [v / 255 for v in c]
        c = tuple(c)

    return c


def plot_network(x, **kwargs):
    """Use NetworkX to generate a Plotly network plot.

    The purpose of this function is to have a quick 'n dirty look at your
    neurons' connectivity. For higher quality, interactive visualizations
    have a look at `Cytoscape <http://cytoscape.org/>`_.


    Parameters
    ----------
    x
                      Neurons as list of either:

                      1. skeleton IDs (int or str)
                      2. neuron names (str, exact match)
                      3. annotation: e.g. ``'annotation:PN right'``
                      4. CatmaidNeuronList object
                      5. pandas.DataFrame containing an adjacency matrix.,
                         e.g. from :funct:`~pymaid.create_adjacency_matrix`
                      6. NetworkX Graph
    layout :          str | function, default = nx.spring_layout
                      Layout function. See `here <https://networkx.github.io/documentation/latest/reference/drawing.html>`_
                      for available layouts. Use either the function directly
                      or its name.
    syn_cutoff :      int, default=False
                      If provided, connections will be maxed at this value.
    syn_threshold :   int, default=0
                      Edges with less connections are ignored.
    groups :          dict
                      Use to group neurons. Format:
                      ``{'Group A': [skid1, skid2, ...], ...}``
    colormap :        str | tuple, dict
                | Set to 'random' (default) to assign random colors to neurons
                | Use single tuple to assign the same color to all neurons:
                | e.g. ``(220, 10, 50)``
                | Use dict to assign rgb colors to individual neurons:
                | e.g. ``{ neuron1: (200, 200, 0), ...}``
    label_nodes :     bool, default=True
                      Plot neuron labels.
    label_edges :     bool, default=True
                      Plot edge labels.
    width,height :    int, default=800
                      Figure width and height.
    node_hover_text : dict
                      Provide custom hover text for neurons:
                      ``{neuron1: 'hover text', ...}``
    node_size :       int | dict
                      | Use int to set node size once.
                      | Use dict to set size for individual nodes:
                      | ``{neuron1: 20, neuron2: 5, ...}``

    Returns
    -------
    fig : plotly dict
       Use for example ``plotly.offline.plot(fig, filename='plot.html')`` to
       generate html file and open it webbrowser.

    """
    remote_instance = kwargs.get('remote_instance', None)

    layout = kwargs.get('layout', nx.spring_layout)

    if isinstance(layout, str):
        layout = getattr(nx, layout)

    syn_cutoff = kwargs.get('syn_cutoff', None)
    syn_threshold = kwargs.get('syn_threshold', 1)
    colormap = kwargs.get('colormap', 'random')

    label_nodes = kwargs.get('label_nodes', True)
    label_edges = kwargs.get('label_edges', True)
    label_hover = kwargs.get('label_hover', True)

    node_hover_text = kwargs.get('node_hover_text', [])
    node_size = kwargs.get('node_size', 20)

    width = kwargs.get('width', 800)
    height = kwargs.get('height', 800)

    remote_instance = utils._eval_remote_instance(remote_instance)

    if not isinstance(x, (nx.DiGraph, nx.Graph)):
        x = utils.eval_skids(x, remote_instance=remote_instance)
        g = graph.network2nx(x, threshold=syn_threshold)
    else:
        g = x

    pos = layout(g)

    # Prepare colors
    if isinstance(colormap, dict):
        colors = colormap
        # Give grey color to neurons that are not in colormap
        colors.update({n: (.5, .5, .5) for n in g.nodes if n not in colormap})
    elif colormap == 'random':
        c = _random_colors(len(g.nodes), color_space='RGB', color_range=255)
        colors = {n: c[i] for i, n in enumerate(g.nodes)}
    elif isinstance(colormap, (tuple,
                               list,
                               np.ndarray)) and len(colormap) == 3:
        colors = {n: tuple(colormap) for n in g.nodes}
    else:
        logger.error('I dont understand the colors you have provided. Please, '
                     'see help(pymaid.plot_network).')
        return None

    edges = []
    annotations = []
    try:
        max_weight = max(nx.get_edge_attributes(g, 'weight').values())
    except BaseException:
        # This will fail if there are no edges
        max_weight = 1
    for e in list(g.edges.data()):
        e_width = 2 + 5 * round(e[2]['weight']) / max_weight

        edges.append(
            go.Scatter(dict(
                x=[pos[e[0]][0], pos[e[1]][0], None],
                y=[pos[e[0]][1], pos[e[1]][1], None],
                mode='lines',
                hoverinfo='text',
                text=str(e[2]['weight']),
                line=dict(
                    width=e_width,
                    color='rgb(255,0,0)'
                )
            ))
        )

        annotations.append(dict(
            x=pos[e[1]][0],
            y=pos[e[1]][1],
            xref='x',
            yref='y',
            showarrow=True,
            align='center',
            arrowhead=2,
            arrowsize=.5,
            arrowwidth=e_width,
            arrowcolor='#636363',
            ax=pos[e[0]][0],
            ay=pos[e[0]][1],
            axref='x',
            ayref='y',
            standoff=10,
            startstandoff=10,
            opacity=.7

        ))

        if label_edges:
            center_x = (pos[e[1]][0] - pos[e[0]]
                        [0]) / 2 + pos[e[0]][0]
            center_y = (pos[e[1]][1] - pos[e[0]]
                        [1]) / 2 + pos[e[0]][1]

            if e[2]['weight'] == syn_cutoff:
                t = '%i +' % int(e[2]['weight'])
            else:
                t = str(int(e[2]['weight']))

            annotations.append(dict(
                x=center_x,
                y=center_y,
                xref='x',
                yref='y',
                showarrow=False,
                text=t,
                font=dict(color='rgb(0,0,0)', size=10)
            )

            )

    # Prepare hover text
    if not node_hover_text:
        node_hover_text = {n: g.nodes[n]['neuron_name'] for n in g.nodes}
    else:
        # Make sure all nodes are represented
        node_hover_text.update({n: g.nodes[n]['neuron_name']
                                for n in g.nodes if n not in node_hover_text})

    # Prepare node sizes
    if isinstance(node_size, dict):
        n_size = [node_size[n] for n in g.nodes]
    else:
        n_size = node_size

    nodes = go.Scatter(dict(
        x=np.vstack(pos.values())[:, 0],
        y=np.vstack(pos.values())[:, 1],
        text=[node_hover_text[n] for n in g.nodes] if label_hover else None,
        mode='markers',
        hoverinfo='text',
        marker=dict(
            size=n_size,
            color=['rgb' + str(tuple(colors[n])) for n in g.nodes]
        )
    ))

    if label_nodes:
        annotations += [dict(
            x=pos[n][0],
            y=pos[n][1],
            xref='x',
            yref='y',
            text=g.nodes[n]['neuron_name'],
            showarrow=False,
            font=dict(color='rgb(0,0,0)', size=12)
        )
            for n in pos]

    layout = dict(
        width=width,
        height=height,
        showlegend=False,
        annotations=annotations,
        xaxis=dict(
            showline=False,
            zeroline=False,
            showgrid=False,
            showticklabels=False,
            title=''
        ),
        yaxis=dict(
            showline=False,
            zeroline=False,
            showgrid=False,
            showticklabels=False,
            title=''
        ),
        hovermode='closest'
    )

    data = go.Data([nodes])

    fig = go.Figure(data=data, layout=layout)

    logger.info('Done! Use e.g. plotly.offline.plot(fig, '
                'filename="network_plot.html") to plot.')

    return fig


def plot1d(x, ax=None, color=None, **kwargs):
    """Plot neuron topology in 1D according to Cuntz et al. (2010).

    This function breaks a neurons into segments between branch points.
    See Cuntz et al., PLoS Computational Biology (2010) for detailed
    explanation. For very complex neurons, the neuron "barcode"

    Parameters
    ----------
    x :         CatmaidNeuron | CatmaidNeuronList
                Neuron(s) to plot.
    ax :        matplotlib.ax, optional
    cmap :      tuple | dict
                Color. If dict must map skeleton ID to color.
    **kwargs
                Will be passed to ``matplotlib.patches.Rectangle``.

    Returns
    -------
    matplotlib.ax

    Examples
    --------
    >>> import matplotlib.pyplot as plt
    >>> n = pymaid.get_neuron(16)
    >>> ax = pymaid.plot1d(n)
    >>> plt.show()

    """
    if isinstance(x, core.CatmaidNeuronList):
        pass
    elif isinstance(x, core.CatmaidNeuron):
        x = core.CatmaidNeuronList(x)
    else:
        raise TypeError(
            'Unable to work with data of type "{0}"'.format(type(x)))

    if isinstance(color, type(None)):
        color = (0.56, 0.86, 0.34)

    if not ax:
        fig, ax = plt.subplots(figsize=(8, len(x) / 3))

    # Add some default parameters for the plotting to kwargs
    kwargs.update({'lw': kwargs.get('lw', .1),
                   'ec': kwargs.get('ec', (1, 1, 1)),
                   })

    max_x = []
    for ix, n in enumerate(config.tqdm(x, desc='Processing',
                                       disable=config.pbar_hide,
                                       leave=config.pbar_leave)):
        if isinstance(color, dict):
            this_c = color[n.skeleton_id]
        else:
            this_c = color

        # Get topological sort (root -> terminals)
        topology = graph_utils.node_label_sorting(n)

        # Get terminals and branch points
        bp = n.nodes[n.nodes.type == 'branch'].treenode_id.values
        term = n.nodes[n.nodes.type == 'end'].treenode_id.values

        # Order this neuron's segments by topology
        breaks = [topology[0]] + \
            [n for i, n in enumerate(topology) if n in bp or n in term]
        segs = [([s for s in n.small_segments if s[0] == end][0][-1], end)
                for end in breaks[1:]]

        # Now get distances for each segment
        if 'nodes_geodesic_distance_matrix' in n.__dict__:
            # If available, use geodesic distance matrix
            dist_mat = n.nodes_geodesic_distance_matrix
        else:
            # If not, compute matrix for subset of nodes
            dist_mat = graph_utils.geodesic_matrix(
                n, tn_ids=breaks, directed=False)

        dist = np.array([dist_mat.loc[s[0], s[1]] for s in segs]) / 1000
        max_x.append(sum(dist))

        # Plot
        curr_dist = 0
        for k, d in enumerate(dist):
            if segs[k][1] in term:
                c = tuple(np.array(this_c) / 2)
            else:
                c = color

            p = mpatches.Rectangle((curr_dist, ix), d, 1, fc=c, **kwargs)
            ax.add_patch(p)
            curr_dist += d

    ax.set_xlim(0, max(max_x))
    ax.set_ylim(0, len(x))

    ax.set_yticks(np.array(range(0, len(x))) + .5)
    ax.set_yticklabels(x.neuron_name)

    ax.set_xlabel('distance [um]')

    ax.set_frame_on(False)

    try:
        plt.tight_layout()
    except BaseException:
        pass

    return ax


def _volume2vispy(x, **kwargs):
    """Convert CatmaidVolume(s) to vispy visuals."""

    # Must not use _make_iterable here as this will turn into list of keys!
    if not isinstance(x, (list, np.ndarray)):
        x = [x]

    # List to fill with vispy visuals
    visuals = []

    # Now add neuropils:
    for v in x:
        if not isinstance(v, core.Volume):
            raise TypeError('Expected pymaid.Volume, got "{}"'.format(type(v)))

        object_id = uuid.uuid4()

        color = np.array(v.color, dtype=float)

        # Add alpha
        if len(color) < 4:
            color = np.append(color, [.6])

        if max(color) > 1:
            color[:3] = color[:3] / 255

        s = scene.visuals.Mesh(vertices=v.vertices,
                               faces=v.faces, color=color,
                               shading=kwargs.get('shading', 'smooth'))

        # Set some aesthetic parameters
        s.shininess = 0
        s.set_gl_state('translucent', cull_face=True, depth_test=False)

        # Make sure volumes are always drawn after neurons
        s.order = 10

        # Add custom attributes
        s.unfreeze()
        s._object_type = 'catmaid_volume'
        s._volume_name = v.name
        s._object_id = object_id
        s.freeze()

        visuals.append(s)

    return visuals


def _neuron2vispy(x, **kwargs):
    """Convert a CatmaidNeuron/List to vispy visuals.

    Parameters
    ----------
    x :               CatmaidNeuron | CatmaidNeuronList
                      Neuron(s) to plot.
    color :           list | tuple | array | str
                      Color to use for plotting.
    colormap :        tuple | dict | array
                      Color to use for plotting. Dictionaries should be mapped
                      by skeleton ID. Overrides ``color``.
    connectors :      bool, optional
                      If True, plot connectors.
    connectors_only : bool, optional
                      If True, only connectors are plotted.
    by_strahler :     bool, optional
                      If True, shade neurites by strahler order.
    by_confidence :   bool, optional
                      If True, shade neurites by confidence.
    linewidth :       int, optional
                      Set linewidth. Might not work depending on your backend.
    cn_mesh_colors :  bool, optional
                      If True, connectors will have same color as the neuron.
    soma :            bool, optional
    synapse_layout :  dict, optional
                      Sets synapse layout. Default settings::
                        {
                            0: {
                                'name': 'Presynapses',
                                'color': (255, 0, 0)
                                },
                            1: {
                                'name': 'Postsynapses',
                                'color': (0, 0, 255)
                                },
                            2: {
                                'name': 'Gap junctions',
                                'color': (0, 255, 0)
                                },
                            'display': 'lines'  # 'circles'
                        }

    Returns
    -------
    list
                    Contains vispy visuals for each neuron.

    """
    if isinstance(x, core.CatmaidNeuron):
        x = core.CatmaidNeuronList(x)
    elif isinstance(x, core.CatmaidNeuronList):
        pass
    else:
        raise TypeError('Unable to process data of type "{}"'.format(type(x)))

    colors = kwargs.get('color',
                        kwargs.get('c',
                                   kwargs.get('colors', None)))

    colormap, _ = _prepare_colormap(colors,
                                    x, None,
                                    use_neuron_color=kwargs.get('use_neuron_color', False),
                                    color_range=1)

    syn_lay = {
        0: {
            'name': 'Presynapses',
            'color': (1, 0, 0)
        },
        1: {
            'name': 'Postsynapses',
            'color': (0, 0, 1)
        },
        2: {
            'name': 'Gap junctions',
            'color': (0, 1, 0)
        },
        'display': 'lines'  # 'circle'
    }
    syn_lay.update(kwargs.get('synapse_layout', {}))

    # List to fill with vispy visuals
    visuals = []

    for i, neuron in enumerate(x):
        # Generate random ID -> we need this in case we have duplicate
        # skeleton IDs
        object_id = uuid.uuid4()

        neuron_color = colormap[i]

        # Convert color 0-1
        if max(neuron_color) > 1:
            neuron_color = np.array(neuron_color) / 255

        # Get root node indices (may be more than one if neuron has been
        # cut weirdly)
        root_ix = neuron.nodes[
            neuron.nodes.parent_id.isnull()].index.tolist()

        if not kwargs.get('connectors_only', False):
            nodes = neuron.nodes[~neuron.nodes.parent_id.isnull()]

            # Extract treenode_coordinates and their parent's coordinates
            tn_coords = nodes[['x', 'y', 'z']].apply(
                pd.to_numeric).values
            parent_coords = neuron.nodes.set_index('treenode_id').loc[nodes.parent_id.values][['x', 'y', 'z']].apply(pd.to_numeric).values

            # Turn coordinates into segments
            segments = [item for sublist in zip(
                tn_coords, parent_coords) for item in sublist]

            # Add alpha to color based on strahler
            if kwargs.get('by_strahler', False) \
                    or kwargs.get('by_confidence', False):
                if kwargs.get('by_strahler', False):
                    if 'strahler_index' not in neuron.nodes:
                        morpho.strahler_index(neuron)

                    # Generate list of alpha values
                    alpha = neuron.nodes['strahler_index'].values

                if kwargs.get('by_confidence', False):
                    if 'arbor_confidence' not in neuron.nodes:
                        morpho.arbor_confidence(neuron)

                    # Generate list of alpha values
                    alpha = neuron.nodes['arbor_confidence'].values

                # Pop root from coordinate lists
                alpha = np.delete(alpha, root_ix, axis=0)

                alpha = alpha / (max(alpha) + 1)
                # Duplicate values (start and end of each segment!)
                alpha = np.array([v for l in zip(alpha, alpha) for v in l])

                # Turn color into array
                # (need 2 colors per segment for beginning and end)
                neuron_color = np.array(
                    [neuron_color] * (tn_coords.shape[0] * 2), dtype=float)
                neuron_color = np.insert(neuron_color, 3, alpha, axis=1)

            if segments:
                if not kwargs.get('use_radius', False):
                    # Create line plot from segments.
                    t = scene.visuals.Line(pos=np.array(segments),
                                           color=list(neuron_color),
                                           # Can only be used with method 'agg'
                                           width=kwargs.get('linewidth', 1),
                                           connect='segments',
                                           antialias=True,
                                           method='gl')
                    # method can also be 'agg' -> has to use connect='strip'
                    # I don't think this works with 3D lines though

                    # Make visual discoverable
                    t.interactive = True

                    # Add custom attributes
                    t.unfreeze()
                    t._object_type = 'neuron'
                    t._neuron_part = 'neurites'
                    t._skeleton_id = neuron.skeleton_id
                    t._neuron_name = neuron.neuron_name
                    t._object_id = object_id
                    t.freeze()

                    visuals.append(t)
                else:
                    coords = _segments_to_coords(neuron,
                                                 neuron.segments,
                                                 modifier=(1, 1, 1))
                    nodes = neuron.nodes.set_index('treenode_id')
                    radii = [nodes.loc[s, 'radius'].values.astype(float) for s in neuron.segments]

                    t = MeshNeuron(coords,
                                   radii=radii,
                                   color=neuron_color,
                                   use_normals=kwargs.get('use_normals', True),
                                   tube_points=kwargs.get('tube_points', 5))

                    # Add custom attributes
                    t.unfreeze()
                    t._object_type = 'neuron'
                    t._neuron_part = 'neurites'
                    t._skeleton_id = neuron.skeleton_id
                    t._neuron_name = neuron.neuron_name
                    t._object_id = object_id
                    t.freeze()

                    visuals.append(t)

            if kwargs.get('by_strahler', False) or \
               kwargs.get('by_confidence', False):
                # Convert array back to a single color without alpha
                neuron_color = neuron_color[0][:3]

            # Add soma by default. If use_radius=True, add soma only if
            # explicitly requested
            if kwargs.get('soma', kwargs.get('use_radius', False) is False):
                # Extract and plot soma
                soma = neuron.nodes[neuron.nodes.radius > 1]
                if neuron.soma:
                    soma = neuron.nodes.set_index('treenode_id').loc[neuron.soma]
                    sp = create_sphere(7, 7, radius=soma.radius)
                    verts = sp.get_vertices() + soma[['x', 'y', 'z']].values
                    s = scene.visuals.Mesh(vertices=verts,
                                           shading='smooth',
                                           faces=sp.get_faces(),
                                           color=neuron_color)
                    s.ambient_light_color = vispy.color.Color('white')

                    # Make visual discoverable
                    s.interactive = True

                    # Add custom attributes
                    s.unfreeze()
                    s._object_type = 'neuron'
                    s._neuron_part = 'soma'
                    s._skeleton_id = neuron.skeleton_id
                    s._neuron_name = neuron.neuron_name
                    s._object_id = object_id
                    s.freeze()

                    visuals.append(s)

        if kwargs.get('connectors', False) or kwargs.get('connectors_only',
                                                         False):
            for j in [0, 1, 2]:
                if kwargs.get('cn_mesh_colors', False):
                    color = neuron_color
                else:
                    color = syn_lay[j]['color']

                if max(color) > 1:
                    color = np.array(color) / 255

                this_cn = neuron.connectors[
                    neuron.connectors.relation == j]

                if this_cn.empty:
                    continue

                pos = this_cn[['x', 'y', 'z']].apply(
                    pd.to_numeric).values

                if syn_lay['display'] == 'circles':
                    con = scene.visuals.Markers()

                    con.set_data(pos=np.array(pos),
                                 face_color=color, edge_color=color,
                                 size=syn_lay.get('size', 1))

                    visuals.append(con)

                elif syn_lay['display'] == 'lines':
                    tn_coords = neuron.nodes.set_index('treenode_id').ix[this_cn.treenode_id.values][['x', 'y', 'z']].apply(pd.to_numeric).values

                    segments = [item for sublist in zip(
                        pos, tn_coords) for item in sublist]

                    t = scene.visuals.Line(pos=np.array(segments),
                                           color=color,
                                           # Can only be used with method 'agg'
                                           width=kwargs.get('linewidth', 1),
                                           connect='segments',
                                           antialias=False,
                                           method='gl')
                    # method can also be 'agg' -> has to use connect='strip'

                    # Add custom attributes
                    t.unfreeze()
                    t._object_type = 'neuron'
                    t._neuron_part = 'connectors'
                    t._skeleton_id = neuron.skeleton_id
                    t._neuron_name = neuron.neuron_name
                    t._object_id = object_id
                    t.freeze()

                    visuals.append(t)

    return visuals


def _dp2vispy(x, **kwargs):
    """Convert dotprops(s) to vispy visuals.

    Parameters
    ----------
    x :             core.Dotprops | pd.DataFrame
                    Dotprop(s) to plot.
    colormap :      tuple | dict | array
                    Color to use for plotting. Dictionaries should be mapped
                    to gene names.
    scale_vect :    int, optional
                    Vector to scale dotprops by.

    Returns
    -------
    list
                    Contains vispy visuals for each dotprop.

    """
    if not isinstance(x, (core.Dotprops, pd.DataFrame)):
        raise TypeError('Unable to process data of type "{}"'.format(type(x)))

    visuals = []

    # Parse colors for dotprops
    colors = kwargs.get('color',
                        kwargs.get('c',
                                   kwargs.get('colors', None)))
    _, colormap = _prepare_colormap(colors,
                                    None, x, use_neuron_color=False,
                                    color_range=1)

    scale_vect = kwargs.get('scale_vect', 1)

    for i, n in enumerate(x.itertuples()):
        # Generate random ID -> we need this in case we have duplicate skeleton IDs
        object_id = uuid.uuid4()

        color = colormap[i]

        # Prepare lines - this is based on nat:::plot3d.dotprops
        halfvect = n.points[
            ['x_vec', 'y_vec', 'z_vec']] / 2 * scale_vect

        starts = n.points[['x', 'y', 'z']
                          ].values - halfvect.values
        ends = n.points[['x', 'y', 'z']
                        ].values + halfvect.values

        segments = [item for sublist in zip(
            starts, ends) for item in sublist]

        t = scene.visuals.Line(pos=np.array(segments),
                               color=color,
                               width=2,
                               connect='segments',
                               antialias=False,
                               method='gl')  # method can also be 'agg'

        # Add custom attributes
        t.unfreeze()
        t._object_type = 'dotprop'
        t._neuron_part = 'neurites'
        t._neuron_name = n.gene_name
        t._object_id = object_id
        t.freeze()

        visuals.append(t)

        # Add soma
        sp = create_sphere(5, 5, radius=4)
        s = scene.visuals.Mesh(vertices=sp.get_vertices() +
                                        np.array([n.X, n.Y, n.Z]),
                               faces=sp.get_faces(),
                               color=color)

        # Add custom attributes
        s.unfreeze()
        s._object_type = 'dotprop'
        s._neuron_part = 'soma'
        s._neuron_name = n.gene_name
        s._object_id = object_id
        s.freeze()

        visuals.append(s)

    return visuals


def _points2vispy(x, **kwargs):
    """Convert points to vispy visuals.

    Parameters
    ----------
    x :             list of arrays
                    Points to plot.
    color :         tuple | array
                    Color to use for plotting.
    size :          int, optional
                    Marker size.

    Returns
    -------
    list
                    Contains vispy visuals for points.

    """
    colors = kwargs.get('color',
                        kwargs.get('c',
                                   kwargs.get('colors',
                                              _eval_color(config.default_color, 1))))

    visuals = []
    for p in x:
        object_id = uuid.uuid4()
        if not isinstance(p, np.ndarray):
            p = np.array(p)

        con = scene.visuals.Markers()
        con.set_data(pos=p,
                     face_color=colors,
                     edge_color=colors,
                     size=kwargs.get('size', 2))

        # Add custom attributes
        con.unfreeze()
        con._object_type = 'points'
        con._object_id = object_id
        con.freeze()

        visuals.append(con)

    return visuals
