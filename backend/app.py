import logging
import sys
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
from pydantic import BaseModel
import osmnx as ox
import networkx as nx
import json
from pathlib import Path
from diskcache import Cache
from copy import deepcopy
from contextlib import asynccontextmanager
from collections import defaultdict

BASE_SPEED_KPH = 10
PLACE_NAME = "Edinburgh, Scotland"
CACHE_GRAPH = True
WEB_MERCARTOR_CRS = 3857


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


class RouteRequest(BaseModel):
    start: tuple[float, float]
    end: tuple[float, float]
    following_weight: float
    preferred_routes: list[int] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global GRAPH, GRAPH_LOOKUP
    t0 = time.time()
    logger.info("Loading graph...")
    if CACHE_GRAPH and Path("../dev_cache").exists():
        logger.info("Loading cached graph from dev_cache")
        cache = Cache("../dev_cache")
        GRAPH = cache.get("graph")
        GRAPH_LOOKUP = cache.get("graph_lookup")
    elif CACHE_GRAPH:
        logger.info("Caching graph to dev_cache")
        cache = Cache("../dev_cache")
        GRAPH, GRAPH_LOOKUP = get_graph(PLACE_NAME, BASE_SPEED_KPH)
        cache.set("graph", GRAPH)
        cache.set("graph_lookup", GRAPH_LOOKUP)
    else:
        logger.info("Loading graph without caching")
        GRAPH, GRAPH_LOOKUP = get_graph(PLACE_NAME, BASE_SPEED_KPH)

    logger.info(f"Graph loaded in {time.time() - t0:.2f} seconds")
    logger.info(f"Graph has {len(GRAPH.nodes)} nodes and {len(GRAPH.edges)} edges")
    logger.info(f"Graph lookup has {len(GRAPH_LOOKUP)} entries")

    yield

    # Shutdown
    logger.info("Shutting down API...")
    del GRAPH, GRAPH_LOOKUP


app = FastAPI(debug=True, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust to match your frontend's origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/generate_route")
async def generate_route(request: RouteRequest):
    logger.info(f"Received route request: {request}")
    # Placeholder logic for generating a route
    route = get_route(
        request.start,
        request.end,
        GRAPH,
        request.following_weight,
        request.preferred_routes,
    )
    route = route.dissolve()
    return json.loads(route[["geometry"]].to_json())


def get_graph_lookup(graph):
    # my assumption was that that we also get reverse edges, when we iterate, but maybe not??
    osm_lookup = defaultdict(list)
    for u, v, k, data in list(graph.edges(data=True, keys=True)):
        if type(data["osmid"]) == int:
            osm_lookup[data["osmid"]].append((u, v, k))
            osm_lookup[data["osmid"]].append((v, u, k))
        else:
            for _id in data["osmid"]:
                # multiple osmid for a single edge
                osm_lookup[_id].append((u, v, k))
                osm_lookup[_id].append((v, u, k))
    return osm_lookup


def get_graph(place_name: str, base_speed_kph: int):
    graph = ox.graph.graph_from_place(
        place_name,
        network_type="bike",
        simplify=True,
        retain_all=True,
        truncate_by_edge=True,
    )
    ox.routing.add_edge_speeds(graph, fallback=base_speed_kph)
    ox.routing.add_edge_travel_times(graph)
    return graph, get_graph_lookup(graph)


def get_route(
    start: tuple[float, float],
    end: tuple[float, float],
    graph: nx.Graph,
    following_weight: float,
    preferred_routes: list[int] = None,
):

    if preferred_routes is not None:
        graph = deepcopy(graph)
        logger.info(f"Preferred routes: {preferred_routes}")

        mapped_edges = (
            pd.Series(preferred_routes).astype(int).map(GRAPH_LOOKUP).dropna()
        )
        mapped_edges = [
            edge
            for route in preferred_routes
            for edge in GRAPH_LOOKUP.get(int(route), [])
        ]
        print(f"Mapped edges:\n {mapped_edges}")
        speedy_routes = {x: following_weight * BASE_SPEED_KPH for x in mapped_edges}
        logger.info(f"Speedy routes: {speedy_routes}")
        nx.set_edge_attributes(graph, speedy_routes, "speed_kph")
        graph = ox.routing.add_edge_travel_times(
            graph
        )  # TODO - only recalculate travel times for speedy routes
        # check that we've set the attributes correctly
        for k, v in speedy_routes.items():
            if k in graph.edges:
                logger.info(f"speed_kph for edge {k}: {graph.edges[k]['speed_kph']}")
                logger.info(f"travel time for edge {k}: {graph.edges[k]['travel_time']}")
                logger.info(f"edge data: {graph.edges[k]}")

    start_node = ox.distance.nearest_nodes(
        graph,
        start[0],
        start[1],
    )

    end_node = ox.distance.nearest_nodes(
        graph,
        end[0],
        end[1],
    )

    route = ox.routing.shortest_path(
        graph,
        int(start_node),
        int(end_node),
        weight="travel_time",
    )
    route_gdf = ox.routing.route_to_gdf(graph, route)
    route_gdf["name_ref"] = None
    logger.info(
        f"Route length: {int(route_gdf.to_crs(route_gdf.estimate_utm_crs()).length.sum())} meters"
    )
    ox.routing.utils.settings.all_oneway
    logger
    return route_gdf
