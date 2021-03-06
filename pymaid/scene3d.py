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


""" This module contains classes for 3d visualization using vispy.
"""

# TO-DO:
# [x] keyboard shortcuts to cycle back and forth through neurons
# [x] set_color method (takes colormap as input)
# [/] method and shortcut for screenshot (generic filename for shortcut)
# [ ] animate method: makes camera rotate?
# [-] CANCELLED grey, transparent background for legend
# [x] logging
# [x] modifier keys for selection (shift)
# [ ] how to deal with duplicate skeleton IDs? Use id() or hex(id())?
#    -> would have to link somas & connectors to that ID (set as parent)
# [ ] dragging selection (ctrl+shift?) - see gist
# [x] show shortcuts at bottom in overlay
# [ ] function/shortcut to show/hide connectors (if available)
# [ ] crosshair for picking? shows on_mouse_move with modifier key
# [x] could snap to closest position on given neuron?
#     -> for line visuals, `.pos` contains all points of that visual
# [x] make ctrl-click display a marker at given position
# [ ] keyboard shortcut to toggle volumes
# [ ] add lasso/rectangle selection (complicated)
# [ ] shortcut to toggle connectors
# [ ]

import uuid
import platform
import colorsys
import webbrowser
from functools import wraps
import os
import warnings

import numpy as np
import pandas as pd
import scipy.spatial
import seaborn as sns
import png
import matplotlib.colors as mcl

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import vispy
    import vispy.scene
    import vispy.util

from . import utils, plotting, fetch, config

__all__ = ['Viewer', 'Browser']

logger = config.logger

# This makes sure the app is run correctly
headless = int(os.environ.get('PYMAID_HEADLESS', '0'))
if utils._type_of_script() == 'ipython':
    if headless:
        logger.info('Pymaid is running in headless mode')
    elif utils.is_headless():
        logger.info('No display detected. Pymaid is running in headless mode')
    else:
        try:
            ipython = get_ipython()
            ipython.magic("%gui qt5")
        except BaseException:
            pass

try:
    # Try setting vispy backend to PyQt5
    vispy.use(app='PyQt5')
except BaseException:
    pass


def block_all(function):
    """Decorator to block all events on canvas and view."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        viewer = args[0]
        viewer.canvas.events.block_all()
        viewer.view3d.events.block_all()
        try:
            # Execute function
            res = function(*args, **kwargs)
        except BaseException:
            raise
        finally:
            viewer.canvas.events.unblock_all()
            viewer.view3d.events.unblock_all()
        # Return result
        return res
    return wrapper


def block_canvas(function):
    """Decorator to block all events on canvas are being made."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        viewer = args[0]
        viewer.canvas.events.block_all()
        try:
            # Execute function
            res = function(*args, **kwargs)
        except BaseException:
            raise
        finally:
            viewer.canvas.events.unblock_all()
        # Return result
        return res
    return wrapper


class Browser:
    """Vispy browser.

    Parameters
    ----------
    n_rows/n_cols : int, optional
                    Number of rows and columns in the browser.

    """
    def __init__(self, n_rows=2, n_cols=3, link=False, **kwargs):
        # Update some defaults as necessary
        defaults = dict(keys=None,
                        show=True,
                        bgcolor='white',
                        config={'depth_size': 32})
        defaults.update(kwargs)

        # Generate canvas
        self.canvas = vispy.scene.SceneCanvas(**defaults)

        # Add grid
        self.grid = self.canvas.central_widget.add_grid()

        # Add 3d widgets
        self.viewers = []
        for i in range(n_rows):
            for k in range(n_cols):
                v = self.grid.add_view(row=i, col=k)
                v.camera = 'turntable'
                v.border_color = (.5, .5, .5, 1)
                self.viewers.append(v)

        if link:
            for v in self.viewers[1:]:
                self.viewers[0].camera.link(v.camera)

    def add_to_all(self, x, center=True, clear=False, **kwargs):
        """ Add visuals to all viewers. """
        for v in range(len(self.viewers)):
            self.add(x, viewer=v, center=center, clear=clear, **kwargs)

    def add_and_divide(self, x, center=True, clear=False, **kwargs):
        """ Divide up visuals onto available viewers. """
        data = utils._parse_objects(x)

        v = 0
        for d in data:
            if isinstance(d, pd.DataFrame):
                d = d.itertuples()
            for to_add in d:
                self.add(to_add, viewer=v, center=center,
                         clear=clear, **kwargs)
                v += 1

                if v == len(self.viewers):
                    v = 0

    def add(self, x, viewer=1, center=True, clear=False, **kwargs):
        """Add objects to canvas.

        Parameters
        ----------
        x :         skeleton IDs | CatmaidNeuron/List | Dotprops | Volumes | Points | vispy visuals
                    Object(s) to add to the canvas.
        viewer :    int | slice, optional
                    Index of the viewer to add object to.
        center :    bool, optional
                    If True, re-center camera to all objects on canvas.
        clear :     bool, optional
                    If True, clear canvas before adding new objects.
        **kwargs
                    Keyword arguments passed when generating visuals. See
                    :func:`~pymaid.plot3d` for options.

        Returns
        -------
        None

        """
        (skids, skdata, dotprops, volumes,
         points, visuals) = utils._parse_objects(x)

        colors = kwargs.get('color',
                            kwargs.get('c',
                                       kwargs.get('colors', None)))
        # Parse colors for neurons and dotprops
        neuron_cmap, skdata_cmap = plotting._prepare_colormap(colors,
                                                              skdata, dotprops,
                                                              use_neuron_color=kwargs.get('use_neuron_color', False))
        kwargs['color'] = neuron_cmap + skdata_cmap

        if skids:
            visuals += plotting._neuron2vispy(fetch.get_neurons(skids),
                                              **kwargs)
        if skdata:
            visuals += plotting._neuron2vispy(skdata, **kwargs)
        if not dotprops.empty:
            visuals += plotting._dp2vispy(dotprops, **kwargs)
        if volumes:
            visuals += plotting._volume2vispy(volumes, **kwargs)
        if points:
            visuals += plotting._points2vispy(points,
                                              **kwargs.get('scatter_kws', {}))

        if not visuals:
            raise ValueError('No visuals generated.')

        if clear:
            self.clear()

        if isinstance(viewer, int):
            to_add = self.viewers[viewer:viewer + 1]
        elif isinstance(viewer, slice):
            to_add = self.viewers[viewer]
        else:
            raise TypeError('Unable to find viewer at {}'.format(type(viewer)))

        for view in to_add:
            for v in visuals:
                view.add(v)

            if center:
                self.center_camera(view)

    def show(self):
        """Show viewer."""
        self.canvas.show()

    def close(self):
        """Close viewer. """
        if self == globals().get('viewer', None):
            globals().pop('viewer')
        self.canvas.close()

    def get_visuals(self, viewer):
        """Return list of all 3D visuals on given viewer."""
        if isinstance(viewer, int):
            viewer = self.viewers[viewer]

        return [v for v in viewer.children[0].children if isinstance(v, vispy.scene.visuals.VisualNode)]

    def center_camera(self, viewer):
        """Center camera on visuals."""
        if isinstance(viewer, int):
            viewer = self.viewers[viewer]

        viewer.camera.set_range()


