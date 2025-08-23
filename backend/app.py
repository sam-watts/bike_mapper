import logging
import os
import sys
import time
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
from fastapi.responses import JSONResponse
import pandas as pd
import geopandas as gpd
from pydantic import BaseModel
import osmnx as ox
import networkx as nx
import json
from pathlib import Path
from diskcache import Cache
from copy import deepcopy
from contextlib import asynccontextmanager
from collections import defaultdict

from gt_routing import create_router_from_networkx

BASE_SPEED_KPH = 5
PLACE_NAME = "Edinburgh, Scotland"
CACHE_GRAPH = True
WEB_MERCARTOR_CRS = 3857
IS_PROD = "RAILWAY_ENVIRONMENT_ID" in os.environ

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
# Set OSMnx logging to INFO and add to our logger
logging.getLogger("osmnx").setLevel(logging.INFO)


class RouteRequest(BaseModel):
    start: tuple[float, float]
    end: tuple[float, float]
    following_weight: float
    preferred_routes: list[int] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global GRAPH, GRAPH_LOOKUP, GT_ROUTER
    t0 = time.time()
    logger.info("Loading graph...")

    if CACHE_GRAPH and Path("../dev_cache").exists() and not IS_PROD:
        logger.info("Loading cached graph from dev_cache")
        cache = Cache("../dev_cache")
        GRAPH = cache.get("graph")
        GRAPH_LOOKUP = cache.get("graph_lookup")
        GT_ROUTER = cache.get("gt_router")

        GT_ROUTER = create_router_from_networkx(GRAPH)

    elif CACHE_GRAPH and not IS_PROD:
        logger.info("Caching graph to dev_cache")
        cache = Cache("../dev_cache")
        GRAPH, GRAPH_LOOKUP = get_graph(PLACE_NAME, BASE_SPEED_KPH)

        # Create graph-tool router
        logger.info("Creating graph-tool router...")
        GT_ROUTER = create_router_from_networkx(GRAPH)

        cache.set("graph", GRAPH)
        cache.set("graph_lookup", GRAPH_LOOKUP)

    else:
        logger.info("Loading graph without caching")
        GRAPH, GRAPH_LOOKUP = get_graph(PLACE_NAME, BASE_SPEED_KPH)
        GT_ROUTER = create_router_from_networkx(GRAPH)

    logger.info(f"Graph loaded in {time.time() - t0:.2f} seconds")
    logger.info(f"Graph has {len(GRAPH.nodes)} nodes and {len(GRAPH.edges)} edges")
    logger.info(f"Graph lookup has {len(GRAPH_LOOKUP)} entries")

    # Print GT router stats
    gt_stats = GT_ROUTER.get_stats()
    logger.info(f"Graph-tool router stats: {gt_stats}")

    yield

    # Shutdown
    logger.info("Shutting down API...")
    del GRAPH, GRAPH_LOOKUP, GT_ROUTER


app = FastAPI(debug=True, lifespan=lifespan)


# Middleware to log all requests
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    exception_raised = False
    logger.info(f"Incoming request: {request.method} {request.url}")

    try:
        response = await call_next(request)
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        exception_raised = True
    finally:
        duration = time.time() - start_time
        status_string = "completed" if not exception_raised else "failed"
        logger.info(
            f"Request {status_string} | {request.method} {request.url.path} | duration: {duration:.2f} seconds"
        )

    return response


if IS_PROD:
    # Production: Only allow your frontend domain
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://sam-watts.github.io"
        ],  # Replace with your actual frontend URL
        allow_credentials=True,
        allow_methods=["GET", "POST"],  # Only allow needed methods
        allow_headers=["content-type"],  # Only allow needed headers
    )
else:
    # Development: Allow localhost for testing
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5000",
            "http://localhost:3000",
        ],  # Your dev frontend URLs
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health")
async def health_check():
    """Health check endpoint to verify the service is ready."""
    if GT_ROUTER is None:
        return JSONResponse(status_code=503, content={"status": "error", "message": "Service not ready"})
    return JSONResponse(status_code=200, content={"status": "ok", "message": "Service is healthy"})


@app.post("/generate_route")
async def generate_route(request: RouteRequest):
    logger.info(f"Received route request: {request}")

    # Use graph-tool routing instead of NetworkX
    route_data = get_route_gt(
        request.start,
        request.end,
        GT_ROUTER,
        request.following_weight,
        request.preferred_routes,
    )

    route_gdf = route_data["route_gdf"].dissolve()
    geojson_data = json.loads(route_gdf[["geometry"]].to_json())

    response = {
        "geojson": geojson_data,
        "distance_meters": route_data["distance_meters"],
        "travel_time_seconds": route_data["travel_time_seconds"],
    }

    return response


def get_graph_lookup(graph):
    """Original function for compatibility."""
    osm_lookup = defaultdict(list)
    for u, v, k, data in list(graph.edges(data=True, keys=True)):
        if type(data["osmid"]) == int:
            osm_lookup[data["osmid"]].append((u, v, k))
            osm_lookup[data["osmid"]].append((v, u, k))
        else:
            for _id in data["osmid"]:
                osm_lookup[_id].append((u, v, k))
                osm_lookup[_id].append((v, u, k))
    return osm_lookup


