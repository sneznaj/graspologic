﻿# Copyright (c) Microsoft Corporation and contributors.
# Licensed under the MIT License.

from typing import Any, Collection, Dict, List, Optional, Tuple, Union

import matplotlib as mpl
import matplotlib.axes
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
import sklearn.mixture
from beartype import beartype
from matplotlib.axes import Axes
from matplotlib.collections import LineCollection
from matplotlib.colors import Colormap
from mpl_toolkits.axes_grid1 import make_axes_locatable
from scipy import linalg
from scipy.sparse import csr_matrix
from sklearn.preprocessing import Binarizer
from sklearn.utils import check_array, check_consistent_length, check_X_y

from ..embed import select_svd
from ..preconditions import (
    check_argument,
    check_argument_types,
    check_optional_argument_types,
)
from ..types import GraphRepresentation
from ..utils import import_graph, pass_to_ranks

# Type aliases
FigSizeType = Tuple[int, int]


def _check_common_inputs(
    figsize: Optional[FigSizeType] = None,
    height: Optional[float] = None,
    title: Optional[str] = None,
    context: Optional[str] = None,
    font_scale: Optional[float] = None,
    legend_name: Optional[str] = None,
    title_pad: Optional[float] = None,
    hier_label_fontsize: Optional[float] = None,
) -> None:
    # Handle figsize
    if figsize is not None:
        if not isinstance(figsize, tuple):
            msg = "figsize must be a tuple, not {}.".format(type(figsize))
            raise TypeError(msg)

    # Handle heights
    if height is not None:
        if not isinstance(height, (int, float)):
            msg = "height must be an integer or float, not {}.".format(type(height))
            raise TypeError(msg)

    # Handle title
    if title is not None:
        if not isinstance(title, str):
            msg = "title must be a string, not {}.".format(type(title))
            raise TypeError(msg)

    # Handle context
    if context is not None:
        if not isinstance(context, str):
            msg = "context must be a string, not {}.".format(type(context))
            raise TypeError(msg)
        elif context not in ["paper", "notebook", "talk", "poster"]:
            msg = "context must be one of (paper, notebook, talk, poster), \
                not {}.".format(
                context
            )
            raise ValueError(msg)

    # Handle font_scale
    if font_scale is not None:
        if not isinstance(font_scale, (int, float)):
            msg = "font_scale must be an integer or float, not {}.".format(
                type(font_scale)
            )
            raise TypeError(msg)

    # Handle legend name
    if legend_name is not None:
        if not isinstance(legend_name, str):
            msg = "legend_name must be a string, not {}.".format(type(legend_name))
            raise TypeError(msg)

    if hier_label_fontsize is not None:
        if not isinstance(hier_label_fontsize, (int, float)):
            msg = "hier_label_fontsize must be a scalar, not {}.".format(
                type(legend_name)
            )
            raise TypeError(msg)

    if title_pad is not None:
        if not isinstance(title_pad, (int, float)):
            msg = "title_pad must be a scalar, not {}.".format(type(legend_name))
            raise TypeError(msg)


def _transform(arr: np.ndarray, method: Optional[str]) -> np.ndarray:
    if method is not None:
        if method in ["log", "log10"]:
            # arr = np.log(arr, where=(arr > 0))
            # hacky, but np.log(arr, where=arr>0) is really buggy
            arr = arr.copy()
            if method == "log":
                arr[arr > 0] = np.log(arr[arr > 0])
            else:
                arr[arr > 0] = np.log10(arr[arr > 0])
        elif method in ["zero-boost", "simple-all", "simple-nonzero"]:
            arr = pass_to_ranks(arr, method=method)
        elif method == "binarize":
            transformer = Binarizer().fit(arr)
            arr = transformer.transform(arr)
        else:
            msg = f"Transform must be one of {{log, log10, binarize, zero-boost, \
            simple-all, simple-nonzero}}, not {method}."
            raise ValueError(msg)

    return arr


def _process_graphs(
    graphs: Collection[np.ndarray],
    inner_hier_labels: Optional[Union[np.ndarray, List[Any]]],
    outer_hier_labels: Optional[Union[np.ndarray, List[Any]]],
    transform: Optional[str],
    sort_nodes: bool,
) -> List[np.ndarray]:
    """Handles transformation and sorting of graphs for plotting"""
    for g in graphs:
        check_consistent_length(g, inner_hier_labels, outer_hier_labels)

    graphs = [_transform(arr, transform) for arr in graphs]

    if inner_hier_labels is not None:
        inner_hier_labels = np.array(inner_hier_labels)
        if outer_hier_labels is None:
            outer_hier_labels = np.ones_like(inner_hier_labels)
        else:
            outer_hier_labels = np.array(outer_hier_labels)
    else:
        inner_hier_labels = np.ones(graphs[0].shape[0], dtype=int)
        outer_hier_labels = np.ones_like(inner_hier_labels)

    graphs = [
        _sort_graph(arr, inner_hier_labels, outer_hier_labels, sort_nodes)
        for arr in graphs
    ]
    return graphs