class Viewer:
    """Vispy 3D viewer.

    Parameters
    ----------
    picking :   bool, default = False
                If ``True``, allow selecting neurons by shift-clicking on
                neurons and placing a 3D cursor via control-click (for OSX:
                command-click).
    **kwargs
              Keyword arguments passed to ``vispy.scene.SceneCanvas``.

    Attributes
    ----------
    picking :       bool,
                    Set to ``True`` to allow picking via shift-clicking.
    selected :      np.array
                    List of currently selected neurons. Can also be used to
                    set the selection.
    show_legend :   bool
                    Set to ``True`` or press ``L`` to show legend. This may
                    impact performance.
    legend_font_size : int
                    Font size for legend.

    Examples
    --------
    This viewer is what :func:`pymaid.plot3d` uses when ``backend='vispy'``.
    Instead of :func:`pymaid.plot3d` we can interact with the viewer directly:

    >>> # Open a 3D viewer
    >>> v = pymaid.Viewer()
    >>> # Get and add neurons
    >>> nl = pymaid.get_neuron('annotation:glomerulus DA1')
    >>> v.add(nl)
    >>> # Colorize
    >>> v.colorize()
    >>> # Assign specific colors
    >>> v.set_colors({nl[0].skeleton_id: (1, 0, 0)})
    >>> # Clear the canvas
    >>> v.clear()

    You can change the background color from the start or on-the-go:

    >>> # Set background to green
    >>> v = pymaid.Viewer(bgcolor='green')
    >>> # Set background back to white
    >>> v.canvas.bgcolor = (1, 1, 1)

    """
    def __init__(self, picking=False, **kwargs):
        # Update some defaults as necessary
        defaults = dict(keys=None,
                        show=True,
                        title='pymaid Viewer',
                        bgcolor='black')
        defaults.update(kwargs)

        # Set border rim -> this depends on how the framework (e.g. QT5)
        # renders the window
        self._rim_bot = 15
        self._rim_top = 20
        self._rim_left = 10
        self._rim_right = 10

        # Generate canvas
        self.canvas = vispy.scene.SceneCanvas(**defaults)

        # Add and setup 3d view
        self.view3d = self.canvas.central_widget.add_view()
        self.camera3d = vispy.scene.ArcballCamera()
        self.view3d.camera = self.camera3d

        # Add permanent overlays
        self.overlay = self._draw_overlay()

        self.canvas.unfreeze()
        self.canvas._overlay = self.overlay
        self.canvas._view3d = self.view3d
        self.canvas._wrapper = self
        self.canvas.freeze()

        # Add picking functionality
        if picking:
            self.picking = True
        else:
            self.picking = False

        # Set cursor_pos to None
        self.cursor_pos = None

        # Add keyboard shortcuts
        self.canvas.connect(on_key_press)

        # Add resize control to keep overlay in position
        self.canvas.connect(on_resize)

        # Legend settings
        self.__show_legend = False
        self.__selected = []
        self._cycle_index = -1
        self.__legend_font_size = 7

        # Color to use when selecting neurons
        self.highlight_color = (1, .9, .6)

        # Keep track of initial camera position
        self._camera_default = self.view3d.camera.get_state()

        # Cycle mode can be 'hide' or 'alpha'
        self._cycle_mode = 'alpha'
        self.active_neuron = []

        # Cursors
        self._cursor = None
        self._picking_radius = 20

        # Labels
        self._labelmap = {}
        self._labels = {}
        self.label_mode = False

    def _draw_overlay(self):
        overlay = vispy.scene.widgets.ViewBox(parent=self.canvas.scene)
        self.view3d.add_widget(overlay)

        """
        # Legend title
        t = vispy.scene.visuals.Text('Legend', pos=(10,10),
                                  anchor_x='left', name='permanent',
                                  parent=overlay,
                                  color=(0,0,0), font_size=9)
        """

        # Text color depends on background color
        v = self.canvas.bgcolor.hsv[2]
        text_color = colorsys.hsv_to_rgb(0, 0, 1-v)

        # Keyboard shortcuts
        self._key_shortcuts = {'O': 'toggle overlay',
                               'L': 'toggle legend',
                               'P': 'toggle picking',
                               'Q/W': 'cycle neurons',
                               'U': 'unhide all',
                               'F': 'show/hide FPS',
                               '1': 'XY',
                               '2': 'XZ',
                               '3': 'YZ'}

        shorts_text = 'SHORTCUTS: ' + \
                      ' | '.join(['<{0}> {1}'.format(k, v)
                                for k, v in self._key_shortcuts.items()])
        self._shortcuts = vispy.scene.visuals.Text(shorts_text,
                                                   pos=(self._rim_left,
                                                        overlay.size[1] - self._rim_bot),
                                                   anchor_x='left',
                                                   anchor_y='bottom',
                                                   name='permanent',
                                                   method='gpu',
                                                   parent=overlay,
                                                   color=text_color,
                                                   font_size=6)

        # FPS (hidden at start)
        self._fps_text = vispy.scene.visuals.Text('FPS',
                                                  pos=(overlay.size[0] / 2,
                                                       self._rim_top),
                                                  anchor_x='center',
                                                  anchor_y='top',
                                                  name='permanent',
                                                  method='gpu',
                                                  parent=overlay,
                                                  color=text_color,
                                                  font_size=6)
        self._fps_text.visible = False

        # Picking shortcuts (hidden at start)
        self._picking_shortcuts = {'LMB @legend': 'show/hide neuron',
                                   'SHIFT+LMB @neuron': 'select neuron',
                                   'D': 'deselect all',
                                   'H': 'hide selected',
                                   'C': 'url to cursor'}

        # Add platform-specific modifiers
        if platform.system() == 'darwin':
            self._picking_shortcuts['CMD+LMB'] = 'set cursor'
        else:
            self._picking_shortcuts['CTRL+LMB'] = 'set cursor'

        shorts_text = 'PICKING: ' + \
                      ' | '.join(['<{0}> {1}'.format(k, v)
                                for k, v in self._picking_shortcuts.items()])
        self._picking_text = vispy.scene.visuals.Text(shorts_text,
                                                      pos=(self._rim_left,
                                                           overlay.size[1] - self._rim_bot - 10),
                                                      anchor_x='left',
                                                      anchor_y='bottom',
                                                      name='permanent',
                                                      method='gpu',
                                                      parent=overlay,
                                                      color=text_color,
                                                      font_size=6)
        self._picking_text.visible = False

        # Text box in top right to display arbitrary data
        self._data_text = vispy.scene.visuals.Text('',
                                                   pos=(overlay.size[0] - self._rim_right,
                                                        self._rim_top),
                                                   anchor_x='right',
                                                   anchor_y='top',
                                                   name='permanent',
                                                   method='gpu',
                                                   parent=overlay,
                                                   color=text_color,
                                                   font_size=6)

        return overlay

    @property
    def show_legend(self):
        """Set to ``True`` to hide neuron legend."""
        return self.__show_legend

    @show_legend.setter
    def show_legend(self, v):
        if not isinstance(v, bool):
            raise TypeError('Need boolean, got "{}"'.format(type(v)))

        if v != self.show_legend:
            self.__show_legend = v
            # Make sure changes take effect
            self.update_legend()

    @property
    def legend_font_size(self):
        """Change legend's font size."""
        return self.__legend_font_size

    @legend_font_size.setter
    def legend_font_size(self, val):
        self.__legend_font_size = val
        if self.show_legend:
            self.update_legend()

    @property
    def picking(self):
        """Set to ``True`` to allow picking."""
        return self.__picking

    def _render_fb(self, crop=None):
        """Render framebuffer. """
        if not crop:
            crop=(0, 0,
                  self.canvas.size[0] * self.canvas.pixel_scale,
                  self.canvas.size[1] * self.canvas.pixel_scale)

        # We have to temporarily deactivate the overlay and view3d
        # otherwise we won't be able to see what's on the 3D or might
        # see holes in the framebuffer
        self.view3d.interactive = False
        self.overlay.interactive = False
        p = self.canvas._render_picking(crop=crop)
        self.view3d.interactive = True
        self.overlay.interactive = True
        return p

    def toggle_picking(self):
        """Toggle picking and overlay text."""
        if self.picking:
            self.picking = False
            self._picking_text.visible = False
        else:
            self.picking = True
            self._picking_text.visible = True

    @picking.setter
    def picking(self, v):
        if not isinstance(v, bool):
            raise TypeError('Need bool, got {}'.format(type(v)))

        self.__picking = v

        if self.picking:
            self.canvas.connect(on_mouse_press)
        else:
            self.canvas.events.mouse_press.disconnect(on_mouse_press)

    @property
    def visible(self):
        """List of skeleton IDs of currently visible neurons."""
        return [s for s in self.neurons if self.neurons[s][0].visible]

    @property
    def invisible(self):
        """List of skeleton IDs of currently invisible neurons."""
        return [s for s in self.neurons if not self.neurons[s][0].visible]

    @property
    def selected(self):
        """Skeleton IDs of currently selected neurons."""
        return self.__selected

    @selected.setter
    def selected(self, val):
        skids = utils.eval_skids(val)

        if not isinstance(skids, np.ndarray):
            skids = np.array(skids)

        neurons = self.neurons

        logger.debug('{0} neurons selected ({1} previously)'.format(
            len(skids), len(self.selected)))

        # First un-highlight neurons no more selected
        for s in [s for s in self.__selected if s not in set(skids)]:
            for v in neurons[s]:
                if isinstance(v, vispy.scene.visuals.Mesh):
                    v.color = v._stored_color
                else:
                    v.set_data(color=v._stored_color)

        # Highlight new additions
        for s in skids:
            if s not in self.__selected:
                for v in neurons[s]:
                    # Keep track of old colour
                    v.unfreeze()
                    v._stored_color = v.color
                    v.freeze()
                    if isinstance(v, vispy.scene.visuals.Mesh):
                        v.color = self.highlight_color
                    else:
                        v.set_data(color=self.highlight_color)

        self.__selected = skids

        # Update legend
        if self.show_legend:
            self.update_legend()

        # Update data text
        # Currently nly the development version of vispy supports escape
        # character (e.g. \n)
        t = '| '.join(['{} - #{}'.format(self.neurons[s][0]._neuron_name,
                                         s) for s in self.__selected])
        self._data_text.text = t

    @property
    def visuals(self):
        """List of all 3D visuals on this canvas."""
        return [v for v in self.view3d.children[0].children if isinstance(v, vispy.scene.visuals.VisualNode)]

    @property
    def neurons(self):
        """List of visible + invisible neuron visuals currently on the canvas.

        Returns
        -------
        dict
                    ``{skeleton_ID: [neurites, soma]}``

        """
        # Collect neuron objects
        neuron_obj = [c for c in self.visuals if 'neuron' in getattr(
            c, '_object_type', '')]

        # Collect skeleton IDs
        skids = set([ob._skeleton_id for ob in neuron_obj])

        # Map visuals to unique skids
        return {s: [ob for ob in neuron_obj if ob._skeleton_id == s] for s in skids}

    @property
    def _neuron_obj(self):
        """Return neurons by their object id."""
        # Collect neuron objects
        neuron_obj = [c for c in self.visuals if 'neuron' in getattr(
            c, '_object_type', '')]

        # Collect skeleton IDs
        obj_ids = set([ob._object_id for ob in neuron_obj])

        # Map visuals to unique skids
        return {s: [ob for ob in neuron_obj if ob._object_id == s] for s in obj_ids}

    def clear_legend(self):
        """Clear legend."""
        # Clear legend except for title
        for l in [l for l in self.overlay.children if isinstance(l, vispy.scene.visuals.Text) and l.name != 'permanent']:
            l.parent = None

    def clear(self):
        """Clear canvas."""
        for v in self.visuals:
            v.parent = None

        self.clear_legend()

    def make_global(self):
        """Make this the global viewer."""
        globals()['viewer'] = self

    def remove(self, to_remove):
        """Remove given neurons/visuals from canvas."""

        if not isinstance(to_remove, vispy.scene.visuals.VisualNode):
            skids = utils.eval_skids(to_remove)
            to_remove = [v for s in skids for v in self.neurons.get(s, [])]

        for v in to_remove:
            v.parent = None

    @block_canvas
    def update_legend(self):
        """Update legend."""

        # Get existing labels
        labels = {l._object_id: l for l in self.overlay.children if getattr(l, '_object_id', None)}

        # If legend is not meant to be shown, make sure everything is hidden and return
        if not self.show_legend:
            for v in labels.values():
                if v.visible:
                    v.visible = False
            return
        else:
            for v in labels.values():
                if not v.visible:
                    v.visible = True

        # Labels to be removed
        to_remove = [s for s in labels if s not in self._neuron_obj]
        for s in to_remove:
            labels[s].parent = None

        # Generate new labels
        to_add = [s for s in self._neuron_obj if s not in labels]
        for s in to_add:
            l = vispy.scene.visuals.Text('{0} - #{1}'.format(self._neuron_obj[s][0]._neuron_name,
                                                             self._neuron_obj[s][0]._skeleton_id),
                                         anchor_x='left',
                                         anchor_y='top',
                                         parent=self.overlay,
                                         font_size=self.legend_font_size)
            l.interactive = True
            l.unfreeze()
            l._object_id = s
            l._skeleton_id = self._neuron_obj[s][0]._skeleton_id
            l.freeze()

        # Position and color labels
        labels = {l._object_id: l for l in self.overlay.children if getattr(
            l, '_object_id', None)}
        for i, s in enumerate(sorted(self._neuron_obj)):
            if self._neuron_obj[s][0].visible:
                color = self._neuron_obj[s][0].color
            else:
                color = (.3, .3, .3)

            offset = 10 * (self.legend_font_size / 7)

            labels[s].pos = (10, self._rim_top + offset * (i + 1))
            labels[s].color = color
            labels[s].font_size = self.legend_font_size

    def toggle_overlay(self):
        """Toggle legend on and off."""
        self.overlay.visible = self.overlay.visible is False

    def center_camera(self):
        """Center camera on visuals."""
        if not self.visuals:
            return

        xbounds = np.array([v.bounds(0) for v in self.visuals]).flatten()
        ybounds = np.array([v.bounds(1) for v in self.visuals]).flatten()
        zbounds = np.array([v.bounds(2) for v in self.visuals]).flatten()

        self.camera3d.set_range((xbounds.min(), xbounds.max()),
                                (ybounds.min(), ybounds.max()),
                                (zbounds.min(), zbounds.max()))

    def add(self, x, center=True, clear=False, **kwargs):
        """Add objects to canvas.

        Parameters
        ----------
        x :         skeleton IDs | CatmaidNeuron/List | Dotprops | Volumes | Points | vispy Visuals
                    Object(s) to add to the canvas.
        center :    bool, optional
                    If True, re-center camera to all objects on canvas.
        clear :     bool, optional
                    If True, clear canvas before adding new objects.
        **kwargs
                    Keyword arguments passed when generating visuals. See
                    :func:`~pymaid.plot3d` for options.

        Returns
        -------
        None

        """
        (skids, skdata, dotprops, volumes,
         points, visuals) = utils._parse_objects(x)

        # Parse colors for neurons and dotprops
        neuron_cmap, skdata_cmap = plotting._prepare_colormap(kwargs.get('color',
                                                                         kwargs.get('colors', None)),
                                                              skdata, dotprops,
                                                              use_neuron_color=kwargs.get('use_neuron_color', False))
        kwargs['color'] = neuron_cmap + skdata_cmap

        if skids:
            visuals += plotting._neuron2vispy(fetch.get_neurons(skids),
                                              **kwargs)
        if skdata:
            visuals += plotting._neuron2vispy(skdata, **kwargs)
        if not dotprops.empty:
            visuals += plotting._dp2vispy(dotprops, **kwargs)
        if volumes:
            visuals += plotting._volume2vispy(volumes, **kwargs)
        if points:
            visuals += plotting._points2vispy(points,
                                              **kwargs.get('scatter_kws', {}))

        if not visuals:
            raise ValueError('No visuals generated.')

        if clear:
            self.clear()

        for v in visuals:
            self.view3d.add(v)

        if center:
            self.center_camera()

        if self.show_legend:
            self.update_legend()

    def show(self):
        """Show viewer."""
        self.canvas.show()

    def close(self):
        """Close viewer."""
        if self == globals().get('viewer', None):
            globals().pop('viewer')
        self.canvas.close()

    def hide_neurons(self, n):
        """Hide given neuron(s)."""
        skids = utils.eval_skids(n)

        neurons = self.neurons

        for s in skids:
            for v in neurons[s]:
                if v.visible:
                    v.visible = False

        self.update_legend()

    def hide_selected(self):
        """Hide currently selected neuron(s)."""
        self.hide_neurons(self.selected)

    def unhide_neurons(self, n=None, check_alpha=False):
        """Unhide given neuron(s).

        Use ``n`` to unhide specific neurons.

        """
        if not isinstance(n, type(None)):
            skids = utils.eval_skids(n)
        else:
            skids = list(self.neurons.keys())

        neurons = self.neurons

        for s in skids:
            for v in neurons[s]:
                if not v.visible:
                    v.visible = True
            if check_alpha:
                c = list(mcl.to_rgba(neurons[s][0].color))
                if c[3] != 1:
                    c[3] = 1
                    self.set_colors({s: c})

        self.update_legend()
        self._data_text.text = ''
        self.active_neuron = []

    def toggle_neurons(self, n):
        """Toggle neuron(s) visibility."""

        n = utils._make_iterable(n)

        if False not in [isinstance(u, uuid.UUID) for u in n]:
            obj = self._neuron_obj
        else:
            n = utils.eval_skids(n)
            obj = self.neurons

        for s in n:
            for v in obj[s]:
                v.visible = v.visible is False

        self.update_legend()

    def toggle_select(self, n):
        """Toggle selected of given neuron."""
        skids = utils.eval_skids(n)

        neurons = self.neurons

        for s in skids:
            if self.selected != s:
                self.selected = s
                for v in neurons[s]:
                    self._selected_color = v.color
                    v.set_data(color=self.highlight_color)
            else:
                self.selected = None
                for v in neurons[s]:
                    v.set_data(color=self._selected_color)

        self.update_legend()

    @block_all
    def set_colors(self, c, include_connectors=False):
        """Set neuron color.

        Parameters
        ----------
        c :      tuple | dict
                 RGB color(s) to apply. Values must be 0-1. Accepted:
                   1. Tuple of single color. Applied to all visible neurons.
                   2. Dictionary mapping skeleton IDs to colors.

        """
        if isinstance(c, (tuple, list, np.ndarray, str)):
            cmap = {s: c for s in self.neurons}
        elif isinstance(c, dict):
            cmap = c
        else:
            raise TypeError(
                'Unable to use colors of type "{}"'.format(type(c)))

        for n in self.neurons:
            if n in cmap:
                for v in self.neurons[n]:
                    if v._neuron_part == 'connectors' and not include_connectors:
                        continue
                    new_c = mcl.to_rgba(cmap[n])
                    if isinstance(v, vispy.scene.visuals.Mesh):
                        v.color = new_c
                    else:
                        v.set_data(color=mcl.to_rgba(cmap[n]))

        if self.show_legend:
            self.update_legend()

    @block_all
    def set_alpha(self, a, include_connectors=True):
        """Set neuron color alphas.

        Parameters
        ----------
        a :      tuple | dict
                 Alpha value(s) to apply. Values must be 0-1. Accepted:
                   1. Tuple of single alpha. Applied to all visible neurons.
                   2. Dictionary mapping skeleton IDs to alpha.

        """
        if isinstance(a, (tuple, list, np.ndarray, str)):
            amap = {s: a for s in self.neurons}
        elif isinstance(a, dict):
            amap = a
        else:
            raise TypeError(
                'Unable to use colors of type "{}"'.format(type(a)))

        for n in self.neurons:
            if n in amap:
                for v in self.neurons[n]:
                    if v._neuron_part == 'connectors' and not include_connectors:
                        continue
                    try:
                        this_c = v.color.rgba
                    except BaseException:
                        this_c = v.color

                    if len(this_c) == 4 and this_c[3] == amap[n]:
                        continue

                    new_c = tuple([this_c[0], this_c[1], this_c[2], amap[n]])
                    if isinstance(v, vispy.scene.visuals.Mesh):
                        v.color = mcl.to_rgba(new_c)
                    else:
                        v.set_data(color=mcl.to_rgba(new_c))

        if self.show_legend:
            self.update_legend()

    def colorize(self, palette='hls', include_connectors=False):
        """Colorize neurons using a seaborn color palette."""

        colors = sns.color_palette(palette, len(self.neurons))
        cmap = {s: colors[i] for i, s in enumerate(self.neurons)}

        self.set_colors(cmap, include_connectors=include_connectors)

    def _cycle_neurons(self, increment):
        """Cycle through neurons."""
        self._cycle_index += increment

        # If mode is 'hide' cycle over all neurons
        if self._cycle_mode == 'hide':
            to_cycle = self.neurons
        # If mode is 'alpha' ignore all hidden neurons
        else:
            to_cycle = {s: self.neurons[s] for s in self.visible}

        if self._cycle_index < 0:
            self._cycle_index = len(to_cycle) - 1
        elif self._cycle_index > len(to_cycle) - 1:
            self._cycle_index = 0

        neurons_sorted = sorted(to_cycle.keys())

        to_hide = [n for i, n in enumerate(neurons_sorted) if i != self._cycle_index]
        to_show = [neurons_sorted[self._cycle_index]]

        # Depending on background color, we have to use different alphas
        v = self.canvas.bgcolor.hsv[2]
        out_alpha = .05 + .2 * v

        if self._cycle_mode == 'hide':
            self.hide_neurons(to_hide)
            self.unhide_neurons(to_show)
        elif self._cycle_mode == 'alpha':
            # Get current colors
            new_amap = {}
            for n in to_cycle:
                this_c = list(to_cycle[n][0].color)
                # Make sure colors are (r, g, b, a)
                if len(this_c) < 4:
                    this_a = 1
                else:
                    this_a = this_c[3]

                # If neuron needs to be hidden, add to cmap
                if n in to_hide and this_a != out_alpha:
                    new_amap[n] = out_alpha
                elif n in to_show and this_a != 1:
                    new_amap[n] = 1
            self.set_alpha(new_amap)
        else:
            raise ValueError('Unknown cycle mode '
                             '"{}". Use "hide" or '
                             '"alpha"!'.format(self._cycle_mode))

        self.active_neuron = to_show
        self._data_text.text = '{} [{}/{}]'.format('|'.join(to_show),
                                                   self._cycle_index,
                                                   len(self.neurons))

    def _draw_fps(self, fps):
        """Callback for ``canvas.measure_fps``."""
        self._fps_text.text = '{:.2f} FPS'.format(fps)

    def _toggle_fps(self):
        """Switch FPS measurement on and off."""
        if not self._fps_text.visible:
            self.canvas.measure_fps(1, self._draw_fps)
            self._fps_text.visible = True
        else:
            self.canvas.measure_fps(1, None)
            self._fps_text.visible = False

    def _snap_cursor(self, pos, visual, open_browser=False):
        """Snap cursor to clostest vertex of visual."""
        if not getattr(self, '_cursor', None):
            self._cursor = vispy.scene.visuals.Arrow(pos=np.array([(0, 0, 0), (1000, 0, 0)]),
                                                     color=(1, 0, 0, 1),
                                                     arrow_color=(1, 0, 0, 1),
                                                     arrow_size=10,
                                                     arrows=np.array([[800, 0, 0, 1000, 0, 0]]))

        if not self._cursor.parent:
            self.add(self._cursor, center=False)

        # Get vertices for this visual
        if isinstance(visual, vispy.scene.visuals.Line):
            verts = visual.pos
        elif isinstance(visual, vispy.scene.visuals.Mesh):
            verts = visual.mesh_data.get_vertices()

        # Map vertices to canvas
        tr = visual.get_transform(map_to='canvas')
        co_on_canvas = tr.map(verts)[:, [0, 1]]

        # Find the closest vertex to this mouse click pos
        tree = scipy.spatial.cKDTree(co_on_canvas)
        dist, ix = tree.query(pos)

        # Map canvas pos back to world coordinates
        self.cursor_pos = np.array(verts[ix])
        self.cursor_active_skeleton = getattr(visual, '_skeleton_id', None)

        # Generate arrow coords
        vec_to_center = np.array(self.camera3d.center) - self.cursor_pos
        norm_to_center = vec_to_center / np.sqrt(np.sum(vec_to_center**2))
        start = self.cursor_pos - (norm_to_center * 10000)
        arrows = np.array([np.append(self.cursor_pos - (norm_to_center * 200),
                                     self.cursor_pos - (norm_to_center * 100))])

        self._cursor.set_data(pos=np.array([start, self.cursor_pos]),
                              arrows=arrows)

        logger.debug('World coordinates: {}'.format(self.cursor_pos))

        url = fetch.url_to_coordinates(self.cursor_pos, 5,
                                       active_skeleton_id=self.cursor_active_skeleton)
        print('URL: {}'.format(url))

        if open_browser:
            webbrowser.open_new_tab(url)

    def url_to_cursor(self, open_browser=False):
        """Open or return URL to current cursor position.

        Parameters
        ----------
        open_browser :  bool, optional
                        If True, will try opening URL in new tab.

        Returns
        -------
        URL :           str
                        Only if open_browser is False.

        """
        if isinstance(self.cursor_pos, type(None)):
            logger.info('Must place cursor first.')
            return

        url = fetch.url_to_coordinates(self.cursor_pos, 5,
                                       active_skeleton_id=self.cursor_active_skeleton)

        if open_browser:
            webbrowser.open_new_tab(url)
        else:
            return url

    def screenshot(self, filename='screenshot.png', pixel_scale=2,
                   alpha=True, hide_overlay=True):
        """Save a screenshot.

        Parameters
        ----------
        filename :      str, optional
                        Filename to save to.
        pixel_scale :   int, optional
                        Factor by which to scale canvas. Determines image
                        dimensions.
        alpha :         bool, optional
                        If True, will export transparent background.
        hide_overlay :  bool, optional
                        If True, will hide overlay for screenshot.

        """
        if alpha:
            bgcolor = list(self.canvas.bgcolor.rgb) + [0]
        else:
            bgcolor = list(self.canvas.bgcolor.rgb)

        region = (0, 0, self.canvas.size[0], self.canvas.size[1])
        size = tuple(np.array(self.canvas.size) * pixel_scale)

        if hide_overlay:
            prev_state = self.overlay.visible
            self.overlay.visible = False

        m = self.canvas.render(region=region, size=size, bgcolor=bgcolor)

        if hide_overlay:
            self.overlay.visible = prev_state

        im = png.from_array(m, mode='RGBA')
        im.save(filename)

    def visuals_at(self, pos):
        """Return visuals at given canvas position."""
        # There appears to be some odd offsets - perhaps because of the
        # window's top bar?
        pos = (pos[0] - self._rim_left, pos[1] - self._rim_top)

        # Map mouse pos to framebuffer
        tr = self.canvas.transforms.get_transform(map_from='canvas',
                                                  map_to='framebuffer')
        pos = tr.map(pos)

        # Render framebuffer in picking mode
        p = self._render_fb(crop=(pos[0] - self._picking_radius / 2,
                                  pos[1] - self._picking_radius / 2,
                                  self._picking_radius,
                                  self._picking_radius))

        logger.debug('Picking framebuffer:')
        logger.debug(p)

        # List visuals in order from distance to center
        ids = []
        seen = set()
        center = (np.array(p.shape) / 2).astype(int)
        for i in range(self._picking_radius * self.canvas.pixel_scale):
            subr = p[center[0] - i: center[0] + i + 1,
                     center[1] - i: center[1] + i + 1]
            subr_ids = set(list(np.unique(subr)))
            ids.extend(list(subr_ids - seen))
            seen |= subr_ids
        visuals = [vispy.scene.visuals.VisualNode._visual_ids.get(x, None) for x in ids]

        return [v for v in visuals if v is not None]

    def set_view(self, view):
        """Reset camera position.

        Parameters
        ----------
        view :      "XY" | "XZ" | "YZ" |
                    Use e.g. "-XY" to invert rotation

        """
        if isinstance(view, vispy.util.quaternion.Quaternion):
            q = view
        elif view == 'XY':
            q = vispy.util.quaternion.Quaternion(w=1, x=0, y=0, z=0)
        elif view == '-XY':
            q = vispy.util.quaternion.Quaternion(w=0, x=1, y=0, z=0)
        elif view == 'XZ':
            q = vispy.util.quaternion.Quaternion(w=-.65, x=-.75, y=0, z=0)
        elif view == '-XZ':
            q = vispy.util.quaternion.Quaternion(w=1, x=-.4, y=0, z=0)
        elif view == 'YZ':
            q = vispy.util.quaternion.Quaternion(w=.6, x=0.5, y=0.5, z=-.4)
        elif view == '-YZ':
            q = vispy.util.quaternion.Quaternion(w=-.5, x=-0.5, y=0.5, z=-.5)
        else:
            raise TypeError('Unable to set view from {}'.format(type(view)))

        self.camera3d._quaternion = q
        # This is necessary to force a redraw
        self.camera3d.set_range()

    def label_setup(self, labels):
        """Quickly label neurons.

        Binds keys to labels. Pressing a label key will add this label
        as `.label` property to the neuron and cycle to the next neuron.

        Parameters
        ----------
        labels :    dict
                    Dictionary mapping keys to labels. Must not use keys
                    already in use.

        Examples
        --------
        >>> # Get some neurons
        >>> nl = pymaid.get_neurons('annotation:WTPN2017_mlALT_right')
        >>> # Create viewer and add neurons
        >>> v = pymaid.Viewer()
        >>> v.add(nl)
        >>> # Bind keys to labels
        >>> v.label_setup({'n': 'PN', 'm': 'notPN'})
        >>> # Now use keys "n" and "m" to assign labels
        >>> # Subset by applied labels
        >>> pns = nl.skid[v.labels['PN']]

        """
        # TODO:
        # - Make sure to only cycle through non-labeled neurons
        # - Add labels to the actual neurons

        if not isinstance(labels, dict):
            raise TypeError('Expected dict, got "{}"'.format(type(labels)))

        self._labelmap = labels
        self.label_mode = True
        self._labels = {}
        self._cycle_neurons(0)

    @property
    def labels(self):
        """Manually assigned labels.

        See :func:`pymaid.Viewer.label_setup`.

        """
        return {l: [n for n, k in self._labels.items() if k == l] for l in self._labelmap.values()}

    def _label(self, key):
        """Check event key against annotations, adds annotation to neuron
        and cycles to the next neuron.
        """
        if self.label_mode:
            if key in self._labelmap:
                l = self._labelmap[key]
                self._labels.update({n: l for n in self.active_neuron})
                self._cycle_neurons(1)


