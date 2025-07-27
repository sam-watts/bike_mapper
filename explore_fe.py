import marimo

__generated_with = "0.12.10"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import geopandas as gpd
    import folium
    return folium, gpd, mo


@app.cell
def _(gpd):
    cycleways = gpd.read_parquet("data/fe_cycleways.parquet")
    return (cycleways,)


@app.cell
def _(cycleways):
    cycleways.plot()
    return


@app.cell
def _(folium):
    m = folium.Map()
    m 
    return (m,)


@app.cell
def _(m):
    m
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