def heatmap(
    X: GraphRepresentation,
    transform: Optional[str] = None,
    figsize: Tuple[int, int] = (10, 10),
    title: Optional[str] = None,
    context: str = "talk",
    font_scale: int = 1,
    xticklabels: bool = False,
    yticklabels: bool = False,
    cmap: str = "RdBu_r",
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    center: int = 0,
    cbar: bool = True,
    inner_hier_labels: Optional[Union[np.ndarray, List[Any]]] = None,
    outer_hier_labels: Optional[Union[np.ndarray, List[Any]]] = None,
    hier_label_fontsize: int = 30,
    ax: Optional[matplotlib.axes.Axes] = None,
    title_pad: Optional[float] = None,
    sort_nodes: bool = False,
    **kwargs: Any,
) -> matplotlib.axes.Axes:
    r"""
    Plots a graph as a color-encoded matrix.

    Nodes can be grouped by providing ``inner_hier_labels`` or both
    ``inner_hier_labels`` and ``outer_hier_labels``. Nodes can also
    be sorted by the degree from largest to smallest degree nodes.
    The nodes will be sorted within each group if labels are also
    provided.

    Read more in the `Heatmap: Visualizing a Graph Tutorial
    <https://microsoft.github.io/graspologic/tutorials/plotting/heatmaps.html>`_

    Parameters
    ----------
    X : nx.Graph or np.ndarray object
        Graph or numpy matrix to plot

    transform : None, or string {'log', 'log10', 'zero-boost', 'simple-all', 'simple-nonzero'}

        - 'log'
            Plots the natural log of all nonzero numbers
        - 'log10'
            Plots the base 10 log of all nonzero numbers
        - 'zero-boost'
            Pass to ranks method. preserves the edge weight for all 0s, but ranks
            the other edges as if the ranks of all 0 edges has been assigned.
        - 'simple-all'
            Pass to ranks method. Assigns ranks to all non-zero edges, settling
            ties using the average. Ranks are then scaled by
            :math:`\frac{rank(\text{non-zero edges})}{n^2 + 1}`
            where n is the number of nodes
        - 'simple-nonzero'
            Pass to ranks method. Same as simple-all, but ranks are scaled by
            :math:`\frac{rank(\text{non-zero edges})}{\text{# non-zero edges} + 1}`
        - 'binarize'
            Binarize input graph such that any edge weight greater than 0 becomes 1.

    figsize : tuple of integers, optional, default: (10, 10)
        Width, height in inches.

    title : str, optional, default: None
        Title of plot.

    context :  None, or one of {paper, notebook, talk (default), poster}
        The name of a preconfigured set.

    font_scale : float, optional, default: 1
        Separate scaling factor to independently scale the size of the font
        elements.

    xticklabels, yticklabels : bool or list, optional
        If list-like, plot these alternate labels as the ticklabels.

    cmap : str, list of colors, or matplotlib.colors.Colormap, default: 'RdBu_r'
        Valid matplotlib color map.

    vmin, vmax : floats, optional (default=None)
        Values to anchor the colormap, otherwise they are inferred from the data and
        other keyword arguments.

    center : float, default: 0
        The value at which to center the colormap

    cbar : bool, default: True
        Whether to draw a colorbar.

    inner_hier_labels : array-like, length of X's first dimension, default: None
        Categorical labeling of the nodes. If not None, will group the nodes
        according to these labels and plot the labels on the marginal

    outer_hier_labels : array-like, length of X's first dimension, default: None
        Categorical labeling of the nodes, ignored without ``inner_hier_labels``
        If not None, will plot these labels as the second level of a hierarchy on the
        marginals

    hier_label_fontsize : int
        Size (in points) of the text labels for the ``inner_hier_labels`` and
        ``outer_hier_labels``.

    ax : matplotlib Axes, optional
        Axes in which to draw the plot, otherwise will generate its own axes

    title_pad : int, float or None, optional (default=None)
        Custom padding to use for the distance of the title from the heatmap. Autoscales
        if ``None``

    sort_nodes : boolean, optional (default=False)
        Whether or not to sort the nodes of the graph by the sum of edge weights
        (degree for an unweighted graph). If ``inner_hier_labels`` is passed and
        ``sort_nodes`` is ``True``, will sort nodes this way within block.

    **kwargs : dict, optional
        additional plotting arguments passed to Seaborn's ``heatmap``
    """
    _check_common_inputs(
        figsize=figsize,
        title=title,
        context=context,
        font_scale=font_scale,
        hier_label_fontsize=hier_label_fontsize,
        title_pad=title_pad,
    )

    # Handle ticklabels
    if isinstance(xticklabels, list):
        if len(xticklabels) != X.shape[1]:
            msg = "xticklabels must have same length {}.".format(X.shape[1])
            raise ValueError(msg)
    elif not isinstance(xticklabels, bool):
        msg = "xticklabels must be a bool or a list, not {}".format(type(xticklabels))
        raise TypeError(msg)

    if isinstance(yticklabels, list):
        if len(yticklabels) != X.shape[0]:
            msg = "yticklabels must have same length {}.".format(X.shape[0])
            raise ValueError(msg)
    elif not isinstance(yticklabels, bool):
        msg = "yticklabels must be a bool or a list, not {}".format(type(yticklabels))
        raise TypeError(msg)

    # Handle cmap
    if not isinstance(cmap, (str, list, Colormap)):
        msg = "cmap must be a string, list of colors, or matplotlib.colors.Colormap,"
        msg += " not {}.".format(type(cmap))
        raise TypeError(msg)

    # Handle center
    if center is not None:
        if not isinstance(center, (int, float)):
            msg = "center must be a integer or float, not {}.".format(type(center))
            raise TypeError(msg)

    # Handle cbar
    if not isinstance(cbar, bool):
        msg = "cbar must be a bool, not {}.".format(type(center))
        raise TypeError(msg)

    arr = import_graph(X)

    arr = _process_graphs(
        [arr], inner_hier_labels, outer_hier_labels, transform, sort_nodes
    )[0]

    # Global plotting settings
    CBAR_KWS = dict(shrink=0.7)  # norm=colors.Normalize(vmin=0, vmax=1))

    with sns.plotting_context(context, font_scale=font_scale):
        if ax is None:
            fig, ax = plt.subplots(figsize=figsize)
        plot = sns.heatmap(
            arr,
            cmap=cmap,
            square=True,
            xticklabels=xticklabels,
            yticklabels=yticklabels,
            cbar_kws=CBAR_KWS,
            center=center,
            cbar=cbar,
            ax=ax,
            vmin=vmin,
            vmax=vmax,
            **kwargs,
        )

        if title is not None:
            if title_pad is None:
                if inner_hier_labels is not None:
                    title_pad = 1.5 * font_scale + 1 * hier_label_fontsize + 30
                else:
                    title_pad = 1.5 * font_scale + 15
            plot.set_title(title, pad=title_pad)
        if inner_hier_labels is not None:
            if outer_hier_labels is not None:
                plot.set_yticklabels([])
                plot.set_xticklabels([])
                _plot_groups(
                    plot,
                    arr,
                    inner_hier_labels,
                    outer_hier_labels,
                    fontsize=hier_label_fontsize,
                )
            else:
                _plot_groups(plot, arr, inner_hier_labels, fontsize=hier_label_fontsize)
    return plot