def on_mouse_press(event):
    """Manage picking on canvas."""
    canvas = event.source
    viewer = canvas._wrapper

    try:
        viewer.interactive = False
        canvas._overlay.interactive = False
        vis_at = viewer.visuals_at([event.pos[0] + 15,
                                    event.pos[1] + 15])
    finally:
        viewer.interactive = True
        canvas._overlay.interactive = True

    logger.debug('Mouse press at {0}: {1}'.format(event.pos, vis_at))

    modifiers = [key.name for key in event.modifiers]
    if event.modifiers:
        logger.debug('Modifiers found: {0}'.format(modifiers))

    # Iterate over visuals in this canvas at cursor position
    for v in vis_at:
        # Skip views
        if isinstance(v, vispy.scene.widgets.ViewBox):
            continue
        # If legend entry, toggle visibility
        elif isinstance(v, vispy.scene.visuals.Text):
            viewer.toggle_neurons(v._object_id)
            break
        # If control modifier, try snapping cursor
        if 'Control' in modifiers:
            viewer._snap_cursor(event.pos, v,
                                open_browser='Shift' in modifiers)
            break
        # If shift modifier, add to/remove from current selection
        elif isinstance(v, vispy.scene.visuals.VisualNode) \
             and getattr(v, '_skeleton_id', None) \
             and 'Shift' in modifiers:
            if v._skeleton_id not in set(viewer.selected):
                viewer.selected = np.append(viewer.selected, v._skeleton_id)
            else:
                viewer.selected = viewer.selected[viewer.selected !=
                                                  v._skeleton_id]
            break


