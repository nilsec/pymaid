# A collection of tools to remotely access a CATMAID server via its API
#
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

""" Interface with Blender

Examples
--------
>>> from pymaid import pymaid, b3d
>>> # Initialise connection to CATMAID server
>>> rm = pymaid.CatmaidInstance( url, http_user, http_pw, token )
>>> pymaid.remote_instance = rm
>>> # Load a bunch of neurons
>>> neuronlist = pymaid.get_3D_skeleton('annotation:glomerulus DA1')
>>> handler = b3d.handler()
>>> # Export neurons into Blender
>>> handler.add( neuronlist )
>>> # Colorize
>>> handler.colorize()
>>> # Change bevel
>>> handler.bevel( .05 )
>>> # Select subset and set color
>>> handler.select( nl[:10] ).color(1,0,0)
"""

import pandas as pd
from pymaid import core, pymaid
import logging
import colorsys

try:
    import bpy
except:
    raise ImportError(
        'Unable to load bpy - this module only works from within Blender!')

module_logger = logging.getLogger('Blender')

if not module_logger.handlers:
    sh = logging.StreamHandler()
    sh.setLevel(logging.DEBUG)
    # Create formatter and add it to the handlers
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    sh.setFormatter(formatter)
    module_logger.addHandler(sh)


class handler:
    """ Class that interfaces with scene in Blender.

    Parameters
    ----------
    conversion :   float, optional
                   Conversion factor between CATMAID and Blender coordinates

    Notes
    -----
    The handler adds neurons and keeps track of them in the scene. If you
    request a list of objects via its attributes (e.g. handler.neurons) or
    via :func:`pymaid.b3d.handler.select`, a :class:`pymaid.b3d.object_list`
    is returned. This class lets you change basic parameters of your selected
    neurons.

    Attributes
    ----------
    All these attributes return an `object_list` class which you can use
    to manipulate the selection. See :class:`pymaid.b3d.object_list` for a
    list of modules.

    neurons :       returns list containing all neurons
    connectors :    returns list containing all connectors
    soma :          returns list containing all somata
    selected :      returns list containing selected objects
    presynapses :   returns list containing all presynapses
    postsynapses :  returns list containing all postsynapses
    gapjunctions :  returns list containing all gap junctions
    abutting :      returns list containing all abutting connectors
    all :           returns list containing all objects

    Examples
    --------
    >>> # Get some neurons
    >>> nl = core.CatmaidNeuronList( [ 12345, 67890 ], remote_instance = rm )
    >>> # Initialize handler
    >>> handler = b3d.handler()
    >>> # Add neurons
    >>> handler.add( nl )
    >>> # Assign colors to all neurons
    >>> handler.colorize()
    >>> # Select all somas and change color to black
    >>> handler.soma.color(0,0,0)
    >>> # Clear scene
    >>> handler.clear()
    >>> # Add only soma
    >>> handler.add( nl, neurites=False, connectors=False )
    """

    # Default colors of connectors are defined here
    cn_dict = {
        0: dict(name='presynapses',
                color=(1, 0, 0)),
        1: dict(name='postsynapses',
                color=(0, 0, 1)),
        2: dict(name='gapjunction',
                color=(0, 1, 0)),
        3: dict(name='abutting',
                color=(1, 0, 1))
    }

    def __init__(self, conversion=1 / 10000):
        self.conversion = conversion
        self.cn_dict = handler.cn_dict

        # Add indexer class
        self.ix = _IXIndexer(self)

    def __getattr__(self, key):
        if key == 'neurons' or key == 'neuron' or key == 'neurites':
            return object_list([ob.name for ob in bpy.data.objects if ob['type'] == 'NEURON'])
        elif key == 'connectors' or key == 'connector':
            return object_list([ob.name for ob in bpy.data.objects if ob['type'] == 'CONNECTORS'])
        elif key == 'soma' or key == 'somas':
            return object_list([ob.name for ob in bpy.data.objects if ob['type'] == 'SOMA'])
        elif key == 'selected':
            return object_list([ob.name for ob in bpy.context.selected_objects])
        elif key == 'presynapses':
            return object_list([ob.name for ob in bpy.data.objects if ob['type'] == 'CONNECTORS' and ob['cn_type'] == 0])
        elif key == 'postsynapses':
            return object_list([ob.name for ob in bpy.data.objects if ob['type'] == 'CONNECTORS' and ob['cn_type'] == 1])
        elif key == 'gapjunctions':
            return object_list([ob.name for ob in bpy.data.objects if ob['type'] == 'CONNECTORS' and ob['cn_type'] == 2])
        elif key == 'abutting':
            return object_list([ob.name for ob in bpy.data.objects if ob['type'] == 'CONNECTORS' and ob['cn_type'] == 3])
        elif key == 'all':
            return self.neurons + self.connectors + self.soma
        else:
            raise AttributeError('Unknown attribute ' + key)

    def add(self, x, neurites=True, soma=True, connectors=True):
        """ Add neuron(s) to scene

        Parameters
        ----------
        x :             {CatmaidNeuron, CatmaidNeuronList}
                        Neuron(s) to import into Blender
        neurites :      bool, optional
                        Plot neurites. Default = True
        soma :          bool, optional
                        Plot somas. Default = True
        connectors :    bool, optional
                        Plot connectors. Default = True
        """

        if isinstance(x, core.CatmaidNeuron):
            self._create_neuron(x, neurites=neurites,
                                soma=soma, connectors=connectors)
        elif isinstance(x, core.CatmaidNeuronList):
            for n in x:
                self._create_neuron(n, neurites=neurites,
                                    soma=soma, connectors=connectors)
                bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
        else:
            module_logger.error(
                'Unable to interpret data type ' + str(type(x)))
            raise AttributeError('Unable to add data of type' + str(type(x)))

        return

    def clear(self):
        """ Clear all neurons """
        self.all.delete()

    def _create_neuron(self, x, neurites=True, soma=True, connectors=True):
        """Create neuron object """

        mat_name = ('M#' + x.neuron_name)[:59]

        mat = bpy.data.materials.get(mat_name,
                                     bpy.data.materials.new(mat_name))

        if neurites:
            self._create_neurites(x, mat)
        if soma and x.soma:
            self._create_soma(x, mat)
        if connectors:
            self._create_connectors(x)
        return

    def _create_neurites(self, x, mat):
        """Create neuron branches """
        cu = bpy.data.curves.new(x.neuron_name + ' mesh', 'CURVE')
        ob = bpy.data.objects.new('#' + x.neuron_name, cu)
        bpy.context.scene.objects.link(ob)
        ob.location = (0, 0, 0)
        ob.show_name = True
        ob['type'] = 'NEURON'
        ob['skeleton_id'] = x.skeleton_id
        cu.dimensions = '3D'
        cu.fill_mode = 'FULL'
        cu.bevel_resolution = 5
        cu.bevel_depth = 0.007

        for s in x.slabs:
            newSpline = cu.splines.new('POLY')
            coords = x.nodes.set_index('treenode_id').ix[s][
                ['x', 'y', 'z']].as_matrix()
            coords *= self.conversion
            coords = coords.tolist()

            # Add points
            newSpline.points.add(len(coords) - 1)

            # Move points
            for i, p in enumerate(coords):
                newSpline.points[i].co = (p[0], p[2], -p[1], 0)

        ob.active_material = mat

        return

    def _create_soma(self, x, mat):
        """ Create soma """
        s = x.nodes.set_index('treenode_id').ix[x.soma]
        loc = s[['x', 'y', 'z']].as_matrix() * self.conversion
        rad = s.radius * self.conversion
        soma_ob = bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8, size=rad / 2, view_align=False,
                                                       enter_editmode=False, location=(loc[0], loc[2], -loc[1]), rotation=(0, 0, 0),
                                                       layers=[
                                                           l for l in bpy.context.scene.layers]
                                                       )
        bpy.ops.object.shade_smooth()
        bpy.context.active_object.name = 'Soma of ' + x.neuron_name
        bpy.context.active_object['type'] = 'SOMA'
        bpy.context.active_object['skeleton_id'] = x.skeleton_id

        bpy.context.scene.objects.active.active_material = mat

        return

    def _create_connectors(self, x):
        """ Create connectors """
        for i in self.cn_dict:
            con = x.connectors[x.connectors.relation == i]

            if con.empty:
                continue

            cn_coords = con[['x', 'y', 'z']].as_matrix()
            cn_coords *= self.conversion

            tn_coords = x.nodes.set_index('treenode_id').ix[
                con.treenode_id.tolist()][['x', 'y', 'z']].as_matrix()
            tn_coords *= self.conversion

            ob_name = '%s of %s' % (self.cn_dict[i]['name'], x.skeleton_id)

            cu = bpy.data.curves.new(ob_name + ' mesh', 'CURVE')
            ob = bpy.data.objects.new(ob_name, cu)
            ob['type'] = 'CONNECTORS'
            ob['cn_type'] = i
            ob['skeleton_id'] = x.skeleton_id
            bpy.context.scene.objects.link(ob)
            ob.location = (0, 0, 0)
            ob.show_name = False
            cu.dimensions = '3D'
            cu.fill_mode = 'FULL'
            cu.bevel_resolution = 0
            cu.bevel_depth = 0.007
            cu.resolution_u = 0

            for cn in zip(cn_coords, tn_coords):
                newSpline = cu.splines.new('POLY')

                # Add a second point
                newSpline.points.add(1)

                # Move points
                newSpline.points[0].co = (cn[0][0], cn[0][2], -cn[0][1], 0)
                newSpline.points[1].co = (cn[1][0], cn[1][2], -cn[1][1], 0)

            mat_name = '%s of #%s' % (
                self.cn_dict[i]['name'], str(x.skeleton_id))

            mat = bpy.data.materials.get(mat_name,
                                         bpy.data.materials.new(mat_name))
            mat.diffuse_color = self.cn_dict[i]['color']
            ob.active_material = mat

        return

    def select(self, x, *args):
        """ Select given neurons

        Parameters
        ----------
        x :     {list of skeleton IDs, CatmaidNeuron/List, pd Dataframe}

        Returns
        -------
        :class:`pymaid.b3d.object_list` :  containing requested neurons

        Examples
        --------
        >>> selection = handler.select( [123456,7890] )
        >>> # Get only connectors
        >>> cn = selection.connectors
        >>> # Hide everything else
        >>> cn.hide_others()
        >>> # Change color of presynapses
        >>> selection.presynapses.color( 0, 1, 0 )
        """

        skids = pymaid.eval_skids(x)

        names = []

        for ob in bpy.data.objects:
            ob.select = False
            if 'skeleton_id' in ob:
                if ob['skeleton_id'] in skids:
                    ob.select = True
                    names.append(ob.name)
        return object_list(names, handler=self)

    def color(self, r, g, b):
        """ Assign color to all neurons

        Parameters
        ----------
        r :     float
                red, range 0-1
        g :     float
                green, range 0-1
        b :     float
                blue, range 0-1

        Notes
        -----
        This will only change color of neurons, if you want to change
        color of e.g. connectors, use:

        >>> handler.connectors.color( r,g,b )
        """
        self.neurons.color(r, g, b)

    def colorize(self):
        """ Colorize ALL neurons

        Notes
        -----
        This will only change color of neurons, if you want to change
        color of e.g. connectors, use:

        >>> handler.connectors.colorize()
        """
        self.neurons.colorize()

    def bevel(self, r):
        """Change bevel of ALL neurons

        Parameters
        ----------
        r :         float
                    new bevel radius

        Notes
        -----
        This will only change bevel of neurons, if you want to change
        bevel of e.g. connectors, use:

        >>> handler.connectors.bevel( .02 )
        """
        self.neurons.bevel_depth(r)

    def hide(self):
        """ Hide all neuron-related objects"""
        self.all.hide()

    def unhide(self):
        """ Unide all neuron-related objects"""
        self.all.unhide()