def gridplot(
    X: GraphRepresentation,
    labels: Optional[List[str]] = None,
    transform: Optional[str] = None,
    height: int = 10,
    title: Optional[str] = None,
    context: str = "talk",
    font_scale: float = 1,
    alpha: float = 0.7,
    sizes: Tuple[int, int] = (10, 200),
    palette: str = "Set1",
    legend_name: str = "Type",
    inner_hier_labels: Optional[Union[np.ndarray, List[Any]]] = None,
    outer_hier_labels: Optional[Union[np.ndarray, List[Any]]] = None,
    hier_label_fontsize: int = 30,
    title_pad: Optional[float] = None,
    sort_nodes: bool = False,
) -> matplotlib.axes.Axes:
    r"""
    Plots multiple graphs on top of each other with dots as edges.

    This function is useful for visualizing multiple graphs simultaneously.
    The size of the dots correspond to the edge weights of the graphs, and
    colors represent input graphs.

    Read more in the `Gridplot: Visualize Multiple Graphs Tutorial
    <https://microsoft.github.io/graspologic/tutorials/plotting/gridplot.html>`_

    Parameters
    ----------
    X : list of nx.Graph or np.ndarray object
        List of nx.Graph or numpy arrays to plot
    labels : list of str
        List of strings, which are labels for each element in X.
        ``len(X) == len(labels)``.
    transform : None, or string {'log', 'log10', 'zero-boost', 'simple-all', 'simple-nonzero'}

        - 'log'
            Plots the natural log of all nonzero numbers
        - 'log10'
            Plots the base 10 log of all nonzero numbers
        - 'zero-boost'
            Pass to ranks method. preserves the edge weight for all 0s, but ranks
            the other edges as if the ranks of all 0 edges has been assigned.
        - 'simple-all'
            Pass to ranks method. Assigns ranks to all non-zero edges, settling
            ties using the average. Ranks are then scaled by
            :math:`\frac{rank(\text{non-zero edges})}{n^2 + 1}`
            where n is the number of nodes
        - 'simple-nonzero'
            Pass to ranks method. Same as simple-all, but ranks are scaled by
            :math:`\frac{rank(\text{non-zero edges})}{\text{# non-zero edges} + 1}`
        - 'binarize'
            Binarize input graph such that any edge weight greater than 0 becomes 1.
    height : int, optional, default: 10
        Height of figure in inches.
    title : str, optional, default: None
        Title of plot.
    context :  None, or one of {paper, notebook, talk (default), poster}
        The name of a preconfigured set.
    font_scale : float, optional, default: 1
        Separate scaling factor to independently scale the size of the font
        elements.
    palette : str, dict, optional, default: 'Set1'
        Set of colors for mapping the ``hue`` variable. If a dict, keys should
        be values in the ``hue`` variable.
        For acceptable string arguments, see the palette options at
        :doc:`Choosing Colormaps in Matplotlib <tutorials/colors/colormaps>`.
    alpha : float [0, 1], default : 0.7
        Alpha value of plotted gridplot points
    sizes : length 2 tuple, default: (10, 200)
        Min and max size to plot edge weights
    legend_name : string, default: 'Type'
        Name to plot above the legend
    inner_hier_labels : array-like, length of X's first dimension, default: None
        Categorical labeling of the nodes. If not None, will group the nodes
        according to these labels and plot the labels on the marginal
    outer_hier_labels : array-like, length of X's first dimension, default: None
        Categorical labeling of the nodes, ignored without ``inner_hier_labels``
        If not None, will plot these labels as the second level of a hierarchy on the
        marginals
    hier_label_fontsize : int
        Size (in points) of the text labels for the ``inner_hier_labels`` and
        ``outer_hier_labels``.
    title_pad : int, float or None, optional (default=None)
        Custom padding to use for the distance of the title from the heatmap. Autoscales
        if ``None``
    sort_nodes : boolean, optional (default=False)
        Whether or not to sort the nodes of the graph by the sum of edge weights
        (degree for an unweighted graph). If ``inner_hier_labels`` is passed and
        ``sort_nodes`` is ``True``, will sort nodes this way within block.
    """
    _check_common_inputs(
        height=height,
        title=title,
        context=context,
        font_scale=font_scale,
        hier_label_fontsize=hier_label_fontsize,
        title_pad=title_pad,
    )

    if isinstance(X, list):
        graphs = [import_graph(x) for x in X]
    else:
        msg = "X must be a list, not {}.".format(type(X))
        raise TypeError(msg)

    if labels is None:
        labels = np.arange(len(X))

    check_consistent_length(X, labels)

    graphs = _process_graphs(
        X, inner_hier_labels, outer_hier_labels, transform, sort_nodes
    )

    if isinstance(palette, str):
        palette = sns.color_palette(palette, desat=0.75, n_colors=len(labels))

    dfs = []
    for idx, graph in enumerate(graphs):
        rdx, cdx = np.where(graph > 0)
        weights = graph[(rdx, cdx)]
        df = pd.DataFrame(
            np.vstack([rdx + 0.5, cdx + 0.5, weights]).T,
            columns=["rdx", "cdx", "Weights"],
        )
        df[legend_name] = [labels[idx]] * len(cdx)
        dfs.append(df)

    df = pd.concat(dfs, axis=0)

    with sns.plotting_context(context, font_scale=font_scale):
        sns.set_style("white")
        plot = sns.relplot(
            data=df,
            x="cdx",
            y="rdx",
            hue=legend_name,
            size="Weights",
            sizes=sizes,
            alpha=alpha,
            palette=palette,
            height=height,
            facet_kws={
                "sharex": True,
                "sharey": True,
                "xlim": (0, graph.shape[0] + 1),
                "ylim": (0, graph.shape[0] + 1),
            },
        )
        plot.ax.axis("off")
        plot.ax.invert_yaxis()
        if title is not None:
            if title_pad is None:
                if inner_hier_labels is not None:
                    title_pad = 1.5 * font_scale + 1 * hier_label_fontsize + 30
                else:
                    title_pad = 1.5 * font_scale + 15
            plt.title(title, pad=title_pad)
    if inner_hier_labels is not None:
        if outer_hier_labels is not None:
            _plot_groups(
                plot.ax,
                graphs[0],
                inner_hier_labels,
                outer_hier_labels,
                fontsize=hier_label_fontsize,
            )
        else:
            _plot_groups(
                plot.ax, graphs[0], inner_hier_labels, fontsize=hier_label_fontsize
            )
    return plot


def pairplot(
    X: np.ndarray,
    labels: Optional[Union[np.ndarray, List[Any]]] = None,
    col_names: Optional[Union[np.ndarray, List[Any]]] = None,
    title: Optional[str] = None,
    legend_name: Optional[str] = None,
    variables: Optional[List[str]] = None,
    height: float = 2.5,
    context: str = "talk",
    font_scale: float = 1,
    palette: str = "Set1",
    alpha: float = 0.7,
    size: float = 50,
    marker: str = ".",
    diag_kind: str = "auto",
) -> sns.PairGrid:
    r"""
    Plot pairwise relationships in a dataset.

    By default, this function will create a grid of axes such that each dimension
    in data will by shared in the y-axis across a single row and in the x-axis
    across a single column.

    The off-diagonal axes show the pairwise relationships displayed as scatterplot.
    The diagonal axes show the univariate distribution of the data for that
    dimension displayed as either a histogram or kernel density estimates (KDEs).

    Read more in the `Pairplot: Visualizing High Dimensional Data Tutorial
    <https://microsoft.github.io/graspologic/tutorials/plotting/pairplot.html>`_

    Parameters
    ----------
    X : array-like, shape (n_samples, n_features)
        Input data.
    labels : array-like or list, shape (n_samples), optional
        Labels that correspond to each sample in ``X``.
    col_names : array-like or list, shape (n_features), optional
        Names or labels for each feature in ``X``. If not provided, the default
        will be `Dimension 1, Dimension 2, etc`.
    title : str, optional, default: None
        Title of plot.
    legend_name : str, optional, default: None
        Title of the legend.
    variables : list of variable names, optional
        Variables to plot based on col_names, otherwise use every column with
        a numeric datatype.
    height : int, optional, default: 10
        Height of figure in inches.
    context :  None, or one of {paper, notebook, talk (default), poster}
        The name of a preconfigured set.
    font_scale : float, optional, default: 1
        Separate scaling factor to independently scale the size of the font
        elements.
    palette : str, dict, optional, default: 'Set1'
        Set of colors for mapping the ``hue`` variable. If a dict, keys should
        be values in the ``hue`` variable.
        For acceptable string arguments, see the palette options at
        :doc:`Choosing Colormaps in Matplotlib <tutorials/colors/colormaps>`.
    alpha : float, optional, default: 0.7
        Opacity value of plotter markers between 0 and 1
    size : float or int, optional, default: 50
        Size of plotted markers.
    marker : string, optional, default: '.'
        Matplotlib marker specifier, see the marker options at
        :doc:`Matplotlib style marker specification <api/markers_api>`
    """
    _check_common_inputs(
        height=height,
        title=title,
        context=context,
        font_scale=font_scale,
        legend_name=legend_name,
    )

    # Handle X
    if not isinstance(X, (list, np.ndarray)):
        msg = "X must be array-like, not {}.".format(type(X))
        raise TypeError(msg)

    # Handle Y
    if labels is not None:
        if not isinstance(labels, (list, np.ndarray)):
            msg = "Y must be array-like or list, not {}.".format(type(labels))
            raise TypeError(msg)
        elif X.shape[0] != len(labels):
            msg = "Expected length {}, but got length {} instead for Y.".format(
                X.shape[0], len(labels)
            )
            raise ValueError(msg)

    # Handle col_names
    if col_names is None:
        col_names = ["Dimension {}".format(i) for i in range(1, X.shape[1] + 1)]
    elif not isinstance(col_names, list):
        msg = "col_names must be a list, not {}.".format(type(col_names))
        raise TypeError(msg)
    elif X.shape[1] != len(col_names):
        msg = "Expected length {}, but got length {} instead for col_names.".format(
            X.shape[1], len(col_names)
        )
        raise ValueError(msg)

    # Handle variables
    if variables is not None:
        if len(variables) > len(col_names):
            msg = "variables cannot contain more elements than col_names."
            raise ValueError(msg)
        else:
            for v in variables:
                if v not in col_names:
                    msg = "{} is not a valid key.".format(v)
                    raise KeyError(msg)
    else:
        variables = col_names

    df = pd.DataFrame(X, columns=col_names)
    if labels is not None:
        if legend_name is None:
            legend_name = "Type"
        df_labels = pd.DataFrame(labels, columns=[legend_name])
        df = pd.concat([df_labels, df], axis=1)

        names, counts = np.unique(labels, return_counts=True)
        if counts.min() < 2:
            diag_kind = "hist"
    plot_kws = dict(
        alpha=alpha,
        s=size,
        # edgecolor=None, # could add this latter
        linewidth=0,
        marker=marker,
    )
    with sns.plotting_context(context=context, font_scale=font_scale):
        if labels is not None:
            pairs = sns.pairplot(
                df,
                hue=legend_name,
                vars=variables,
                height=height,
                palette=palette,
                diag_kind=diag_kind,
                plot_kws=plot_kws,
            )
        else:
            pairs = sns.pairplot(
                df,
                vars=variables,
                height=height,
                palette=palette,
                diag_kind=diag_kind,
                plot_kws=plot_kws,
            )
        pairs.set(xticks=[], yticks=[])
        pairs.fig.subplots_adjust(top=0.945)
        pairs.fig.suptitle(title)

    return pairs


