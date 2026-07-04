FROM node:24-alpine AS build

WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
ARG VITE_MATSYA_API_BASE_URL=http://localhost:8020
ENV VITE_MATSYA_API_BASE_URL=$VITE_MATSYA_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