class object_list:
    """ Collection of Blender objects

    Notes
    -----
    Object_lists should normally be constructed via the handler 
    (see :class:`pymaid.b3d.handler`)! List works with object NAMES to prevent 
    Blender from crashing when trying to access neurons that do not exist
    anymore. This also means that changing names manually will compromise a 
    object list. 

    Attributes
    ----------
    All these attributes return another `object_list` class which you can use
    to manipulate the subselection. 

    neurons :       returns list containing just neurons
    connectors :    returns list containing all connectors
    soma :          returns list containing all somata
    presynapses :   returns list containing all presynapses
    postsynapses :  returns list containing all postsynapses
    gapjunctions :  returns list containing all gap junctions
    abutting :      returns list containing all abutting connectors    

    Examples
    --------
    >>> from pymaid import pymaid, b3d
    >>> rm = pymaid.CatmaidInstance( 'server_url', 'user', 'pw', 'token' )
    >>> pymaid.remote_instance = rm
    >>> nl = pymaid.get_3D_skeleton('annotation:glomerulus DA1')
    >>> handler = b3d.handler()
    >>> handler.add( nl )
    >>> # Select only neurons on the right
    >>> right = handler.select('annotation:uPN right')
    >>> # This can be nested to change e.g. color of all right presynases
    >>> handler.select('annotation:uPN right').presynapses.color( 0, 1, 0 )

    """

    def __init__(self, object_names, handler=None):
        if not isinstance(object_names, list):
            object_names = [object_names]

        self.object_names = object_names
        self.handler = handler

    def __getattr__(self, key):
        if key == 'neurons' or key == 'neuron' or key == 'neurites':
            return object_list([n for n in self.object_names if n in bpy.data.objects and bpy.data.objects[n]['type'] == 'NEURON'])
        elif key == 'connectors' or key == 'connector':
            return object_list([n for n in self.object_names if n in bpy.data.objects and bpy.data.objects[n]['type'] == 'CONNECTORS'])
        elif key == 'soma' or key == 'somas':
            return object_list([n for n in self.object_names if n in bpy.data.objects and bpy.data.objects[n]['type'] == 'SOMA'])
        elif key == 'presynapses':
            return object_list([n for n in self.object_names if n in bpy.data.objects and bpy.data.objects[n]['type'] == 'CONNECTORS' and bpy.data.objects[n]['cn_type'] == 0])
        elif key == 'postsynapses':
            return object_list([n for n in self.object_names if n in bpy.data.objects and bpy.data.objects[n]['type'] == 'CONNECTORS' and bpy.data.objects[n]['cn_type'] == 1])
        elif key == 'gapjunctions':
            return object_list([n for n in self.object_names if n in bpy.data.objects and bpy.data.objects[n]['type'] == 'CONNECTORS' and bpy.data.objects[n]['cn_type'] == 2])
        elif key == 'abutting':
            return object_list([n for n in self.object_names if n in bpy.data.objects and bpy.data.objects[n]['type'] == 'CONNECTORS' and bpy.data.objects[n]['cn_type'] == 3])
        else:
            raise AttributeError('Unknown attribute ' + key)

    def __getitem__(self, key):
        if isinstance(key, int) or isinstance(key, slice):
            return object_list(self.object_names[key], handler=self.handler)
        else:
            raise Exception('Unable to index non-integers.')

    def __str__(self):
        return self.__repr__()

    def __repr__(self):
        self._repr = pd.DataFrame([[n, n in bpy.data.objects] for n in self.object_names],
                                  columns=['name', 'still_exists']
                                  )
        return str(self._repr)

    def __len__(self):
        return len(self.object_names)

    def __add__(self, to_add):
        if not isinstance(to_add, object_list):
            raise AttributeError('Can only merge other object lists')
        print(to_add.object_names)
        return object_list(list(set(self.object_names + to_add.object_names)),
                           handler=self.handler)

    def select(self, unselect_others=True):
        """ Select objects in 3D viewer

        Parameters
        ----------
        unselect_others :   bool, optional
                            If False, will not unselect other objects
        """
        for ob in bpy.data.objects:
            if ob.name in self.object_names:
                ob.select = True
            elif unselect_others:
                ob.select = False

    def color(self, r, g, b):
        """ Assign color to all objects in the list

        Parameters
        ----------
        r :     float
                red, range 0-1
        g :     float
                green, range 0-1
        b :     float
                blue, range 0-1
        """
        for ob in bpy.data.objects:
            if ob.name in self.object_names:
                ob.active_material.diffuse_color = (r, g, b)

    def colorize(self):
        """ Assign colors across the color spectrum
        """
        for i, n in enumerate(self.object_names):
            c = colorsys.hsv_to_rgb(1 / (len(self) + 1) * i, 1, 1)
            if n in bpy.data.objects:
                bpy.data.objects[n].active_material.diffuse_color = c

    def bevel(self, r):
        """Change bevel of objects

        Parameters
        ----------
        r :         float
                    new bevel radius 
        """
        for n in self.object_names:
            if n in bpy.data.objects:
                if bpy.data.objects[n].type == 'CURVE':
                    bpy.data.objects[n].data.bevel_depth = r

    def hide(self):
        """Hide objects"""
        for i, n in enumerate(self.object_names):
            if n in bpy.data.objects:
                bpy.data.objects[n].hide = True

    def unhide(self):
        """Unhide objects"""
        for i, n in enumerate(self.object_names):
            if n in bpy.data.objects:
                bpy.data.objects[n].hide = False

    def hide_others(self):
        """Hide everything BUT these objects"""
        for ob in bpy.data.objects:
            if ob.name in self.object_names:
                ob.hide = False
            else:
                ob.hide = True

    def delete(self):
        """Delete neurons in the selection"""
        self.select(unselect_others=True)
        bpy.ops.object.delete()
