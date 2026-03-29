FROM node:20-slim AS frontend-build

WORKDIR /frontend

# Install and build frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

# Install backend dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY backend ./backend
COPY main.py agent.py ./

# Copy compiled frontend from the build stage
COPY --from=frontend-build /frontend/dist ./frontend/dist

# Expose cloud run port
ENV PORT=8080
EXPOSE 8080

# Run
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
