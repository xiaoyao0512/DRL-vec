"""
A NetworkX addon program to compute the Ollivier-Ricci curvature of a given NetworkX graph.



Author:

    Chien-Chun Ni
    http://www3.cs.stonybrook.edu/~chni/

Reference:
    Ni, C.-C., Lin, Y.-Y., Gao, J., Gu, X., & Saucan, E. (2015). Ricci curvature of the Internet topology (Vol. 26, pp. 2758-2766). Presented at the 2015 IEEE Conference on Computer Communications (INFOCOM), IEEE.
    Ollivier, Y. (2009). Ricci curvature of Markov chains on metric spaces. Journal of Functional Analysis, 256(3), 810-864.

Change logs:

    2018-08-04  |  added time_info - Boolean value to suppress time info.

"""

from multiprocessing import Pool,cpu_count

import importlib
import time

import cvxpy as cvx
import networkx as nx
import numpy as np


def ricciCurvature_singleEdge(G, source, target, alpha, length, verbose):
    """
    Ricci curvature computation process for a given single edge.

    :param G: The original graph
    :param source: The index of the source node
    :param target: The index of the target node
    :param alpha: Ricci curvature parameter
    :param length: all pair shortest paths dict
    :param verbose: print detail log
    :return: The Ricci curvature of given edge
    """

    EPSILON = 1e-7  # to prevent divided by zero

    assert source != target, "Self loop is not allowed."  # to prevent self loop

    # If the weight of edge is too small, return 0 instead.
    if length[source][target] < EPSILON:
        print("Zero Weight edge detected, return ricci Curvature as 0 instead.")
        return {(source, target): 0}

    source_nbr = list(G.predecessors(source)) if G.is_directed() else list(G.neighbors(source))
    target_nbr = list(G.successors(target)) if G.is_directed() else list(G.neighbors(target))

    # Append source and target node into weight distribution matrix x,y
    if not source_nbr:
        source_nbr.append(source)
        x = [1]
    else:
        x = [(1.0 - alpha) / len(source_nbr)] * len(source_nbr)
        source_nbr.append(source)
        x.append(alpha)

    if not target_nbr:
        target_nbr.append(target)
        y = [1]
    else:
        y = [(1.0 - alpha) / len(target_nbr)] * len(target_nbr)
        target_nbr.append(target)
        y.append(alpha)

    # construct the cost dictionary from x to y
    d = np.zeros((len(x), len(y)))

    for i, s in enumerate(source_nbr):
        for j, t in enumerate(target_nbr):
            assert t in length[s], "Target node not in list, should not happened, pair (%d, %d)" % (s, t)
            d[i][j] = length[s][t]

    x = np.array([x]).T  # the mass that source neighborhood initially owned
    y = np.array([y]).T  # the mass that target neighborhood needs to received

    t0 = time.time()
    rho = cvx.Variable((len(target_nbr), len(source_nbr)))  # the transportation plan rho

    # objective function d(x,y) * rho * x, need to do element-wise multiply here
    obj = cvx.Minimize(cvx.sum(cvx.multiply(np.multiply(d.T, x.T), rho)))

    # \sigma_i rho_{ij}=[1,1,...,1]
    source_sum = cvx.sum(rho, axis=0, keepdims=True)
    constrains = [rho * x == y, source_sum == np.ones((1, (len(source_nbr)))), 0 <= rho, rho <= 1]
    prob = cvx.Problem(obj, constrains)

    m = prob.solve(solver="ECOS_BB")  # change solver here if you want
    if verbose:
        print(time.time() - t0, " secs for cvxpy.",)

    result = 1 - (m / length[source][target])  # divided by the length of d(i, j)
    if verbose:
        print("#source_nbr: %d, #target_nbr: %d, Ricci curvature = %f" % (len(source_nbr), len(target_nbr), result))

    return {(source, target): result}


def _wrapRicci(stuff):
    return ricciCurvature_singleEdge(*stuff)


def ricciCurvature(G, alpha=0.5, weight=None, proc=cpu_count(), edge_list=[], verbose=False, time_info=False):
    """
     Compute ricci curvature for all nodes and edges in G.
         Node ricci curvature is defined as the average of all it's adjacency edge.
     :param G: A connected NetworkX graph.
     :param alpha: The parameter for the discrete ricci curvature, range from 0 ~ 1.
                     It means the share of mass to leave on the original node.
                     eg. x -> y, alpha = 0.4 means 0.4 for x, 0.6 to evenly spread to x's nbr.
     :param weight: The edge weight used to compute Ricci curvature.
     :param proc: Number of processing used for parallel computing
     :param edge_list: Target edges to compute curvature
     :param verbose: Set True to output the detailed log.
     :return: G: A NetworkX graph with Ricci Curvature with edge attribute "ricciCurvature"
     """

    # JCS - added time_info argument to suppress time info console output

    # Construct the all pair shortest path lookup
    if importlib.util.find_spec("networkit") is not None:
        import networkit as nk
        t0 = time.time()
        Gk = nk.nxadapter.nx2nk(G, weightAttr=weight)
        apsp = nk.distance.APSP(Gk).run().getDistances()
        length = {}
        for i, n1 in enumerate(G.nodes()):
            length[n1] = {}
            for j, n2 in enumerate(G.nodes()):
                length[n1][n2] = apsp[i][j]
        if time_info:
            print(time.time() - t0, " sec for all pair by NetworKit.")
    else:
        print("NetworKit not found, use NetworkX for all pair shortest path instead.")
        t0 = time.time()
        length = dict(nx.all_pairs_dijkstra_path_length(G, weight=weight))
        print(time.time() - t0, " sec for all pair.")

    t0 = time.time()
    # compute edge ricci curvature
    p = Pool(processes=proc)

    # if there is no assigned edges to compute, compute all edges instead
    if not edge_list:
        edge_list = G.edges()
    args = [(G, source, target, alpha, length, verbose) for source, target in edge_list]

    result = p.map_async(_wrapRicci, args)
    result = result.get()
    p.close()
    p.join()

    # assign edge Ricci curvature from result to graph G
    for rc in result:
        for k in list(rc.keys()):
            source, target = k
            G[source][target]['ricciCurvature'] = rc[k]

    # compute node Ricci curvature
    for n in G.nodes():
        rcsum = 0  # sum of the neighbor Ricci curvature
        if G.degree(n) != 0:
            for nbr in G.neighbors(n):
                if 'ricciCurvature' in G[n][nbr]:
                    rcsum += G[n][nbr]['ricciCurvature']

            # assign the node Ricci curvature to be the average of node's adjacency edges
            G.node[n]['ricciCurvature'] = rcsum / G.degree(n)
            if verbose:
                print("node %d, Ricci Curvature = %f" % (n, G.node[n]['ricciCurvature']))

    if time_info:
        print(time.time() - t0, " sec for Ricci curvature computation.")
    return G
