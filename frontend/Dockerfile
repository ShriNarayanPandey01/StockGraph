FROM node:24-alpine

WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
ARG MARKETGRAPH_PLATFORM_URL=http://platform-api:8002
ENV MARKETGRAPH_PLATFORM_URL=${MARKETGRAPH_PLATFORM_URL}

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

ENV HOSTNAME=0.0.0.0
EXPOSE 3000
CMD ["npm", "run", "start"]