def get_graph(place_name: str, base_speed_kph: int):
    """Original function for compatibility."""
    graph = ox.graph.graph_from_place(
        place_name,
        network_type="bike",
        simplify=True,
        retain_all=True,
        truncate_by_edge=True,
    )
    ox.routing.add_edge_speeds(graph, fallback=base_speed_kph)
    ox.routing.add_edge_travel_times(graph)
    for u, v, k, data in graph.edges(keys=True, data=True):
        data["original_travel_time"] = data["travel_time"]
    return graph, get_graph_lookup(graph)


def get_route_gt(
    start: tuple[float, float],
    end: tuple[float, float],
    gt_router,  # GraphToolRouter instance
    following_weight: float,
    preferred_routes: list[int] = None,
):
    """
    Modified routing function that uses graph-tool router.
    """

    # Handle preferred routes by modifying speeds
    if preferred_routes is not None:
        logger.debug(f"Preferred routes: {preferred_routes}")

        # Get the graph lookup from the router
        graph_lookup = gt_router.get_graph_lookup()

        mapped_edges = [
            edge
            for route in preferred_routes
            for edge in graph_lookup.get(int(route), [])
        ]

        logger.debug(f"Mapped edges:\n {mapped_edges}")

        # Create speed modifications
        speedy_routes = {x: following_weight * BASE_SPEED_KPH for x in mapped_edges}
        logger.debug(f"Speedy routes: {speedy_routes}")

        # Apply speed changes to the router
        gt_router.set_edge_speeds(speedy_routes)
        gt_router.add_edge_travel_times()

    # Find nearest nodes using graph-tool router
    start_node = gt_router.nearest_nodes(start[0], start[1])
    end_node = gt_router.nearest_nodes(end[0], end[1])

    logger.info(f"Start node: {start_node}, End node: {end_node}")

    # Find shortest path using graph-tool
    route = gt_router.shortest_path(start_node, end_node, weight="travel_time")

    if route is None:
        logger.error("No route found")
        return {
            "route_gdf": gpd.GeoDataFrame(),
            "distance_meters": 0,
            "travel_time_seconds": 0,
        }

    # Convert route to GeoDataFrame
    route_gdf = gt_router.route_to_gdf(route)
    route_gdf["name_ref"] = None

    # Calculate distance in meters
    distance_meters = int(route_gdf.to_crs(route_gdf.estimate_utm_crs()).length.sum())

    # Calculate total travel time in seconds
    travel_time_seconds = route_gdf["original_travel_time"].sum()

    logger.info(f"Route length: {distance_meters} meters")
    logger.info(f"Route travel time: {travel_time_seconds:.1f} seconds")

    return {
        "route_gdf": route_gdf,
        "distance_meters": distance_meters,
        "travel_time_seconds": travel_time_seconds,
    }


# Keep original function for backward compatibility
def get_route(
    start: tuple[float, float],
    end: tuple[float, float],
    graph: nx.Graph,
    following_weight: float,
    preferred_routes: list[int] = None,
):
    """Original routing function using NetworkX (for comparison)."""

    if preferred_routes is not None:
        graph = deepcopy(graph)
        logger.debug(f"Preferred routes: {preferred_routes}")

        mapped_edges = (
            pd.Series(preferred_routes).astype(int).map(GRAPH_LOOKUP).dropna()
        )
        mapped_edges = [
            edge
            for route in preferred_routes
            for edge in GRAPH_LOOKUP.get(int(route), [])
        ]
        logger.debug(f"Mapped edges:\n {mapped_edges}")
        speedy_routes = {x: following_weight * BASE_SPEED_KPH for x in mapped_edges}
        logger.debug(f"Speedy routes: {speedy_routes}")
        nx.set_edge_attributes(graph, speedy_routes, "speed_kph")
        graph = ox.routing.add_edge_travel_times(graph)

        for k, v in speedy_routes.items():
            if k in graph.edges:
                logger.debug(f"speed_kph for edge {k}: {graph.edges[k]['speed_kph']}")
                logger.debug(
                    f"travel time for edge {k}: {graph.edges[k]['travel_time']}"
                )
                logger.debug(f"edge data: {graph.edges[k]}")

    start_node = ox.distance.nearest_nodes(graph, start[0], start[1])
    end_node = ox.distance.nearest_nodes(graph, end[0], end[1])

    route = ox.routing.shortest_path(
        graph,
        int(start_node),
        int(end_node),
        weight="travel_time",
    )
    route_gdf = ox.routing.route_to_gdf(graph, route)
    route_gdf["name_ref"] = None

    distance_meters = int(route_gdf.to_crs(route_gdf.estimate_utm_crs()).length.sum())
    travel_time_seconds = route_gdf["original_travel_time"].sum()

    logger.info(f"Route length: {distance_meters} meters")
    logger.info(f"Route travel time: {travel_time_seconds:.1f} seconds")
    logger.info(route_gdf[["original_travel_time", "length"]].T.to_markdown())

    return {
        "route_gdf": route_gdf,
        "distance_meters": distance_meters,
        "travel_time_seconds": travel_time_seconds,
    }
