import pandas as pd
import streamlit as st
import geopandas as gpd
from streamlit_folium import st_folium
from folium.plugins import Draw
import folium
import osmnx as ox
import networkx as nx
from shapely.geometry import LineString, Point, MultiLineString, Polygon


def multiline_to_single_line(geometry: LineString | MultiLineString) -> LineString:
  if isinstance(geometry, (LineString, Polygon, Point)):
      return geometry
  
  coords = list(map(lambda part: list(part.coords), geometry.geoms))
  flat_coords = [Point(*point) for segment in coords for point in segment]
  return LineString(flat_coords)


# Load vector data
data_path = "data/fe_cycleways.parquet"
gdf = gpd.read_parquet(data_path)

# Initialize Streamlit app
st.title("Bike Mapper")
st.write("Select cycleways by clicking on them.")

BASE_SPEED_KPH = 10
PREFERRED_ROUTE_MULTIPLIER = 2

place_name = "Edinburgh, Scotland"

def get_graph_lookup(graph):
    osm_lookup = {}
    for u, v, k, data in list(graph.edges(data=True, keys=True)):
        if type(data["osmid"]) == int:
            osm_lookup[data["osmid"]] = (u, v, k)
        else:
            for _id in data["osmid"]:
                osm_lookup[_id] = (u, v, k)
    return osm_lookup


@st.cache_resource
def get_graph(place_name: str):
    graph = ox.graph.graph_from_place(
        place_name,
        network_type="bike",
        simplify=True,
        retain_all=True,
        truncate_by_edge=True,
    )
    nx.set_edge_attributes(graph, BASE_SPEED_KPH, "speed_kph")
    ox.routing.add_edge_travel_times(graph)
    return graph, get_graph_lookup(graph)   


def get_route(start: tuple[float, float], end: tuple[float, float], graph, preferred_routes=None):
    if preferred_routes is not None:
        speedy_routes = {x: PREFERRED_ROUTE_MULTIPLIER * BASE_SPEED_KPH for x in pd.Series(preferred_routes).astype(int).map(GRAPH_LOOKUP).dropna()}
        st.write("Speedy routes: ", speedy_routes)
        nx.set_edge_attributes(graph, speedy_routes, "speed_kph")
        ox.routing.add_edge_travel_times(graph)

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
    st.write(route)
    route_gdf = ox.routing.route_to_gdf(graph, route)
    route_gdf["name_ref"] = None
    return route_gdf

fg = folium.FeatureGroup(name="Cycleways")

GRAPH, GRAPH_LOOKUP = get_graph(place_name)

if "route_fg" not in locals():
    route_fg = folium.FeatureGroup(name="Calculated route")

if "calculated_route" in st.session_state:
    # add the geometry to a feature group
    route_fg = folium.FeatureGroup(name="Calculated route")
    folium.GeoJson(
        st.session_state.calculated_route,
        name="Cycleways",
        tooltip=folium.GeoJsonTooltip(fields=["name_ref"]),
        style_function=lambda x: {
            "weight": 3,
            "color": "green",
        },
    ).add_to(route_fg)


# Create a Folium map
m = folium.Map(
    location=[gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()],
    zoom_start=12,
)
Draw(
    export=False,
    draw_options={
        "polyline": False,
        "polygon": False,
        "circle": False,
        "rectangle": False,
        "marker": True,
        "circlemarker": False,
        "edit": True,
    },
).add_to(m)

# button to clear selected lines
if st.button("Clear selected lines"):
    st.session_state.selected_lines = {}
    st.rerun()

# gdf = gdf.explode(column="geometry").reset_index(drop=True)
gdf["colour"] = "blue"

if "selected_lines" not in st.session_state:
    st.session_state.selected_lines = {}
else:
    gdf.loc[
        gdf.index.isin(map(int, st.session_state.selected_lines.keys())), "colour"
    ] = "red"

gdf.loc[gdf.index.isin(st.session_state.selected_lines.keys())].drop(columns="geometry")

# Add GeoJSON layer to the map
geojson_layer = folium.GeoJson(
    gdf,
    name="Cycleways",
    tooltip=folium.GeoJsonTooltip(fields=["name_ref"]),
    highlight_function=lambda _: {"weight": 3, "color": "orange"},
    style_function=lambda x: {
        "weight": 2,
        "color": x["properties"]["colour"],
    },
)
geojson_layer.add_to(fg)

# Add map to Streamlit
map_data = st_folium(m, width=700, height=500, feature_group_to_add=[fg, route_fg], layer_control=folium.LayerControl())
map_data
match map_data.get("last_active_drawing"):
    case {"geometry": {"type": "Point"}}:
        points = map_data["all_drawings"]
        if len(points) > 2:
            st.warning("Can only route between two points. Please remove points until only two remain.")
    case {"geometry": {"type": "LineString" | "MultiLineString"}}:
        current_line_id = map_data["last_active_drawing"]["id"]
        if current_line_id is not None:
            if current_line_id not in st.session_state["selected_lines"].keys():
                st.session_state.selected_lines[current_line_id] = map_data[
                    "last_active_drawing"
                ]
                st.rerun()

st.write("Selected lines: ", st.session_state.selected_lines.keys())
# # Display selected features
# if map_data and "last_active_drawing" in map_data and map_data["last_active_drawing"]:
#     selected_feature = map_data["last_active_drawing"]
#     st.write("Selected Feature:", selected_feature)
# else:
#     st.write("No feature selected.")

if st.button("Calculate route"):
    st.session_state.calculated_route = get_route(
        map_data["all_drawings"][0]["geometry"]["coordinates"],
        map_data["all_drawings"][1]["geometry"]["coordinates"],
        GRAPH,
        preferred_routes=list(st.session_state.selected_lines.keys()),
    )

st.write(pd.Series(list(st.session_state.selected_lines.keys())).map(GRAPH_LOOKUP))
GRAPH_LOOKUP[1209807768]

# st.write("graph lookup: ", GRAPH_LOOKUP)
