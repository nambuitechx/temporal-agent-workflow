# ── giai đoạn 1: build Vite ─────────────────────────────────────────────
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY . .
RUN npm run build

# ── giai đoạn 2: nginx tĩnh + proxy /api → backend ──────────────────────
FROM nginx:1.27-alpine
ENV API_UPSTREAM=http://backend:8000
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
