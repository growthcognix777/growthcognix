FROM node:22-alpine AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_DATA_MODE=api
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_PUBLIC_DATA_MODE=$NEXT_PUBLIC_DATA_MODE NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-alpine
WORKDIR /app
RUN npm i -g serve@14
COPY --from=build /app/out ./out
EXPOSE 3000
CMD ["serve", "out", "-l", "3000"]