def _plot_ellipse_and_data(
    data: pd.DataFrame,
    X: np.ndarray,
    j: int,
    k: int,
    means: np.ndarray,
    covariances: np.ndarray,
    ax: matplotlib.axes.Axes,
    label_palette: Dict[Any, str],
    cluster_palette: Dict[Any, str],
    alpha: float,
) -> None:
    r"""
    plot_ellipse makes a scatter plot from the two dimensions j,k where j
    corresponds to x-axis
    and k corresponds to the y-axis onto the axis that is ax. plot_ellipse then
    applies a gmm ellipse onto the scatterplot
    using the data from Y_(which is stored in data["clusters"]),
    means, covariances.

    Parameters
    ----------
    X : array-like, shape (n_samples, n_features)
        Input data.
    j : int
        column index of feature of interest from X which will be the x-axis data.
    k : int
        column index of feature of interest from X which will be the y-axis data.
    means : array-like, shape (n_components, n_features)
        Estimated means from gmm
    covariances : array-like, shape (with 'full') (n_components, n_features, n_features)
        estimated covariances from gmm
    ax : axis object
        The location where plot_ellipse will plot
    label_palette : dict, optional, default: dictionary using 'Set1'
    cluster_palette : dict, optional, default: dictionary using 'Set1'
    alpha : float, optional, default: 0.7
        Opacity value of plotter markers between 0 and 1

    References
    ----------
    .. [1]  https://scikit-learn.org/stable/auto_examples/mixture/plot_gmm_covariances.html#sphx-glr-auto-examples-mixture-plot-gmm-covariances-py.
    """
    sns.scatterplot(
        data=data, x=X[:, j], y=X[:, k], ax=ax, hue="labels", palette=label_palette
    )
    for i, (mean, covar) in enumerate(zip(means, covariances)):
        v, w = linalg.eigh(covar)
        v = 2.0 * np.sqrt(2.0) * np.sqrt(v)
        u = w[0] / linalg.norm(w[0])
        # Plot an ellipse to show the Gaussian component
        angle = np.arctan(u[1] / u[0])
        angle = 180.0 * angle / np.pi
        ell = mpl.patches.Ellipse(
            [mean[j], mean[k]],
            v[0],
            v[1],
            180.0 + angle,
            color=cluster_palette[i],
        )
        ell.set_clip_box(ax.bbox)
        ell.set_alpha(alpha)
        ax.add_artist(ell)
        # removes tick marks from off diagonal graphs
        ax.set(xticks=[], yticks=[], xlabel=k, ylabel=k)
        ax.legend().remove()


