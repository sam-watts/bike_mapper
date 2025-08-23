"""
Graph-tool based routing module that replicates OSMnx routing functionality.

This module provides efficient routing capabilities using graph-tool instead of networkx,
while maintaining compatibility with OSMnx data structures and workflows.
"""

import logging
from typing import List, Tuple, Dict, Any, Optional, Union
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import LineString, Point
import networkx as nx
from collections import defaultdict
import graph_tool as gt
from graph_tool.topology import shortest_path
from sklearn.neighbors import BallTree

logger = logging.getLogger(__name__)


class GraphToolRouter:
    """
    A routing engine that uses graph-tool for efficient shortest path calculations.

    This class converts NetworkX graphs (typically from OSMnx) to graph-tool format
    and provides routing functionality with improved performance.
    """

    def __init__(self, nx_graph: nx.MultiDiGraph):
        """
        Initialize the router with a NetworkX graph.

        Args:
            nx_graph: NetworkX MultiDiGraph from OSMnx
        """
        self.nx_graph = nx_graph
        self.gt_graph = None
        self.node_mapping = {}  # nx_node_id -> gt_vertex_index
        self.reverse_node_mapping = {}  # gt_vertex_index -> nx_node_id
        self.edge_mapping = {}  # (nx_u, nx_v, nx_key) -> gt_edge
        self.reverse_edge_mapping = {}  # gt_edge -> (nx_u, nx_v, nx_key)

        # Node coordinates for nearest neighbor search
        self.node_coords = None
        self.ball_tree = None

        # Edge and node property maps
        self.travel_time_map = None
        self.speed_map = None
        self.length_map = None
        self.osmid_map = None
        self.geometry_map = None

        # Convert the graph
        self._convert_graph()
        self._setup_spatial_index()

    def _convert_graph(self):
        """Convert NetworkX graph to graph-tool format."""
        logger.info("Converting NetworkX graph to graph-tool format...")

        # Create graph-tool graph
        self.gt_graph = gt.Graph(directed=True)

        # Create vertex mapping
        nx_nodes = list(self.nx_graph.nodes())
        for i, nx_node in enumerate(nx_nodes):
            gt_vertex = self.gt_graph.add_vertex()
            self.node_mapping[nx_node] = int(gt_vertex)
            self.reverse_node_mapping[int(gt_vertex)] = nx_node

        # Add edges and create edge mapping
        self.travel_time_map = self.gt_graph.new_edge_property("double")
        self.speed_map = self.gt_graph.new_edge_property("double")
        self.length_map = self.gt_graph.new_edge_property("double")
        self.osmid_map = self.gt_graph.new_edge_property("python::object")
        self.geometry_map = self.gt_graph.new_edge_property("python::object")

        # Add node coordinates as vertex properties
        self.node_x_map = self.gt_graph.new_vertex_property("double")
        self.node_y_map = self.gt_graph.new_vertex_property("double")

        # Set node coordinates
        for nx_node, data in self.nx_graph.nodes(data=True):
            gt_vertex = self.node_mapping[nx_node]
            self.node_x_map[gt_vertex] = data.get("x", data.get("lon", 0))
            self.node_y_map[gt_vertex] = data.get("y", data.get("lat", 0))

        # Add edges
        for u, v, key, data in self.nx_graph.edges(keys=True, data=True):
            gt_u = self.node_mapping[u]
            gt_v = self.node_mapping[v]

            gt_edge = self.gt_graph.add_edge(gt_u, gt_v)

            # Store edge mapping
            self.edge_mapping[(u, v, key)] = gt_edge
            self.reverse_edge_mapping[gt_edge] = (u, v, key)

            # Set edge properties
            self.travel_time_map[gt_edge] = data.get("travel_time", float("inf"))
            self.speed_map[gt_edge] = data.get("speed_kph", 5.0)
            self.length_map[gt_edge] = data.get("length", 0.0)
            self.osmid_map[gt_edge] = data.get("osmid", None)
            self.geometry_map[gt_edge] = data.get("geometry", None)

        logger.info(
            f"Converted graph with {self.gt_graph.num_vertices()} vertices and {self.gt_graph.num_edges()} edges"
        )

    def _setup_spatial_index(self):
        """Setup spatial index for nearest neighbor queries."""
        logger.info("Setting up spatial index for nearest neighbor queries...")

        # Extract node coordinates
        coords = []
        for nx_node in self.node_mapping.keys():
            node_data = self.nx_graph.nodes[nx_node]
            x = node_data.get("x", node_data.get("lon", 0))
            y = node_data.get("y", node_data.get("lat", 0))
            coords.append(
                [np.radians(y), np.radians(x)]
            )  # lat, lon in radians for haversine

        self.node_coords = np.array(coords)
        self.ball_tree = BallTree(self.node_coords, metric="haversine")

        logger.info("Spatial index setup complete")

    def nearest_nodes(self, x: float, y: float, k: int = 1) -> Union[int, List[int]]:
        """
        Find the nearest node(s) to a given coordinate.

        Args:
            x: Longitude
            y: Latitude
            k: Number of nearest nodes to return

        Returns:
            Node ID(s) of the nearest node(s)
        """
        query_point = np.array([[np.radians(y), np.radians(x)]])
        distances, indices = self.ball_tree.query(query_point, k=k)

        nx_nodes = list(self.node_mapping.keys())

        if k == 1:
            return nx_nodes[indices[0][0]]
        else:
            return [nx_nodes[idx] for idx in indices[0]]

    def shortest_path(
        self, source: int, target: int, weight: str = "travel_time"
    ) -> Optional[List[int]]:
        """
        Find the shortest path between two nodes.

        Args:
            source: Source node ID (NetworkX node ID)
            target: Target node ID (NetworkX node ID)
            weight: Edge weight to use ('travel_time', 'length')

        Returns:
            List of node IDs forming the shortest path, or None if no path exists
        """
        if source not in self.node_mapping or target not in self.node_mapping:
            logger.warning(f"Source {source} or target {target} not found in graph")
            return None

        gt_source = self.node_mapping[source]
        gt_target = self.node_mapping[target]

        # Select weight map
        if weight == "travel_time":
            weight_map = self.travel_time_map
        elif weight == "length":
            weight_map = self.length_map
        else:
            logger.warning(f"Unknown weight type: {weight}, using travel_time")
            weight_map = self.travel_time_map

        try:
            # Find shortest path using graph-tool
            vertex_list, edge_list = shortest_path(
                self.gt_graph,
                self.gt_graph.vertex(gt_source),
                self.gt_graph.vertex(gt_target),
                weights=weight_map,
            )

            # Convert back to NetworkX node IDs
            path = [self.reverse_node_mapping[int(v)] for v in vertex_list]
            return path

        except Exception as e:
            logger.error(f"Error finding shortest path: {e}")
            return None

    def route_to_gdf(self, route: List[int]) -> gpd.GeoDataFrame:
        """
        Convert a route (list of node IDs) to a GeoDataFrame.

        Args:
            route: List of node IDs forming the route

        Returns:
            GeoDataFrame with route edges and their attributes
        """
        if not route or len(route) < 2:
            return gpd.GeoDataFrame()

        edges_data = []

        for i in range(len(route) - 1):
            u, v = route[i], route[i + 1]

            # Find the edge in the original NetworkX graph
            # Handle potential multi-edges
            edge_data = None
            edge_key = None

            if self.nx_graph.has_edge(u, v):
                if isinstance(self.nx_graph[u][v], dict):
                    # Multi-edge case
                    for key, data in self.nx_graph[u][v].items():
                        edge_data = data
                        edge_key = key
                        break  # Take the first edge
                else:
                    edge_data = self.nx_graph[u][v]
                    edge_key = 0

            if edge_data is None:
                logger.warning(f"Edge ({u}, {v}) not found in original graph")
                continue

            # Create edge record
            edge_record = {
                "u": u,
                "v": v,
                "key": edge_key,
                "osmid": edge_data.get("osmid", None),
                "length": edge_data.get("length", 0.0),
                "travel_time": edge_data.get("travel_time", 0.0),
                "original_travel_time": edge_data.get(
                    "original_travel_time", edge_data.get("travel_time", 0.0)
                ),
                "speed_kph": edge_data.get("speed_kph", 5.0),
                "geometry": edge_data.get("geometry", None),
            }

            # If no geometry, create one from node coordinates
            if edge_record["geometry"] is None:
                u_data = self.nx_graph.nodes[u]
                v_data = self.nx_graph.nodes[v]

                u_x = u_data.get("x", u_data.get("lon", 0))
                u_y = u_data.get("y", u_data.get("lat", 0))
                v_x = v_data.get("x", v_data.get("lon", 0))
                v_y = v_data.get("y", v_data.get("lat", 0))

                edge_record["geometry"] = LineString([(u_x, u_y), (v_x, v_y)])

            edges_data.append(edge_record)

        if not edges_data:
            return gpd.GeoDataFrame()

        # Create GeoDataFrame
        gdf = gpd.GeoDataFrame(edges_data, crs="EPSG:4326")
        gdf = gdf.set_geometry("geometry")
        return gdf

    def set_edge_speeds(self, speeds: Dict[Tuple[int, int, int], float]):
        """
        Set speeds for specific edges.

        Args:
            speeds: Dictionary mapping (u, v, key) tuples to speed values in km/h
        """
        for (u, v, key), speed in speeds.items():
            if (u, v, key) in self.edge_mapping:
                gt_edge = self.edge_mapping[(u, v, key)]
                self.speed_map[gt_edge] = speed

                # Recalculate travel time
                length_km = self.length_map[gt_edge] / 1000.0
                travel_time = (length_km / speed) * 3600  # Convert to seconds
                self.travel_time_map[gt_edge] = travel_time

                # Also update the original NetworkX graph
                if self.nx_graph.has_edge(u, v, key):
                    self.nx_graph[u][v][key]["speed_kph"] = speed
                    self.nx_graph[u][v][key]["travel_time"] = travel_time

    def add_edge_travel_times(self):
        """
        Recalculate travel times for all edges based on current speeds.
        """
        for gt_edge in self.gt_graph.edges():
            speed = self.speed_map[gt_edge]
            length_km = self.length_map[gt_edge] / 1000.0

            if speed > 0:
                travel_time = (length_km / speed) * 3600  # Convert to seconds
            else:
                travel_time = float("inf")

            self.travel_time_map[gt_edge] = travel_time

            # Update original NetworkX graph as well
            u, v, key = self.reverse_edge_mapping[gt_edge]
            if self.nx_graph.has_edge(u, v, key):
                self.nx_graph[u][v][key]["travel_time"] = travel_time

    def get_graph_lookup(self) -> Dict[int, List[Tuple[int, int, int]]]:
        """
        Create a lookup dictionary mapping OSM IDs to edge tuples.

        Returns:
            Dictionary mapping OSM IDs to lists of (u, v, key) tuples
        """
        osm_lookup = defaultdict(list)

        for (u, v, key), gt_edge in self.edge_mapping.items():
            osmid = self.osmid_map[gt_edge]

            if osmid is not None:
                if isinstance(osmid, (list, tuple)):
                    for oid in osmid:
                        osm_lookup[int(oid)].append((u, v, key))
                        osm_lookup[int(oid)].append((v, u, key))  # Add reverse edge
                else:
                    osm_lookup[int(osmid)].append((u, v, key))
                    osm_lookup[int(osmid)].append((v, u, key))  # Add reverse edge

        return osm_lookup

    def get_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the graph.

        Returns:
            Dictionary with graph statistics
        """
        return {
            "num_nodes": self.gt_graph.num_vertices(),
            "num_edges": self.gt_graph.num_edges(),
            "is_directed": self.gt_graph.is_directed(),
            "avg_degree": (
                float(self.gt_graph.num_edges()) / float(self.gt_graph.num_vertices())
                if self.gt_graph.num_vertices() > 0
                else 0
            ),
        }


def create_router_from_networkx(nx_graph: nx.MultiDiGraph) -> GraphToolRouter:
    """
    Create a GraphToolRouter from a NetworkX graph.

    Args:
        nx_graph: NetworkX MultiDiGraph (typically from OSMnx)

    Returns:
        Configured GraphToolRouter instance
    """
    return GraphToolRouter(nx_graph)


def route_to_gdf_gt(graph: nx.MultiDiGraph, route: List[int]) -> gpd.GeoDataFrame:
    """
    Convert a route to a GeoDataFrame using NetworkX graph data.
    This is a standalone function that doesn't require GraphToolRouter.

    Args:
        graph: NetworkX graph
        route: List of node IDs

    Returns:
        GeoDataFrame with route edges
    """
    if not route or len(route) < 2:
        return gpd.GeoDataFrame()

    edges_data = []

    for i in range(len(route) - 1):
        u, v = route[i], route[i + 1]

        # Find the edge in the NetworkX graph
        edge_data = None
        edge_key = None

        if graph.has_edge(u, v):
            if isinstance(graph[u][v], dict):
                # Multi-edge case
                for key, data in graph[u][v].items():
                    edge_data = data
                    edge_key = key
                    break
            else:
                edge_data = graph[u][v]
                edge_key = 0

        if edge_data is None:
            continue

        # Create edge record
        edge_record = {
            "u": u,
            "v": v,
            "key": edge_key,
            "osmid": edge_data.get("osmid", None),
            "length": edge_data.get("length", 0.0),
            "travel_time": edge_data.get("travel_time", 0.0),
            "original_travel_time": edge_data.get(
                "original_travel_time", edge_data.get("travel_time", 0.0)
            ),
            "speed_kph": edge_data.get("speed_kph", 5.0),
            "geometry": edge_data.get("geometry", None),
        }

        # If no geometry, create one from node coordinates
        if edge_record["geometry"] is None:
            u_data = graph.nodes[u]
            v_data = graph.nodes[v]

            u_x = u_data.get("x", u_data.get("lon", 0))
            u_y = u_data.get("y", u_data.get("lat", 0))
            v_x = v_data.get("x", v_data.get("lon", 0))
            v_y = v_data.get("y", v_data.get("lat", 0))

            edge_record["geometry"] = LineString([(u_x, u_y), (v_x, v_y)])

        edges_data.append(edge_record)

    if not edges_data:
        return gpd.GeoDataFrame()

    return gpd.GeoDataFrame(edges_data, crs="EPSG:4326")