def on_key_press(event):
    """Manage keyboard shortcuts for canvas."""

    canvas = event.source
    viewer = canvas._wrapper

    logger.debug('Key pressed: {0}'.format(event.text))

    modifiers = [key.name for key in event.modifiers]

    if event.text.lower() == 'o':
        viewer.toggle_overlay()
    elif event.text.lower() == 'l':
        viewer.show_legend = viewer.show_legend is False
    elif event.text.lower() == 'd':
        viewer.selected = []
    elif event.text.lower() == 'q':
        viewer._cycle_neurons(-1)
    elif event.text.lower() == 'w':
        viewer._cycle_neurons(1)
    elif event.text.lower() == 'h':
        viewer.hide_selected()
    elif event.text.lower() == 'u':
        viewer.unhide_neurons(check_alpha=True)
    elif event.text.lower() == 'f':
        viewer._toggle_fps()
    elif event.text.lower() == 'p':
        viewer.toggle_picking()
    elif event.text.lower() in ['1', '2', '3', '!', '@', '£']:
        v = {'1': 'XY', '2': 'XZ', '3': 'YZ',
             '!': '-XY', '@': '-XZ', '£': '-YZ'}[event.text.lower()]
        viewer.set_view(v)
    elif event.text.lower() == 'c':
        viewer.url_to_cursor(open_browser=True)
    # If none of the above, trigger viewer label
    else:
        viewer._label(event.text.lower())


def on_resize(event):
    """Keep overlay in place upon resize."""
    viewer = event.source._wrapper
    viewer._shortcuts.pos = (10, event.size[1])
    viewer._picking_text.pos = (10, event.size[1] - 10)
    viewer._fps_text.pos = (event.size[0] - 10, 10)

    # Idea for fixing fontsize/linebreaks:
    # Render canvas to framebuffer via `_render_picking` and with region
    # outside the current canvas size: if a text ID shows up, we have to
    # resize