def pairplot_with_gmm(
    X: np.ndarray,
    gmm: sklearn.mixture.GaussianMixture,
    labels: Optional[Union[np.ndarray, List[Any]]] = None,
    cluster_palette: Union[str, Dict] = "Set1",
    label_palette: Union[str, Dict] = "Set1",
    title: Optional[str] = None,
    legend_name: Optional[str] = None,
    context: str = "talk",
    font_scale: float = 1,
    alpha: float = 0.7,
    figsize: Tuple[int, int] = (12, 12),
    histplot_kws: Optional[Dict[str, Any]] = None,
) -> Tuple[matplotlib.pyplot.Figure, matplotlib.pyplot.Axes]:
    r"""
    Plot pairwise relationships in a dataset, also showing a clustering predicted by
    a Gaussian mixture model.

    By default, this function will create a grid of axes such that each dimension
    in data will by shared in the y-axis across a single row and in the x-axis
    across a single column.

    The off-diagonal axes show the pairwise relationships displayed as scatterplot.
    The diagonal axes show the univariate distribution of the data for that
    dimension displayed as either a histogram or kernel density estimates (KDEs).

    Read more in the `Pairplot with GMM: Visualizing High Dimensional Data and
    Clustering Tutorial
    <https://microsoft.github.io/graspologic/tutorials/plotting/pairplot_with_gmm.html>`_

    Parameters
    ----------
    X : array-like, shape (n_samples, n_features)
        Input data.
    gmm: GaussianMixture object
        A fit :class:`sklearn.mixture.GaussianMixture` object.
        Gaussian mixture models (GMMs) are probabilistic models for representing data
        based on normally distributed subpopulations, GMM clusters each data point into
        a corresponding subpopulation.
    labels : array-like or list, shape (n_samples), optional
        Labels that correspond to each sample in ``X``.
        If labels are not passed in then labels are predicted by ``gmm``.
    label_palette : str or dict, optional, default: 'Set1'
        Palette used to color points if ``labels`` are passed in.
    cluster_palette : str or dict, optional, default: 'Set1'
        Palette used to color GMM ellipses (and points if no ``labels`` are passed).
    title : string, default: ""
        Title of the plot.
    legend_name : string, default: None
        Name to put above the legend.
        If ``None``, will be "Cluster" if no custom ``labels`` are passed, and ""
        otherwise.
    context :  None, or one of {talk (default), paper, notebook, poster}
        Seaborn plotting context
    font_scale : float, optional, default: 1
        Separate scaling factor to independently scale the size of the font
        elements.
    alpha : float, optional, default: 0.7
        Opacity value of plotter markers between 0 and 1
    figsize : tuple
        The size of the 2d subplots configuration
    histplot_kws : dict, default: {}
        Keyword arguments passed down to :func:`seaborn.histplot`

    Returns
    -------
    fig : matplotlib Figure
    axes : np.ndarray
        Array of matplotlib Axes

    See Also
    --------
    graspologic.plot.pairplot
    graspologic.cluster.AutoGMMCluster
    sklearn.mixture.GaussianMixture
    """
    # Handle X and labels
    if labels is not None:
        check_X_y(X, labels)
        # if custom labels pass sets default
        if legend_name is None:
            legend_name = ""
    else:
        # sets default if no custom labels passed
        legend_name = "Cluster"
    # Handle gmm
    if gmm is None:
        msg = "You must input a sklearn.mixture.GaussianMixture"
        raise NameError(msg)
    Y_, means, covariances = gmm.predict(X), gmm.means_, gmm.covariances_
    data = pd.DataFrame(data=X)
    n_components = gmm.n_components

    # reformat covariances in preparation for ellipse plotting
    if gmm.covariance_type == "tied":
        covariances = np.repeat(
            gmm.covariances_[np.newaxis, :, :], n_components, axis=0
        )
    elif gmm.covariance_type == "diag":
        covariances = np.array(
            [np.diag(gmm.covariances_[i]) for i in range(n_components)]
        )
    elif gmm.covariance_type == "spherical":
        covariances = np.array(
            [
                np.diag(np.repeat(gmm.covariances_[i], X.shape[1]))
                for i in range(n_components)
            ]
        )

    # setting up the data DataFrame
    if labels is None:
        lab_names = [i for i in range(n_components)]
        data["labels"] = np.asarray([lab_names[Y_[i]] for i in range(Y_.shape[0])])
    else:
        data["labels"] = labels
    data["clusters"] = Y_
    # labels are given we must check whether input is correct
    if labels is not None:
        if isinstance(label_palette, str):
            colors = sns.color_palette(label_palette, n_components)
            label_palette = dict(zip(np.unique(np.asarray(labels)), colors))
        elif not isinstance(label_palette, dict):
            msg = "When giving labels must supply palette in string or dictionary"
            raise ValueError(msg)
        if isinstance(cluster_palette, str):
            colors = sns.color_palette(cluster_palette, n_components)
            cluster_palette = dict(zip(np.unique(Y_), colors))
        elif not isinstance(label_palette, dict):
            msg = "When giving labels must supply palette in string or dictionary"
            raise ValueError(msg)
    else:
        # no labels given we go to default.
        colors = sns.color_palette(cluster_palette, n_components)
        labels = np.unique(Y_)
        cluster_palette = dict(zip(np.unique(labels), colors))
        label_palette = dict(zip(np.unique(np.asarray(labels)), colors))

    with sns.plotting_context(context=context, font_scale=font_scale):
        dimensions = X.shape[1]
        # we only want 1 scatter plot for 2 features
        if X.shape[1] == 2:
            dimensions = 1
        fig, axes = plt.subplots(dimensions, dimensions, figsize=figsize, squeeze=False)
        # this will allow for uniform iteration whether axes was 2d or 1d
        axes = axes.flatten()

        if histplot_kws is None:
            histplot_kws = {}

        for i in range(dimensions):
            for j in range(dimensions):
                if i == j and X.shape[1] > 2:
                    # take care of the histplot on diagonal
                    for t, lab in zip([i for i in range(X.shape[1])], label_palette):
                        sns.histplot(
                            X[Y_ == t, i],
                            ax=axes[dimensions * i + j],
                            color=label_palette[lab],
                            **histplot_kws,
                        )
                    # this removes the tick marks from the histplot
                    axes[dimensions * i + j].set_xticks([])
                    axes[dimensions * i + j].set_yticks([])
                else:
                    # take care off off-diagonal scatterplots
                    dim1, dim2 = j, i
                    # with only a scatter plot we must make sure we plot
                    # the first and second feature of X
                    if X.shape[1] == 2:
                        dim1, dim2 = 0, 1
                    _plot_ellipse_and_data(
                        data,
                        X,
                        dim1,
                        dim2,
                        means,
                        covariances,
                        axes[dimensions * i + j],
                        label_palette,
                        cluster_palette,
                        alpha=alpha,
                    )
        # formatting
        if title:
            plt.suptitle(title)
        for i in range(dimensions):
            for j in range(dimensions):
                if X.shape[1] == 2:
                    axes[dimensions * i + j].set_ylabel("Dimension " + str(1))
                    axes[dimensions * i + j].set_xlabel("Dimension " + str(2))
                else:
                    axes[dimensions * i + j].set_ylabel("Dimension " + str(i + 1))
                    axes[dimensions * i + j].set_xlabel("Dimension " + str(j + 1))

        for ax in axes.flat:
            ax.label_outer()
            ax.spines["right"].set_visible(False)
            ax.spines["top"].set_visible(False)
        # set up the legend correctly by only getting handles(colored dot)
        # and label corresponding to unique pairs
        if X.shape[1] == 2:
            handles, labels = axes[0].get_legend_handles_labels()
        else:
            handles, labels = axes[1].get_legend_handles_labels()
        fig.legend(
            handles,
            labels,
            loc="center right",
            title=legend_name,
        )
        # allows for the legend to not overlap with plots while also keeping
        # legend in frame
        fig.subplots_adjust(right=0.85)
        return fig, axes


def _distplot(
    data: np.ndarray,
    labels: Optional[Union[np.ndarray, List[Any]]] = None,
    direction: str = "out",
    title: str = "",
    context: str = "talk",
    font_scale: float = 1,
    figsize: Tuple[int, int] = (10, 5),
    palette: str = "Set1",
    xlabel: str = "",
    ylabel: str = "Density",
) -> matplotlib.pyplot.Axes:

    plt.figure(figsize=figsize)
    ax = plt.gca()
    palette = sns.color_palette(palette)
    plt_kws = {"cumulative": True}
    with sns.plotting_context(context=context, font_scale=font_scale):
        if labels is not None:
            categories, counts = np.unique(labels, return_counts=True)
            for i, cat in enumerate(categories):
                cat_data = data[np.where(labels == cat)]
                if counts[i] > 1 and cat_data.min() != cat_data.max():
                    x = np.sort(cat_data)
                    y = np.arange(len(x)) / float(len(x))
                    plt.plot(x, y, label=cat, color=palette[i])
                else:
                    ax.axvline(cat_data[0], label=cat, color=palette[i])
            plt.legend()
        else:
            if data.min() != data.max():
                sns.histplot(data, hist=False, kde_kws=plt_kws)
            else:
                ax.axvline(data[0])

        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)

    return ax


def degreeplot(
    X: np.ndarray,
    labels: Optional[Union[np.ndarray, List[Any]]] = None,
    direction: str = "out",
    title: str = "Degree plot",
    context: str = "talk",
    font_scale: float = 1,
    figsize: Tuple[int, int] = (10, 5),
    palette: str = "Set1",
) -> matplotlib.pyplot.Axes:
    r"""
    Plots the distribution of node degrees for the input graph.
    Allows for sets of node labels, will plot a distribution for each
    node category.

    Parameters
    ----------
    X : np.ndarray (2D)
        input graph
    labels : 1d np.ndarray or list, same length as dimensions of ``X``
        Labels for different categories of graph nodes
    direction : string, ('out', 'in')
        Whether to plot out degree or in degree for a directed graph
    title : string, default : 'Degree plot'
        Plot title
    context :  None, or one of {talk (default), paper, notebook, poster}
        Seaborn plotting context
    font_scale : float, optional, default: 1
        Separate scaling factor to independently scale the size of the font
        elements.
    palette : str, dict, optional, default: 'Set1'
        Set of colors for mapping the ``hue`` variable. If a dict, keys should
        be values in the ``hue`` variable.
        For acceptable string arguments, see the palette options at
        :doc:`Choosing Colormaps in Matplotlib <tutorials/colors/colormaps>`.
    figsize : tuple of length 2, default (10, 5)
        Size of the figure (width, height)

    Returns
    -------
    ax : matplotlib axis object
        Output plot
    """
    _check_common_inputs(
        figsize=figsize, title=title, context=context, font_scale=font_scale
    )
    check_array(X)
    if direction == "out":
        axis = 0
        check_consistent_length((X, labels))
    elif direction == "in":
        axis = 1
        check_consistent_length((X.T, labels))
    else:
        raise ValueError('direction must be either "out" or "in"')
    degrees = np.count_nonzero(X, axis=axis)
    ax = _distplot(
        degrees,
        labels=labels,
        title=title,
        context=context,
        font_scale=font_scale,
        figsize=figsize,
        palette=palette,
        xlabel="Node degree",
    )
    return ax


