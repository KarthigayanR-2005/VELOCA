FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 go build -o /loadgen .

FROM alpine:3.20
WORKDIR /app
COPY --from=build /loadgen /app/loadgen
ENTRYPOINT ["/app/loadgen"]
