# Mapbox Frontend Application

This project is a web application that utilizes Mapbox to display a map and allows users to select linestrings from a geoparquet file. It provides functionality to set start and end points for route generation via a placeholder HTTP endpoint.

## Project Structure

```
mapbox-frontend-app
├── src
│   ├── index.html       # Main HTML document
│   ├── styles.css       # Styles for the application
│   └── app.js           # JavaScript functionality
├── data
│   └── cycleways.parquet # Linestring data in geoparquet format
├── README.md            # Project documentation
```

## Setup Instructions

1. **Clone the repository**:
   ```
   git clone <repository-url>
   cd mapbox-frontend-app
   ```

2. **Install dependencies**:
   Ensure you have a local server to serve the files. You can use tools like `http-server` or any other static file server.

3. **Run the application**:
   Start your local server in the `mapbox-frontend-app` directory and navigate to `http://localhost:PORT/src/index.html` in your web browser.

## Usage

- The application will display a Mapbox map.
- Users can select linestrings from the displayed cycleways.
- Set start and end points for route generation.
- The application will send requests to a placeholder HTTP endpoint to generate routes based on the selected points.

## Dependencies

- Mapbox GL JS: Ensure you have a valid Mapbox access token and include it in your JavaScript code.
- Any additional libraries required for handling geoparquet files and HTTP requests.

## License

This project is licensed under the MIT License. See the LICENSE file for more details.