def edgeplot(
    X: np.ndarray,
    labels: Optional[Union[np.ndarray, List[Any]]] = None,
    nonzero: bool = False,
    title: str = "Edge plot",
    context: str = "talk",
    font_scale: float = 1,
    figsize: Tuple[int, int] = (10, 5),
    palette: str = "Set1",
) -> matplotlib.pyplot.Axes:
    r"""
    Plots the distribution of edge weights for the input graph.
    Allows for sets of node labels, will plot edge weight distribution
    for each node category.

    Parameters
    ----------
    X : np.ndarray (2D)
        Input graph
    labels : 1d np.ndarray or list, same length as dimensions of ``X``
        Labels for different categories of graph nodes
    nonzero : boolean, default: False
        Whether to restrict the edgeplot to only the non-zero edges
    title : string, default : 'Edge plot'
        Plot title
    context :  None, or one of {talk (default), paper, notebook, poster}
        Seaborn plotting context
    font_scale : float, optional, default: 1
        Separate scaling factor to independently scale the size of the font
        elements.
    palette : str, dict, optional, default: 'Set1'
        Set of colors for mapping the ``hue`` variable. If a dict, keys should
        be values in the ``hue`` variable.
        For acceptable string arguments, see the palette options at
        :doc:`Choosing Colormaps in Matplotlib <tutorials/colors/colormaps>`.
    figsize : tuple of length 2, default (10, 5)
        Size of the figure (width, height)

    Returns
    -------
    ax : matplotlib axis object
        Output plot
    """
    _check_common_inputs(
        figsize=figsize, title=title, context=context, font_scale=font_scale
    )
    check_array(X)
    check_consistent_length((X, labels))
    edges = X.ravel()
    labels = np.tile(labels, (1, X.shape[1]))
    labels = labels.ravel()  # type: ignore
    if nonzero:
        labels = labels[edges != 0]
        edges = edges[edges != 0]
    ax = _distplot(
        edges,
        labels=labels,
        title=title,
        context=context,
        font_scale=font_scale,
        figsize=figsize,
        palette=palette,
        xlabel="Edge weight",
    )
    return ax


@beartype
def networkplot(
    adjacency: Union[np.ndarray, csr_matrix],
    x: Union[np.ndarray, str],
    y: Union[np.ndarray, str],
    node_data: Optional[pd.DataFrame] = None,
    node_hue: Optional[Union[np.ndarray, str]] = None,
    palette: Optional[Union[str, list, dict]] = None,
    node_size: Optional[Union[np.ndarray, str]] = None,
    node_sizes: Optional[Union[list, dict, tuple]] = None,
    node_alpha: float = 0.8,
    edge_hue: str = "source",
    edge_linewidth: float = 0.2,
    edge_alpha: float = 0.2,
    title: str = "",
    context: str = "talk",
    font_scale: float = 1.0,
    figsize: Tuple[int, int] = (10, 10),
    ax: Optional[Axes] = None,
    legend: Optional[str] = None,
    node_kws: dict = {},
    edge_kws: dict = {},
) -> Axes:
    r"""
    Plots a 2D layout of a network. Allows for an adjacency matrix
    with ``x, y`` as 1D arrays that represent the coordinates of each
    node, or an adjacency matrix with ``node_data`` and ``x, y`` as
    keys. Note that the nodes in the adjacency matrix are assumed to be ordered the same
    way as in ``x``, ``y``, and ``node_data``.

    Parameters
    ----------
    adjacency: np.ndarray, csr_matrix
        Adjacency matrix of input network.
    x,y: np.ndarray, str
        Variables that specify the positions on the x and y axes. Either an
        array of x, y coordinates or a string that accesses a vector in
        ``node_data``. If ``x, y`` are arrays, they must be indexed the
        same way as the adjacency matrix of the input network.
    node_data: pd.DataFrame, optional, default: None
        Input data. When ``node_data`` is None, ``x, y`` must be np.ndarrays.
        When ``node_data`` is a dataframe, ``x, y`` must be strings. Must be
        indexed the same way as the adjacency matrix of the input network.
    node_hue: np.ndarray, str, optional, default: None
        Variable that produces nodes with different colors. Can be either
        categorical or numeric, and colors are mapped based on ``palette``.
        However if ``palette`` is None, ``node_hue`` is treated as numeric
        and 'Set1' is used as ``palette``.
    palette: str, list, dict, optional, default: None
        Method for choosing colors specified in ``node_hue``. Can be a string
        argument supported by :func:`seaborn.color_palette`, a list of colors,
        or a dictionary with ``node_hue`` variables as keys and colors as its
        values. Note that ``palette`` will not affect the plot if ``node_hue``
        is not given.
    node_size: np.ndarray, str, optional, default: None
        Variable that produces nodes with different sizes. Can be either categorical
        or numeric, and sizes are determined based on ``node_sizes``. If the
        argument ``node_sizes`` is None, ``node_size`` will be treated as
        numeric variables.
    node_sizes: list, dict, tuple, optional, default: None
        Method for choosing sizes specified in ``node_size``. Can be a list of
        sizes, a dictionary with ``node_size`` variables as keys and sizes as
        its values, or a tuple defining the minimum and maximum size values.
        Note that ``node_sizes`` will not affect the output plot if ``node_hue``
        is not given.
    node_alpha: float, default: 0.8
        Proportional opacity of the nodes.
    edge_hue: str, one of {source (default), target}
        Determines edge color based on its source or target node.
    edge_linewidth: float, default: 0.2
        Linewidth of the edges.
    edge_alpha: float, default: 0.2
        Proportional opacity of the edges.
    title: str
        Plot title.
    context :  None, or one of {talk (default), paper, notebook, poster}
        Seaborn plotting context
    font_scale : float, optional, default: 1.0
        Separate scaling factor to independently scale the size of the font
        elements.
    figsize : tuple of length 2, default: (10, 10)
        Size of the figure (width, height)
    ax: matplotlib.axes.Axes, optional, default: None
        Axes in which to draw the plot. Otherwise, will generate own axes.
    legend: None (default), or one of {brief, full, auto}
        How to draw the legend. If “brief”, numeric hue and size variables
        will be represented with a sample of evenly spaced values. If “full”,
        every group will get an entry in the legend. If “auto”, choose
        between brief or full representation based on number of levels. If
        None, no legend data is added and no legend is drawn.
    node_kws: dict, optional
        Optional arguments for :func:`seaborn.scatterplot`.
    edge_kws: dict, optional
        Optional arguments for :class:`matplotlib.collections.LineCollection`.

    Returns
    -------
    ax : matplotlib axis object
        Output plot

    Notes
    -----
    Node colors are determined by ``node_hue`` and ``palette``, and if
    ``node_hue`` is None, all nodes will have the same default color
    used by :func:`seaborn.scatterplot`. If ``node_hue`` is given but
    ``palette`` is None, ``palette`` is set to 'Set1' and ``node_hue``
    will be treated as numeric variables. Edge colors are determined by
    its nodes, and ``edge_hue`` dictates whether the edges are colored
    based on its source or target nodes.

    Node sizes can also vary based on ``node_size`` and ``node_sizes``,
    and if ``node_size`` is None, all nodes will be of the same default
    size used by :func:`seaborn.scatterplot`. If ``node_size`` is given
    but ``node_sizes`` is None, ``node_size`` will be treated as numeric
    variables.

    Note that ``palette`` and ``node_sizes`` will not affect the output
    plot if ``node_hue`` and ``node_size`` are None, and ``node_hue`` and
    ``node_size`` must be the same types as ``x, y``.

    """

    _check_common_inputs(
        figsize=figsize, title=title, context=context, font_scale=font_scale
    )

    index = range(adjacency.shape[0])
    hue_key: Optional[str]
    if isinstance(x, np.ndarray):
        check_consistent_length(adjacency, x, y)
        check_argument(
            node_data is None, "If x and y are numpy arrays, meta_data must be None."
        )
        plot_df = pd.DataFrame(index=index)
        x_key = "x"
        y_key = "y"
        plot_df.loc[:, x_key] = x
        plot_df.loc[:, y_key] = y
        if node_hue is not None:
            check_argument(
                isinstance(node_hue, np.ndarray),
                "If x and y are numpy arrays, node_hue must be a list or a numpy array.",
            )
            check_consistent_length(x, node_hue)
            hue_key = "hue"
            plot_df.loc[:, hue_key] = node_hue
            if palette is None:
                palette = "Set1"
        else:
            hue_key = None
    elif isinstance(x, str) and isinstance(y, str):
        check_consistent_length(adjacency, node_data)
        if not isinstance(node_data, pd.DataFrame):
            raise ValueError(
                "If x and y are strings, node_data must be pandas DataFrame."
            )
        plot_df = node_data.copy()
        x_key = x
        y_key = y
        if node_hue is not None:
            if not isinstance(node_hue, str):
                raise ValueError(
                    "If x and y are strings, node_hue must also be a string."
                )
            hue_key = node_hue
            if palette is None:
                palette = "Set1"
        else:
            hue_key = None
    else:
        raise TypeError("x and y must be numpy arrays or strings.")

    pre_inds, post_inds = adjacency.nonzero()
    pre = np.array(index)[pre_inds.astype(int)]
    post = np.array(index)[post_inds.astype(int)]
    rows = {"source": pre, "target": post}

    edgelist = pd.DataFrame(rows)
    pre_edgelist = edgelist.copy()
    post_edgelist = edgelist.copy()

    pre_edgelist["x"] = pre_edgelist["source"].map(plot_df[x_key])
    pre_edgelist["y"] = pre_edgelist["source"].map(plot_df[y_key])
    post_edgelist["x"] = post_edgelist["target"].map(plot_df[x_key])
    post_edgelist["y"] = post_edgelist["target"].map(plot_df[y_key])
    pre_coords = list(zip(pre_edgelist["x"], pre_edgelist["y"]))
    post_coords = list(zip(post_edgelist["x"], post_edgelist["y"]))
    coords = list(zip(pre_coords, post_coords))

    plot_palette: Optional[Dict]

    if node_hue is not None:
        if isinstance(palette, str):
            sns_palette: List = sns.color_palette(
                palette, n_colors=len(plot_df[hue_key].unique())
            )
            plot_palette = dict(zip(plot_df[hue_key].unique(), sns_palette))
        elif isinstance(palette, list):
            plot_palette = dict(zip(plot_df[hue_key].unique(), palette))
        elif isinstance(palette, dict):
            plot_palette = palette
        edgelist[hue_key] = edgelist[edge_hue].map(plot_df[hue_key])
        edge_colors = edgelist[hue_key].map(plot_palette)
    else:
        plot_palette = None
        edge_colors = None

    with sns.plotting_context(context=context, font_scale=font_scale):
        if ax is None:
            _, ax = plt.subplots(1, 1, figsize=figsize)
        sns.scatterplot(
            data=plot_df,
            x=x_key,
            y=y_key,
            hue=hue_key,
            palette=plot_palette,
            size=node_size,
            sizes=node_sizes,
            ax=ax,
            legend=legend,
            alpha=node_alpha,
            zorder=1,
            **node_kws,
        )
        ax.set_title(title)
        lc = LineCollection(
            segments=coords,
            alpha=edge_alpha,
            linewidths=edge_linewidth,
            colors=edge_colors,
            zorder=0,
            **edge_kws,
        )
        ax.add_collection(lc)
        ax.set(xticks=[], yticks=[])

    return ax


