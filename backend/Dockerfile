FROM ghcr.io/prefix-dev/pixi:latest

WORKDIR /app

# Copy pixi configuration files
COPY pixi.toml pixi.lock pyproject.toml ./

# Install dependencies using pixi
RUN pixi install --frozen

COPY . .
EXPOSE 8000

CMD ["pixi", "run", "fastapi", "run", "--host", "0.0.0.0", "--port", "8000"]