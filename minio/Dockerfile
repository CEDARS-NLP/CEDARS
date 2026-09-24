FROM golang:1.22-alpine AS build

ARG MINIO_VERSION

RUN apk add --no-cache git
RUN git clone --branch "${MINIO_VERSION}" --depth 1 https://github.com/minio/minio.git /src

WORKDIR /src
RUN CGO_ENABLED=0 go build \
	-tags kqueue \
	-trimpath \
	--ldflags "$(go run buildscripts/gen-ldflags.go)" \
	-o /out/minio .

FROM alpine:3.20

RUN apk add --no-cache ca-certificates
COPY --from=build /out/minio /usr/bin/minio

EXPOSE 9000 9001
VOLUME ["/data"]

ENTRYPOINT ["/usr/bin/minio"]
CMD ["server", "/data", "--console-address", ":9001"]