def screeplot(
    X: np.ndarray,
    title: str = "Scree plot",
    context: str = "talk",
    font_scale: float = 1,
    figsize: Tuple[int, int] = (10, 5),
    cumulative: bool = True,
    show_first: Optional[int] = None,
) -> matplotlib.pyplot.Axes:
    r"""
    Plots the distribution of singular values for a matrix, either showing the
    raw distribution or an empirical CDF (depending on ``cumulative``)

    Parameters
    ----------
    X : np.ndarray (2D)
        Input matrix
    title : string, default : 'Scree plot'
        Plot title
    context :  None, or one of {talk (default), paper, notebook, poster}
        Seaborn plotting context
    font_scale : float, optional, default: 1
        Separate scaling factor to independently scale the size of the font
        elements.
    figsize : tuple of length 2, default (10, 5)
        Size of the figure (width, height)
    cumulative : boolean, default: True
        Whether or not to plot a cumulative cdf of singular values
    show_first : int or None, default: None
        Whether to restrict the plot to the first ``show_first`` components

    Returns
    -------
    ax : matplotlib axis object
        Output plot
    """
    _check_common_inputs(
        figsize=figsize, title=title, context=context, font_scale=font_scale
    )
    check_array(X)
    if show_first is not None:
        if not isinstance(show_first, int):
            msg = "show_first must be an int"
            raise TypeError(msg)
    if not isinstance(cumulative, bool):
        msg = "cumulative must be a boolean"
        raise TypeError(msg)
    _, D, _ = select_svd(X, n_components=X.shape[1], algorithm="full")
    D /= D.sum()
    if cumulative:
        y = np.cumsum(D[:show_first])
    else:
        y = D[:show_first]
    _ = plt.figure(figsize=figsize)
    ax = plt.gca()
    xlabel = "Component"
    ylabel = "Variance explained"
    with sns.plotting_context(context=context, font_scale=font_scale):
        plt.plot(y)
        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel(ylabel)
    return ax


def _sort_inds(
    graph: np.ndarray,
    inner_labels: np.ndarray,
    outer_labels: np.ndarray,
    sort_nodes: bool,
) -> np.ndarray:
    sort_df = pd.DataFrame(columns=("inner_labels", "outer_labels"))
    sort_df["inner_labels"] = inner_labels
    sort_df["outer_labels"] = outer_labels

    # get frequencies of the different labels so we can sort by them
    inner_label_counts = _get_freq_vec(inner_labels)
    outer_label_counts = _get_freq_vec(outer_labels)

    # inverse counts so we can sort largest to smallest
    # would rather do it this way so can still sort alphabetical for ties
    sort_df["inner_counts"] = len(inner_labels) - inner_label_counts
    sort_df["outer_counts"] = len(outer_labels) - outer_label_counts

    # get node edge sums (not exactly degrees if weighted)
    node_edgesums = graph.sum(axis=1) + graph.sum(axis=0)
    sort_df["node_edgesums"] = node_edgesums.max() - node_edgesums

    if sort_nodes:
        by = [
            "outer_counts",
            "outer_labels",
            "inner_counts",
            "inner_labels",
            "node_edgesums",
        ]
    else:
        by = ["outer_counts", "outer_labels", "inner_counts", "inner_labels"]
    sort_df.sort_values(by=by, kind="mergesort", inplace=True)

    sorted_inds = sort_df.index.values
    return sorted_inds


