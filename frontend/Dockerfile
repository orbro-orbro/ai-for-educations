FROM node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL=http://localhost:8000
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
ARG VITE_SYNTHETIC_DEMO=false
ENV VITE_SYNTHETIC_DEMO=${VITE_SYNTHETIC_DEMO}
ARG VITE_MODEL_LABEL=
ENV VITE_MODEL_LABEL=${VITE_MODEL_LABEL}
RUN npm run build

EXPOSE 5173
CMD ["./node_modules/.bin/vite", "preview", "--host", "0.0.0.0", "--port", "5173"]
