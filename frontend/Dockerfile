FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
# Which commit this bundle was built from; shown in the sidebar. Pass --build-arg GIT_SHA=<sha>.
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA}
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