def _sort_graph(
    graph: np.ndarray,
    inner_labels: np.ndarray,
    outer_labels: np.ndarray,
    sort_nodes: bool,
) -> np.ndarray:
    inds = _sort_inds(graph, inner_labels, outer_labels, sort_nodes)
    graph = graph[inds, :][:, inds]
    return graph


def _get_freqs(
    inner_labels: np.ndarray, outer_labels: np.ndarray
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    # use this because unique would give alphabetical
    _, outer_freq = _unique_like(outer_labels)
    outer_freq_cumsum = np.hstack((0, outer_freq.cumsum()))

    # for each group of outer labels, calculate the boundaries of the inner labels
    inner_freq = np.array([])
    for i in range(outer_freq.size):
        start_ind = outer_freq_cumsum[i]
        stop_ind = outer_freq_cumsum[i + 1]
        _, temp_freq = _unique_like(inner_labels[start_ind:stop_ind])
        inner_freq = np.hstack([inner_freq, temp_freq])
    inner_freq_cumsum = np.hstack((0, inner_freq.cumsum()))

    return inner_freq, inner_freq_cumsum, outer_freq, outer_freq_cumsum


def _get_freq_vec(vals: np.ndarray) -> np.ndarray:
    # give each set of labels a vector corresponding to its frequency
    _, inv, counts = np.unique(vals, return_counts=True, return_inverse=True)
    count_vec = counts[inv]
    return count_vec


def _unique_like(vals: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    # gives output like
    uniques, inds, counts = np.unique(vals, return_index=True, return_counts=True)
    inds_sort = np.argsort(inds)
    uniques = uniques[inds_sort]
    counts = counts[inds_sort]
    return uniques, counts


# assume that the graph has already been plotted in sorted form
def _plot_groups(
    ax: matplotlib.pyplot.Axes,
    graph: np.ndarray,
    inner_labels: Union[np.ndarray, List[Any]],
    outer_labels: Optional[Union[np.ndarray, List[Any]]] = None,
    fontsize: int = 30,
) -> matplotlib.pyplot.Axes:
    inner_labels_arr = np.array(inner_labels)
    plot_outer = True
    if outer_labels is None:
        outer_labels_arr = np.ones_like(inner_labels)
        plot_outer = False
    else:
        outer_labels_arr = np.array(outer_labels)

    sorted_inds = _sort_inds(graph, inner_labels_arr, outer_labels_arr, False)
    inner_labels_arr = inner_labels_arr[sorted_inds]
    outer_labels_arr = outer_labels_arr[sorted_inds]

    inner_freq, inner_freq_cumsum, outer_freq, outer_freq_cumsum = _get_freqs(
        inner_labels_arr, outer_labels_arr
    )
    inner_unique, _ = _unique_like(inner_labels_arr)
    outer_unique, _ = _unique_like(outer_labels_arr)

    n_verts = graph.shape[0]
    axline_kws = dict(linestyle="dashed", lw=0.9, alpha=0.3, zorder=3, color="grey")
    # draw lines
    for x in inner_freq_cumsum[1:-1]:
        ax.vlines(x, 0, n_verts + 1, **axline_kws)
        ax.hlines(x, 0, n_verts + 1, **axline_kws)

    # add specific lines for the borders of the plot
    pad = 0.001
    low = pad
    high = 1 - pad
    ax.plot((low, low), (low, high), transform=ax.transAxes, **axline_kws)
    ax.plot((low, high), (low, low), transform=ax.transAxes, **axline_kws)
    ax.plot((high, high), (low, high), transform=ax.transAxes, **axline_kws)
    ax.plot((low, high), (high, high), transform=ax.transAxes, **axline_kws)

    # generic curve that we will use for everything
    lx = np.linspace(-np.pi / 2.0 + 0.05, np.pi / 2.0 - 0.05, 500)
    tan = np.tan(lx)
    curve = np.hstack((tan[::-1], tan))

    divider = make_axes_locatable(ax)

    # inner curve generation
    inner_tick_loc = inner_freq.cumsum() - inner_freq / 2
    inner_tick_width = inner_freq / 2
    # outer curve generation
    outer_tick_loc = outer_freq.cumsum() - outer_freq / 2
    outer_tick_width = outer_freq / 2

    # top inner curves
    ax_x = divider.new_vertical(size="5%", pad=0.0, pack_start=False)
    ax.figure.add_axes(ax_x)
    _plot_brackets(
        ax_x,
        np.tile(inner_unique, len(outer_unique)),
        inner_tick_loc,
        inner_tick_width,
        curve,
        "inner",
        "x",
        n_verts,
        fontsize,
    )
    # side inner curves
    ax_y = divider.new_horizontal(size="5%", pad=0.0, pack_start=True)
    ax.figure.add_axes(ax_y)
    _plot_brackets(
        ax_y,
        np.tile(inner_unique, len(outer_unique)),
        inner_tick_loc,
        inner_tick_width,
        curve,
        "inner",
        "y",
        n_verts,
        fontsize,
    )

    if plot_outer:
        # top outer curves
        pad_scalar = 0.35 / 30 * fontsize
        ax_x2 = divider.new_vertical(size="5%", pad=pad_scalar, pack_start=False)
        ax.figure.add_axes(ax_x2)
        _plot_brackets(
            ax_x2,
            outer_unique,
            outer_tick_loc,
            outer_tick_width,
            curve,
            "outer",
            "x",
            n_verts,
            fontsize,
        )
        # side outer curves
        ax_y2 = divider.new_horizontal(size="5%", pad=pad_scalar, pack_start=True)
        ax.figure.add_axes(ax_y2)
        _plot_brackets(
            ax_y2,
            outer_unique,
            outer_tick_loc,
            outer_tick_width,
            curve,
            "outer",
            "y",
            n_verts,
            fontsize,
        )
    return ax


def _plot_brackets(
    ax: matplotlib.pyplot.Axes,
    group_names: np.ndarray,
    tick_loc: np.ndarray,
    tick_width: np.ndarray,
    curve: np.ndarray,
    level: str,
    axis: str,
    max_size: int,
    fontsize: int,
) -> None:
    for x0, width in zip(tick_loc, tick_width):
        x = np.linspace(x0 - width, x0 + width, 1000)
        if axis == "x":
            ax.plot(x, -curve, c="k")
            ax.patch.set_alpha(0)
        elif axis == "y":
            ax.plot(curve, x, c="k")
            ax.patch.set_alpha(0)
    ax.set_yticks([])
    ax.set_xticks([])
    ax.tick_params(axis=axis, which="both", length=0, pad=7)
    for direction in ["left", "right", "bottom", "top"]:
        ax.spines[direction].set_visible(False)
    if axis == "x":
        ax.set_xticks(tick_loc)
        ax.set_xticklabels(group_names, fontsize=fontsize, verticalalignment="center")
        ax.xaxis.set_label_position("top")
        ax.xaxis.tick_top()
        ax.xaxis.labelpad = 30
        ax.set_xlim(0, max_size)
        ax.tick_params(axis="x", which="major", pad=5 + fontsize / 4)
    elif axis == "y":
        ax.set_yticks(tick_loc)
        ax.set_yticklabels(group_names, fontsize=fontsize, verticalalignment="center")
        ax.set_ylim(0, max_size)
        ax.invert_yaxis()
